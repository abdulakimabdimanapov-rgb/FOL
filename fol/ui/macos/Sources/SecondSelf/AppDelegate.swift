import AppKit
import SwiftUI
import Carbon

// Global hotkey reference — stored in a box to be mutable and Sendable
private final class HotKeyBox: @unchecked Sendable {
    var ref: EventHotKeyRef?
}
private let hotKeyBox = HotKeyBox()
private let hotKeyID = EventHotKeyID(signature: 0x464F4C, id: 1) // 'FOL'

/// Hotkey callback — called when Cmd+Shift+T is pressed
private func hotkeyHandler(nextHandler: EventHandlerCallRef?, event: EventRef?, userData: UnsafeMutableRawPointer?) -> OSStatus {
    guard let userData else { return noErr }
    let appDelegate = Unmanaged<AppDelegate>.fromOpaque(userData).takeUnretainedValue()
    Task { @MainActor in
        appDelegate.handleHotkey()
    }
    return noErr
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private var notchPanel: NotchPanel!
    private let viewModel = NotchViewModel()

    func applicationDidFinishLaunching(_ notification: Notification) {
        setupMenuBar()
        setupNotchPanel()
        registerGlobalHotkey()

        // Connect to FOL server
        viewModel.connectOnLaunch()
    }

    func applicationWillTerminate(_ notification: Notification) {
        unregisterGlobalHotkey()
    }

    // MARK: - Global Hotkey (Cmd+Shift+T)

    private func registerGlobalHotkey() {
        // Register the hotkey: Cmd+Shift+T
        let modifiers: UInt32 = UInt32(cmdKey) | UInt32(shiftKey)
        let keyCode = UInt32(kVK_ANSI_T)

        let status = RegisterEventHotKey(
            keyCode,
            modifiers,
            hotKeyID,
            GetEventDispatcherTarget(),
            0,
            &hotKeyBox.ref
        )

        guard status == noErr else {
            print("Failed to register hotkey: \(status)")
            return
        }

        // Install event handler
        let selfPtr = Unmanaged.passUnretained(self).toOpaque()
        var handlerRef: EventHandlerRef?

        var eventSpec = EventTypeSpec(
            eventClass: OSType(kEventClassKeyboard),
            eventKind: UInt32(kEventHotKeyPressed)
        )

        let handlerStatus = InstallEventHandler(
            GetEventDispatcherTarget(),
            hotkeyHandler,
            1,
            &eventSpec,
            selfPtr,
            &handlerRef
        )

        if handlerStatus != noErr {
            print("Failed to install hotkey handler: \(handlerStatus)")
        }
    }

    private func unregisterGlobalHotkey() {
        if let ref = hotKeyBox.ref {
            UnregisterEventHotKey(ref)
            hotKeyBox.ref = nil
        }
    }

    /// Called when the hotkey is pressed — toggles the panel
    @objc func handleHotkey() {
        togglePanel()
    }

    // MARK: - Menu Bar

    private func setupMenuBar() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            button.title = "FOL"
            button.font = NSFont.monospacedSystemFont(ofSize: 12, weight: .medium)
        }

        let menu = NSMenu()
        menu.addItem(withTitle: "Toggle Panel", action: #selector(togglePanel), keyEquivalent: "s")
        menu.addItem(.separator())
        menu.addItem(withTitle: "About FOL", action: #selector(showAbout), keyEquivalent: "")
        menu.addItem(.separator())
        menu.addItem(withTitle: "Quit FOL", action: #selector(quitApp), keyEquivalent: "q")
        statusItem.menu = menu
    }

    // MARK: - Notch Panel

    private func setupNotchPanel() {
        notchPanel = NotchPanel(viewModel: viewModel)
        notchPanel.orderFront(nil)
    }

    // MARK: - Actions

    @objc private func togglePanel() {
        if notchPanel.isVisible {
            notchPanel.orderOut(nil)
            viewModel.collapse()
        } else {
            notchPanel.orderFront(nil)
        }
    }

    @objc private func showAbout() {
        let alert = NSAlert()
        alert.messageText = "FOL"
        alert.informativeText = "Version 2.0.0\nYour personal AI assistant.\n\nBuilt with ❤️"
        alert.alertStyle = .informational
        alert.runModal()
    }

    @objc private func quitApp() {
        unregisterGlobalHotkey()
        NSApp.terminate(nil)
    }
}
