"""FOL macOS Native App — Floating notch-style island window using PyObjC.

This creates a borderless, always-on-top transparent window that hosts
the FOL web UI, similar to the macOS Notch UI.

Usage:
    # From fol-app/ directory:
    python fol/fol_mac_app.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import webbrowser
from pathlib import Path

# Ensure `fol/` is in sys.path when running from parent directory
_fol_dir = Path(__file__).parent
if str(_fol_dir) not in sys.path:
    sys.path.insert(0, str(_fol_dir))

# PyObjC imports for native macOS window
try:
    import objc
    from AppKit import (
        NSApplication,
        NSApp,
        NSBackingStoreBuffered,
        NSBezierPath,
        NSColor,
        NSScreen,
        NSStatusBar,
        NSStatusItem,
        NSMenu,
        NSMenuItem,
        NSImage,
        NSWindow,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorStationary,
        NSWindowStyleMaskClosable,
        NSWindowStyleMaskFullSizeContentView,
        NSWindowStyleMaskMiniaturizable,
        NSObject,
    )
    from WebKit import WebView
    HAS_PYOBJC = True
except ImportError:
    HAS_PYOBJC = False
    print("PyObjC not installed. Install with: pip install pyobjc pyobjc-framework-WebKit")

import uvicorn
import time as _time

# Project paths
PROJECT_DIR = Path(__file__).parent
UI_DIR = PROJECT_DIR / "ui" / "web"
FOL_DIR = PROJECT_DIR


class FolAppDelegate(NSObject):
    """App delegate for the FOL macOS app."""

    # Store as regular Python attrs (more reliable with modern PyObjC)
    window = None
    web_view = None
    status_item = None
    server_thread = None
    is_visible = False

    @objc.method
    def applicationDidFinishLaunching_(self, notification):
        """Called when the app finishes launching."""
        self.is_visible = True

        # Create the main window — borderless, floating, transparent
        screen = NSScreen.mainScreen()
        screen_frame = screen.frame()

        # Window size — compact island style
        window_width = 520
        window_height = 600

        # Position: top center, near the notch
        window_x = (screen_frame.size.width - window_width) / 2
        window_y = screen_frame.size.height - window_height - 45  # Below menu bar

        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            ((window_x, window_y), (window_width, window_height)),
            NSWindowStyleMaskFullSizeContentView | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable,
            NSBackingStoreBuffered,
            True,
        )

        # Configure window
        window.setTitle_("FOL")
        window.setTitlebarAppearsTransparent_(True)
        window.setTitleVisibility_(1)  # NSTitleVisibilityHidden
        window.setMovableByWindowBackground_(True)
        window.setOpaque_(False)
        window.setBackgroundColor_(NSColor.clearColor())
        window.setHasShadow_(True)
        window.setLevel_(15)  # Above normal windows, below system
        window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorStationary
        )
        window.setIsVisible_(True)
        window.setReleasedWhenClosed_(False)
        window.setHidesOnDeactivate_(False)
        window.setAnimationBehavior_(2)  # NSWindowAnimationBehaviorDocumentWindow

        # Set the content view to be transparent
        content_view = window.contentView()
        content_view.setWantsLayer_(True)
        content_view.layer().setCornerRadius_(16.0)
        content_view.layer().setMasksToBounds_(True)

        # Create WebView for the FOL UI
        web_frame = content_view.bounds()
        web_view = WebView.alloc().initWithFrame_frameName_groupName_(
            web_frame, "FOLWebView", "FOLGroup"
        )
        web_view.setAutoresizingMask_(18)  # Width + Height flexible
        web_view.setBackgroundColor_(NSColor.clearColor())
        content_view.addSubview_(web_view)

        self.window = window
        self.web_view = web_view

        # Load the FOL UI
        index_path = UI_DIR / "index.html"
        if index_path.exists():
            url = f"file://{index_path.absolute()}"
            web_view.setMainFrameURL_(url)
            print(f"Loading FOL UI from: {url}")
        else:
            print(f"Warning: UI not found at {index_path}")

        # Set up status bar menu
        self._setup_status_bar()

        # Start the FOL API server in a background thread
        self._start_server()

        # Show window
        window.makeKeyAndOrderFront_(None)
        window.makeMainWindow()

        print("FOL macOS app launched successfully!")

    @objc.method
    def _setup_status_bar(self):
        """Create a menu bar status item."""
        status_bar = NSStatusBar.systemStatusBar()
        status_item = status_bar.statusItemWithLength_(-1)  # NSVariableStatusItemLength

        # Set the status bar icon
        image = NSImage.alloc().initWithSize_((18, 18))
        image.lockFocus()
        NSColor.whiteColor().set()

        # Draw a simple circle icon
        path = NSBezierPath.bezierPathWithOvalInRect_(((2, 2), (14, 14)))
        path.fill()

        image.unlockFocus()
        image.setTemplate_(True)
        status_item.setImage_(image)
        status_item.setTitle_("")

        # Create menu
        menu = NSMenu.alloc().init()

        show_item = menu.addItemWithTitle_action_keyEquivalent_("Show FOL", "showWindow:", "f")
        show_item.setTarget_(self)

        menu.addItem_(NSMenuItem.separatorItem())

        quit_item = menu.addItemWithTitle_action_keyEquivalent_("Quit", "terminate:", "q")
        quit_item.setTarget_(NSApp)

        status_item.setMenu_(menu)
        self.status_item = status_item

    @objc.method
    def showWindow_(self, sender):
        """Show the main window."""
        self.window.makeKeyAndOrderFront_(None)
        self.window.setIsVisible_(True)
        self.is_visible = True

    @objc.method
    def toggleWindow_(self, sender):
        """Toggle window visibility."""
        if self.is_visible:
            self.window.setIsVisible_(False)
            self.is_visible = False
        else:
            self.window.makeKeyAndOrderFront_(None)
            self.window.setIsVisible_(True)
            self.is_visible = True

    @objc.method
    def _start_server(self):
        """Start the FOL API server in a background thread."""
        def run_server():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                # Import and initialize FOL
                sys.path.insert(0, str(FOL_DIR))
                from core.app import FOL
                from api.rest.server import app, set_fol_instance

                print("Initializing FOL backend...")
                fol = FOL()
                loop.run_until_complete(fol.lifecycle.start())
                set_fol_instance(fol)
                print("FOL backend ready!")

                # Start uvicorn
                config = uvicorn.Config(
                    app,
                    host="127.0.0.1",
                    port=8754,
                    log_level="warning",
                    loop="auto",
                    access_log=False,
                )
                server = uvicorn.Server(config)
                loop.run_until_complete(server.serve())
            except Exception as e:
                print(f"Server error: {e}")
                # Fallback: just serve static files
                self._run_static_server()

        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()

        # Wait a moment then reload the web view to pick up the server
        def reload_after_delay():
            _time.sleep(2)
            if self.web_view:
                self.web_view.setMainFrameURL_("http://127.0.0.1:8754/")

        threading.Thread(target=reload_after_delay, daemon=True).start()

    @objc.method
    def _run_static_server(self):
        """Simple static file server as fallback."""
        import http.server
        import socketserver

        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(UI_DIR), **kwargs)

            def do_POST(self):
                """Mock API endpoint."""
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"response": "FOL server is starting... Please wait."}')

            def log_message(self, format, *args):
                pass  # Suppress logs

        with socketserver.TCPServer(("127.0.0.1", 8754), Handler) as httpd:
            print("FOL static server running on http://127.0.0.1:8754")
            httpd.serve_forever()

    @objc.method
    def applicationShouldTerminateAfterLastWindowClosed_(self, sender):
        return False

    @objc.method
    def applicationWillTerminate_(self, notification):
        """Clean up on quit."""
        print("FOL shutting down...")
        if self.status_item:
            NSStatusBar.systemStatusBar().removeStatusItem_(self.status_item)


def main():
    """Main entry point for the FOL macOS app."""
    if not HAS_PYOBJC:
        print("Error: PyObjC is required for the macOS app.")
        print("Install with: pip install pyobjc pyobjc-framework-WebKit")
        print("\nFalling back to web-only mode...")
        webbrowser.open("http://127.0.0.1:8754")
        return

    # Set up the app
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(0)  # NSApplicationActivationPolicyAccessory — no dock icon

    delegate = FolAppDelegate.alloc().init()
    app.setDelegate_(delegate)

    # Run the app
    app.run()


if __name__ == "__main__":
    main()
