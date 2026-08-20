import Foundation

// MARK: - Twin State

/// Represents the current state of the digital twin agent.
/// Drives character animations and UI status indicators.
enum TwinState: String {
    case idle       // Ready, subtle breathing animation
    case thinking   // Processing request, vertical bob
    case working    // Executing tools, rotation wiggle
    case complete   // Task finished, scale bounce
    case cancelled  // Task stopped by the user (POST /chat/interrupt)
    case error      // Something went wrong, tilt
}
