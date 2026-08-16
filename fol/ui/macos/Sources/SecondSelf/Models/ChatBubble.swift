import SwiftUI

/// A single message in the chat conversation
struct ChatBubbleMessage: Identifiable, Equatable {
    let id = UUID()
    let role: MessageRole
    let content: String
    let timestamp: Date

    enum MessageRole {
        case user
        case assistant
    }

    static func == (lhs: ChatBubbleMessage, rhs: ChatBubbleMessage) -> Bool {
        lhs.id == rhs.id
    }
}

/// iMessage-style chat bubble view
struct ChatBubble: View {
    let message: ChatBubbleMessage

    var body: some View {
        HStack {
            if message.role == .user {
                Spacer(minLength: 40)
            }

            VStack(alignment: message.role == .user ? .trailing : .leading, spacing: 2) {
                Text(message.content)
                    .font(.system(size: 13, weight: .regular, design: .rounded))
                    .foregroundStyle(message.role == .user ? .white : Theme.primaryText)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(
                        bubbleBackground
                    )
                    .textSelection(.enabled)

                Text(formatTime(message.timestamp))
                    .font(.system(size: 9, weight: .medium, design: .rounded))
                    .foregroundStyle(Theme.secondaryText.opacity(0.5))
                    .padding(.horizontal, 4)
            }

            if message.role == .assistant {
                Spacer(minLength: 40)
            }
        }
    }

    @ViewBuilder
    private var bubbleBackground: some View {
        if message.role == .user {
            Capsule()
                .fill(
                    LinearGradient(
                        colors: [Theme.accentColor, Theme.accentColor.opacity(0.8)],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .shadow(color: Theme.accentColor.opacity(0.2), radius: 4, y: 2)
        } else {
            Capsule()
                .fill(Color(white: 0.12))
                .overlay(
                    Capsule()
                        .strokeBorder(Color.white.opacity(0.06), lineWidth: 0.5)
                )
        }
    }

    private func formatTime(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter.string(from: date)
    }
}

/// Typing indicator with animated dots
struct TypingIndicator: View {
    @State private var dotOffsets: [CGFloat] = [0, 0, 0]

    var body: some View {
        HStack {
            HStack(spacing: 5) {
                ForEach(0..<3, id: \.self) { i in
                    Circle()
                        .fill(Theme.accentColor.opacity(0.6))
                        .frame(width: 6, height: 6)
                        .offset(y: dotOffsets[i])
                        .animation(
                            .easeInOut(duration: 0.4)
                            .repeatForever(autoreverses: true)
                            .delay(Double(i) * 0.15),
                            value: dotOffsets[i]
                        )
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .background(
                Capsule()
                    .fill(Color(white: 0.12))
                    .overlay(
                        Capsule()
                            .strokeBorder(Color.white.opacity(0.06), lineWidth: 0.5)
                    )
            )

            Spacer()
        }
        .onAppear {
            dotOffsets = [4, 4, 4]
        }
    }
}
