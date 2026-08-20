import Foundation

// MARK: - Risk Timeout Configuration

/// Centralized timeout configuration for risk-level A2UI components.
/// Each risk level has its own timeout behavior:
/// - Level 3 (PEEK): Auto-dismiss after a short delay (non-blocking)
/// - Level 4 (CONFIRM): Auto-deny after a longer timeout (requires action)
/// - Level 5 (STRICT): Countdown timer with auto-deny (critical action)
enum RiskTimeoutConfig {
    
    // MARK: - Level 3: PEEK_CONFIRM
    
    /// Time before the peek notification auto-dismisses (seconds).
    /// Default: 3.0 seconds — enough to read, not enough to be annoying.
    static let peekAutoDismiss: TimeInterval = 3.0
    
    /// Fade-out animation duration for peek notifications.
    static let peekFadeOutDuration: TimeInterval = 0.5
    
    // MARK: - Level 4: CONFIRM
    
    /// Time before a confirmation card auto-denies (seconds).
    /// Default: 60.0 seconds — enough time to review, but not indefinite.
    static let confirmAutoDeny: TimeInterval = 60.0
    
    /// Warning threshold: when remaining time drops below this, show visual warning.
    /// Default: 10.0 seconds.
    static let confirmWarningThreshold: TimeInterval = 10.0
    
    /// Enable countdown display for confirmations.
    static let confirmShowCountdown: Bool = true
    
    // MARK: - Level 5: STRICT_CONFIRM
    
    /// Time before a strict modal auto-denies (seconds).
    /// Default: 30.0 seconds — shorter than CONFIRM for dangerous actions.
    static let strictAutoDeny: TimeInterval = 30.0
    
    /// Warning threshold: when remaining time drops below this, show critical warning.
    /// Default: 10.0 seconds.
    static let strictWarningThreshold: TimeInterval = 10.0
    
    /// Enable haptic feedback at warning threshold.
    static let strictHapticAtWarning: Bool = true
    
    /// Enable haptic feedback on auto-deny.
    static let strictHapticOnAutoDeny: Bool = true
    
    // MARK: - Visual Settings
    
    /// Whether to show the countdown timer badge.
    static let showCountdownBadge: Bool = true
    
    /// Whether to animate the progress bar shrinking.
    static let animateProgressBar: Bool = true
    
    // MARK: - Computed Helpers
    
    /// Get the auto-deny timeout for a given risk level.
    static func autoDenyTimeout(for level: RiskLevel) -> TimeInterval {
        switch level {
        case .peek:
            return peekAutoDismiss
        case .confirm:
            return confirmAutoDeny
        case .strict:
            return strictAutoDeny
        }
    }
    
    /// Get the warning threshold for a given risk level.
    static func warningThreshold(for level: RiskLevel) -> TimeInterval {
        switch level {
        case .peek:
            return 0  // No warning for peek
        case .confirm:
            return confirmWarningThreshold
        case .strict:
            return strictWarningThreshold
        }
    }
    
    /// Risk levels for configuration.
    enum RiskLevel {
        case peek    // Level 3: PEEK_CONFIRM
        case confirm // Level 4: CONFIRM
        case strict  // Level 5: STRICT_CONFIRM
    }
}
