import SwiftUI

struct NotchView: View {
    @Bindable var viewModel: NotchViewModel
    @State private var isHovering = false
    // Smooth animated dimensions
    @State private var animatedWidth: CGFloat = Theme.collapsedWidth
    @State private var animatedHeight: CGFloat = Theme.collapsedHeight
    @State private var animatedCornerRadius: CGFloat = Theme.cornerRadius
    @State private var contentOpacity: Double = 1.0
    @State private var backgroundScale: CGFloat = 1.0
    @State private var isMorphing = false
    @State private var hoverOffset: CGFloat = 0

    var body: some View {
        ZStack(alignment: .top) {
            // ─── Mascot behind the bar ──────────────────────────
            if viewModel.panelState == .collapsed {
                PeepingMascot(barHeight: Theme.collapsedHeight, isVisible: isHovering)
                    .transition(.opacity.combined(with: .scale(scale: 0.8)))
            }

            // ─── Background bar — morphs between states ────────
            RoundedRectangle(cornerRadius: animatedCornerRadius)
                .fill(.ultraThinMaterial)
                .overlay(
                    RoundedRectangle(cornerRadius: animatedCornerRadius)
                        .fill(Theme.panelBackground)
                )
                .overlay(
                    // Glow effect on expand
                    RoundedRectangle(cornerRadius: animatedCornerRadius)
                        .stroke(Theme.accentColor.opacity(isHovering ? 0.3 : 0.0), lineWidth: 1)
                        .animation(.easeInOut(duration: 0.3), value: isHovering)
                )
                .shadow(color: .black.opacity(0.4), radius: viewModel.panelState == .expanded ? 20 : 10, y: viewModel.panelState == .expanded ? 8 : 4)
                .frame(width: animatedWidth, height: animatedHeight)
                .scaleEffect(backgroundScale)
                .animation(
                    .spring(response: 0.45, dampingFraction: 0.78, blendDuration: 0.1),
                    value: animatedWidth
                )
                .animation(
                    .spring(response: 0.45, dampingFraction: 0.78, blendDuration: 0.1),
                    value: animatedHeight
                )
                .animation(
                    .spring(response: 0.35, dampingFraction: 0.8),
                    value: animatedCornerRadius
                )

            // ─── Content — crossfades between states ───────────
            Group {
                switch viewModel.panelState {
                case .collapsed:
                    CollapsedView(viewModel: viewModel)
                        .transition(.opacity.combined(with: .scale(scale: 0.95)))

                case .preview:
                    PreviewView(viewModel: viewModel)
                        .transition(.opacity.combined(with: .move(edge: .top).combined(with: .scale(scale: 0.98))))

                case .expanded:
                    ExpandedView(viewModel: viewModel)
                        .transition(.opacity.combined(with: .scale(scale: 0.97)))
                }
            }
            .opacity(contentOpacity)
            .animation(.easeInOut(duration: 0.2), value: contentOpacity)
        }
        .frame(width: animatedWidth + hoverOffset, height: animatedHeight + (viewModel.panelState == .collapsed ? PeepingMascot.hangHeight : 0))
        .onHover { hovering in
            if viewModel.panelState == .collapsed {
                withAnimation(.easeInOut(duration: 0.2)) {
                    isHovering = hovering
                }
                // Subtle hover expand — separate from morph animation
                if hovering && !isMorphing {
                    withAnimation(.spring(response: 0.3, dampingFraction: 0.85)) {
                        hoverOffset = 20
                    }
                } else {
                    withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) {
                        hoverOffset = 0
                    }
                }
            }
        }
        .onTapGesture {
            if viewModel.panelState == .collapsed {
                viewModel.handleClick()
            }
        }
        .onChange(of: viewModel.panelState) { oldValue, newValue in
            if newValue != .collapsed {
                isHovering = false
            }
            animateTransition(to: newValue)
        }
    }

    // MARK: - Dynamic Island Morph Animation

    private func animateTransition(to state: PanelState) {
        guard !isMorphing else { return }
        isMorphing = true

        // 1. Fade out current content
        withAnimation(.easeOut(duration: 0.12)) {
            contentOpacity = 0.3
        }

        // 2. Morph background shape
        let targetWidth: CGFloat
        let targetHeight: CGFloat
        let targetCornerRadius: CGFloat

        switch state {
        case .collapsed:
            targetWidth = Theme.collapsedWidth
            targetHeight = Theme.collapsedHeight
            targetCornerRadius = Theme.cornerRadius
        case .preview:
            targetWidth = Theme.previewWidth
            targetHeight = Theme.previewHeight
            targetCornerRadius = Theme.cornerRadius + 2
        case .expanded:
            targetWidth = Theme.expandedWidth
            targetHeight = Theme.expandedHeight
            targetCornerRadius = Theme.expandedCornerRadius
        }

        // Background scale pulse — like Dynamic Island "blob" effect
        withAnimation(.easeOut(duration: 0.15)) {
            backgroundScale = 1.05
        }
        withAnimation(.easeInOut(duration: 0.3).delay(0.1)) {
            backgroundScale = 1.0
        }

        // Morph dimensions with spring
        withAnimation(.spring(response: 0.45, dampingFraction: 0.78, blendDuration: 0.15)) {
            animatedWidth = targetWidth
            animatedHeight = targetHeight
            animatedCornerRadius = targetCornerRadius
        }

        // 3. Fade in new content after morph starts — cancellable
        Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(150))
            guard !Task.isCancelled else { return }
            withAnimation(.easeIn(duration: 0.2)) {
                contentOpacity = 1.0
            }
            isMorphing = false
        }
    }

    private var onStateChange: (@Sendable (PanelState) -> Void)? {
        viewModel.onStateChange
    }
}
