//
//  NoShortsApp.swift
//  NoShorts
//

import SwiftUI
import UIKit

@main
final class AppDelegate: UIResponder, UIApplicationDelegate {
    // Lock for our own app window (browsing chrome). The AVPlayerViewController
    // window is handled separately in supportedInterfaceOrientationsFor below.
    static var orientationLock: UIInterfaceOrientationMask = .portrait

    var window: UIWindow?

    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        let window = UIWindow(frame: UIScreen.main.bounds)
        window.rootViewController = OrientedHostingController(rootView: ContentView())
        window.makeKeyAndVisible()
        self.window = window

        // When AVPlayerViewController dismisses its own UIWindow, force our
        // window back to portrait. Without this nudge, iOS leaves us in
        // whatever orientation the player ended in.
        NotificationCenter.default.addObserver(
            forName: UIWindow.didBecomeHiddenNotification,
            object: nil,
            queue: .main
        ) { [weak self] note in
            guard let win = note.object as? UIWindow, AppDelegate.isVideoFullscreenWindow(win) else { return }
            self?.window?.rootViewController?.setNeedsUpdateOfSupportedInterfaceOrientations()
            for case let scene as UIWindowScene in UIApplication.shared.connectedScenes {
                scene.requestGeometryUpdate(.iOS(interfaceOrientations: .portrait))
            }
        }

        return true
    }

    func application(
        _ application: UIApplication,
        supportedInterfaceOrientationsFor window: UIWindow?
    ) -> UIInterfaceOrientationMask {
        // AVPlayerViewController presents in a separate UIWindow. iOS asks the
        // AppDelegate for that window's mask — return a single landscape so the
        // player can't rotate between left/right via the device sensor.
        if AppDelegate.isVideoFullscreenWindow(window) {
            return .landscapeRight
        }
        return AppDelegate.orientationLock
    }

    // The fullscreen video window's class name on iOS varies by version
    // (AVFullScreenWindow, _UIRemoteKeyboardWindow-style internals, etc.) but
    // reliably contains "Fullscreen" or "AVPlayer" — match loosely.
    static func isVideoFullscreenWindow(_ window: UIWindow?) -> Bool {
        guard let window else { return false }
        let name = String(describing: type(of: window))
        return name.contains("Fullscreen") || name.contains("AVPlayer")
    }
}

// SwiftUI's default UIHostingController returns .all for supportedInterfaceOrientations,
// which makes iOS follow the device sensor regardless of what the AppDelegate says.
// Subclassing and deferring to AppDelegate.orientationLock pins the orientation.
final class OrientedHostingController<Content: View>: UIHostingController<Content> {
    override var supportedInterfaceOrientations: UIInterfaceOrientationMask {
        AppDelegate.orientationLock
    }

    override var preferredInterfaceOrientationForPresentation: UIInterfaceOrientation {
        switch AppDelegate.orientationLock {
        case .landscapeRight: return .landscapeRight
        case .landscapeLeft: return .landscapeLeft
        case .portrait: return .portrait
        default: return .portrait
        }
    }
}
