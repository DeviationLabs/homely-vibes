//
//  NoShortsApp.swift
//  NoShorts
//
//  Created by Amit Butala on 4/26/26.
//

import SwiftUI
import UIKit

@main
struct NoShortsApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) var delegate
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}

final class AppDelegate: NSObject, UIApplicationDelegate {
    // Source of truth for which orientations iOS will rotate to. Updated by
    // ContentView when navigating between watch and non-watch pages.
    static var orientationLock: UIInterfaceOrientationMask = .portrait

    func application(_ application: UIApplication, supportedInterfaceOrientationsFor window: UIWindow?) -> UIInterfaceOrientationMask {
        AppDelegate.orientationLock
    }
}
