import SwiftUI
import AppKit

// MARK: - App Entry Point
// macOS notch-resident digital twin app. No dock icon (LSUIElement = true).
// Global hotkey Cmd+Shift+T toggles the chat panel.

@main
struct FOLApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        Settings {
            EmptyView()
        }
    }
}

// MARK: - App Delegate

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var overlayController: NotchOverlayController?
    private var globalHotkeyMonitor: Any?
    private var subprocesses: [Process] = []
    private var repoRoot: URL?
    private var pythonPath: String?
    private var envVars: [String: String] = [:]

    // Menu bar status item
    private var statusItem: NSStatusItem?
    private var logEntries: [String] = []
    private let maxLogEntries = 30

    /// Retained notification observer tokens so they can be removed on termination.
    private var logObservers: [NSObjectProtocol] = []

    /// Shared accessor for .env variables. Available after applicationDidFinishLaunching.
    /// Used by ElevenLabsService to read ELEVENLABS_API_KEY without duplicating .env parsing.
    /// nonisolated(unsafe): set once during startup, read-only after. Safe in practice.
    nonisolated(unsafe) static private(set) var sharedEnvVars: [String: String] = [:]

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)

        // Register default settings
        UserDefaults.standard.register(defaults: [
            "autoExpandOnActivity": true
        ])

        // Discover repo root, python, and env vars once
        discoverEnvironment()

        // Check what's already running (services are kept, not restarted)
        cleanupStaleProcesses()

        // Verify secondself user exists (first-time install check)
        checkAgentUser()

        // Clear agent browser session for a fresh start
        clearAgentBrowser()

        // LOCAL MODE: Install Python deps on first launch, then start services.
        Task {
            await FirstLaunchInstaller.installIfNeeded(
                repoRoot: repoRoot!,
                pythonPath: pythonPath ?? "/usr/bin/python3"
            )
            await MainActor.run {
                statusLog("Python dependencies ready")

                // Start backend services — each one only if its port is free.
                statusLog("Local mode: starting orchestrator...")
                launchPython(script: "orchestrator/server.py", label: "Orchestrator", port: 8420)

                statusLog("Starting agent server...")
                launchPython(script: "agent-server/server.py", label: "Agent Server", port: 8421)

                statusLog("Starting FOL server...")
                launchPython(script: "fol/run_api_server.py", label: "FOL Server", port: 8754)
            }
        }

        // Always create the notch — it shows chat (no sign-in required)
        Task { @MainActor in
            let controller = NotchOverlayController()
            overlayController = controller
        }

        // Register global hotkey: Cmd+Shift+T
        globalHotkeyMonitor = NSEvent.addGlobalMonitorForEvents(
            matching: .keyDown
        ) { [weak self] event in
            Task { @MainActor in
                self?.handleGlobalKeyEvent(event)
            }
        }
        NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            Task { @MainActor in
                self?.handleGlobalKeyEvent(event)
            }
            return event
        }

        // Menu bar status icon
        setupStatusItem()

        // Redirect prints to the log buffer
        statusLog("App launched")
        statusLog("Repo: \(repoRoot?.path ?? "not found")")
        statusLog("Python: \(pythonPath ?? "not found")")

        // Observe UI events for status logging
        observeUIEvents()

        // Play JARVIS boot chime after a short delay (let the UI settle)
        Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(600))
            AudioManager.shared.restoreMuteState()
            AudioManager.shared.playBootChime()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let monitor = globalHotkeyMonitor {
            NSEvent.removeMonitor(monitor)
        }
        // Stop backend services started by this app
        for p in subprocesses {
            p.terminate()
            p.waitUntilExit()
        }
        // Clean up temporary service logs created by this app
        let fm = FileManager.default
        if let files = try? fm.contentsOfDirectory(atPath: "/tmp") {
            for f in files where f.hasPrefix("secondself-") && f.hasSuffix(".log") {
                try? fm.removeItem(atPath: "/tmp/\(f)")
            }
        }
        // Clean up notification observers
        for observer in logObservers {
            NotificationCenter.default.removeObserver(observer)
        }
        logObservers.removeAll()
    }

    // MARK: - Menu Bar Status Item

    private func setupStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let button = statusItem?.button {
            button.image = NSImage(systemSymbolName: "brain.head.profile", accessibilityDescription: "FOL")
            button.image?.size = NSSize(width: 18, height: 18)
            button.image?.isTemplate = true
        }
        rebuildMenu()
    }

    private func rebuildMenu() {
        let menu = NSMenu()

        // Status header
        let header = NSMenuItem(title: "FOL", action: nil, keyEquivalent: "")
        header.isEnabled = false
        menu.addItem(header)
        menu.addItem(NSMenuItem.separator())

        // Connection status
        let orchestratorStatus = checkPort(8420) ? "Orchestrator: running" : "Orchestrator: stopped"
        let agentStatus = checkPort(8421) ? "Agent Server: running" : "Agent Server: stopped"
        let folStatus = checkPort(8754) ? "FOL API: running" : "FOL API: stopped"

        for label in [orchestratorStatus, agentStatus, folStatus] {
            let item = NSMenuItem(title: label, action: nil, keyEquivalent: "")
            item.isEnabled = false
            if label.contains("running") {
                item.image = NSImage(systemSymbolName: "circle.fill", accessibilityDescription: nil)
                item.image?.isTemplate = false
            } else {
                item.image = NSImage(systemSymbolName: "circle", accessibilityDescription: nil)
            }
            menu.addItem(item)
        }

        menu.addItem(NSMenuItem.separator())

        // Recent logs
        let logsHeader = NSMenuItem(title: "Recent Logs", action: nil, keyEquivalent: "")
        logsHeader.isEnabled = false
        menu.addItem(logsHeader)

        let recentLogs = logEntries.suffix(10)
        if recentLogs.isEmpty {
            let empty = NSMenuItem(title: "  (no logs yet)", action: nil, keyEquivalent: "")
            empty.isEnabled = false
            menu.addItem(empty)
        } else {
            for entry in recentLogs {
                let item = NSMenuItem(title: "  \(entry)", action: nil, keyEquivalent: "")
                item.isEnabled = false
                item.attributedTitle = NSAttributedString(
                    string: "  \(entry)",
                    attributes: [.font: NSFont.monospacedSystemFont(ofSize: 10, weight: .regular)]
                )
                menu.addItem(item)
            }
        }

        menu.addItem(NSMenuItem.separator())

        // Actions
        menu.addItem(NSMenuItem(title: "Toggle Panel", action: #selector(togglePanel), keyEquivalent: "t"))
        menu.addItem(NSMenuItem(title: "Refresh Status", action: #selector(refreshStatus), keyEquivalent: "r"))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "Quit FOL", action: #selector(quitApp), keyEquivalent: "q"))

        statusItem?.menu = menu
    }

    func statusLog(_ message: String) {
        let timestamp = DateFormatter.localizedString(from: Date(), dateStyle: .none, timeStyle: .medium)
        let entry = "\(timestamp) \(message)"
        logEntries.append(entry)
        if logEntries.count > maxLogEntries {
            logEntries.removeFirst()
        }
        print("[FOL] \(message)")
        // Rebuild menu to show new log
        DispatchQueue.main.async { [weak self] in
            self?.rebuildMenu()
        }
    }

    private func checkPort(_ port: Int) -> Bool {
        let sock = socket(AF_INET, SOCK_STREAM, 0)
        guard sock >= 0 else { return false }
        defer { close(sock) }
        var addr = sockaddr_in()
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = in_port_t(port).bigEndian
        addr.sin_addr.s_addr = inet_addr("127.0.0.1")
        let result = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                connect(sock, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        return result == 0
    }

    @objc private func togglePanel() {
        overlayController?.togglePanel()
    }

    @MainActor
    @objc private func refreshStatus() {
        statusLog("Status refreshed")
        rebuildMenu()
    }

    @MainActor
    @objc private func quitApp() {
        NSApp.terminate(nil)
    }

    // MARK: - Startup Cleanup

    private func cleanupStaleProcesses() {
        // Services that are already running are KEPT (never restarted), so
        // this is now a status pass rather than a kill pass.
        print("[FOL] Checking existing services (running ones are kept)...")
        for (name, port) in [("Orchestrator", 8420), ("Agent Server", 8421), ("FOL", 8754)] {
            if checkPort(port) {
                statusLog("\(name) already running on :\(port) — keeping")
            } else {
                statusLog("\(name) free on :\(port)")
            }
        }
    }

    private func killProcesses(matching pattern: String) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/pkill")
        process.arguments = ["-f", pattern]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        try? process.run()
        process.waitUntilExit()
    }

    private func killPort(_ port: Int) {
        // Use lsof to find PID on port, then kill it
        let lsof = Process()
        lsof.executableURL = URL(fileURLWithPath: "/usr/sbin/lsof")
        lsof.arguments = ["-ti", ":\(port)"]
        let pipe = Pipe()
        lsof.standardOutput = pipe
        lsof.standardError = FileHandle.nullDevice
        try? lsof.run()
        lsof.waitUntilExit()

        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        guard let output = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines),
              !output.isEmpty else { return }

        for pidStr in output.components(separatedBy: .newlines) {
            if let pid = Int32(pidStr.trimmingCharacters(in: .whitespaces)) {
                kill(pid, SIGTERM)
            }
        }
    }

    /// Returns true if first-run setup is needed (user missing or agent not healthy).
    private func checkAgentUser() {
        let check = Process()
        check.executableURL = URL(fileURLWithPath: "/usr/bin/id")
        check.arguments = ["secondself"]
        check.standardOutput = FileHandle.nullDevice
        check.standardError = FileHandle.nullDevice
        try? check.run()
        check.waitUntilExit()

        if check.terminationStatus != 0 {
            statusLog("secondself user not found — setup wizard will show")
        } else {
            statusLog("secondself user found")
        }
    }

    /// Whether the first-run setup wizard should be shown.
    /// Only checks UserDefaults + user existence (fast, no network).
    nonisolated var needsFirstRunSetup: Bool {
        if UserDefaults.standard.bool(forKey: "setupComplete") { return false }

        // Check if secondself user exists (fast shell check)
        let check = Process()
        check.executableURL = URL(fileURLWithPath: "/usr/bin/id")
        check.arguments = ["secondself"]
        check.standardOutput = FileHandle.nullDevice
        check.standardError = FileHandle.nullDevice
        do {
            try check.run()
            check.waitUntilExit()
        } catch {
            return true
        }

        return check.terminationStatus != 0
    }

    private func clearAgentBrowser() {
        // Tell agent-server to close any stale browser session
        guard let url = URL(string: "http://localhost:8421/browser/close") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.httpBody = "{}".data(using: .utf8)
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 2
        URLSession.shared.dataTask(with: request) { _, _, error in
            if let error = error {
                print("[FOL] Browser clear skipped (agent-server may not be running): \(error.localizedDescription)")
            } else {
                print("[FOL] Agent browser session cleared ✓")
            }
        }.resume()
    }

    // MARK: - Environment Discovery

    private func discoverEnvironment() {
        // Check well-known locations for the repo, then walk up from binary
        let fm = FileManager.default
        let home = NSHomeDirectory()
        var knownPaths: [String] = [
            "\(home)/second-self",
            "\(home)/Desktop/Fol",              // Xcode / swift run from repo
            "/usr/local/share/second-self",
        ]

        // Also check inside the .app bundle (DMG install: backend bundled in Resources)
        if let bundlePath = Bundle.main.resourcePath {
            let bundledBackend = bundlePath + "/backend"
            if fm.fileExists(atPath: bundledBackend + "/orchestrator/server.py") {
                knownPaths.insert(bundledBackend, at: 0)
            }
        }

        var root: URL?
        for path in knownPaths {
            if fm.fileExists(atPath: "\(path)/orchestrator/server.py") {
                root = URL(fileURLWithPath: path)
                break
            }
        }

        // Fallback: walk up from binary (works in dev with swift run)
        if root == nil {
            let execURL = Bundle.main.executableURL ?? URL(fileURLWithPath: ProcessInfo.processInfo.arguments[0])
            var candidate = execURL.deletingLastPathComponent()
            for _ in 0..<10 {
                if fm.fileExists(atPath: candidate.appendingPathComponent("orchestrator/server.py").path) {
                    root = candidate
                    break
                }
                candidate = candidate.deletingLastPathComponent()
            }
        }

        repoRoot = root ?? URL(fileURLWithPath: "\(home)/second-self")

        envVars = ProcessInfo.processInfo.environment
        let envPath = repoRoot!.appendingPathComponent(".env")
        if let contents = try? String(contentsOf: envPath, encoding: .utf8) {
            for line in contents.components(separatedBy: .newlines) {
                let trimmed = line.trimmingCharacters(in: .whitespaces)
                if trimmed.isEmpty || trimmed.hasPrefix("#") { continue }
                let parts = trimmed.split(separator: "=", maxSplits: 1)
                if parts.count == 2 {
                    envVars[String(parts[0])] = String(parts[1])
                }
            }
        }

        // Expose env vars to other services (e.g. ElevenLabsService reads ELEVENLABS_API_KEY)
        AppDelegate.sharedEnvVars = envVars

        let userHome = envVars["HOME"] ?? NSHomeDirectory()
        let candidates = [
            "/usr/local/share/second-self/python/bin/python3",
            "\(userHome)/.pyenv/versions/3.11.8/bin/python3",
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
            "/usr/bin/python3"
        ]
        pythonPath = candidates.first { FileManager.default.fileExists(atPath: $0) } ?? "/usr/bin/python3"
    }

    // MARK: - Launch Python Subprocess

    private func launchPython(script: String, label: String, port: Int? = nil) {
        guard let root = repoRoot, let python = pythonPath else {
            statusLog("Cannot start \(label): repoRoot or python not configured")
            return
        }

        // If the service is already listening, don't start a second instance.
        if let port = port, checkPort(port) {
            statusLog("\(label) already running on :\(port) — skipping start")
            return
        }

        let scriptPath = root.appendingPathComponent(script)
        guard FileManager.default.fileExists(atPath: scriptPath.path) else {
            statusLog("\(script) not found at \(scriptPath.path), skipping")
            return
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = [scriptPath.path]
        process.currentDirectoryURL = root
        process.environment = envVars

        // Redirect stdout+stderr to a log file so we can debug failures.
        // GUI apps have no terminal — without this, Python crash output is invisible.
        let logPath = "/tmp/secondself-\(label.lowercased().replacingOccurrences(of: " ", with: "-")).log"
        FileManager.default.createFile(atPath: logPath, contents: nil, attributes: nil)
        if let logHandle = FileHandle(forWritingAtPath: logPath) {
            process.standardOutput = logHandle
            process.standardError = logHandle
        }

        do {
            try process.run()
            subprocesses.append(process)
            statusLog("\(label) started (PID \(process.processIdentifier), log: \(logPath))")
        } catch {
            statusLog("Failed to start \(label): \(error)")
        }
    }

    private func launchModule(module: String, args: [String], label: String) {
        guard let root = repoRoot, let python = pythonPath else {
            statusLog("Cannot start \(label): repoRoot or python not configured")
            return
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = ["-m", module] + args
        process.currentDirectoryURL = root
        process.environment = envVars

        // Redirect output to a log file (same reason as launchPython)
        let logPath = "/tmp/secondself-\(label.lowercased().replacingOccurrences(of: " ", with: "-")).log"
        FileManager.default.createFile(atPath: logPath, contents: nil, attributes: nil)
        if let logHandle = FileHandle(forWritingAtPath: logPath) {
            process.standardOutput = logHandle
            process.standardError = logHandle
        }

        do {
            try process.run()
            subprocesses.append(process)
            statusLog("\(label) started (PID \(process.processIdentifier), log: \(logPath))")
        } catch {
            statusLog("Failed to start \(label): \(error)")
        }
    }

    private func handleGlobalKeyEvent(_ event: NSEvent) {
        // Cmd+Shift+T: toggle panel
        let requiredFlags: NSEvent.ModifierFlags = [.command, .shift]
        let keyT: UInt16 = 17
        if event.modifierFlags.contains(requiredFlags) && event.keyCode == keyT {
            Task { @MainActor in
                overlayController?.togglePanel()
            }
            return
        }

        // Escape: collapse to compact
        let keyEscape: UInt16 = 53
        if event.keyCode == keyEscape {
            Task { @MainActor in
                overlayController?.collapse()
            }
        }
    }

    // MARK: - UI Event Logging

    /// Observe notifications posted by SwiftUI views and log key user interactions
    /// to the status menu for debugging and observability.
    /// Tokens are retained in `logObservers` so they can be removed on termination.
    /// Observe notifications posted by SwiftUI views and log key user interactions
    /// to the status menu for debugging and observability.
    /// Tokens are retained in `logObservers` so they can be removed on termination.
    private func observeUIEvents() {
        let center = NotificationCenter.default
        let queue = OperationQueue.main

        let chatToken = center.addObserver(forName: .secondSelfChatOpened, object: nil, queue: queue) { [weak self] _ in
            Task { @MainActor in
                self?.statusLog("Chat opened")
            }
        }
        logObservers.append(chatToken)

        let focusToken = center.addObserver(forName: .secondSelfInputFocused, object: nil, queue: queue) { [weak self] _ in
            Task { @MainActor in
                self?.statusLog("Input field focused")
            }
        }
        logObservers.append(focusToken)

        let sentToken = center.addObserver(forName: .secondSelfMessageSent, object: nil, queue: queue) { [weak self] _ in
            Task { @MainActor in
                self?.statusLog("Message sent")
            }
        }
        logObservers.append(sentToken)
    }
}
