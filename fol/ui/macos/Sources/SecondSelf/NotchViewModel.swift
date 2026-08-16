import SwiftUI

enum PanelState: Sendable {
    case collapsed
    case preview
    case expanded
}

@Observable
@MainActor
final class NotchViewModel {
    var panelState: PanelState = .collapsed
    var previewText: String = "FOL starting..."
    var inputText: String = ""
    var inputPlaceholder: String = "Спроси FOL..."
    var isStatusActive: Bool = false
    var isLoading: Bool = false
    var isSpeaking: Bool = false
    var responseText: String = ""
    var actionsText: String = ""
    var sessionId: String = "fol-default"
    var isOnboarded: Bool = false
    var isRecording: Bool = false
    var isTranscribing: Bool = false

    // Chat history for iMessage-style bubbles
    var chatMessages: [ChatBubbleMessage] = []

    // Camera service
    let cameraService = CameraService()

    private let audioRecorder = AudioRecorder()
    private let tts = TextToSpeech()
    var voiceEnabled: Bool = false
    var currentVoiceName: String = "Daniel"
    var availableVoices: [(name: String, display: String)] = []

    var onStateChange: (@Sendable (PanelState) -> Void)?

    // MARK: - Auto-connect on launch

    func connectOnLaunch() {
        // Load saved voice preferences
        voiceEnabled = UserDefaults.standard.bool(forKey: "fol_voice_enabled")
        let savedVoice = UserDefaults.standard.string(forKey: "fol_voice_name") ?? "Daniel"
        currentVoiceName = savedVoice
        availableVoices = TextToSpeech.availableVoices
        tts.setVoice(savedVoice)

        isLoading = true
        previewText = "Connecting to FOL..."

        Task {
            // Try to connect to FOL server
            do {
                let latest = try await APIClient.shared.fetchLatestSession()
                if latest.found {
                    sessionId = latest.session_id ?? "fol-default"
                    isOnboarded = true
                    isStatusActive = true
                    previewText = "FOL готов — нажми чтобы начать."
                    addAssistantMessage("Привет! Я FOL — твой второй я. Спроси меня о чём угодно.")
                    isLoading = false
                    // Start camera
                    cameraService.startCapture()
                    return
                }
            } catch {
                // Server not running
            }

            // Fallback — try onboarding (creates a local session)
            previewText = "Настройка FOL..."
            do {
                let userName = ProcessInfo.processInfo.environment["USER"] ?? "User"
                let sid = try await APIClient.shared.onboard(name: userName)
                sessionId = sid
                isOnboarded = true
                isStatusActive = true
                previewText = "FOL готов."
                addAssistantMessage("Привет! Я FOL. Чем могу помочь?")
            } catch {
                previewText = "Не могу подключиться к FOL."
                addAssistantMessage("Убедись что сервер запущен. Используй: python run_api_server.py")
            }
            isLoading = false
            // Start camera
            cameraService.startCapture()
        }
    }

    // MARK: - Chat History Management

    func addUserMessage(_ text: String) {
        let msg = ChatBubbleMessage(role: .user, content: text, timestamp: Date())
        chatMessages.append(msg)
        saveConversationToObsidian(userInput: text, role: "user")
    }

    func addAssistantMessage(_ text: String) {
        let msg = ChatBubbleMessage(role: .assistant, content: text, timestamp: Date())
        chatMessages.append(msg)
        saveConversationToObsidian(userInput: text, role: "assistant")
    }

    // MARK: - Obsidian Auto-Save

    private func saveConversationToObsidian(userInput: String, role: String) {
        // Save via the API server's Obsidian integration
        // This runs in background - non-blocking
        Task {
            do {
                let message = role == "user" ? "[User]: \(userInput)" : "[FOL]: \(userInput)"
                let _ = try await APIClient.shared.saveToObsidian(content: message, category: "Conversations")
            } catch {
                // Silent fail - Obsidian save is best-effort
            }
        }
    }

    // MARK: - State Transitions (Dynamic Island style)

    func handleClick() {
        switch panelState {
        case .collapsed:
            panelState = .expanded
        case .preview:
            panelState = .expanded
        case .expanded:
            break
        }
        onStateChange?(panelState)
    }

    func collapse() {
        tts.stop()
        isSpeaking = false
        panelState = .collapsed
        onStateChange?(panelState)
    }

    func toggleExpanded() {
        panelState = panelState == .expanded ? .collapsed : .expanded
        onStateChange?(panelState)
    }

    // MARK: - Voice Input

    func toggleVoiceInput() {
        if isRecording {
            stopVoiceInput()
        } else {
            startVoiceInput()
        }
    }

    func startVoiceInput() {
        isRecording = true
        addAssistantMessage("🎤 Слушаю...")
        previewText = "Говори..."

        Task {
            let started = await audioRecorder.startRecording()
            if !started {
                isRecording = false
                addAssistantMessage("Не удалось получить доступ к микрофону.")
                previewText = "Ошибка микрофона"
            }
        }
    }

    func stopVoiceInput() {
        isRecording = false
        isTranscribing = true
        previewText = "Распознаю..."

        guard let audioURL = audioRecorder.stopRecording() else {
            isTranscribing = false
            addAssistantMessage("Запись не удалась.")
            return
        }

        Task {
            do {
                let text = try await APIClient.shared.transcribeAudio(fileURL: audioURL)
                // Clean up temp file
                try? FileManager.default.removeItem(at: audioURL)

                if text.isEmpty {
                    addAssistantMessage("Не удалось распознать речь.")
                    previewText = "Попробуй ещё раз"
                } else {
                    inputText = text
                    previewText = "Распознано: \(text.prefix(40))"
                    // Auto-send the transcribed text
                    sendMessage()
                }
            } catch {
                addAssistantMessage("Ошибка распознавания: \(error.localizedDescription)")
                previewText = "Ошибка"
            }
            isTranscribing = false
        }
    }

    // MARK: - Voice Output (TTS)

    func toggleVoice() {
        voiceEnabled.toggle()
        if !voiceEnabled {
            tts.stop()
            isSpeaking = false
        }
        UserDefaults.standard.set(voiceEnabled, forKey: "fol_voice_enabled")
    }

    func selectVoice(_ voiceName: String) {
        guard voiceName != currentVoiceName else { return }
        if tts.setVoice(voiceName) {
            currentVoiceName = voiceName
            UserDefaults.standard.set(voiceName, forKey: "fol_voice_name")
        }
    }

    private func speakResponse(_ text: String) {
        guard voiceEnabled, !text.isEmpty else { return }
        isSpeaking = true
        tts.speak(text) { [weak self] in
            Task { @MainActor in
                self?.isSpeaking = false
            }
        }
    }

    // MARK: - Chat

    func sendMessage() {
        let message = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !message.isEmpty else { return }
        guard !isLoading else { return }
        guard isOnboarded else {
            addAssistantMessage("Подожди секунду, идёт подключение...")
            return
        }

        addUserMessage(message)
        inputText = ""
        isLoading = true
        actionsText = ""
        previewText = "Думаю..."

        Task {
            do {
                let result = try await APIClient.shared.sendChatMessage(message, sessionId: sessionId)
                addAssistantMessage(result.response)
                if !result.actions_taken.isEmpty {
                    actionsText = result.actions_taken
                        .map { "[\($0.tool)] \($0.summary)" }
                        .joined(separator: "\n")
                }
                previewText = String(result.response.prefix(80))
                // Speak response if voice is enabled
                speakResponse(result.response)
            } catch {
                addAssistantMessage("Ошибка: \(error.localizedDescription)")
                previewText = "Что-то пошло не так."
            }
            isLoading = false
        }
    }
}
