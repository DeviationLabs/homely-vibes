import Foundation

/// Poll cadence, persisted in UserDefaults so a choice survives relaunch.
///
/// 180s is the default: the underlying windows move slowly (the 5-hour bar
/// shifts ~0.5%/min at a heavy sustained pace, the 7-day bar far slower), so
/// polling faster mostly spends requests to redraw an unchanged number.
enum RefreshInterval {
    static let defaultSeconds: TimeInterval = 180
    static let choices: [TimeInterval] = [30, 60, 180, 300, 600, 1800]

    private static let key = "refreshIntervalSeconds"

    /// Falls back to the default when unset, or when a stored value has drifted
    /// outside the offered choices (hand-edited plist, or a value retired by a
    /// later version) — a 0 or negative value here would spin the timer hot.
    static var current: TimeInterval {
        get {
            let stored = UserDefaults.standard.double(forKey: key)
            return choices.contains(stored) ? stored : defaultSeconds
        }
        set { UserDefaults.standard.set(newValue, forKey: key) }
    }

    static func label(for seconds: TimeInterval) -> String {
        seconds < 60
            ? "\(Int(seconds))s"
            : "\(Int(seconds / 60)) min"
    }
}
