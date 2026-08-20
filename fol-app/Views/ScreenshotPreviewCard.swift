import SwiftUI
import AppKit

// MARK: - Screenshot Preview Card (Animated)

/// Inline screenshot from the agent's browser, rendered as a card
/// with animated entrance, olive-green glow border, and slide-in caption.
struct ScreenshotPreviewCard: View {
    let data: ScreenshotData

    @State private var decodedImage: NSImage?
    @State private var decodeFailed: Bool = false
    @State private var appeared: Bool = false
    @State private var glowPhase: CGFloat = 0
    @State private var captionOffset: CGFloat = 12
    @State private var captionOpacity: Double = 0

    private let maxBase64Length = 15_000_000  // ~10 MB decoded
    private let maxDecodedBytes = 10_485_760  // 10 MB

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let nsImage = decodedImage {
                // Animated image with scale-in entrance
                Image(nsImage: nsImage)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(maxHeight: 200)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                    .overlay(
                        RoundedRectangle(cornerRadius: 8)
                            .stroke(
                                LinearGradient(
                                    colors: [
                                        Color.ssTwinGreen.opacity(0.3 + glowPhase * 0.4),
                                        Color.ssTwinGreen.opacity(0.1),
                                        Color.ssTwinGreen.opacity(0.3 + glowPhase * 0.4),
                                    ],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                ),
                                lineWidth: 1
                            )
                    )
                    .shadow(color: Color.ssTwinGreen.opacity(0.15 + Double(glowPhase) * 0.15), radius: 8, x: 0, y: 0)
                    .scaleEffect(appeared ? 1.0 : 0.92)
                    .opacity(appeared ? 1.0 : 0)
                    .animation(.ssContentReveal, value: appeared)

            } else if decodeFailed {
                // Broken image fallback
                HStack {
                    Image(systemName: "photo.badge.exclamationmark")
                        .font(.system(size: 20))
                        .foregroundColor(Color.ssTextSecondary)
                    Text("Image unavailable")
                        .font(.system(size: 11))
                        .foregroundColor(Color.ssTextSecondary)
                }
                .frame(maxWidth: .infinity, minHeight: 60)
                .background(
                    RoundedRectangle(cornerRadius: 8)
                        .fill(Color.ssBackground)
                )
            } else {
                // Loading placeholder with shimmer
                RoundedRectangle(cornerRadius: 8)
                    .fill(Color.ssBackground)
                    .frame(maxWidth: .infinity, minHeight: 60, maxHeight: 100)
                    .overlay(
                        ProgressView()
                            .controlSize(.small)
                    )
            }

            // Caption — slides in from below after image loads
            if let caption = data.caption {
                Text(caption)
                    .font(.system(size: 11))
                    .italic()
                    .foregroundColor(Color.ssTextSecondary)
                    .lineLimit(2)
                    .offset(y: captionOffset)
                    .opacity(captionOpacity)
            }
        }
        .padding(10)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(Color.ssSurface)
                .overlay(
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(Color.ssBorder, lineWidth: 0.5)
                )
        )
        .task {
            await decodeImageAsync()
        }
        .onAppear {
            // Start glow pulse animation
            withAnimation(.easeInOut(duration: 2.0).repeatForever(autoreverses: true)) {
                glowPhase = 1.0
            }
        }
    }

    // MARK: - Image Decoding (off main thread + animated entrance)

    private func decodeImageAsync() async {
        let base64 = data.imageBase64
        let maxLen = maxBase64Length
        let maxBytes = maxDecodedBytes
        let result: NSImage? = await Task.detached(priority: .userInitiated) {
            guard base64.count < maxLen,
                  let bytes = Data(base64Encoded: base64),
                  bytes.count < maxBytes else {
                return nil
            }
            return NSImage(data: bytes)
        }.value

        if let image = result {
            decodedImage = image
            // Stagger the animations for a polished entrance
            withAnimation(.ssContentReveal) {
                appeared = true
            }
            // Caption slides in after image
            withAnimation(.ssContentReveal.delay(0.15)) {
                captionOffset = 0
                captionOpacity = 1
            }
        } else {
            decodeFailed = true
        }
    }
}
