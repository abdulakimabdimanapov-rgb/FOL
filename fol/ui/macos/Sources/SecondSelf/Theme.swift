import SwiftUI

enum Theme {
    // ─── Colors — Dynamic Island inspired ─────────────────────────
    static let panelBackground = Color.black.opacity(0.92)
    static let pillBackground = Color(white: 0.08)
    static let pillBorder = Color(white: 0.2)
    static let primaryText = Color.white
    static let secondaryText = Color(white: 0.55)
    static let accentColor = Color(red: 124/255, green: 92/255, blue: 255/255) // #7c5cff
    static let accentGreen = Color(red: 0.2, green: 0.85, blue: 0.4)
    static let accentBlue = Color(red: 0.3, green: 0.5, blue: 1.0)
    static let accentGlow = Color(red: 124/255, green: 92/255, blue: 255/255).opacity(0.5)
    static let warmGlow = Color(red: 1.0, green: 0.6, blue: 0.3).opacity(0.4)
    static let coolGlow = Color(red: 0.3, green: 0.7, blue: 1.0).opacity(0.4)

    // ─── Dynamic Island Dimensions ────────────────────────────────
    static let collapsedWidth: CGFloat = 220
    static let collapsedHeight: CGFloat = 36
    static let previewWidth: CGFloat = 340
    static let previewHeight: CGFloat = 130
    static let expandedWidth: CGFloat = 420
    static let expandedHeight: CGFloat = 540
    static let cornerRadius: CGFloat = 20
    static let expandedCornerRadius: CGFloat = 22
    static let inputPillHeight: CGFloat = 42

    // ─── Animation Timing ────────────────────────────────────────
    static let breatheDuration: Double = 3.0
    static let pulseDuration: Double = 1.5
    static let expandDuration: Double = 0.35
    static let collapseDuration: Double = 0.3

    // ─── Music Visualization ─────────────────────────────────────
    static let barCount: Int = 5
    static let barWidth: CGFloat = 3
    static let barMinHeight: CGFloat = 4
    static let barMaxHeight: CGFloat = 16
    static let barSpacing: CGFloat = 2

    // ─── Fonts ────────────────────────────────────────────────────
    static let captionFont = Font.system(size: 11, weight: .medium, design: .rounded)
    static let bodyFont = Font.system(size: 13, weight: .regular, design: .rounded)
    static let titleFont = Font.system(size: 14, weight: .semibold, design: .rounded)
    static let largeTitleFont = Font.system(size: 20, weight: .bold, design: .rounded)
}
