import AppKit
import SwiftUI

@MainActor
final class NotchPanel: NSPanel {
    private let viewModel: NotchViewModel

    init(viewModel: NotchViewModel) {
        self.viewModel = viewModel

        let initialRect = NSRect(x: 0, y: 0, width: 220, height: 38)

        super.init(
            contentRect: initialRect,
            styleMask: [.nonactivatingPanel, .fullSizeContentView, .borderless],
            backing: .buffered,
            defer: false
        )

        configurePanel()
        installSwiftUIContent()
        positionAtNotch()
    }

    // MARK: - Panel Configuration

    private func configurePanel() {
        isFloatingPanel = true
        level = .floating
        collectionBehavior = [
            .canJoinAllSpaces,
            .fullScreenAuxiliary,
            .stationary,
        ]
        isOpaque = false
        backgroundColor = .clear
        hasShadow = true
        titleVisibility = .hidden
        titlebarAppearsTransparent = true
        isMovableByWindowBackground = false
        hidesOnDeactivate = false
        animationBehavior = .utilityWindow

    }

    // MARK: - SwiftUI Content

    private func installSwiftUIContent() {
        viewModel.onStateChange = { [weak self] state in
            Task { @MainActor in
                self?.animateToState(state)
            }
        }

        let rootView = NotchView(viewModel: viewModel)
            .ignoresSafeArea()
        contentView = NSHostingView(rootView: rootView)
    }

    // MARK: - Dynamic Island Morph Animation

    private func animateToState(_ state: PanelState) {
        let targetSize = sizeForState(state)
        let targetOrigin = originForSize(targetSize)

        // Animate frame change — setFrame with animate:true handles the spring
        self.setFrame(
            NSRect(origin: targetOrigin, size: targetSize),
            display: true,
            animate: true
        )
    }

    // MARK: - Positioning

    func positionAtNotch() {
        guard let screen = NSScreen.main else { return }
        let geo = ScreenGeometry(screen: screen)
        let size = sizeForCurrentState()

        let origin = NSPoint(
            x: geo.notchCenterX - size.width / 2,
            y: screen.frame.maxY - size.height
        )

        setFrame(NSRect(origin: origin, size: size), display: true, animate: true)
    }

    private func originForSize(_ size: NSSize) -> NSPoint {
        guard let screen = NSScreen.main else { return .zero }
        let geo = ScreenGeometry(screen: screen)
        return NSPoint(
            x: geo.notchCenterX - size.width / 2,
            y: screen.frame.maxY - size.height
        )
    }

    func sizeForCurrentState() -> NSSize {
        sizeForState(viewModel.panelState)
    }

    private func sizeForState(_ state: PanelState) -> NSSize {
        switch state {
        case .collapsed:
            return NSSize(width: Theme.collapsedWidth, height: Theme.collapsedHeight + PeepingMascot.hangHeight)
        case .preview:
            return NSSize(width: Theme.previewWidth, height: Theme.previewHeight)
        case .expanded:
            return NSSize(width: Theme.expandedWidth, height: Theme.expandedHeight)
        }
    }

    // MARK: - Key/Focus Behavior

    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}
