import SwiftUI

// MARK: - Chat Input Bar

/// Matches Figma node 90:129 (idle) and 136:1120 (recording).
/// Idle: [TextField "Message your Twin..."] [Mic]
/// Has text: [TextField] [Mic] [Send]
/// Recording: [Waveform visualization] [Mic] with cream glow
struct ChatInputBar: View {
    @Binding var text: String
    let isEnabled: Bool
    let voiceState: VoiceInputState
    let audioLevel: Float
    let isMuted: Bool
    let jarvisVolume: Float
    let onSend: (String) -> Void
    let onTapToRecord: () -> Void
    let onTapToStop: () -> Void
    let onVoiceCancel: () -> Void
    let onPermissionTap: () -> Void
    let onToggleMute: () -> Void
    let onVolumeChange: (Float) -> Void

    @FocusState private var isFocused: Bool
    @State private var isHoveringAudioControls = false

    /// Tracks whether the current send operation is in-flight to prevent double-sends.
    @State private var isSending = false

    var body: some View {
        VStack(spacing: 6) {
            // Error toast (above bar)
            if case .error(let message) = voiceState {
                errorToast(message)
                    .transition(.asymmetric(
                        insertion: .opacity.combined(with: .move(edge: .bottom)),
                        removal: .opacity
                    ))
            }

            // Transcribing indicator (above bar)
            if voiceState == .transcribing {
                transcribingIndicator
                    .transition(.opacity)
            }

            // Main input bar
            mainInputBar
        }
        .animation(.ssContentReveal, value: voiceState)
        .onAppear {
            if voiceState == .recording { startRecordingGlow() }
            // Auto-focus the text field when the input bar appears.
            // Delay slightly to let the panel finish becoming key.
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                isFocused = true
                // Only log focus when the text field is actually visible
                if voiceState != .recording {
                    NotificationCenter.default.post(name: .secondSelfInputFocused, object: nil)
                }
            }
        }
        .onChange(of: isEnabled) { _, newValue in
            // When the text field becomes enabled again (twin done thinking),
            // reclaim focus so the user can immediately type their next message.
            // Skip if voice is recording — the waveform replaces the text field.
            if newValue && voiceState != .recording {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
                    isFocused = true
                    NotificationCenter.default.post(name: .secondSelfInputFocused, object: nil)
                }
            }
        }
        .onChange(of: voiceState) { oldState, newState in
            if newState == .recording {
                startRecordingGlow()
            } else if oldState == .recording {
                stopRecordingGlow()
            }
        }
    }

    // MARK: - Main Input Bar

    private var mainInputBar: some View {
        HStack(spacing: 6) {
            // JARVIS mute toggle — always visible (silences both voice + sound effects)
            muteButton
                .padding(.leading, 2)

            if isHoveringAudioControls || isMuted {
                VolumeSlider(value: jarvisVolume, onChange: onVolumeChange)
                    .frame(width: 58)
                    .transition(.opacity.combined(with: .scale(scale: 0.96, anchor: .leading)))
            }

            // Content area: text field OR waveform
            if voiceState == .recording {
                AudioWaveformView(audioLevel: audioLevel)
                    .frame(maxWidth: .infinity)
                    .frame(height: 28)
                    .transition(.opacity)
            } else {
                TextField("Message FOL...", text: $text)
                    .textFieldStyle(.plain)
                    .font(.system(size: 13))
                    .foregroundColor(Color.ssTextPrimary)
                    .focused($isFocused)
                    .onSubmit { sendIfValid() }
                    .disabled(!isEnabled)
                    .transition(.opacity)
            }

            // Mic button (always visible, independent of isEnabled)
            VoiceInputButton(
                voiceState: voiceState,
                onTapToRecord: onTapToRecord,
                onTapToStop: onTapToStop,
                onCancel: onVoiceCancel,
                onPermissionTap: onPermissionTap
            )

            // Send button: only when there's text to send
            // Spring entrance: scale from 0.3 with slight overshoot, bouncy but subtle
            if canSend {
                Button(action: sendIfValid) {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.system(size: 24))
                        .foregroundColor(Color.ssUserOlive)
                }
                .buttonStyle(.plain)
                .transition(.asymmetric(
                    insertion: .scale(scale: 0.3).combined(with: .opacity),
                    removal: .scale(scale: 0.5).combined(with: .opacity)
                ))
                .animation(
                    .spring(response: 0.35, dampingFraction: 0.6, blendDuration: 0.08),
                    value: canSend
                )
            }
        }
        .padding(.leading, 8)
        .padding(.trailing, 6)
        .padding(.vertical, 6)
        .background(recordingBarBackground)
        .overlay(recordingBorderGlow)
        .overlay(recordingShimmerOverlay)
        .shadow(
            color: voiceState == .recording ? Color.ssCream.opacity(glowOpacity * 0.5) : Color.clear,
            radius: voiceState == .recording ? glowRadius : 0,
            x: 0, y: 0
        )
        .animation(.ssMicro, value: canSend)
        .animation(.ssMicro, value: isHoveringAudioControls)
        .onHover { isHoveringAudioControls = $0 }
    }

    // MARK: - Recording Glow Effects

    @State private var glowOpacity: Double = 0.6
    @State private var glowRadius: CGFloat = 18
    @State private var shimmerPhase: CGFloat = 0
    @State private var borderPhase: CGFloat = 0

    private var isRecording: Bool {
        voiceState == .recording
    }

    /// Pulsing background during recording — subtly brightens and darkens
    private var recordingBarBackground: some View {
        RoundedRectangle(cornerRadius: 15)
            .fill(
                isRecording
                    ? Color(hex: 0x2A2A2E)
                    : Color(hex: 0x262629)
            )
    }

    /// Animated shimmer sweep across the input bar during recording
    private var recordingShimmerOverlay: some View {
        GeometryReader { geo in
            if isRecording {
                LinearGradient(
                    colors: [
                        .clear,
                        .clear,
                        Color.ssCream.opacity(0.08),
                        Color.ssCream.opacity(0.12),
                        Color.ssCream.opacity(0.08),
                        .clear,
                        .clear,
                    ],
                    startPoint: .leading,
                    endPoint: .trailing
                )
                .frame(width: geo.size.width * 0.4)
                .offset(x: shimmerOffset(for: geo.size.width))
                .clipShape(RoundedRectangle(cornerRadius: 15))
                .allowsHitTesting(false)
            }
        }
    }

    /// Pulsing border glow ring during recording
    private var recordingBorderGlow: some View {
        RoundedRectangle(cornerRadius: 15)
            .stroke(
                isRecording
                    ? Color.ssCream.opacity(borderPhase * 0.35)
                    : .clear,
                lineWidth: isRecording ? 1.5 : 0
            )
            .allowsHitTesting(false)
    }

    private func shimmerOffset(for totalWidth: CGFloat) -> CGFloat {
        let shimmerWidth = totalWidth * 0.4
        return -shimmerWidth + (totalWidth + shimmerWidth) * shimmerPhase
    }

    /// Start all recording glow animations
    private func startRecordingGlow() {
        // Reset
        glowOpacity = 0.6
        glowRadius = 14
        shimmerPhase = 0
        borderPhase = 0

        // Shadow glow pulse
        withAnimation(.easeInOut(duration: 0.9).repeatForever(autoreverses: true)) {
            glowOpacity = 1.0
            glowRadius = 24
        }

        // Shimmer sweep
        withAnimation(.linear(duration: 1.8).repeatForever(autoreverses: false)) {
            shimmerPhase = 1.0
        }

        // Border pulse
        withAnimation(.easeInOut(duration: 1.2).repeatForever(autoreverses: true)) {
            borderPhase = 1.0
        }
    }

    private func stopRecordingGlow() {
        withAnimation(.easeOut(duration: 0.25)) {
            glowOpacity = 0
            glowRadius = 0
            shimmerPhase = 0
            borderPhase = 0
        }
    }

    // MARK: - Mute Button

    /// Small speaker icon that toggles JARVIS voice on/off.
    /// Shows speaker.wave.2 when unmuted, speaker.slash when muted.
    /// Gentle color: white when unmuted, muted red-orange when muted.
    private var muteButton: some View {
        Button(action: onToggleMute) {
            Image(systemName: isMuted ? "speaker.slash.fill" : "speaker.wave.2.fill")
                .font(.system(size: 12))
                .foregroundColor(isMuted ? Color.ssError.opacity(0.7) : Color.ssTextSecondary.opacity(0.5))
                .frame(width: 20, height: 20)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help(isMuted ? "Unmute JARVIS (voice + sounds)" : "Mute JARVIS (voice + sounds)")
        .animation(.ssMicro, value: isMuted)
    }

    // MARK: - Transcribing Indicator

    private var transcribingIndicator: some View {
        HStack(spacing: 8) {
            ProgressView()
                .controlSize(.mini)
                .tint(Color.ssUserOlive)

            Text("Transcribing...")
                .font(.system(size: 11, weight: .medium))
                .foregroundColor(Color.ssTextSecondary)

            Spacer()
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 4)
    }

    // MARK: - Error Toast

    private func errorToast(_ message: String) -> some View {
        HStack(spacing: 6) {
            Image(systemName: "exclamationmark.circle.fill")
                .font(.system(size: 11))
                .foregroundColor(Color.ssError)

            Text(message)
                .font(.system(size: 11, weight: .medium))
                .foregroundColor(Color.ssError.opacity(0.9))
                .lineLimit(1)

            Spacer()
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 5)
        .background(
            RoundedRectangle(cornerRadius: 8)
                .fill(Color.ssError.opacity(0.1))
        )
    }

    // MARK: - Helpers

    private var canSend: Bool {
        isEnabled && !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func sendIfValid() {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty && isEnabled, !isSending else { return }

        isSending = true
        let textToSend = trimmed
        text = ""

        // Call onSend AFTER clearing text so the binding is clean.
        // We use the captured textToSend to avoid any race with the binding.
        onSend(textToSend)
        NotificationCenter.default.post(name: .secondSelfMessageSent, object: nil)

        // Re-focus on next runloop — allows SwiftUI to settle the view update
        // before requesting focus. Without this, the field editor on macOS 14
        // can lose its connection to the NSTextField and stop accepting input.
        DispatchQueue.main.async {
            isFocused = true
            // Unlock sending after a small delay to prevent double-sends.
            // 150ms is enough — by then canSend is false anyway (text is cleared).
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
                isSending = false
            }
        }
    }
}

// MARK: - Volume Slider

/// Compact horizontal slider for JARVIS master volume.
/// Uses direct Binding to value — no @State, no sync issues.
struct VolumeSlider: View {
    let value: Float
    let onChange: (Float) -> Void

    var body: some View {
        Slider(
            value: Binding(
                get: { value },
                set: { onChange($0) }
            ),
            in: 0...1,
            step: 0.05
        )
        .controlSize(.mini)
        .accentColor(Color.ssTextSecondary.opacity(0.4))
        .help("JARVIS volume")
    }
}

// MARK: - Audio Waveform Visualization

/// Reactive waveform that responds to real microphone audio levels.
/// Uses a physics-inspired model: bars oscillate with inertia and
/// smoothly converge toward the target audio level, creating a
/// fluid "liquid" feel that looks like real audio waveforms.
/// The center bar represents the current level; surrounding bars
/// ripple outward with decaying energy.
struct AudioWaveformView: View {
    let audioLevel: Float // 0.0 to 1.0

    private static let barWidth: CGFloat = 2.5
    private static let barSpacing: CGFloat = 2.5

    // Physics state per bar: [currentHeight, velocity]
    @State private var barStates: [(height: CGFloat, velocity: CGFloat)] = []
    @State private var barCount: Int = 50
    @State private var phase: CGFloat = 0
    // Color oscillation: 0→1→0 loop, drives green↔cream gradient shift
    @State private var colorPhase: CGFloat = 0

    // Spring physics constants
    private let stiffness: CGFloat = 180
    private let damping: CGFloat = 12
    private let maxBarHeight: CGFloat = 26
    private let minBarHeight: CGFloat = 2

    // Timer for updating physics simulation
    private let updateTimer = Timer.publish(every: 1/60, on: .main, in: .common).autoconnect()

    var body: some View {
        GeometryReader { geo in
            let count = max(1, Int(geo.size.width / (Self.barWidth + Self.barSpacing)))
            let centerIndex = count / 2

            HStack(spacing: Self.barSpacing) {
                ForEach(0..<count, id: \.self) { index in
                    RoundedRectangle(cornerRadius: 1.5)
                        .fill(
                            LinearGradient(
                                colors: [
                                    barTint(for: index, center: centerIndex).opacity(0.9),
                                    barTint(for: index, center: centerIndex).opacity(0.4),
                                ],
                                startPoint: .top,
                                endPoint: .bottom
                            )
                        )
                        .frame(
                            width: Self.barWidth,
                            height: animatedHeight(for: index, center: centerIndex)
                        )
                        .animation(.spring(response: 0.15, dampingFraction: 0.65), value: barStates[safe: index]?.height ?? minBarHeight)
                }
            }
            .frame(width: geo.size.width, height: geo.size.height, alignment: .center)
            .onAppear {
                let c = count
                barCount = c
                barStates = Array(repeating: (height: minBarHeight, velocity: 0), count: c)
            }
            .onChange(of: count) { _, newCount in
                if barStates.count != newCount {
                    barStates = Array(repeating: (height: minBarHeight, velocity: 0), count: newCount)
                    barCount = newCount
                }
            }
            .onReceive(updateTimer) { _ in
                updatePhysics(center: centerIndex)
            }
        }
    }

    // MARK: - Physics Update

    /// Spring physics simulation: each bar is a mass-spring-damper system.
    /// The center bar targets the audio level; neighboring bars target
    /// decaying ripples of that level, creating a natural wave effect.
    // MARK: - Animated Bar Color

    /// Each bar gets a color that oscillates between olive-green and cream.
    /// The oscillation is offset per bar so a color wave flows across the waveform.
    /// Manual RGB interpolation (avoids Color.mix which requires macOS 15+).
    private static let barOliveR = CGFloat(156) / 255.0
    private static let barOliveG = CGFloat(161) / 255.0
    private static let barOliveB = CGFloat(97) / 255.0
    private static let barCreamR = CGFloat(251) / 255.0
    private static let barCreamG = CGFloat(255) / 255.0
    private static let barCreamB = CGFloat(212) / 255.0

    private func barTint(for index: Int, center: Int) -> Color {
        let distance = CGFloat(abs(index - center))
        // Each bar's phase is offset by its distance from center, creating a wave
        let waveOffset = sin(colorPhase * .pi * 2 - distance * 0.12) * 0.5 + 0.5
        // Keep the mix subtle: 0 → ssUserOlive, max 0.65 → olive with cream hint
        let mixAmount = waveOffset * 0.65

        let r = Self.barOliveR + (Self.barCreamR - Self.barOliveR) * mixAmount
        let g = Self.barOliveG + (Self.barCreamG - Self.barOliveG) * mixAmount
        let b = Self.barOliveB + (Self.barCreamB - Self.barOliveB) * mixAmount

        return Color(red: r, green: g, blue: b)
    }

    private func updatePhysics(center: Int) {
        guard !barStates.isEmpty else { return }
        phase += 0.05
        // Slowly oscillate color phase (full cycle ~2.6s at 60fps)
        colorPhase += 0.006

        let targetLevel = CGFloat(audioLevel)
        let count = barStates.count

        for i in 0..<count {
            let distance = abs(i - center)
            let decay = max(0, 1.0 - CGFloat(distance) * 0.12)

            // Ripple: targets form a wave that spreads from center
            let rippleOffset = sin(phase - CGFloat(distance) * 0.4) * 0.15
            let targetHeight = minBarHeight + (targetLevel + rippleOffset) * decay * (maxBarHeight - minBarHeight)
            let clamped = max(minBarHeight, min(maxBarHeight, targetHeight))

            // Spring physics: F = -k*x - d*v
            let displacement = barStates[i].height - clamped
            let springForce = -stiffness * displacement
            let dampingForce = -damping * barStates[i].velocity
            let acceleration = springForce + dampingForce

            barStates[i].velocity += acceleration * 0.016 // dt ≈ 1/60
            barStates[i].velocity *= 0.97 // slight energy loss
            barStates[i].height += barStates[i].velocity * 0.016

            // Clamp
            barStates[i].height = max(minBarHeight, min(maxBarHeight, barStates[i].height))
        }
    }

    private func animatedHeight(for index: Int, center: Int) -> CGFloat {
        guard index < barStates.count else { return minBarHeight }
        // Add a subtle idle oscillation even at zero input
        let idleBreath = sin(CGFloat(index) * 0.3 + phase) * 1.5 + 2
        return max(minBarHeight, barStates[index].height + (audioLevel < 0.02 ? idleBreath * 0.3 : 0))
    }
}

// MARK: - Safe Array Access

extension Array {
    subscript(safe index: Int) -> Element? {
        guard index >= 0 && index < count else { return nil }
        return self[index]
    }
}
