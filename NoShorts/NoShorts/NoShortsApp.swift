//
//  NoShortsApp.swift
//  NoShorts
//

import SwiftUI
import UIKit

@main
struct NoShortsApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) var delegate
    var body: some Scene {
        WindowGroup { ContentView() }
    }
}

final class AppDelegate: NSObject, UIApplicationDelegate {
    // Source of truth for the orientation iOS will rotate to / hold at.
    // Updated by the JS-driven video-play/pause handler in ContentView.
    static var orientationLock: UIInterfaceOrientationMask = .portrait

    func application(
        _ application: UIApplication,
        supportedInterfaceOrientationsFor window: UIWindow?
    ) -> UIInterfaceOrientationMask {
        AppDelegate.orientationLock
    }
}
