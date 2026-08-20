import SwiftUI

// MARK: - Action Info Card

/// Animated card showing file/code information with a bouncing icon entrance,
/// file details (name, size, type), and an optional diff preview for code changes.
/// Used by the A2UI renderer when the agent performs file or code operations.
struct ActionInfoCard: View {
    let fileName: String
    let fileSize: String?
    let fileType: FileType
    let diffPreview: String?  // unified diff lines, optional
    let caption: String?

    @State private var iconScale: CGFloat = 0.3
    @State private var iconOpacity: Double = 0
    @State private var detailsOffset: CGFloat = 8
    @State private var detailsOpacity: Double = 0
    @State private var diffHeight: CGFloat = 0
    @State private var diffOpacity: Double = 0

    enum FileType: String {
        case code
        case document
        case image
        case audio
        case video
        case archive
        case other

        var icon: String {
            switch self {
            case .code: return "doc.text.fill"
            case .document: return "doc.fill"
            case .image: return "photo.fill"
            case .audio: return "waveform"
            case .video: return "film.fill"
            case .archive: return "archivebox.fill"
            case .other: return "doc.fill"
            }
        }

        var color: Color {
            switch self {
            case .code: return Color.ssTwinGreen
            case .document: return Color.ssCream
            case .image: return Color(hex: 0x5AC8FA)
            case .audio: return Color(hex: 0xFF9F0A)
            case .video: return Color(hex: 0xFF375F)
            case .archive: return Color.ssTextSecondary
            case .other: return Color.ssTextSecondary
            }
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            // Header row: animated icon + file name
            HStack(spacing: 10) {
                // Bouncing file type icon
                Image(systemName: fileType.icon)
                    .font(.system(size: 16, weight: .medium))
                    .foregroundColor(fileType.color)
                    .frame(width: 28, height: 28)
                    .background(
                        RoundedRectangle(cornerRadius: 7)
                            .fill(fileType.color.opacity(0.15))
                    )
                    .scaleEffect(iconScale)
                    .opacity(iconOpacity)

                VStack(alignment: .leading, spacing: 2) {
                    Text(fileName)
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundColor(Color.ssTextPrimary)
                        .lineLimit(1)

                    if let size = fileSize {
                        Text(size)
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundColor(Color.ssTextSecondary)
                    }
                }

                Spacer()
            }
            .offset(y: detailsOffset)
            .opacity(detailsOpacity)

            // Caption
            if let caption = caption {
                Text(caption)
                    .font(.system(size: 11))
                    .foregroundColor(Color.ssTextSecondary)
                    .italic()
                    .offset(y: detailsOffset)
                    .opacity(detailsOpacity)
            }

            // Diff preview (collapsible, animated height)
            if let diff = diffPreview {
                ScrollView(.vertical, showsIndicators: false) {
                    VStack(alignment: .leading, spacing: 1) {
                        ForEach(Array(diff.components(separatedBy: "\n").prefix(12).enumerated()), id: \.offset) { _, line in
                            diffLine(line)
                        }
                        if diff.components(separatedBy: "\n").count > 12 {
                            Text("  … \(diff.components(separatedBy: "\n").count - 12) more lines")
                                .font(.system(size: 9, design: .monospaced))
                                .foregroundColor(Color.ssTextSecondary.opacity(0.6))
                                .padding(.top, 2)
                        }
                    }
                    .font(.system(size: 10, design: .monospaced))
                }
                .frame(maxHeight: 140)
                .padding(6)
                .background(
                    RoundedRectangle(cornerRadius: 6)
                        .fill(Color.ssBackground)
                )
                .clipShape(RoundedRectangle(cornerRadius: 6))
                .frame(maxHeight: diffOpacity > 0 ? .infinity : 0)
                .opacity(diffOpacity)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(Color.ssSurface)
                .overlay(
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(Color.ssBorder, lineWidth: 0.5)
                )
        )
        .onAppear {
            animateEntrance()
        }
    }

    // MARK: - Diff Lines

    @ViewBuilder
    private func diffLine(_ line: String) -> some View {
        let trimmed = line.hasPrefix(" ") ? String(line.dropFirst()) : line
        let isAdded = line.hasPrefix("+")
        let isRemoved = line.hasPrefix("-")
        let isHunk = line.hasPrefix("@@")

        Text(trimmed)
            .foregroundColor(
                isAdded ? Color.ssSuccess :
                isRemoved ? Color.ssError :
                isHunk ? Color.ssTwinGreen.opacity(0.7) :
                Color.ssTextSecondary.opacity(0.7)
            )
            .background(
                isAdded ? Color.ssSuccess.opacity(0.08) :
                isRemoved ? Color.ssError.opacity(0.08) :
                Color.clear
            )
    }

    // MARK: - Animated Entrance

    private func animateEntrance() {
        // Icon bounces in
        withAnimation(.ssMicro) {
            iconScale = 1.0
            iconOpacity = 1.0
        }

        // Details slide in
        withAnimation(.ssContentReveal.delay(0.1)) {
            detailsOffset = 0
            detailsOpacity = 1.0
        }

        // Diff expands
        if diffPreview != nil {
            withAnimation(.ssContentReveal.delay(0.25)) {
                diffOpacity = 1.0
                diffHeight = 140
            }
        }
    }
}
