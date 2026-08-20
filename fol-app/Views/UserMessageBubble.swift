import SwiftUI

// MARK: - User Message Bubble

struct UserMessageBubble: View {
    let text: String
    let timestamp: Date

    var body: some View {
        VStack(alignment: .trailing, spacing: 5) {
            HStack(alignment: .bottom, spacing: 0) {
                Spacer(minLength: 54)

                Text(text)
                    .font(.system(size: 14, weight: .regular))
                    .lineSpacing(3)
                    .foregroundColor(.white)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, 13)
                    .padding(.vertical, 10)
                    .frame(maxWidth: 292, alignment: .leading)
                    .background(
                        RoundedRectangle(cornerRadius: 14, style: .continuous)
                            .fill(
                                LinearGradient(
                                    colors: [
                                        Color.ssUserOlive.opacity(0.96),
                                        Color.ssUserOlive.opacity(0.82)
                                    ],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                )
                            )
                    )
            }

            Text(formattedTime)
                .font(.system(size: 10, weight: .medium))
                .foregroundColor(Color.ssTextSecondary.opacity(0.75))
                .padding(.trailing, 2)
        }
    }

    private static let timeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "h:mm a"
        return formatter
    }()

    private var formattedTime: String {
        Self.timeFormatter.string(from: timestamp)
    }
}
