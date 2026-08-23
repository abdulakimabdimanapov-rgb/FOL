import Foundation

/// First-launch dependency installer.
///
/// On the very first run (or after an update) the Python backend services
/// cannot start because `pip install` has not been executed yet.  This
/// lightweight utility detects that situation, runs the install in the
/// background, and reports progress through the AppDelegate status log.
///
/// Usage (from AppDelegate):
///   await FirstLaunchInstaller.installIfNeeded(repoRoot: repoRoot, pythonPath: pythonPath)
enum FirstLaunchInstaller {

    // MARK: - Public API

    /// Returns `true` when Python deps are ready (marker file exists or
    /// install already completed this session).
    static var isReady: Bool { _ready }

    /// Run `pip install` if the marker file is missing.
    /// Awaits completion so callers can block service startup.
    static func installIfNeeded(repoRoot: URL, pythonPath: String) async {
        guard !isReady else { return }

        let marker = markerURL(repoRoot: repoRoot)

        // Fast path — marker exists, skip
        if FileManager.default.fileExists(atPath: marker.path) {
            _ready = true
            return
        }

        // Slow path — install deps
        await withCheckedContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                Self.runInstall(repoRoot: repoRoot, pythonPath: pythonPath, marker: marker)
                Self._ready = true
                continuation.resume()
            }
        }
    }

    // MARK: - Internal

    nonisolated(unsafe) private static var _ready = false

    /// Marker file lives next to the repo root so updates / reinstalls can
    /// re-trigger by simply deleting it.
    private static func markerURL(repoRoot: URL) -> URL {
        repoRoot.appendingPathComponent(".fol-deps-installed")
    }

    private static func runInstall(repoRoot: URL, pythonPath: String, marker: URL) {
        let logPrefix = "[FirstLaunch]"

        func log(_ msg: String) {
            print("\(logPrefix) \(msg)")
        }

        // Locate requirements.txt
        let reqFile = repoRoot.appendingPathComponent("requirements.txt")
        guard FileManager.default.fileExists(atPath: reqFile.path) else {
            log("requirements.txt not found — skipping pip install")
            writeMarker(marker)
            return
        }

        log("Installing Python dependencies …")

        // ── 1. Try the bundled setup script first (handles system deps too) ──
        let setupScript = repoRoot
            .appendingPathComponent("setup")
            .appendingPathComponent("install_deps.py")

        if FileManager.default.fileExists(atPath: setupScript.path) {
            let exitCode = run(
                pythonPath,
                args: [setupScript.path, "--python"],
                cwd: repoRoot
            )
            if exitCode == 0 {
                log("Dependencies installed via install_deps.py ✅")
                writeMarker(marker)
                return
            }
            log("install_deps.py exited \(exitCode) — falling back to pip")
        }

        // ── 2. Fallback: direct pip install ──
        let exitCode = run(
            pythonPath,
            args: ["-m", "pip", "install", "-r", reqFile.path, "--quiet"],
            cwd: repoRoot
        )

        if exitCode == 0 {
            log("Python dependencies installed ✅")
            writeMarker(marker)
        } else {
            // Partial failure — still mark as done so we don't block startup.
            // Individual services will log their own import errors.
            log("pip install exited \(exitCode) — some deps may be missing")
            writeMarker(marker)
        }
    }

    /// Run a subprocess and return its exit code.
    @discardableResult
    private static func run(_ executable: String, args: [String], cwd: URL) -> Int32 {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: executable)
        proc.arguments = args
        proc.currentDirectoryURL = cwd

        // Suppress output in production (GUI app has no terminal)
        let devNull = FileHandle.nullDevice
        proc.standardOutput = devNull
        proc.standardError = devNull

        do {
            try proc.run()
            proc.waitUntilExit()
            return proc.terminationStatus
        } catch {
            print("[FirstLaunch] Failed to run \(executable): \(error)")
            return -1
        }
    }

    /// Write the marker so subsequent launches skip the install.
    private static func writeMarker(_ url: URL) {
        try? "installed".write(to: url, atomically: true, encoding: .utf8)
    }
}
