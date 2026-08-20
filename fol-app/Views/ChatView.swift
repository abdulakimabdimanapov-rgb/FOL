import SwiftUI

// MARK: - Chat View

/// Message list only. Input bar and VNC are handled by NotchViews.
struct ChatView: View {
    @ObservedObject var viewModel: ChatViewModel

    var body: some View {
        ZStack(alignment: .top) {
            VStack(spacing: 0) {
                // Suggestion banner (slides in from top)
                if let suggestion = viewModel.currentSuggestion {
                    SuggestionBanner(
                        suggestion: suggestion,
                        onAccept: { viewModel.acceptSuggestion() },
                        onDismiss: { viewModel.dismissSuggestion() },
                        onTellMeMore: { viewModel.tellMeMore() }
                    )
                    .transition(.move(edge: .top).combined(with: .opacity))
                    .padding(.top, 28)
                    .padding(.horizontal, 19)
                    .zIndex(1)
                }

                ScrollViewReader { scrollProxy in
                    ScrollView {
                        LazyVStack(spacing: 12) {
                            ForEach(viewModel.messages) { message in
                                messageView(for: message)
                                    .id(message.id)
                                    .transition(transitionForMessage(message))
                            }

                            let showStatus = viewModel.twinState == .thinking
                                || viewModel.twinState == .working
                                || !viewModel.statusText.isEmpty
                            if showStatus {
                                HStack(spacing: 8) {
                                    TwinWorkingIndicator(
                                        statusText: viewModel.statusText,
                                        isDone: viewModel.statusText == "Done"
                                    )

                                    if viewModel.twinState == .thinking || viewModel.twinState == .working {
                                        Button(action: { viewModel.interruptTask() }) {
                                            Image(systemName: "stop.fill")
                                                .font(.system(size: 11, weight: .bold))
                                                .foregroundColor(.white)
                                                .frame(width: 26, height: 26)
                                                .background(Circle().fill(Color.white.opacity(0.15)))
                                                .contentShape(Circle())
                                        }
                                        .buttonStyle(.plain)
                                        .help("Stop")
                                        .transition(.scale.combined(with: .opacity))
                                    }
                                }
                                .id("working-indicator")
                                .transition(.opacity.combined(with: .scale(scale: 0.97)))
                            }
                        }
                    }
                    .padding(.horizontal, 19)
                    .padding(.top, 30)
                    .padding(.bottom, 16)
                    .animation(.ssMessageEntrance, value: viewModel.messages.count)
                    .onAppear {
                        if let lastMessage = viewModel.messages.last {
                            scrollProxy.scrollTo(lastMessage.id, anchor: .bottom)
                        }
                    }
                    .onChange(of: viewModel.messages.count) { _, _ in
                        withAnimation(.ssScrollSpring) {
                            if let lastMessage = viewModel.messages.last {
                                scrollProxy.scrollTo(lastMessage.id, anchor: .bottom)
                            }
                        }
                    }
                }
            }

            // Solid black + fade covering the notch area so content can't peek through
            VStack(spacing: 0) {
                Color.black
                    .frame(height: 16)

                LinearGradient(
                    colors: [.black, .black.opacity(0)],
                    startPoint: .top,
                    endPoint: .bottom
                )
                .frame(height: 8)
            }
            .allowsHitTesting(false)
        }
    }

    @ViewBuilder
    private func messageView(for message: ChatMessage) -> some View {
        switch message.content {
        case .text(let text):
            if message.sender == .twin {
                VStack(alignment: .leading, spacing: 6) {
                    TwinMessageBubble(text: text, timestamp: message.timestamp)
                    if message.id == viewModel.lastErrorMessageID {
                        Button(action: { viewModel.retryLastMessage() }) {
                            Label("Retry", systemImage: "arrow.clockwise")
                                .font(.system(size: 11, weight: .semibold))
                                .foregroundColor(.white)
                                .padding(.horizontal, 12)
                                .padding(.vertical, 5)
                                .background(Capsule().fill(Color.ssTwinOlive))
                        }
                        .buttonStyle(.plain)
                        .help("Retry last request")
                    }
                }
            } else {
                UserMessageBubble(text: text, timestamp: message.timestamp)
            }
        case .toolCall(let tool, let args, let result, let progress):
            ToolCallPill(tool: tool, args: args, result: result, progress: progress)
        case .component(let payload):
            A2UIRenderer(payload: payload, isStreaming: false, onAction: { actionId, context in
                viewModel.sendComponentAction(actionId: actionId, context: context)
            })
        }
    }

    private func transitionForMessage(_ message: ChatMessage) -> AnyTransition {
        switch message.content {
        case .text:
            // Smooth scale + opacity with slight offset for natural feel
            return .asymmetric(
                insertion: .opacity.combined(with: .scale(scale: 0.95).combined(with: .offset(y: 8))),
                removal: .opacity.combined(with: .scale(scale: 0.95))
            )
        case .toolCall:
            return .asymmetric(
                insertion: .opacity.combined(with: .scale(scale: 0.92)),
                removal: .opacity.combined(with: .scale(scale: 0.92))
            )
        case .component:
            return .asymmetric(
                insertion: .opacity.combined(with: .scale(scale: 0.92)),
                removal: .opacity.combined(with: .scale(scale: 0.92))
            )
        }
    }
}

// MARK: - Twin Working Indicator

/// Animated dots + live status text ("Thinking…" / "Searching…" / "Writing…"),
/// green checkmark once the task is done.
struct TwinWorkingIndicator: View {
    var statusText: String
    var isDone: Bool = false

    @State private var phase: Int = 0

    var body: some View {
        HStack {
            HStack(spacing: 8) {
                if isDone {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundColor(Color(hex: 0x30D158))
                        .transition(.scale.combined(with: .opacity))
                } else {
                    TimelineView(.periodic(from: .now, by: 0.4)) { context in
                        HStack(spacing: 5) {
                            ForEach(0..<3, id: \.self) { index in
                                Circle()
                                    .fill(Color.white.opacity(0.9))
                                    .frame(width: 8, height: 8)
                                    .scaleEffect(index == phase ? 1.15 : 1.0)
                                    .opacity(index == phase ? 1.0 : 0.5)
                                    .animation(.ssMicro, value: phase)
                            }
                        }
                        .onChange(of: context.date) { _, _ in
                            phase = (phase + 1) % 3
                        }
                    }
                }

                if !statusText.isEmpty {
                    Text(statusText)
                        .font(.system(size: 13, weight: .medium))
                        .foregroundColor(.white.opacity(0.9))
                        .lineLimit(1)
                        .id("status-\(statusText)")
                        .transition(.opacity.combined(with: .move(edge: .bottom)))
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(
                RoundedRectangle(cornerRadius: 15)
                    .fill(Color.ssTwinOlive)
            )
            .animation(.spring(response: 0.3, dampingFraction: 0.8), value: statusText)

            Spacer()
        }
    }
}
