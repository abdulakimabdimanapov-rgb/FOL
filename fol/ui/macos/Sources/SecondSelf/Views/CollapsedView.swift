import SwiftUI

struct CollapsedView: View {
    let viewModel: NotchViewModel
    @State private var breathingOpacity: Double = 0.4
    @State private var barHeights: [CGFloat] = Array(repeating: Theme.barMinHeight, count: Theme.barCount)
    @State private var barTimer: Timer?

    var body: some View {
        HStack(spacing: 10) {
            // ─── Status dot with breathing glow ──────────────────
            ZStack {
                Circle()
                    .fill(viewModel.isStatusActive ? Theme.accentColor : Theme.secondaryText)
                    .frame(width: 8, height: 8)

                if viewModel.isStatusActive {
                    Circle()
                        .fill(Theme.accentGlow)
                        .frame(width: 16, height: 16)
                        .blur(radius: 4)
                        .opacity(breathingOpacity)
                }
            }

            // ─── FOL label ──────────────────────────────────────
            Text("FOL")
                .font(Theme.titleFont)
                .foregroundStyle(Theme.primaryText)

            // ─── Music visualizer bars (when loading/speaking) ──
            if viewModel.isLoading {
                HStack(spacing: Theme.barSpacing) {
                    ForEach(0..<Theme.barCount, id: \.self) { i in
                        RoundedRectangle(cornerRadius: 1.5)
                            .fill(Theme.accentColor)
                            .frame(width: Theme.barWidth, height: barHeights[i])
                            .animation(
                                .easeInOut(duration: 0.4)
                                .repeatForever(autoreverses: true)
                                .delay(Double(i) * 0.1),
                                value: barHeights[i]
                            )
                    }
                }
                .frame(height: Theme.barMaxHeight)
                .transition(.opacity)
            }

            Spacer()

            // ─── Mini chevron ───────────────────────────────────
            Image(systemName: "chevron.down")
                .font(.system(size: 8, weight: .bold))
                .foregroundStyle(Theme.secondaryText.opacity(0.4))
                .rotationEffect(.degrees(viewModel.panelState == .collapsed ? 0 : 180))
        }
        .padding(.horizontal, 16)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .contentShape(Rectangle())
        .onAppear {
            startBreathing()
            if viewModel.isLoading {
                startMusicBars()
            }
        }
        .onDisappear {
            stopMusicBars()
        }
        .onChange(of: viewModel.isLoading) { _, loading in
            if loading { startMusicBars() } else { stopMusicBars() }
        }
    }

    // MARK: - Animations

    private func startBreathing() {
        withAnimation(
            .easeInOut(duration: Theme.breatheDuration)
            .repeatForever(autoreverses: true)
        ) {
            breathingOpacity = 0.8
        }
    }

    private func startMusicBars() {
        barTimer?.invalidate()
        for i in 0..<Theme.barCount {
            barHeights[i] = CGFloat.random(in: Theme.barMinHeight...Theme.barMaxHeight)
        }
        barTimer = Timer.scheduledTimer(withTimeInterval: 0.35, repeats: true) { _ in
            guard viewModel.isLoading else { return }
            for i in 0..<Theme.barCount {
                withAnimation(.easeInOut(duration: 0.25)) {
                    barHeights[i] = CGFloat.random(in: Theme.barMinHeight...Theme.barMaxHeight)
                }
            }
        }
    }

    private func stopMusicBars() {
        barTimer?.invalidate()
        barTimer = nil
        withAnimation(.easeInOut(duration: 0.3)) {
            barHeights = Array(repeating: Theme.barMinHeight, count: Theme.barCount)
        }
    }
}
