import SwiftUI

// MARK: - Twin Message Bubble

struct TwinMessageBubble: View {
    let text: String
    let timestamp: Date

    var body: some View {
        HStack(alignment: .top, spacing: 9) {
            avatar

            VStack(alignment: .leading, spacing: 5) {
                HStack(spacing: 6) {
                    Text("FOL")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundColor(Color.ssCream.opacity(0.78))

                    Text(formattedTime)
                        .font(.system(size: 10, weight: .medium))
                        .foregroundColor(Color.ssTextSecondary.opacity(0.75))
                }

                Text(text)
                    .font(.system(size: 14, weight: .regular))
                    .lineSpacing(3)
                    .foregroundColor(Color.ssTextPrimary)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, 13)
                    .padding(.vertical, 11)
                    .frame(maxWidth: 310, alignment: .leading)
                    .background(
                        RoundedRectangle(cornerRadius: 14, style: .continuous)
                            .fill(Color.ssSurface.opacity(0.96))
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: 14, style: .continuous)
                            .stroke(Color.ssBorder.opacity(0.55), lineWidth: 0.8)
                    )
            }

            Spacer(minLength: 20)
        }
    }

    private var avatar: some View {
        ZStack {
            Circle()
                .fill(
                    LinearGradient(
                        colors: [Color.ssTwinGreen.opacity(0.95), Color.ssCream.opacity(0.78)],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )

            Text("F")
                .font(.system(size: 11, weight: .bold))
                .foregroundColor(.black.opacity(0.78))
        }
        .frame(width: 24, height: 24)
        .padding(.top, 17)
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
