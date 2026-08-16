import SwiftUI

struct ExpandedView: View {
    @Bindable var viewModel: NotchViewModel
    @State private var breathingOpacity: Double = 0.3
    @State private var barHeights: [CGFloat] = Array(repeating: Theme.barMinHeight, count: Theme.barCount)
    @State private var barTimer: Timer?

    var body: some View {
        VStack(spacing: 0) {
            // ─── Dynamic Island Header with Camera Feed ──────────
            HStack(spacing: 10) {
                // Camera feed circle (front camera)
                ZStack {
                    Circle()
                        .fill(Color.black.opacity(0.3))
                        .frame(width: 32, height: 32)

                    if let frame = viewModel.cameraService.currentFrame {
                        Image(decorative: frame, scale: 1, orientation: .up)
                            .resizable()
                            .aspectRatio(contentMode: .fill)
                            .frame(width: 32, height: 32)
                            .clipShape(Circle())
                            .overlay(
                                Circle()
                                    .strokeBorder(Theme.accentColor.opacity(0.4), lineWidth: 1)
                            )
                    } else {
                        // Placeholder - pulsing orb
                        Circle()
                            .fill(
                                LinearGradient(
                                    colors: [Theme.accentColor, Theme.accentBlue],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                )
                            )
                            .frame(width: 16, height: 16)
                            .shadow(color: Theme.accentGlow, radius: 8)
                            .scaleEffect(breathingOpacity > 0.5 ? 1.1 : 0.9)
                    }
                }

                Text("FOL")
                    .font(Theme.titleFont)
                    .foregroundStyle(Theme.primaryText)

                // Music visualizer (when loading)
                if viewModel.isLoading {
                    HStack(spacing: Theme.barSpacing) {
                        ForEach(0..<Theme.barCount, id: \.self) { i in
                            RoundedRectangle(cornerRadius: 1.5)
                                .fill(
                                    LinearGradient(
                                        colors: [Theme.accentColor, Theme.accentBlue],
                                        startPoint: .bottom,
                                        endPoint: .top
                                    )
                                )
                                .frame(width: Theme.barWidth, height: barHeights[i])
                                .animation(
                                    .easeInOut(duration: 0.35)
                                    .repeatForever(autoreverses: true)
                                    .delay(Double(i) * 0.08),
                                    value: barHeights[i]
                                )
                        }
                    }
                    .frame(height: Theme.barMaxHeight)
                    .transition(.opacity.combined(with: .scale))
                }

                Spacer()

                // Voice toggle
                Button(action: { viewModel.toggleVoice() }) {
                    Image(systemName: viewModel.voiceEnabled ? "speaker.wave.2.fill" : "speaker.slash.fill")
                        .font(.system(size: 12))
                        .foregroundStyle(viewModel.voiceEnabled ? Theme.accentColor : Theme.secondaryText.opacity(0.5))
                }
                .buttonStyle(.plain)

                // Collapse button
                Button(action: { viewModel.collapse() }) {
                    Image(systemName: "chevron.up")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(Theme.secondaryText)
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, 16)
            .padding(.top, 14)
            .padding(.bottom, 10)

            // ─── Divider ────────────────────────────────────────
            Rectangle()
                .fill(Color.white.opacity(0.08))
                .frame(height: 0.5)
                .padding(.horizontal, 16)

            // ─── Chat Messages (iMessage style) ─────────────────
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 8) {
                        // Welcome message if no messages
                        if viewModel.chatMessages.isEmpty && !viewModel.isLoading {
                            emptyStateView
                        }

                        // Chat bubbles
                        ForEach(viewModel.chatMessages) { message in
                            ChatBubble(message: message)
                                .id(message.id)
                                .transition(.asymmetric(
                                    insertion: .move(edge: .bottom).combined(with: .opacity),
                                    removal: .opacity
                                ))
                        }

                        // Typing indicator
                        if viewModel.isLoading {
                            TypingIndicator()
                                .id("typing")
                        }
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 12)
                }
                .onChange(of: viewModel.chatMessages.count) { _, _ in
                    withAnimation(.easeOut(duration: 0.3)) {
                        if let lastMessage = viewModel.chatMessages.last {
                            proxy.scrollTo(lastMessage.id, anchor: .bottom)
                        }
                    }
                }
                .onChange(of: viewModel.isLoading) { _, loading in
                    if loading {
                        withAnimation {
                            proxy.scrollTo("typing", anchor: .bottom)
                        }
                    }
                }
            }
            .frame(maxWidth: .infinity)
            .frame(height: 380)
            .background(
                // Subtle gradient background
                LinearGradient(
                    colors: [
                        Color.clear,
                        Theme.accentColor.opacity(0.02),
                    ],
                    startPoint: .top,
                    endPoint: .bottom
                )
            )

            Spacer(minLength: 0)

            // ─── Input Pill ─────────────────────────────────────
            InputPill(viewModel: viewModel)
                .padding(.horizontal, 12)
                .padding(.bottom, 12)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onAppear {
            startAnimations()
        }
        .onDisappear {
            stopMusicBars()
        }
        .onChange(of: viewModel.isLoading) { _, loading in
            if loading { startMusicBars() } else { stopMusicBars() }
        }
    }

    // MARK: - Empty State

    private var emptyStateView: some View {
        VStack(spacing: 16) {
            // Animated jellyfish icon
            Image(systemName: "bubble.left.and.bubble.right")
                .font(.system(size: 32))
                .foregroundStyle(
                    LinearGradient(
                        colors: [Theme.accentColor, Theme.accentBlue],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .shadow(color: Theme.accentGlow, radius: 8)
                .scaleEffect(breathingOpacity > 0.5 ? 1.1 : 0.9)

            Text("Начни разговор")
                .font(Theme.bodyFont)
                .foregroundStyle(Theme.secondaryText.opacity(0.6))

            Text("🎤 Нажми на микрофон или напиши")
                .font(Theme.captionFont)
                .foregroundStyle(Theme.secondaryText.opacity(0.4))
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 50)
    }

    // MARK: - Animations

    private func startAnimations() {
        withAnimation(
            .easeInOut(duration: Theme.breatheDuration)
            .repeatForever(autoreverses: true)
        ) {
            breathingOpacity = 0.8
        }

        if viewModel.isLoading {
            startMusicBars()
        }
    }

    private func startMusicBars() {
        barTimer?.invalidate()
        for i in 0..<Theme.barCount {
            barHeights[i] = CGFloat.random(in: Theme.barMinHeight...Theme.barMaxHeight)
        }
        barTimer = Timer.scheduledTimer(withTimeInterval: 0.3, repeats: true) { _ in
            guard viewModel.isLoading else { return }
            for i in 0..<Theme.barCount {
                withAnimation(.easeInOut(duration: 0.2)) {
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
