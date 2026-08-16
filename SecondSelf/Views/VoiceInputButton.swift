import SwiftUI

// MARK: - Voice Input Button

/// Olive mic button with smooth animations.
/// Idle: olive mic icon
/// Recording: red stop icon with pulsing glow ring
/// Transcribing: spinner
/// Error: shake animation
struct VoiceInputButton: View {
    let voiceState: VoiceInputState
    let onTapToRecord: () -> Void
    let onTapToStop: () -> Void
    let onCancel: () -> Void
    let onPermissionTap: () -> Void

    @State private var shakeOffset: CGFloat = 0
    @State private var pulseScale: CGFloat = 1.0
    @State private var pulseOpacity: CGFloat = 0.0
    @State private var glowRadius: CGFloat = 0

    var body: some View {
        Group {
            switch voiceState {
            case .hidden:
                EmptyView()
            case .permissionNeeded:
                micButton(icon: "mic.slash", bg: Color.ssTextSecondary.opacity(0.3))
                    .onTapGesture { onPermissionTap() }
                    .help("Tap to enable microphone")
                    .transition(.scale.combined(with: .opacity))

            case .idle:
                micButton(icon: "mic.fill", bg: Color.ssUserOlive)
                    .onTapGesture { onTapToRecord() }
                    .transition(.scale.combined(with: .opacity))
                    .help("Tap to record")

            case .recording:
                recordingButton
                    .onTapGesture { onTapToStop() }
                    .transition(.scale.combined(with: .opacity))
                    .help("Tap to stop recording")

            case .transcribing:
                ZStack {
                    RoundedRectangle(cornerRadius: 14)
                        .fill(Color.ssUserOlive)
                        .frame(width: 28, height: 28)
                    ProgressView()
                        .controlSize(.small)
                        .tint(.white)
                }
                .frame(width: 36, height: 36)
                .transition(.scale.combined(with: .opacity))

            case .error:
                micButton(icon: "exclamationmark.circle.fill", bg: Color.ssError)
                    .offset(x: shakeOffset)
                    .onAppear { runShake() }
                    .transition(.scale.combined(with: .opacity))
            }
        }
        .animation(.spring(response: 0.25, dampingFraction: 0.75), value: voiceState)
    }

    // MARK: - Recording Button with Pulse Ring

    private var recordingButton: some View {
        ZStack {
            // Outer glow ring 1
            Circle()
                .stroke(Color.ssRecordingRed.opacity(pulseOpacity * 0.4), lineWidth: 2)
                .frame(width: 42, height: 42)
                .scaleEffect(pulseScale)

            // Outer glow ring 2 (delayed)
            Circle()
                .stroke(Color.ssRecordingRed.opacity(pulseOpacity * 0.2), lineWidth: 1.5)
                .frame(width: 50, height: 50)
                .scaleEffect(pulseScale * 1.15)

            // Inner icon background
            RoundedRectangle(cornerRadius: 14)
                .fill(Color.ssRecordingRed)
                .frame(width: 28, height: 28)
                .shadow(color: Color.ssRecordingRed.opacity(0.6), radius: glowRadius, x: 0, y: 0)

            // Stop icon
            Image(systemName: "stop.fill")
                .font(.system(size: 14, weight: .medium))
                .foregroundColor(.white)
        }
        .frame(width: 36, height: 36)
        .contentShape(Rectangle())
        .onAppear { startPulseAnimation() }
        .onDisappear { stopPulseAnimation() }
    }

    // MARK: - Pulse Animation Loop

    private func startPulseAnimation() {
        // Reset to starting state
        pulseScale = 1.0
        pulseOpacity = 1.0
        glowRadius = 6

        // Animate the glow radius
        withAnimation(.easeInOut(duration: 0.8).repeatForever(autoreverses: true)) {
            glowRadius = 12
        }

        // Animate the outer ring pulse
        withAnimation(.easeInOut(duration: 1.2).repeatForever(autoreverses: true)) {
            pulseScale = 1.2
            pulseOpacity = 0.3
        }
    }

    private func stopPulseAnimation() {
        withAnimation(.easeOut(duration: 0.2)) {
            pulseScale = 1.0
            pulseOpacity = 0
            glowRadius = 0
        }
    }

    // MARK: - Mic Button

    private func micButton(icon: String, bg: Color) -> some View {
        ZStack {
            RoundedRectangle(cornerRadius: 14)
                .fill(bg)
                .frame(width: 28, height: 28)

            Image(systemName: icon)
                .font(.system(size: 14, weight: .medium))
                .foregroundColor(.white)
        }
        .frame(width: 36, height: 36)
        .contentShape(Rectangle())
    }

    // MARK: - Shake Animation

    private func runShake() {
        shakeOffset = 0
        withAnimation(.interpolatingSpring(stiffness: 300, damping: 10)) {
            shakeOffset = 6
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.08) {
            withAnimation(.interpolatingSpring(stiffness: 300, damping: 10)) {
                shakeOffset = -5
            }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.16) {
            withAnimation(.interpolatingSpring(stiffness: 300, damping: 10)) {
                shakeOffset = 4
            }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.24) {
            withAnimation(.spring(response: 0.2, dampingFraction: 0.6)) {
                shakeOffset = 0
            }
        }
    }
}
