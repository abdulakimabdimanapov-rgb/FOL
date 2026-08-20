import SwiftUI

// MARK: - Audio Visualizer Badge

/// Compact waveform badge for the expanded notch state.
/// Shows a mini audio visualizer when the user is speaking (MLX Whisper active)
/// or when the twin is thinking. 5 bars with spring physics, olive-green gradient.
struct AudioVisualizerBadge: View {
    let audioLevel: Float  // 0.0 to 1.0
    let isActive: Bool     // false = hidden, true = visible

    @State private var barHeights: [CGFloat] = Array(repeating: 2, count: 5)
    @State private var barVelocities: [CGFloat] = Array(repeating: 0, count: 5)
    @State private var phase: CGFloat = 0
    @State private var breathePhase: CGFloat = 0

    private let barWidth: CGFloat = 3
    private let barSpacing: CGFloat = 2.5
    private let maxHeight: CGFloat = 14
    private let minHeight: CGFloat = 2
    private let stiffness: CGFloat = 200
    private let damping: CGFloat = 14
    private let timer = Timer.publish(every: 1.0 / 60.0, on: .main, in: .common).autoconnect()

    var body: some View {
        if isActive {
            HStack(spacing: barSpacing) {
                ForEach(0..<5, id: \.self) { index in
                    RoundedRectangle(cornerRadius: 1.5)
                        .fill(barGradient(for: index))
                        .frame(width: barWidth, height: barHeight(for: index))
                }
            }
            .frame(height: 20)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(
                Capsule()
                    .fill(Color.ssSurface)
                    .overlay(
                        Capsule()
                            .stroke(Color.ssTwinGreen.opacity(0.3), lineWidth: 0.5)
                    )
            )
            .onReceive(timer) { _ in
                updatePhysics()
            }
            .transition(.scale.combined(with: .opacity))
            .animation(.ssContentReveal, value: isActive)
        }
    }

    // MARK: - Bar Gradient

    private func barGradient(for index: Int) -> LinearGradient {
        let center = 2
        let distance = CGFloat(abs(index - center))
        let wave = sin(breathePhase * .pi * 2 - distance * 0.5) * 0.3 + 0.7
        let opacity = 0.5 + wave * 0.5

        return LinearGradient(
            colors: [
                Color.ssTwinGreen.opacity(opacity),
                Color.ssTwinGreen.opacity(opacity * 0.4),
            ],
            startPoint: .top,
            endPoint: .bottom
        )
    }

    // MARK: - Bar Height

    private func barHeight(for index: Int) -> CGFloat {
        guard index < barHeights.count else { return minHeight }
        let idleBreathe = sin(CGFloat(index) * 0.6 + breathePhase) * 1.0 + 2
        let level = CGFloat(audioLevel)
        return max(minHeight, barHeights[index] + (level < 0.02 ? idleBreathe : 0))
    }

    // MARK: - Physics

    private func updatePhysics() {
        phase += 0.06
        breathePhase += 0.04

        let targetLevel = CGFloat(audioLevel)

        for i in 0..<5 {
            let distance = CGFloat(abs(i - 2))
            let decay = max(0, 1.0 - distance * 0.25)
            let ripple = sin(phase - distance * 0.5) * 0.1
            let target = minHeight + (targetLevel + ripple) * decay * (maxHeight - minHeight)
            let clamped = max(minHeight, min(maxHeight, target))

            let displacement = barHeights[i] - clamped
            let springForce = -stiffness * displacement
            let dampingForce = -damping * barVelocities[i]

            barVelocities[i] += (springForce + dampingForce) * 0.016
            barVelocities[i] *= 0.96
            barHeights[i] += barVelocities[i] * 0.016
            barHeights[i] = max(minHeight, min(maxHeight, barHeights[i]))
        }
    }
}
