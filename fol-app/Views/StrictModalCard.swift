import SwiftUI
import AppKit

// MARK: - Haptic Feedback Helper

/// Provides haptic feedback for risk-level actions on macOS.
/// Uses NSHapticFeedbackManager for Taptic Engine feedback.
@MainActor
enum RiskHaptic {
    private nonisolated(unsafe) static let performer = NSHapticFeedbackManager.defaultPerformer
    
    private static func perform(_ pattern: NSHapticFeedbackManager.FeedbackPattern) {
        performer.perform(pattern, performanceTime: .default)
    }
    
    /// Strong warning haptic when a dangerous action modal appears.
    static func warning() {
        perform(.levelChange)
    }
    
    /// Critical alert when countdown reaches 10 seconds.
    static func critical() {
        perform(.alignment)
    }
    
    /// Success haptic when action is approved.
    static func success() {
        perform(.generic)
    }
    
    /// Error/rejection haptic when action is denied.
    static func rejection() {
        perform(.levelChange)
    }
    
    /// Lightweight notification haptic for PEEK level.
    static func peek() {
        perform(.alignment)
    }
}

// MARK: - Strict Modal Card

/// Modal-like card for Level 5 (STRICT_CONFIRM) risk actions.
/// Used for dangerous system operations: shell commands, destructive ops.
/// Features timeout countdown, exact signature verification, and emphasis.
struct StrictModalCard: View {
    let actionId: String
    let toolName: String
    let command: String
    let onAllow: () -> Void
    let onDeny: () -> Void
    
    /// Custom timeout override (optional). If nil, uses RiskTimeoutConfig.strictAutoDeny.
    let customTimeout: TimeInterval?
    
    @State private var hasActed = false
    @State private var wasAllowed = false
    @State private var isVisible = false
    @State private var countdown: Int = 0
    @State private var isCountingDown = false
    @State private var pulseOpacity: Double = 0
    @State private var shakeOffset: CGFloat = 0
    
    /// Timer for countdown
    let timer = Timer.publish(every: 1, on: .main, in: .common).autoconnect()
    
    /// Auto-deny timeout in seconds.
    private var autoDenyTimeout: TimeInterval {
        customTimeout ?? RiskTimeoutConfig.strictAutoDeny
    }
    
    /// Warning threshold in seconds.
    private var warningThreshold: Int {
        Int(RiskTimeoutConfig.strictWarningThreshold)
    }
    
    /// Initializer with optional timeout.
    init(
        actionId: String,
        toolName: String,
        command: String,
        onAllow: @escaping () -> Void,
        onDeny: @escaping () -> Void,
        customTimeout: TimeInterval? = nil
    ) {
        self.actionId = actionId
        self.toolName = toolName
        self.command = command
        self.onAllow = onAllow
        self.onDeny = onDeny
        self.customTimeout = customTimeout
    }
    
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            // Warning header with pulsing icon
            HStack(spacing: 10) {
                // Animated warning icon
                Image(systemName: "exclamationmark.shield.fill")
                    .font(.system(size: 18, weight: .bold))
                    .foregroundColor(Color(hex: 0xFF453A))
                    .scaleEffect(isVisible ? 1.0 : 0.3)
                    .animation(.ssContentReveal, value: isVisible)
                    .opacity(pulseOpacity)
                    .animation(.ssGlowPulse.repeatForever(autoreverses: true), value: pulseOpacity)
                
                VStack(alignment: .leading, spacing: 2) {
                    Text("SYSTEM-LEVEL ACTION")
                        .font(.system(size: 12, weight: .bold, design: .monospaced))
                        .foregroundColor(Color(hex: 0xFF453A))
                        .tracking(0.5)
                    
                    Text("Requires explicit confirmation")
                        .font(.system(size: 10))
                        .foregroundColor(Color.ssTextSecondary)
                }
                
                Spacer()
                
                // Countdown badge
                if RiskTimeoutConfig.showCountdownBadge && !hasActed && isCountingDown {
                    Text("\(countdown)s")
                        .font(.system(size: 11, weight: .bold, design: .monospaced))
                        .foregroundColor(countdown <= warningThreshold ? Color(hex: 0xFF453A) : Color.ssTextSecondary)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(
                            Capsule()
                                .fill(Color(hex: 0xFF453A).opacity(countdown <= warningThreshold ? 0.2 : 0.1))
                        )
                        .animation(.easeInOut, value: countdown)
                }
            }
            
            // Command display (monospaced, highlighted)
            VStack(alignment: .leading, spacing: 4) {
                Text("Command:")
                    .font(.system(size: 10, weight: .medium))
                    .foregroundColor(Color.ssTextSecondary)
                
                Text(command)
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundColor(Color.ssTextPrimary)
                    .padding(8)
                    .background(
                        RoundedRectangle(cornerRadius: 6)
                            .fill(Color.ssBackground)
                            .overlay(
                                RoundedRectangle(cornerRadius: 6)
                                    .stroke(Color(hex: 0xFF453A).opacity(0.3), lineWidth: 0.5)
                            )
                    )
                    .offset(x: shakeOffset)
            }
            .opacity(isVisible ? 1.0 : 0)
            .animation(.ssContentReveal.delay(0.15), value: isVisible)
            
            // Tool name
            Text("Tool: \(toolName)")
                .font(.system(size: 10, design: .monospaced))
                .foregroundColor(Color.ssTextSecondary.opacity(0.7))
                .opacity(isVisible ? 1.0 : 0)
                .animation(.ssContentReveal.delay(0.2), value: isVisible)
            
            if !hasActed {
                // Action buttons with emphasis
                HStack(spacing: 12) {
                    Button(action: handleAllow) {
                        HStack(spacing: 6) {
                            Image(systemName: "checkmark.shield.fill")
                                .font(.system(size: 11, weight: .bold))
                            Text("Execute")
                                .font(.system(size: 12, weight: .bold))
                        }
                        .foregroundColor(Color.ssBackground)
                        .padding(.horizontal, 18)
                        .padding(.vertical, 8)
                        .background(
                            Capsule().fill(Color(hex: 0xFF453A))
                        )
                    }
                    .buttonStyle(.plain)
                    .scaleEffect(isVisible ? 1.0 : 0.8)
                    .animation(.ssMicro.delay(0.3), value: isVisible)
                    
                    Button(action: handleDeny) {
                        HStack(spacing: 6) {
                            Image(systemName: "xmark.shield.fill")
                                .font(.system(size: 11, weight: .bold))
                            Text("Cancel")
                                .font(.system(size: 12, weight: .semibold))
                        }
                        .foregroundColor(Color.ssTextSecondary)
                        .padding(.horizontal, 18)
                        .padding(.vertical, 8)
                        .background(
                            Capsule()
                                .stroke(Color.ssBorder, lineWidth: 0.5)
                        )
                    }
                    .buttonStyle(.plain)
                    .scaleEffect(isVisible ? 1.0 : 0.8)
                    .animation(.ssMicro.delay(0.35), value: isVisible)
                    
                    Spacer()
                }
            } else {
                // Post-action status
                HStack(spacing: 8) {
                    Image(systemName: wasAllowed ? "checkmark.circle.fill" : "xmark.circle.fill")
                        .font(.system(size: 14))
                        .foregroundColor(wasAllowed ? Color.ssSuccess : Color.ssError)
                        .scaleEffect(isVisible ? 1.0 : 0.3)
                        .animation(.ssContentReveal, value: isVisible)
                    
                    VStack(alignment: .leading, spacing: 2) {
                        Text(wasAllowed ? "Executed" : "Cancelled")
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundColor(Color.ssTextPrimary)
                        
                        if wasAllowed {
                            Text("System operation completed")
                                .font(.system(size: 10))
                                .foregroundColor(Color.ssTextSecondary)
                        }
                    }
                }
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 14)
        .background(
            RoundedRectangle(cornerRadius: 14)
                .fill(Color.ssSurface)
                .overlay(
                    RoundedRectangle(cornerRadius: 14)
                        .stroke(Color(hex: 0xFF453A).opacity(0.5), lineWidth: 1.5)
                        .shadow(color: Color(hex: 0xFF453A).opacity(0.2), radius: 12, y: 0)
                )
        )
        .onAppear {
            startAnimation()
        }
        .onReceive(timer) { _ in
            guard isCountingDown, !hasActed, countdown > 0 else { return }
            countdown -= 1
            // Haptic: critical alert at warning threshold
            if countdown == warningThreshold && RiskTimeoutConfig.strictHapticAtWarning {
                RiskHaptic.critical()
            }
            if countdown == 0 {
                // Haptic: auto-deny feedback
                if RiskTimeoutConfig.strictHapticOnAutoDeny {
                    RiskHaptic.rejection()
                }
                handleDeny()
            }
        }
    }
    
    private func startAnimation() {
        // Haptic: strong warning when modal appears
        RiskHaptic.warning()
        
        withAnimation(.ssContentReveal) {
            isVisible = true
        }
        
        // Start glow pulse
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
            pulseOpacity = 1.0
        }
        
        // Start countdown
        countdown = Int(autoDenyTimeout)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            isCountingDown = true
        }
        
        // Initial shake for emphasis
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
            withAnimation(.easeInOut(duration: 0.1).repeatCount(3, autoreverses: true)) {
                shakeOffset = 3
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                shakeOffset = 0
            }
        }
    }
    
    private func handleAllow() {
        // Haptic: success feedback on approval
        RiskHaptic.success()
        
        timer.upstream.connect().cancel()
        withAnimation(.ssMicro) {
            hasActed = true
            wasAllowed = true
            isCountingDown = false
        }
        onAllow()
    }
    
    private func handleDeny() {
        // Haptic: rejection feedback on denial
        RiskHaptic.rejection()
        
        timer.upstream.connect().cancel()
        withAnimation(.ssMicro) {
            hasActed = true
            wasAllowed = false
            isCountingDown = false
        }
        onDeny()
    }
}

// MARK: - Preview

#Preview {
    VStack(spacing: 16) {
        StrictModalCard(
            actionId: "act_strict_123",
            toolName: "fol_command",
            command: "sudo rm -rf /tmp/important_data",
            onAllow: {},
            onDeny: {}
        )
    }
    .padding()
    .background(Color.ssBackground)
}
