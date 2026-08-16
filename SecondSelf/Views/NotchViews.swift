import SwiftUI

// MARK: - Expanded Notch Content

/// Switches between status mini view (stage 1) and full chat (stage 2).
/// No authentication needed — always shows chat in local mode.
struct ExpandedNotchContent: View {
    @ObservedObject var chatViewModel: ChatViewModel

    var body: some View {
        ZStack(alignment: .topTrailing) {
            VStack(spacing: 0) {
                if chatViewModel.needsSetup && chatViewModel.expansionStage >= 2 {
                    // First-run setup wizard
                    SetupWizardView {
                        chatViewModel.needsSetup = false
                    }
                    .transition(.asymmetric(
                        insertion: .opacity.combined(with: .move(edge: .bottom)),
                        removal: .opacity
                    ))
                } else {
                    fullChatContent
                        .transition(.asymmetric(
                            insertion: .opacity.combined(with: .move(edge: .bottom)),
                            removal: .opacity
                        ))
                }
            }
        }
        .animation(.ssPanelSpring, value: chatViewModel.expansionStage)
        .animation(.ssPanelSpring, value: chatViewModel.needsSetup)
        .environment(\.colorScheme, .dark)
        .frame(width: 420, height: 560)
    }

    // MARK: - Stage 2: Full Chat (matches Figma 136:996)

    private var fullChatContent: some View {
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
                    onVolumeChange: { newVolume in chatViewModel.setVolume(newVolume) }
                )
            }
            .padding(.horizontal, 12)
            .padding(.bottom, 8)
            .onAppear { chatViewModel.checkMicPermission() }

            // Bottom lip — show/hide PiP
            Button(action: { chatViewModel.toggleVNCFeed() }) {
                HStack {
                    Spacer()
                    Image(systemName: chatViewModel.showVNCFeed ? "chevron.compact.up" : "chevron.compact.down")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundColor(.white.opacity(0.4))
                    Spacer()
                }
                .frame(height: 26)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
        }
        .background(Color.ssNotchBlack)
    }
}
