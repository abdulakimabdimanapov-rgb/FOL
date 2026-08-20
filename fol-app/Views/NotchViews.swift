import SwiftUI

// MARK: - Expanded Notch Content

/// Switches between status mini view (stage 1) and full chat (stage 2).
/// DynamicNotchKit sees this as one "expanded" view, but we swap content internally.
struct ExpandedNotchContent: View {
    @ObservedObject var chatViewModel: ChatViewModel

    // Medium expansion: cycling status text
    @State private var currentWordIndex = 0
    @State private var dotPulsePhase = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(spacing: 0) {
            if chatViewModel.expansionStage >= 2 {
                fullChatContent
                    .transition(.asymmetric(
                        insertion: .opacity.combined(with: .move(edge: .bottom)),
                        removal: .opacity
                    ))
            } else {
                statusMiniContent
                    .transition(.asymmetric(
                        insertion: .opacity,
                        removal: .opacity.combined(with: .move(edge: .bottom))
                    ))
            }
        }
        .animation(.ssPanelSpring, value: chatViewModel.expansionStage)
        .environment(\.colorScheme, .dark)
    }

    // MARK: - Stage 1: Medium Expansion Bar (personality bar)

    private var isActiveState: Bool {
        chatViewModel.twinState == .thinking || chatViewModel.twinState == .working
    }

    private var statusMiniContent: some View {
        HStack(spacing: 12) {
            // Status text with crossfade
            ZStack {
                Text(displayText)
                    .font(.system(size: 18, weight: .medium))
                    .foregroundColor(Color.ssTextPrimary)
                    .id(displayText)
                    .transition(.opacity)
            }
            .animation(.ssContentReveal, value: displayText)

            Spacer()

            // Status indicator
            statusIndicator
        }
        .padding(.leading, 14)
        .padding(.trailing, 14)
        .frame(width: 360, height: 56)
        .contentShape(Rectangle())
        .onTapGesture { chatViewModel.onNotchTap?() }
        .task(id: isActiveState) {
            guard isActiveState else {
                withAnimation(.ssMicro) { dotPulsePhase = false }
                return
            }

            // Randomize starting word each time twin becomes active
            currentWordIndex = Int.random(in: 0..<ThinkingWords.all.count)
            withAnimation(.easeInOut(duration: 1.0).repeatForever(autoreverses: true)) {
                dotPulsePhase = true
            }

            // Cycle words every 2.5s while active
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(2.5))
                guard !Task.isCancelled else { break }
                currentWordIndex = (currentWordIndex + 1) % ThinkingWords.all.count
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Twin status: \(accessibilityStatusText)")
    }

    // MARK: - Stage 2: Full Chat

    private var fullChatContent: some View {
        ZStack(alignment: .topTrailing) {
            VStack(spacing: 0) {
                // Chat messages (no header, chat starts immediately)
                ChatView(viewModel: chatViewModel)

                // Mascot + Input bar
                HStack(alignment: .bottom, spacing: 6) {
                    MascotGIFView(width: 32, height: 42)
                        .frame(width: 32, height: 42)
                        .offset(x: -8, y: -4)

                    ChatInputBar(
                        text: $chatViewModel.inputText,
                        isEnabled: chatViewModel.twinState != .thinking && chatViewModel.twinState != .working,
                        voiceState: chatViewModel.voiceState,
                        audioLevel: chatViewModel.audioLevel,
                        isMuted: chatViewModel.isMuted,
                        jarvisVolume: chatViewModel.jarvisVolume,
                        onSend: { text in chatViewModel.sendMessage(text: text) },
                        onTapToRecord: { chatViewModel.startRecording() },
                        onTapToStop: { chatViewModel.stopRecording() },
                        onVoiceCancel: { chatViewModel.cancelVoiceRecording() },
                        onPermissionTap: { chatViewModel.requestMicPermission() },
                        onToggleMute: { chatViewModel.toggleMute() },
                        onVolumeChange: { chatViewModel.setVolume($0) }
                    )
                }
                .padding(.horizontal, 12)
                .padding(.bottom, 8)
                .onAppear { chatViewModel.checkMicPermission() }

            }
            .frame(width: 420, height: 560)
            .background(Color.ssNotchBlack)

            // Sign out button — top right overlay
            Button(action: {
                // FOL doesn't have sign out, just collapse
                chatViewModel.onNotchClose?()
            }) {
                Image(systemName: "rectangle.portrait.and.arrow.right")
                    .font(.system(size: 10))
                    .foregroundColor(.white.opacity(0.25))
            }
            .buttonStyle(.plain)
            .padding(.top, 28)
            .padding(.trailing, 16)
        }
    }

    // MARK: - Medium Expansion Helpers

    private var displayText: String {
        if reduceMotion && isActiveState {
            return chatViewModel.twinState == .thinking ? "Thinking..." : "Working..."
        }
        switch chatViewModel.twinState {
        case .thinking, .working:
            return ThinkingWords.all[currentWordIndex % ThinkingWords.all.count]
        case .error:
            return "Oops"
        default:
            return "FOL is Ready!"
        }
    }

    @ViewBuilder
    private var statusIndicator: some View {
        Circle()
            .fill(statusDotColor)
            .frame(width: 5, height: 5)
            .opacity(dotPulsePhase ? 0.3 : 1.0)
    }

    private var statusDotColor: Color {
        if !chatViewModel.isConnected { return Color.ssError }
        switch chatViewModel.twinState {
        case .idle: return Color.ssSuccess
        case .thinking, .working: return Color.ssTwinGreen
        case .complete: return Color.ssSuccess
        case .cancelled: return Color.ssTextSecondary
        case .error: return Color.ssError
        }
    }

    private var accessibilityStatusText: String {
        switch chatViewModel.twinState {
        case .thinking: return "Thinking"
        case .working: return "Working"
        case .error: return "Error"
        default: return "FOL is ready"
        }
    }
}

// MARK: - Compact Leading Content

struct CompactLeadingContent: View {
    @ObservedObject var chatViewModel: ChatViewModel
    @State private var pulsePhase: Bool = false

    var body: some View {
        TwinCharacterView(twinState: chatViewModel.twinState, compact: true)
            .frame(width: 24, height: 24)
            .contentShape(Rectangle())
            .onTapGesture { chatViewModel.onNotchTap?() }
    }
}

// MARK: - Compact Trailing Content

struct CompactTrailingContent: View {
    @ObservedObject var chatViewModel: ChatViewModel
    @State private var showCompletionBadge = false

    var body: some View {
        HStack(spacing: 4) {
            if showCompletionBadge {
                Image(systemName: "checkmark.circle.fill")
                    .font(.system(size: 10))
                    .foregroundColor(Color.ssTwinGreen)
                    .transition(.scale.combined(with: .opacity))
            }

            Circle()
                .fill(chatViewModel.isConnected ? Color.ssSuccess : Color.ssError)
                .frame(width: 8, height: 8)
        }
        .contentShape(Rectangle())
        .onTapGesture { chatViewModel.onNotchTap?() }
        .onChange(of: chatViewModel.twinState) { _, newState in
            if newState == .complete {
                withAnimation(.ssMicro) { showCompletionBadge = true }
                Task {
                    try? await Task.sleep(for: .seconds(2))
                    withAnimation(.ssContentDismiss) { showCompletionBadge = false }
                }
            }
        }
    }
}
