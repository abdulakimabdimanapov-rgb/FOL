@preconcurrency import AppKit
@preconcurrency import Foundation
import Combine
import os

// MARK: - Chat View Model

/// Main view model managing chat messages, Twin state, SSE connections,
/// voice input state, and proactive suggestion handling.
/// Two SSE connections: /chat (per-request) and /events (persistent).
@MainActor
final class ChatViewModel: ObservableObject {
    @Published var messages: [ChatMessage] = []
    @Published var twinState: TwinState = .idle
    @Published var isConnected: Bool = false
    @Published var inputText: String = ""
    @Published var voiceState: VoiceInputState = .hidden
    @Published var audioLevel: Float = 0

    /// Real task progress 0.0–1.0 driven by SSE events instead of simulation
    @Published var taskProgress: CGFloat = 0



    /// Live human-readable status from sanitized SSE activity events:
    /// "Listening…", "Thinking…", "Searching…", "Writing…", "Responding…", "Done".
    @Published var statusText: String = ""

    /// Last user text, used by the Retry button after an error.
    private(set) var lastUserText: String = ""
    /// The twin message that holds the last error — Retry renders under it.
    private(set) var lastErrorMessageID: UUID?

    /// Tracks notch expansion: 0=compact, 1=status mini, 2=full chat
    @Published var expansionStage: Int = 0

    /// True when first-run setup wizard should be shown instead of chat
    @Published var needsSetup: Bool = false

    /// Callback for notch tap-to-expand. Set by NotchOverlayController.
    var onNotchTap: (() -> Void)?
    /// Callback for closing expanded notch. Set by NotchOverlayController.
    var onNotchClose: (() -> Void)?

    // Proactive suggestion state
    @Published var currentSuggestion: ProactiveSuggestion?
    @Published var consecutiveDismissals: Int = 0

    private let orchestratorURL = URL(string: ServerConfig.chatEndpoint)!
    private var sseTask: URLSessionDataTask?
    private var reconnectTimer: Timer?
    private var currentTwinMessageID: UUID?
    private(set) var streamingComponentID: UUID?
    private let audioManager = AudioManager.shared

    // Voice input
    let audioRecorder = AudioRecorder()
    private let speechService = SpeechService()
    private let localSTTService = LocalSTTService()
    private var voiceErrorTimer: Task<Void, Never>?
    private var currentTranscriptionFile: URL?
    private let voiceLogger = Logger(subsystem: "com.secondself.app", category: "VoiceInput")

    // Continuous haptic during recording — intensity varies with audio level
    private var hapticTimer: Timer?
    private let hapticSilenceThreshold: Float = 0.15
    private let hapticGentleThreshold: Float = 0.35
    private let hapticModerateThreshold: Float = 0.55

    // Chat history persistence (debounced writes to ~/.fol/chat_history.json)
    private static let maxPersistedMessages = 100
    private var persistCancellables: Set<AnyCancellable> = []
    private var statusClearTask: Task<Void, Never>?

    // TTS — Twin speaks responses with JARVIS voice
    private let ttsService = ElevenLabsService()
    /// Whether ElevenLabs API key is available for TTS
    @Published var hasTTS: Bool = false
    /// User muted JARVIS voice output
    @Published var isMuted: Bool = false
    /// JARVIS volume 0.0–1.0
    @Published var jarvisVolume: Float = 0.7

    // Per-request SSE session for /chat
    private lazy var urlSession: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 300 // 5 min for long SSE streams
        config.timeoutIntervalForResource = 600
        return URLSession(configuration: config, delegate: sseDelegate, delegateQueue: .main)
    }()

    private lazy var sseDelegate: SSESessionDelegate = {
        SSESessionDelegate(viewModel: self)
    }()

    // Persistent SSE session for /events (suggestions)
    private var eventsTask: URLSessionDataTask?
    private var eventsReconnectTimer: Timer?

    private lazy var eventsSession: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = .infinity  // persistent connection
        config.timeoutIntervalForResource = .infinity
        return URLSession(configuration: config, delegate: eventsDelegate, delegateQueue: .main)
    }()

    private lazy var eventsDelegate: EventsSSEDelegate = {
        EventsSSEDelegate(viewModel: self)
    }()

    init() {
        // Start with a welcome message
        let welcome = ChatMessage(
            id: UUID(),
            sender: .twin,
            content: .text("hey, what do you need?"),
            timestamp: Date()
        )

        // Restore the previous conversation (if any) so the dialog survives app restarts.
        if let restored = Self.loadPersistedMessages(), !restored.isEmpty {
            messages = Array(restored.suffix(Self.maxPersistedMessages))
        } else {
            messages.append(welcome)
        }

        // Debounced persist: any chat change is flushed to disk ~1.5s after it settles.
        $messages
            .dropFirst()
            .debounce(for: .seconds(1.5), scheduler: DispatchQueue.main)
            .sink { [weak self] _ in self?.persistMessages() }
            .store(in: &persistCancellables)

        // /events SSE stream connects lazily when orchestrator is confirmed running
        // (triggered by first successful /chat call or explicit startEventsStream())

        // Restore persisted audio settings from AudioManager + sync local flags
        audioManager.restoreMuteState()
        isMuted = audioManager.isMuted
        jarvisVolume = audioManager.volume

        // Live "Speaking…" status: the Dynamic Island follows the voice loop
        // (listening → transcribing → working → speaking) via statusText.
        audioManager.onTTSStateChange = { [weak self] in
            self?.syncSpeakingStatus()
        }

        // Check voice availability (API key in .env)
        checkVoiceAvailability()
        // Check TTS availability
        checkTTSAvailability()

        // Forward audio level from AudioRecorder to this ViewModel so SwiftUI observes it
        audioRecorder.$audioLevel
            .receive(on: DispatchQueue.main)
            .assign(to: &$audioLevel)
    }

    // MARK: - Send Message

    func sendMessage(text: String) {
        guard !text.isEmpty else { return }
        inputText = ""
        lastUserText = text
        lastErrorMessageID = nil

        // Interrupt any JARVIS speech in progress — the user is taking the floor.
        audioManager.stopTTS()

        // Ensure /events stream is connected now that orchestrator is running
        startEventsStream()

        // Add user message
        let userMessage = ChatMessage(
            id: UUID(),
            sender: .user,
            content: .text(text),
            timestamp: Date()
        )
        messages.append(userMessage)

        // Reset progress for new task
        taskProgress = 0

        // Update state
        twinState = .thinking
        taskProgress = 0.05
        audioManager.playTaskStart()

        // Create the SSE request
        var request = URLRequest(url: orchestratorURL)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")

        let payload: [String: Any] = ["message": text]
        request.httpBody = try? JSONSerialization.data(withJSONObject: payload)

        // Cancel any existing SSE task
        sseTask?.cancel()

        // Start SSE stream via delegate-based data task
        sseTask = urlSession.dataTask(with: request)
        sseTask?.resume()
    }

    // MARK: - Stop / Retry

    // MARK: - Speaking Status (voice loop on the Dynamic Island)

    /// Mirrors TTS playback into ``statusText`` so the island shows
    /// "Speaking…" while JARVIS talks, and clears it when speech ends.
    private func syncSpeakingStatus() {
        if audioManager.isTTSPlaying {
            statusClearTask?.cancel()
            statusText = "Speaking…"
        } else if statusText == "Speaking…" {
            statusText = ""
        }
    }

    /// Ask the orchestrator to interrupt the running task (POST /chat/interrupt).
    /// The server emits a "cancelled" state event that flips `twinState`.
    func interruptTask() {
        guard twinState == .thinking || twinState == .working else { return }
        guard let url = URL(string: "\(ServerConfig.orchestratorURL)/chat/interrupt") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: ["reason": "user_cancel"])
        URLSession.shared.dataTask(with: request).resume()
    }

    /// Re-send the last user message after an error — the user never has to
    /// retype or restart the conversation.
    func retryLastMessage() {
        guard !lastUserText.isEmpty else { return }
        guard twinState != .thinking && twinState != .working else { return }
        sendMessage(text: lastUserText)
    }

    // MARK: - SSE Event Handling

    func handleSSEEvent(eventType: String, data: String) {
        guard let event = SSEEventType(rawValue: eventType) else { return }

        switch event {
        case .state:
            // Data is JSON: {"state": "thinking"} or {"state": "complete", "message": "Done!"}
            if let jsonData = data.data(using: .utf8),
               let json = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any],
               let stateStr = json["state"] as? String,
               let newState = TwinState(rawValue: stateStr) {
                twinState = newState
                
                // Map state to real progress + a live human-readable status
                switch newState {
                case .thinking:
                    taskProgress = 0.05
                    statusClearTask?.cancel()
                    statusText = "Thinking…"
                case .working:
                    taskProgress = 0.4
                    statusText = "Working…"
                case .complete:
                    taskProgress = 1.0
                    statusText = "Done"
                    scheduleStatusClear()
                case .cancelled:
                    taskProgress = 0
                    statusClearTask?.cancel()
                    currentTwinMessageID = nil
                    statusText = "Cancelled"
                    scheduleStatusClear()
                case .idle:
                    taskProgress = 0
                    statusText = ""
                case .error:
                    taskProgress = 0
                    statusText = ""
                }
                

                if newState == .complete {
                    audioManager.playCompletion()
                    currentTwinMessageID = nil
                    // Speak the twin's last response with JARVIS voice
                    speakLastTwinMessage()
                }
            }

        case .token:
            // Data is JSON: {"text": "Hello"}
            if let jsonData = data.data(using: .utf8),
               let json = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any],
               let text = json["text"] as? String {
                // Each token chunk nudges progress gradually toward 0.85
                taskProgress = min(0.85, taskProgress + 0.005)
                // First token of the final answer: switch to the responding status.
                if currentTwinMessageID == nil, twinState == .thinking || twinState == .working {
                    statusText = "Responding…"
                }
                appendTokenToCurrentTwinMessage(text)
            }

        case .activity:
            // Coarse, user-safe status — the Response Formatter never sends
            // tool names, arguments, or JSON to the UI.
            handleActivity(data: data)

        case .toolCall:
            // Legacy/defensive path: tool calls are internal now, so this
            // only bumps progress and maps to a generic activity status.
            taskProgress = taskProgress < 0.2 ? 0.2 : min(0.7, taskProgress + 0.12)
            handleActivity(data: data)

        case .toolProgress:
            // Progress details are internal — just nudge the progress bar.
            taskProgress = min(0.85, taskProgress + 0.08)
            handleToolProgress(data: data)

        case .toolResult:
            handleToolResult(data: data)

        case .error:
            twinState = .error
            // Data is JSON: {"message": "description"}
            var errorText = data
            if let jsonData = data.data(using: .utf8),
               let json = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any],
               let msg = json["message"] as? String {
                errorText = msg
            }
            let errorMessage = ChatMessage(
                id: UUID(),
                sender: .twin,
                content: .text("Something went wrong: \(errorText)"),
                timestamp: Date()
            )
            lastErrorMessageID = errorMessage.id
            messages.append(errorMessage)
            currentTwinMessageID = nil

        case .component:
            handleComponent(data: data)

        case .componentStart, .componentDelta, .componentEnd:
            break // Reserved for future streaming component support

        case .suggestion:
            handleSuggestionEvent(data: data)

        case .suggestionAccepted, .suggestionDismissed:
            // Acknowledgements from server, clear if it matches current
            if let jsonData = data.data(using: .utf8),
               let json = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any],
               let id = json["id"] as? String,
               currentSuggestion?.id == id {
                currentSuggestion = nil
            }

        case .ping:
            break
        }
    }

    // MARK: - Suggestion Handling

    private func handleSuggestionEvent(data: String) {
        guard let jsonData = data.data(using: .utf8) else { return }
        do {
            let suggestion = try JSONDecoder().decode(ProactiveSuggestion.self, from: jsonData)
            // Show newest suggestion, drop any unseen older one
            currentSuggestion = suggestion
            print("[ChatViewModel] Suggestion received: \(suggestion.title) (source: \(suggestion.source.rawValue))")
        } catch {
            print("[ChatViewModel] Failed to decode suggestion: \(error)")
        }
    }

    func acceptSuggestion() {
        guard let suggestion = currentSuggestion else { return }
        consecutiveDismissals = 0
        respondToSuggestion(suggestion: suggestion, action: "accept")
        currentSuggestion = nil
    }

    func dismissSuggestion() {
        guard let suggestion = currentSuggestion else { return }
        consecutiveDismissals += 1
        respondToSuggestion(suggestion: suggestion, action: "dismiss")
        currentSuggestion = nil
    }

    func tellMeMore() {
        guard let suggestion = currentSuggestion else { return }
        // Send a message asking the twin to explain the suggestion
        let explainPrompt = "Explain why you suggested: \"\(suggestion.title)\". "
            + "What's your reasoning? What would you do if I accept?"
        sendMessage(text: explainPrompt)
        currentSuggestion = nil
    }

    private func respondToSuggestion(suggestion: ProactiveSuggestion, action: String) {
        let url = URL(string: ServerConfig.suggestionRespondEndpoint)!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let payload: [String: Any] = [
            "suggestion_id": suggestion.id,
            "action": action,
            "description": suggestion.description,
        ]
        request.httpBody = try? JSONSerialization.data(withJSONObject: payload)

        URLSession.shared.dataTask(with: request) { data, _, error in
            if let error = error {
                print("[ChatViewModel] Suggestion respond error: \(error)")
            }
        }.resume()
    }

    // MARK: - Persistent /events SSE Connection

    private var eventsStreamStarted = false

    /// Start the /events SSE connection. Called after orchestrator is confirmed running.
    func startEventsStream() {
        guard !eventsStreamStarted else { return }
        eventsStreamStarted = true
        connectToEventsStream()
    }

    private func connectToEventsStream() {
        let url = URL(string: ServerConfig.eventsEndpoint)!
        var request = URLRequest(url: url)
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")

        eventsTask?.cancel()
        eventsTask = eventsSession.dataTask(with: request)
        eventsTask?.resume()
        print("[ChatViewModel] Connecting to /events stream")
    }

    func handleEventsStreamComplete() {
        // Persistent stream closed, reconnect after delay
        scheduleEventsReconnect()
    }

    func handleEventsStreamError(_ error: Error) {
        if (error as NSError).code == NSURLErrorCancelled { return }
        scheduleEventsReconnect()
    }

    private func scheduleEventsReconnect() {
        eventsReconnectTimer?.invalidate()
        eventsReconnectTimer = Timer.scheduledTimer(withTimeInterval: 3.0, repeats: false) { [weak self] _ in
            Task { @MainActor in
                self?.connectToEventsStream()
            }
        }
    }

    // MARK: - Token Streaming

    private func appendTokenToCurrentTwinMessage(_ token: String) {
        if let existingID = currentTwinMessageID,
           let index = messages.firstIndex(where: { $0.id == existingID }) {
            // Append to existing message
            if case .text(let existingText) = messages[index].content {
                messages[index].content = .text(existingText + token)
            }
        } else {
            // Create a new Twin message
            let newMessage = ChatMessage(
                id: UUID(),
                sender: .twin,
                content: .text(token),
                timestamp: Date()
            )
            currentTwinMessageID = newMessage.id
            messages.append(newMessage)
        }

        // Subtle typing click every ~5th character
        audioManager.incrementTypingCounter()
    }

    // MARK: - Tool Call / Result (internal — never rendered as pills)

    /// Tool calls are internal actions. This defensive path only maps them to
    /// a generic activity status; it never creates tool-call messages, so tool
    /// names and arguments can never appear in the chat.
    private func handleToolCall(data: String) {
        // Finalize any in-progress twin message
        currentTwinMessageID = nil
        handleActivity(data: data)
    }

    private func handleToolProgress(data: String) {
        // Progress details are internal — nothing to display.
    }

    private func handleToolResult(data: String) {
        // Tool completed — internal. Progress nudges forward only.
        taskProgress = min(0.9, taskProgress + 0.15)
    }

    // MARK: - Activity (sanitized status from the Response Formatter)

    /// Coarse, user-safe status: {"category": "computer|productivity|...", "label": "..."}
    /// Tool names, arguments and JSON never reach the UI.
    private func handleActivity(data: String) {
        guard let jsonData = data.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any] else {
            return
        }

        // Each activity nudges the progress bar forward (capped at 0.85)
        taskProgress = taskProgress < 0.2 ? 0.2 : min(0.85, taskProgress + 0.08)

        let category = json["category"] as? String ?? ""
        let label = json["label"] as? String ?? ""

        // Update the live status line with a generic human label.
        if !label.isEmpty {
            statusText = label + "…"
        } else if statusText.isEmpty || statusText == "Thinking…" {
            // Category fallback so the status line never goes blank mid-task.
            switch category {
            case "search": statusText = "Searching…"
            case "computer": statusText = "Working on your Mac…"
            case "writing", "productivity": statusText = "Writing…"
            default: statusText = "Working…"
            }
        }
    }

    // MARK: - Chat History Persistence

    private static var historyFileURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".fol", isDirectory: true)
            .appendingPathComponent("chat_history.json")
    }

    /// Persist only the text conversation (user/twin bubbles). Tool pills and
    /// A2UI cards are execution artifacts — restoring them adds noise, not context.
    private func persistMessages() {
        let textMessages = messages.compactMap { message -> ChatMessage? in
            if case .text = message.content { return message }
            return nil
        }
        let toSave = Array(textMessages.suffix(Self.maxPersistedMessages))
        guard let data = try? JSONEncoder().encode(toSave) else { return }
        do {
            let url = Self.historyFileURL
            try FileManager.default.createDirectory(
                at: url.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try data.write(to: url, options: [.atomic])
        } catch {
            print("[ChatViewModel] Failed to persist chat history: \(error)")
        }
    }

    private static func loadPersistedMessages() -> [ChatMessage]? {
        let url = historyFileURL
        guard let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode([ChatMessage].self, from: data)
    }

    /// Briefly show "Done", then let the status line go back to idle.
    private func scheduleStatusClear() {
        statusClearTask?.cancel()
        statusClearTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(2.5))
            guard !Task.isCancelled else { return }
            self?.statusText = ""
        }
    }

    // MARK: - Component Handling

    private func handleComponent(data: String) {
        // Finalize any in-progress twin text message
        currentTwinMessageID = nil

        guard let jsonData = data.data(using: .utf8) else {
            print("[A2UI] Failed to convert data string to UTF-8")
            return
        }

        // Parse the A2UI payload from {"a2ui": {...}}
        if let json = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any],
           let a2uiDict = json["a2ui"] {
            // Re-serialize the a2ui sub-object and decode
            if let a2uiData = try? JSONSerialization.data(withJSONObject: a2uiDict) {
                do {
                    let payload = try JSONDecoder().decode(A2UIPayload.self, from: a2uiData)
                    print("[A2UI] Decoded payload: \(payload.components.count) components")
                    for comp in payload.components {
                        print("[A2UI]   Component: type=\(comp.type), props=\(comp.properties.keys.sorted())")
                    }
                    appendComponentMessage(payload: payload)
                    return
                } catch {
                    print("[A2UI] Decode error from a2ui sub-object: \(error)")
                }
            }
        }

        // Fallback: try parsing the entire data as A2UI directly
        do {
            let payload = try JSONDecoder().decode(A2UIPayload.self, from: jsonData)
            print("[A2UI] Decoded payload (direct): \(payload.components.count) components")
            appendComponentMessage(payload: payload)
        } catch {
            print("[A2UI] All decode attempts failed: \(error)")
            // Last resort: show as text
            let msg = ChatMessage(
                id: UUID(),
                sender: .twin,
                content: .text("[Component failed to render]"),
                timestamp: Date()
            )
            messages.append(msg)
        }
    }

    private func appendComponentMessage(payload: A2UIPayload) {
        let msg = ChatMessage(
            id: UUID(),
            sender: .twin,
            content: .component(payload),
            timestamp: Date()
        )
        messages.append(msg)
    }

    /// Send a component action as a chat message back to the orchestrator.
    func sendComponentAction(actionId: String, context: String) {
        sendMessage(text: context)
    }

    // MARK: - Connection Management

    func handleStreamComplete() {
        currentTwinMessageID = nil
        if twinState == .thinking || twinState == .working {
            twinState = .idle
            taskProgress = 1.0
            statusText = ""
        }
    }

    func handleStreamError(_ error: Error) {
        isConnected = false
        currentTwinMessageID = nil

        // Always reset twinState so the input field re-enables.
        // This must run BEFORE the cancelled check so even cancelled tasks
        // don't leave twinState stuck in .thinking/.working.
        if twinState == .thinking || twinState == .working {
            twinState = .idle
        }

        // Don't show error for cancelled tasks (intentional disconnects)
        if (error as NSError).code == NSURLErrorCancelled { return }

        // Show a friendly error in the chat so the user knows the server didn't respond.
        // Without this, the user message disappears into the void with no feedback.
        let friendlyMessage: String
        switch (error as NSError).code {
        case NSURLErrorCannotConnectToHost, NSURLErrorDNSLookupFailed:
            friendlyMessage = "⚠️ Can't reach FOL. Click the brain icon in menu bar to check if the service is running."
        case NSURLErrorTimedOut:
            friendlyMessage = "⚠️ FOL took too long to respond. Please try again."
        default:
            friendlyMessage = "⚠️ Connection issue: \(error.localizedDescription)"
        }
        let errorMessage = ChatMessage(
            id: UUID(),
            sender: .twin,
            content: .text(friendlyMessage),
            timestamp: Date()
        )
        lastErrorMessageID = errorMessage.id
        messages.append(errorMessage)

        // Schedule reconnection attempt
        scheduleReconnect()
    }

    private func scheduleReconnect() {
        reconnectTimer?.invalidate()
        reconnectTimer = Timer.scheduledTimer(withTimeInterval: 3.0, repeats: false) { [weak self] _ in
            Task { @MainActor in
                self?.isConnected = false
                // Will reconnect on next sendMessage call
            }
        }
    }

    // MARK: - Voice Input

    // MARK: - TTS (JARVIS Voice)

    /// Check if ElevenLabs API key is present for TTS.
    func checkTTSAvailability() {
        hasTTS = ttsService.hasAPIKey
    }

    /// Speak the most recent twin text message with JARVIS voice.
    /// Only speaks if:
    /// - TTS API key is available
    /// - The last message is a text message from the twin
    /// - The text is at least 3 words long (avoid short acknowledgements)
    /// Toggle JARVIS mute — silences both voice TTS and sound effects.
    func toggleMute() {
        isMuted.toggle()
        audioManager.isMuted = isMuted
        if isMuted { audioManager.stopAll() }
    }

    /// Update JARVIS master volume (0.0–1.0).
    func setVolume(_ newVolume: Float) {
        jarvisVolume = newVolume
        audioManager.volume = newVolume
    }

    private func speakLastTwinMessage() {
        guard hasTTS, !isMuted else { return }

        // Find the last twin text message
        guard let lastTwinMsg = messages.last(where: { $0.sender == .twin }) else { return }

        guard case .text(let text) = lastTwinMsg.content else { return }

        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let wordCount = trimmed.split(separator: " ").count

        // Don't speak very short responses or empty text
        guard wordCount >= 3 else { return }

        Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                let audioData = try await self.ttsService.speak(text: trimmed)
                self.audioManager.playTTSAudio(data: audioData)
            } catch {
                self.voiceLogger.warning("TTS failed: \(error.localizedDescription)")
            }
        }
    }

    /// Check if any STT path is available: OpenAI Whisper, ElevenLabs, or the
    /// local FOL backend (/api/stt with mlx-whisper — no key needed).
    /// The mic button must NOT require a paid cloud key: in local mode the app
    /// launches the FOL server itself, so voice input works out of the box.
    func checkVoiceAvailability() {
        let hasCloud = speechService.hasAPIKey || ttsService.hasAPIKey
        if hasCloud {
            voiceState = .idle
            return
        }
        // No cloud key — probe the local FOL STT backend (retries while the
        // server boots). Hidden only if there is genuinely no STT path.
        voiceState = .hidden
        Task { @MainActor [weak self] in
            let reachable = await LocalSTTService.backendReachable()
            self?.voiceState = reachable ? .idle : .hidden
            if !reachable {
                self?.voiceLogger.warning("Voice hidden: no cloud STT key and FOL backend unreachable")
            }
        }
    }

    /// Pre-flight mic permission check. Call on VoiceInputButton appear.
    func checkMicPermission() {
        guard voiceState != .hidden else { return }
        audioRecorder.checkPermission()
        switch audioRecorder.permissionState {
        case .notDetermined:
            voiceState = .permissionNeeded
        case .authorized:
            if voiceState == .permissionNeeded { voiceState = .idle }
        case .denied:
            voiceState = .permissionNeeded
        }
    }

    /// Request mic permission (from a tap, NOT during hold gesture).
    @MainActor
    func requestMicPermission() {
        audioRecorder.requestPermission { [weak self] granted in
            guard let self else { return }
            if granted {
                self.voiceState = .idle
            } else {
                self.setVoiceError("Microphone access denied. Enable in System Settings > Privacy.")
            }
        }
    }

    // MARK: - Haptic Feedback

    /// Trigger a subtle haptic tap on Force Touch trackpads.
    /// Silently no-ops on non-haptic hardware (Magic Mouse, regular mice).
    private static func playHaptic(_ pattern: NSHapticFeedbackManager.FeedbackPattern) {
        NSHapticFeedbackManager.defaultPerformer.perform(pattern, performanceTime: .default)
    }

    // MARK: - Continuous Haptic During Recording

    /// Schedule the next haptic tick at an interval that varies with audio level.
    /// Louder voice → faster ticks → perceived as more intense haptic feedback.
    /// The timer re-schedules itself, naturally adapting to level changes.
    private func scheduleHapticTick() {
        let level = audioLevel

        let interval: TimeInterval
        if level < hapticSilenceThreshold {
            interval = 0.4 // slow check — barely audible, minimal haptic
        } else if level < hapticGentleThreshold {
            interval = 0.3 // gentle pulse
        } else if level < hapticModerateThreshold {
            interval = 0.18 // moderate pace
        } else {
            interval = 0.09 // fast — feels intense
        }

        hapticTimer?.invalidate()
        hapticTimer = Timer.scheduledTimer(withTimeInterval: interval, repeats: false) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.voiceState == .recording else { return }

                let currentLevel = self.audioLevel
                if currentLevel >= self.hapticGentleThreshold {
                    // Use stronger pattern at high levels for intensity variation
                    let pattern: NSHapticFeedbackManager.FeedbackPattern
                    if currentLevel > self.hapticModerateThreshold {
                        pattern = .levelChange  // stronger bump
                    } else {
                        pattern = .generic      // lighter tap
                    }
                    Self.playHaptic(pattern)
                }
                self.scheduleHapticTick()
            }
        }
    }

    private func startHapticTimer() {
        stopHapticTimer()
        scheduleHapticTick()
    }

    private func stopHapticTimer() {
        hapticTimer?.invalidate()
        hapticTimer = nil
    }

    /// Start recording audio.
    /// Checks mic permission FIRST — won't enter .recording state if not authorized.
    func startRecording() {
        guard voiceState == .idle else { return }

        // Interrupt any JARVIS speech so the mic picks up the user, not the Twin.
        audioManager.stopTTS()

        // Check permission BEFORE setting voiceState, so we don't get stuck
        // in .recording with no actual audio being captured.
        audioRecorder.checkPermission()
        guard audioRecorder.permissionState == .authorized else {
            voiceLogger.warning("Cannot record: mic not authorized (state: \(self.audioRecorder.permissionState))")
            if audioRecorder.permissionState == .notDetermined {
                requestMicPermission()
            } else {
                setVoiceError("Microphone access denied. Enable in System Settings > Privacy & Security > Microphone.")
            }
            return
        }

        audioRecorder.startRecording()
        voiceState = .recording
        // Island status: the assistant is listening (only when idle — during a
        // running task the task status stays on screen).
        if twinState == .idle || twinState == .complete || twinState == .cancelled || twinState == .error {
            statusClearTask?.cancel()
            statusText = "Listening…"
        }
        Self.playHaptic(.generic)
        audioManager.playRecordingChime()
        startHapticTimer()
        voiceLogger.info("Recording started")
    }

    /// Stop recording and begin transcription.
    func stopRecording() {
        guard voiceState == .recording else { return }
        stopHapticTimer()  // stop continuous haptics

        guard let fileURL = audioRecorder.stopRecording() else {
            setVoiceError("Hold longer to record")
            return
        }

        voiceState = .transcribing
        if statusText == "Listening…" {
            statusText = "Transcribing…"
        }
        currentTranscriptionFile = fileURL
        Self.playHaptic(.levelChange)  // subtle bump — recording disengaged
        voiceLogger.info("Voice recording stopped, transcribing...")

        Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                let text = try await self.transcribeWithAvailableSTT(fileURL: fileURL)
                self.handleTranscription(text: text)
            } catch let error as SpeechService.STTError {
                self.setVoiceError(error.errorDescription ?? "Transcription failed")
            } catch let error as ElevenLabsService.STTError {
                self.setVoiceError(error.errorDescription ?? "Transcription failed")
            } catch let error as LocalSTTService.STTError {
                self.setVoiceError(error.errorDescription ?? "Transcription failed")
            } catch {
                self.setVoiceError("Transcription failed")
            }
            // Clean up the audio file
            if let file = self.currentTranscriptionFile {
                self.audioRecorder.cleanUpFile(at: file)
                self.currentTranscriptionFile = nil
            }
        }
    }

    /// Cancel an active recording without transcribing.
    func cancelVoiceRecording() {
        stopHapticTimer()  // stop continuous haptics
        voiceErrorTimer?.cancel()
        voiceErrorTimer = nil

        if voiceState == .recording {
            audioRecorder.cancelRecording()
            voiceLogger.info("Voice recording cancelled")
        }

        // Clean up any in-flight transcription file
        if let file = currentTranscriptionFile {
            audioRecorder.cleanUpFile(at: file)
            currentTranscriptionFile = nil
        }

        // Clear voice statuses if they're still on screen
        if statusText == "Listening…" || statusText == "Transcribing…" {
            statusText = ""
        }

        // Reset to idle (or hidden if no key)
        let hasSTT = speechService.hasAPIKey || ttsService.hasAPIKey
        voiceState = hasSTT ? .idle : .hidden
    }

    /// Transcribe audio using the first available STT service.
    /// Prefers OpenAI Whisper; falls back to ElevenLabs Scribe; finally the
    /// local FOL backend (/api/stt with mlx-whisper) so voice works without
    /// any cloud key.
    private func transcribeWithAvailableSTT(fileURL: URL) async throws -> String {
        if speechService.hasAPIKey {
            return try await speechService.transcribe(fileURL: fileURL)
        }
        if ttsService.hasAPIKey {
            return try await ttsService.transcribe(fileURL: fileURL)
        }
        return try await localSTTService.transcribe(fileURL: fileURL)
    }

    private func handleTranscription(text: String) {
        sendMessage(text: text)
        voiceState = .idle
        voiceLogger.info("Voice message sent: \(text.prefix(40))...")
    }

    private func setVoiceError(_ message: String) {
        voiceState = .error(message)
        voiceLogger.warning("Voice error: \(message)")

        // Auto-clear error after 2 seconds
        voiceErrorTimer?.cancel()
        voiceErrorTimer = Task {
            try? await Task.sleep(for: .seconds(2))
            if case .error = voiceState {
                voiceState = .idle
            }
        }
    }

    deinit {
        sseTask?.cancel()
        eventsTask?.cancel()
        voiceErrorTimer?.cancel()
        // reconnectTimer & eventsReconnectTimer use [weak self] closures,
        // so omitting invalidation here is safe — they'll fire harmlessly
        // or be deallocated naturally.
    }
}

// MARK: - SSE URLSession Delegate (per-request /chat)

/// Custom delegate that receives streaming data and parses SSE events.
@MainActor
final class SSESessionDelegate: NSObject, @preconcurrency URLSessionDataDelegate {
    private weak var viewModel: ChatViewModel?
    private let parser = SSEParser()

    init(viewModel: ChatViewModel) {
        self.viewModel = viewModel
        super.init()
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        guard let text = String(data: data, encoding: .utf8) else { return }

        let events = parser.parse(chunk: text)
        for event in events {
            viewModel?.handleSSEEvent(eventType: event.eventType, data: event.data)
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let error = error {
            viewModel?.handleStreamError(error)
        } else {
            viewModel?.handleStreamComplete()
        }
    }

    func urlSession(
        _ session: URLSession,
        dataTask: URLSessionDataTask,
        didReceive response: URLResponse,
        completionHandler: @escaping (URLSession.ResponseDisposition) -> Void
    ) {
        // Accept the response and continue receiving data
        completionHandler(.allow)

        if let httpResponse = response as? HTTPURLResponse {
Task { @MainActor [weak self] in
                self?.viewModel?.isConnected = (httpResponse.statusCode == 200)
            }
        }
    }
}

// MARK: - Events SSE Delegate (persistent /events)

/// Separate delegate for the persistent /events SSE connection.
/// Routes suggestion events to the same ChatViewModel.
@MainActor
final class EventsSSEDelegate: NSObject, @preconcurrency URLSessionDataDelegate {
    private weak var viewModel: ChatViewModel?
    private let parser = SSEParser()

    init(viewModel: ChatViewModel) {
        self.viewModel = viewModel
        super.init()
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        guard let text = String(data: data, encoding: .utf8) else { return }

        let events = parser.parse(chunk: text)
        for event in events {
            // Route suggestion events through the same handler
            viewModel?.handleSSEEvent(eventType: event.eventType, data: event.data)
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let error = error {
            viewModel?.handleEventsStreamError(error)
        } else {
            viewModel?.handleEventsStreamComplete()
        }
    }

    func urlSession(
        _ session: URLSession,
        dataTask: URLSessionDataTask,
        didReceive response: URLResponse,
        completionHandler: @escaping (URLSession.ResponseDisposition) -> Void
    ) {
        completionHandler(.allow)
    }
}
