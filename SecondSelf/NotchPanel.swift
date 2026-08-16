import AppKit
import SwiftUI
import Combine

// MARK: - NotchPanel
/// Pure NSPanel-based notch panel with Dynamic Island animations.

@MainActor
final class NotchPanel: NSPanel {
    private let viewModel: ChatViewModel

    private var hostingView: NSHostingView<AnyView>?
    private(set) var isExpanded = false

    /// Explicitly allow key window status. Required because `.nonactivatingPanel`
    /// style mask can interact poorly with SwiftUI's focus system on macOS 14+.
    override var canBecomeKey: Bool { true }
    
    // MARK: - Dynamic Island Configuration
    private let compactWidth: CGFloat = 220
    private let compactHeight: CGFloat = 38
    private let expandedWidth: CGFloat = 420
    private let expandedHeight: CGFloat = 560
    private let compactCornerRadius: CGFloat = 14
    private let expandedCornerRadius: CGFloat = 24
    private let expandDuration: TimeInterval = 0.45
    private let compactDuration: TimeInterval = 0.35

    // MARK: - Callbacks
    var onExpand: (() -> Void)?
    var onCompact: (() -> Void)?

    init(viewModel: ChatViewModel) {
        self.viewModel = viewModel

        let screen = NSScreen.main ?? .init()
        let initialRect = NSRect(
            x: screen.frame.midX - compactWidth / 2,
            y: screen.frame.maxY - compactHeight,
            width: compactWidth,
            height: compactHeight
        )

        super.init(
            contentRect: initialRect,
            styleMask: [.nonactivatingPanel, .fullSizeContentView, .borderless],
            backing: .buffered,
            defer: false
        )

        configurePanel()
        installContent()
        applyCornerRadius()
    }

    private func configurePanel() {
        isFloatingPanel = true
        level = .floating
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        isOpaque = false
        backgroundColor = .clear
        hasShadow = false
        titleVisibility = .hidden
        titlebarAppearsTransparent = true
        isMovableByWindowBackground = false
        hidesOnDeactivate = false
    }
    
    private func applyCornerRadius() {
        contentView?.wantsLayer = true
        contentView?.layer?.cornerRadius = compactCornerRadius
        contentView?.layer?.masksToBounds = true
    }

    private func installContent() {
        let content = AnyView(
            NotchContainerView(
                viewModel: viewModel
            )
            .environment(\.colorScheme, .dark)
        )
        let hosting = NSHostingView(rootView: content)
        hosting.layer?.backgroundColor = .clear
        hosting.wantsLayer = true
        hosting.layer?.cornerRadius = compactCornerRadius
        hosting.layer?.masksToBounds = true
        contentView = hosting
        hostingView = hosting
    }

    // MARK: - Dynamic Island Animation
    
    private func animateToState(expanding: Bool, frame: NSRect, cornerRadius: CGFloat) {
        let duration = expanding ? expandDuration : compactDuration
        let timingFn = CAMediaTimingFunction(controlPoints: 0.25, 0.1, 0.25, 1.0)
        
        for layer in [hostingView?.layer, contentView?.layer].compactMap({ $0 }) {
            let anim = CABasicAnimation(keyPath: "cornerRadius")
            anim.fromValue = layer.cornerRadius
            anim.toValue = cornerRadius
            anim.duration = duration
            anim.timingFunction = timingFn
            layer.add(anim, forKey: "cornerRadius")
            layer.cornerRadius = cornerRadius
        }
        
        NSAnimationContext.runAnimationGroup { context in
            context.duration = duration
            context.timingFunction = timingFn
            animator().setFrame(frame, display: true)
        }
    }

    func expand() async {
        guard !isExpanded else { return }
        isExpanded = true
        onExpand?()
        animateToState(expanding: true, frame: notchRect(size: NSSize(width: expandedWidth, height: expandedHeight)), cornerRadius: expandedCornerRadius)
        NSApp.activate(ignoringOtherApps: true)
        makeKeyAndOrderFront(nil)
        try? await Task.sleep(for: .seconds(expandDuration))
    }

    func compact() async {
        guard isExpanded else { return }
        isExpanded = false
        onCompact?()
        animateToState(expanding: false, frame: notchRect(size: NSSize(width: compactWidth, height: compactHeight)), cornerRadius: compactCornerRadius)
        try? await Task.sleep(for: .seconds(compactDuration))
    }

    func toggle() async {
        if isExpanded { await compact() } else { await expand() }
    }

    private func notchRect(size: NSSize) -> NSRect {
        guard let screen = NSScreen.main else { return .zero }
        return NSRect(x: screen.frame.midX - size.width / 2, y: screen.frame.maxY - size.height, width: size.width, height: size.height)
    }

    func positionAtNotch(size: NSSize? = nil) {
        let newFrame = notchRect(size: size ?? frame.size)
        let duration = isExpanded ? expandDuration : compactDuration
        NSAnimationContext.runAnimationGroup { context in
            context.duration = duration
            context.timingFunction = CAMediaTimingFunction(controlPoints: 0.25, 0.1, 0.25, 1.0)
            animator().setFrame(newFrame, display: true)
        }
    }
    
    func reposition() {
        setFrame(notchRect(size: frame.size), display: true)
    }
    
    var compactFrame: NSRect {
        notchRect(size: NSSize(width: compactWidth, height: compactHeight))
    }
}

// MARK: - NotchContainerView

struct NotchContainerView: View {
    @ObservedObject var viewModel: ChatViewModel
    
    @State private var currentTime = Date()
    private let timer = Timer.publish(every: 1.0, on: .main, in: .common).autoconnect()

    var body: some View {
        ZStack {
            if viewModel.expansionStage >= 2 {
                ExpandedNotchContent(chatViewModel: viewModel)
                    .transition(.asymmetric(insertion: .opacity.combined(with: .scale(scale: 0.95)), removal: .opacity))
            } else if viewModel.expansionStage == 1 {
                DynamicIslandStatusBar(viewModel: viewModel, currentTime: $currentTime)
                    .transition(.asymmetric(insertion: .opacity, removal: .opacity.combined(with: .scale(scale: 0.95))))
            } else {
                DynamicIslandCompact(viewModel: viewModel, currentTime: $currentTime)
                    .transition(.opacity)
            }
        }
        .animation(.spring(response: 0.35, dampingFraction: 0.85), value: viewModel.expansionStage)
        .onReceive(timer) { _ in currentTime = Date() }
    }
}

// MARK: - Dynamic Island Compact (Stage 0)

struct DynamicIslandCompact: View {
    @ObservedObject var viewModel: ChatViewModel
    @Binding var currentTime: Date
    
    private var timeString: String {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter.string(from: currentTime)
    }
    
    var body: some View {
        HStack(spacing: 8) {
            Text(timeString)
                .font(.system(size: 14, weight: .semibold, design: .monospaced))
                .foregroundColor(.white)
                .monospacedDigit()
            
            Spacer()
            
            AIStatusDot(state: viewModel.twinState, isConnected: viewModel.isConnected)
        }
        .padding(.horizontal, 16)
        .frame(width: 220, height: 38)
        .background(DynamicIslandBackground())
    }
}

// MARK: - Dynamic Island Status Bar (Stage 1)

struct DynamicIslandStatusBar: View {
    @ObservedObject var viewModel: ChatViewModel
    @Binding var currentTime: Date
    
    @State private var pulsePhase = false
    
    private var timeString: String {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter.string(from: currentTime)
    }
    
    private var isActive: Bool {
        viewModel.twinState == .thinking || viewModel.twinState == .working
    }
    
    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Text(timeString)
                    .font(.system(size: 16, weight: .semibold, design: .monospaced))
                    .foregroundColor(.white)
                    .monospacedDigit()
                
                Spacer()
                
                if isActive {
                    StatusCyclingText(twinState: viewModel.twinState)
                        .transition(.opacity)
                }
                
                AIStatusDot(state: viewModel.twinState, isConnected: viewModel.isConnected)
                    .scaleEffect(pulsePhase && isActive ? 1.3 : 1.0)
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)

            if isActive {
                TaskProgressBar(progress: viewModel.taskProgress)
                    .padding(.horizontal, 16)
                    .padding(.top, 4)
                    .padding(.bottom, 6)
                    .transition(.opacity.combined(with: .scale(scale: 0.9, anchor: .bottom)))
            }
        }
        .frame(width: 360, height: isActive ? 56 : 44)
        .background(DynamicIslandBackground())
        .onTapGesture { viewModel.onNotchTap?() }
        .onAppear {
            withAnimation(.easeInOut(duration: 1.0).repeatForever(autoreverses: true)) {
                pulsePhase = true
            }
        }
    }
}

// MARK: - Dynamic Island Background

struct DynamicIslandBackground: View {
    var body: some View {
        Color.black.opacity(0.85)
            .background(VisualEffectBlur(material: .fullScreenUI, blendingMode: .withinWindow))
    }
}

// MARK: - AI Status Dot with Glow

struct AIStatusDot: View {
    let state: TwinState
    let isConnected: Bool
    
    @State private var glowOpacity: CGFloat = 0
    
    private var dotColor: Color {
        if !isConnected { return Color(hex: 0xFF453A) }
        switch state {
        case .idle:      return Color(hex: 0x30D158)
        case .thinking,
             .working:   return Color(hex: 0xFFD60A)
        case .complete:  return Color(hex: 0x30D158)
        case .error:     return Color(hex: 0xFF453A)
        }
    }
    
    private var isActive: Bool {
        state == .thinking || state == .working
    }
    
    var body: some View {
        ZStack {
            if isActive {
                Circle()
                    .fill(dotColor)
                    .frame(width: 16, height: 16)
                    .opacity(glowOpacity * 0.3)
                    .blur(radius: 4)
            }
            
            Circle()
                .fill(dotColor)
                .frame(width: 8, height: 8)
                .overlay(Circle().stroke(dotColor.opacity(0.3), lineWidth: 1))
                .shadow(color: dotColor.opacity(isActive ? 0.6 : 0.2), radius: isActive ? 4 : 2)
        }
        .onChange(of: isActive) { _, newValue in
            if newValue { startGlowAnimation() } else { stopGlowAnimation() }
        }
    }
    
    private func startGlowAnimation() {
        withAnimation(.easeInOut(duration: 0.8).repeatForever(autoreverses: true)) {
            glowOpacity = 1.0
        }
    }
    
    private func stopGlowAnimation() {
        withAnimation(.easeOut(duration: 0.3)) { glowOpacity = 0 }
    }
}

// MARK: - Status Cycling Text

struct StatusCyclingText: View {
    let twinState: TwinState
    
    @State private var wordIndex = 0
    @State private var timerRef: Timer?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    
    private var displayText: String {
        if reduceMotion {
            return twinState == .thinking ? "Thinking..." : "Working..."
        }
        return ThinkingWords.all[wordIndex % ThinkingWords.all.count]
    }
    
    var body: some View {
        Text(displayText)
            .font(.system(size: 14, weight: .medium))
            .foregroundColor(.white.opacity(0.8))
            .id("status-\(wordIndex)")
            .transition(.opacity.combined(with: .move(edge: .bottom)))
            .animation(.spring(response: 0.3, dampingFraction: 0.8), value: displayText)
            .onAppear { startCycling() }
            .onDisappear { timerRef?.invalidate() }
    }
    
    private func startCycling() {
        wordIndex = Int.random(in: 0..<ThinkingWords.all.count)
        let timer = Timer.scheduledTimer(withTimeInterval: 2.5, repeats: true) { _ in
            Task { @MainActor in
                wordIndex = (wordIndex + 1) % ThinkingWords.all.count
            }
        }
        timerRef = timer
    }
}

// MARK: - Task Progress Bar

struct TaskProgressBar: View {
    /// Real progress 0.0–1.0 driven by SSE events from ChatViewModel
    let progress: CGFloat
    
    @State private var displayedProgress: CGFloat = 0
    
    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                // Background track
                RoundedRectangle(cornerRadius: 2)
                    .fill(Color.white.opacity(0.1))
                    .frame(height: 3)
                
                // Animated fill
                RoundedRectangle(cornerRadius: 2)
                    .fill(LinearGradient(
                        colors: [Color(hex: 0x9CA161), Color(hex: 0xB5B055), Color(hex: 0x9CA161)],
                        startPoint: .leading,
                        endPoint: .trailing
                    ))
                    .frame(width: geo.size.width * displayedProgress, height: 3)
            }
        }
        .frame(height: 3)
        .onChange(of: progress) { _, newValue in
            withAnimation(.spring(response: 0.6, dampingFraction: 0.7)) {
                displayedProgress = newValue
            }
        }
        .onAppear {
            // Animate entry if progress already in-flight (e.g. mid-task stage toggle)
            withAnimation(.spring(response: 0.6, dampingFraction: 0.7)) {
                displayedProgress = progress
            }
        }
    }
}

// MARK: - Visual Effect Blur

struct VisualEffectBlur: NSViewRepresentable {
    let material: NSVisualEffectView.Material
    let blendingMode: NSVisualEffectView.BlendingMode
    
    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.material = material
        view.blendingMode = blendingMode
        view.state = .active
        return view
    }
    
    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {
        nsView.material = material
        nsView.blendingMode = blendingMode
    }
}
