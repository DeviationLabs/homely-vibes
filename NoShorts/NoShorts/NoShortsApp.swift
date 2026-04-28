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
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        // When a new window becomes visible (e.g. AVPlayerViewController) and a
        // video is playing, re-assert landscape on its scene. iOS doesn't
        // automatically apply our existing geometry preference to a freshly
        // presented window.
        NotificationCenter.default.addObserver(
            forName: UIWindow.didBecomeVisibleNotification,
            object: nil,
            queue: .main
        ) { note in
            let window = note.object as? UIWindow
            let cls = window.map { String(describing: type(of: $0)) } ?? "nil"
            NSLog("NoShorts.window didBecomeVisible class=\(cls) lock=\(AppDelegate.orientationLock.rawValue)")
            guard let scene = window?.windowScene else { return }
            window?.rootViewController?.setNeedsUpdateOfSupportedInterfaceOrientations()
            scene.requestGeometryUpdate(.iOS(interfaceOrientations: AppDelegate.orientationLock)) { error in
                NSLog("NoShorts.window didBecomeVisible geometryUpdate failed: \(error)")
            }
        }
        NotificationCenter.default.addObserver(
            forName: UIWindow.didBecomeHiddenNotification,
            object: nil,
            queue: .main
        ) { note in
            let window = note.object as? UIWindow
            let cls = window.map { String(describing: type(of: $0)) } ?? "nil"
            NSLog("NoShorts.window didBecomeHidden class=\(cls) lock=\(AppDelegate.orientationLock.rawValue)")
        }
        return true
    }

    func application(
        _ application: UIApplication,
        supportedInterfaceOrientationsFor window: UIWindow?
    ) -> UIInterfaceOrientationMask {
        let cls = window.map { String(describing: type(of: $0)) } ?? "nil"
        NSLog("NoShorts.supportedOrientations window=\(cls) returning=\(AppDelegate.orientationLock.rawValue)")
        return AppDelegate.orientationLock
    }
}
