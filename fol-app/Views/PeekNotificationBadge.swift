import SwiftUI
import AppKit

// MARK: - Peek Notification Badge

/// Lightweight, auto-dismissing notification for Level 3 (PEEK_CONFIRM) risk actions.
/// Used for interactive GUI actions like clicks, typing, hotkeys.
/// Fades in from the top, auto-dismisses after a short delay.
struct PeekNotificationBadge: View {
    let toolName: String
    let actionDescription: String
    let onDismiss: (() -> Void)?
    
    /// Custom timeout override (optional). If nil, uses RiskTimeoutConfig.peekAutoDismiss.
    let customTimeout: TimeInterval?
    
    @State private var isVisible = false
    @State private var opacity: Double = 0
    @State private var translateY: CGFloat = -20
    
    /// Auto-dismiss delay (seconds) — uses config or custom override.
    private var autoDismissDelay: TimeInterval {
        customTimeout ?? RiskTimeoutConfig.peekAutoDismiss
    }
    
    /// Initializer with optional timeout.
    init(
        toolName: String,
        actionDescription: String,
        onDismiss: (() -> Void)? = nil,
        customTimeout: TimeInterval? = nil
    ) {
        self.toolName = toolName
        self.actionDescription = actionDescription
        self.onDismiss = onDismiss
        self.customTimeout = customTimeout
    }
    
    var body: some View {
        HStack(spacing: 8) {
            // Animated icon
            Image(systemName: "cursorarrow.click.2")
                .font(.system(size: 12, weight: .medium))
                .foregroundColor(Color.ssTwinGreen)
                .scaleEffect(isVisible ? 1.0 : 0.3)
                .animation(.ssContentReveal, value: isVisible)
            
            // Tool name + description
            VStack(alignment: .leading, spacing: 2) {
                Text(toolName)
                    .font(.system(size: 10, weight: .semibold, design: .monospaced))
                    .foregroundColor(Color.ssTwinGreen)
                
                Text(actionDescription)
                    .font(.system(size: 11))
                    .foregroundColor(Color.ssTextSecondary)
                    .lineLimit(1)
            }
            
            Spacer()
            
            // Auto-dismiss indicator (shrinking bar)
            Capsule()
                .fill(Color.ssTwinGreen.opacity(0.3))
                .frame(width: 30, height: 3)
                .overlay(
                    Capsule()
                        .fill(Color.ssTwinGreen)
                        .frame(width: isVisible ? 0 : 30, height: 3)
                        .animation(.linear(duration: autoDismissDelay), value: isVisible)
                )
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(Color.ssSurface.opacity(0.95))
                .overlay(
                    RoundedRectangle(cornerRadius: 10)
                        .stroke(Color.ssTwinGreen.opacity(0.3), lineWidth: 0.5)
                )
                .shadow(color: Color.ssTwinGreen.opacity(0.15), radius: 8, y: 2)
        )
        .opacity(opacity)
        .offset(y: translateY)
        .onAppear {
            startAnimation()
        }
    }
    
    private func startAnimation() {
        // Haptic: lightweight click for Level 3 peek notification
        RiskHaptic.peek()
        
        // Slide in
        withAnimation(.ssContentReveal) {
            isVisible = true
            opacity = 1.0
            translateY = 0
        }
        
        // Auto-dismiss after delay
        DispatchQueue.main.asyncAfter(deadline: .now() + autoDismissDelay) {
            withAnimation(.ssContentDismiss) {
                isVisible = false
                opacity = 0
                translateY = -10
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                onDismiss?()
            }
        }
    }
}

// MARK: - Preview

#Preview {
    VStack(spacing: 12) {
        PeekNotificationBadge(
            toolName: "click",
            actionDescription: "Clicking at (450, 320)",
            onDismiss: nil
        )
        
        PeekNotificationBadge(
            toolName: "type_text",
            actionDescription: "Typing 'Hello World'",
            onDismiss: nil
        )
    }
    .padding()
    .background(Color.ssBackground)
}
