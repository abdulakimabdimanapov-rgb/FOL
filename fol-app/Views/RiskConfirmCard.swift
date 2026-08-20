import SwiftUI
import AppKit

// MARK: - Risk Confirm Card

/// Animated confirmation card for Level 4 (CONFIRM) risk actions.
/// Used for file mutations: write_file, send_email, create_event, etc.
/// Shows risk level, action details, and requires explicit approval.
struct RiskConfirmCard: View {
    let actionId: String
    let toolName: String
    let actionDescription: String
    let riskLevel: RiskLevel
    let onAllow: () -> Void
    let onDeny: () -> Void
    
    /// Custom timeout override (optional). If nil, uses RiskTimeoutConfig.confirmAutoDeny.
    let customTimeout: TimeInterval?
    
    @State private var hasActed = false
    @State private var wasAllowed = false
    @State private var isVisible = false
    @State private var glowOpacity: Double = 0
    @State private var timeRemaining: Int = 0
    @State private var isCountingDown = false
    
    /// Timer for countdown
    let timer = Timer.publish(every: 1, on: .main, in: .common).autoconnect()
    
    /// Auto-deny timeout in seconds.
    private var autoDenyTimeout: TimeInterval {
        customTimeout ?? RiskTimeoutConfig.confirmAutoDeny
    }
    
    /// Warning threshold in seconds.
    private var warningThreshold: TimeInterval {
        RiskTimeoutConfig.confirmWarningThreshold
    }
    
    /// Initializer with optional timeout.
    init(
        actionId: String,
        toolName: String,
        actionDescription: String,
        riskLevel: RiskLevel,
        onAllow: @escaping () -> Void,
        onDeny: @escaping () -> Void,
        customTimeout: TimeInterval? = nil
    ) {
        self.actionId = actionId
        self.toolName = toolName
        self.actionDescription = actionDescription
        self.riskLevel = riskLevel
        self.onAllow = onAllow
        self.onDeny = onDeny
        self.customTimeout = customTimeout
    }
    
    enum RiskLevel: String {
        case fileMutation = "File Mutation"
        case dataSend = "Data Send"
        case eventMutation = "Event Mutation"
        case memoryWrite = "Memory Write"
        
        var icon: String {
            switch self {
            case .fileMutation: return "doc.badge.plus"
            case .dataSend: return "envelope.badge.fill"
            case .eventMutation: return "calendar.badge.exclamationmark"
            case .memoryWrite: return "brain.head.profile"
            }
        }
        
        var color: Color {
            switch self {
            case .fileMutation: return Color(hex: 0xFF9F0A)  // Orange
            case .dataSend: return Color(hex: 0xFF453A)      // Red
            case .eventMutation: return Color(hex: 0xBF5AF2) // Purple
            case .memoryWrite: return Color.ssTwinGreen       // Olive
            }
        }
    }
    
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            // Header with risk level badge
            HStack(spacing: 8) {
                // Animated risk icon
                Image(systemName: riskLevel.icon)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundColor(riskLevel.color)
                    .scaleEffect(isVisible ? 1.0 : 0.3)
                    .animation(.ssContentReveal.delay(0.1), value: isVisible)
                
                VStack(alignment: .leading, spacing: 2) {
                    Text("Confirmation Required")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundColor(Color.ssTextPrimary)
                    
                    Text(riskLevel.rawValue)
                        .font(.system(size: 10, weight: .medium, design: .monospaced))
                        .foregroundColor(riskLevel.color)
                }
                
                Spacer()
                
                // Countdown badge (if enabled)
                if RiskTimeoutConfig.showCountdownBadge && !hasActed && isCountingDown {
                    Text("\(timeRemaining)s")
                        .font(.system(size: 10, weight: .bold, design: .monospaced))
                        .foregroundColor(timeRemaining <= Int(warningThreshold) ? riskLevel.color : Color.ssTextSecondary)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 3)
                        .background(
                            Capsule()
                                .fill(riskLevel.color.opacity(timeRemaining <= Int(warningThreshold) ? 0.2 : 0.1))
                        )
                        .animation(.easeInOut, value: timeRemaining)
                }
                
                // Risk level indicator (animated dots)
                HStack(spacing: 3) {
                    ForEach(0..<5, id: \.self) { index in
                        Circle()
                            .fill(index < 4 ? riskLevel.color : riskLevel.color.opacity(0.3))
                            .frame(width: 5, height: 5)
                            .scaleEffect(isVisible ? 1.0 : 0.0)
                            .animation(.ssContentReveal.delay(Double(index) * 0.05), value: isVisible)
                    }
                }
            }
            
            // Action description
            Text(actionDescription)
                .font(.system(size: 13))
                .foregroundColor(Color.ssTextPrimary)
                .fixedSize(horizontal: false, vertical: true)
                .opacity(isVisible ? 1.0 : 0)
                .animation(.ssContentReveal.delay(0.2), value: isVisible)
            
            // Tool name (subtle)
            Text("Tool: \(toolName)")
                .font(.system(size: 10, design: .monospaced))
                .foregroundColor(Color.ssTextSecondary.opacity(0.7))
                .opacity(isVisible ? 1.0 : 0)
                .animation(.ssContentReveal.delay(0.25), value: isVisible)
            
            if !hasActed {
                // Action buttons
                HStack(spacing: 10) {
                    Button(action: handleAllow) {
                        HStack(spacing: 5) {
                            Image(systemName: "checkmark")
                                .font(.system(size: 10, weight: .bold))
                            Text("Allow")
                                .font(.system(size: 11, weight: .semibold))
                        }
                        .foregroundColor(Color.ssBackground)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 7)
                        .background(
                            Capsule().fill(riskLevel.color)
                        )
                    }
                    .buttonStyle(.plain)
                    .scaleEffect(isVisible ? 1.0 : 0.8)
                    .animation(.ssMicro.delay(0.3), value: isVisible)
                    
                    Button(action: handleDeny) {
                        HStack(spacing: 5) {
                            Image(systemName: "xmark")
                                .font(.system(size: 10, weight: .bold))
                            Text("Deny")
                                .font(.system(size: 11, weight: .medium))
                        }
                        .foregroundColor(Color.ssTextSecondary)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 7)
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
                HStack(spacing: 6) {
                    Image(systemName: wasAllowed ? "checkmark.circle.fill" : "xmark.circle.fill")
                        .font(.system(size: 12))
                        .foregroundColor(wasAllowed ? Color.ssSuccess : Color.ssError)
                        .scaleEffect(isVisible ? 1.0 : 0.3)
                        .animation(.ssContentReveal, value: isVisible)
                    
                    Text(wasAllowed ? "Approved" : "Denied")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundColor(Color.ssTextSecondary)
                }
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(Color.ssSurface)
                .overlay(
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(riskLevel.color.opacity(0.4), lineWidth: 1)
                        .shadow(color: riskLevel.color.opacity(glowOpacity), radius: 8, y: 0)
                )
        )
        .onAppear {
            startAnimation()
        }
        .onReceive(timer) { _ in
            guard isCountingDown, !hasActed, timeRemaining > 0 else { return }
            timeRemaining -= 1
            if timeRemaining == 0 {
                handleDeny()
            }
        }
    }
    
    private func startAnimation() {
        // Haptic: lightweight notification for Level 4
        RiskHaptic.peek()
        
        withAnimation(.ssContentReveal) {
            isVisible = true
        }
        
        // Subtle glow pulse
        withAnimation(.ssGlowPulse.repeatForever(autoreverses: true)) {
            glowOpacity = 0.3
        }
        
        // Start countdown
        timeRemaining = Int(autoDenyTimeout)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            isCountingDown = true
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
            glowOpacity = 0
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
            glowOpacity = 0
        }
        onDeny()
    }
}

// MARK: - Preview

#Preview {
    VStack(spacing: 16) {
        RiskConfirmCard(
            actionId: "act_123",
            toolName: "write_file",
            actionDescription: "Write content to /Users/example/document.txt",
            riskLevel: .fileMutation,
            onAllow: {},
            onDeny: {}
        )
        
        RiskConfirmCard(
            actionId: "act_456",
            toolName: "send_email",
            actionDescription: "Send email to john@example.com with subject 'Meeting Update'",
            riskLevel: .dataSend,
            onAllow: {},
            onDeny: {}
        )
    }
    .padding()
    .background(Color.ssBackground)
}
