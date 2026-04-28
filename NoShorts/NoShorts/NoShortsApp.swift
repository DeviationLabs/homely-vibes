//
//  NoShortsApp.swift
//  NoShorts
//

import SwiftUI
import UIKit

@main
final class AppDelegate: UIResponder, UIApplicationDelegate {
    // Source of truth for which orientations iOS will rotate to.
    // Updated by ContentView as the user navigates between watch pages
    // (landscape) and everything else (portrait).
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
        return true
    }

    func application(
        _ application: UIApplication,
        supportedInterfaceOrientationsFor window: UIWindow?
    ) -> UIInterfaceOrientationMask {
        AppDelegate.orientationLock
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
