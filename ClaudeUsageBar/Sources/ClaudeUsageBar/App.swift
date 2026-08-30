import AppKit

@main
struct ClaudeUsageBarApp {
    @MainActor
    static func main() {
        if CommandLine.arguments.contains("--probe-keychain") {
            KeychainTokenReader.probe()
            return
        }
        if CommandLine.arguments.contains("--probe-usage") {
            probeUsage()
            return
        }
        if CommandLine.arguments.contains("--probe-nudge") {
            probeNudge()
            return
        }

        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        let delegate = AppDelegate()
        app.delegate = delegate
        app.run()
    }

    /// Reports whether the `claude` CLI can be located and driven, without
    /// waiting for a real expiry. Safe to run any time: on a still-valid token
    /// the CLI's refresh path short-circuits to "not_needed", so this only
    /// proves reachability. `ClaudeUsageBar --probe-nudge`.
    private static func probeNudge() {
        let resolved = CredentialRefresher.resolveCLIPath()
        print("claude CLI: \(resolved ?? "NOT FOUND on any candidate path")")
        for candidate in CredentialRefresher.defaultCandidatePaths {
            let executable = FileManager.default.isExecutableFile(atPath: candidate)
            print("  \(executable ? "✓" : "✗") \(candidate)")
        }
        guard resolved != nil else { return }
        let outcome = CredentialRefresher().nudge()
        print("nudge:      \(outcome.logDescription)")
    }

    /// One-shot fetch + print, for verifying the API call against `/usage`
    /// output without needing the menu bar UI. `swift run ClaudeUsageBar --probe-usage`.
    @MainActor
    private static func probeUsage() {
        // .detached so this doesn't inherit MainActor isolation from the
        // caller — otherwise it deadlocks against the semaphore.wait() below
        // (the Task would be queued on the same main thread that's blocked).
        let semaphore = DispatchSemaphore(value: 0)
        Task.detached {
            defer { semaphore.signal() }
            do {
                let snapshot = try await UsageClient.fetchSnapshot()
                func describe(_ label: String, _ window: UsageWindow?) {
                    guard let window else {
                        print("\(label): (absent)")
                        return
                    }
                    print("\(label): \(Int(window.utilization.rounded()))% — resets \(window.resetsAt)")
                }
                describe("five_hour", snapshot.fiveHour)
                describe("seven_day", snapshot.sevenDay)
                describe("seven_day_opus", snapshot.sevenDayOpus)
                describe("seven_day_sonnet", snapshot.sevenDaySonnet)
                if let spend = snapshot.spend {
                    print("spend: \(spend.usedDollars) / \(spend.limitDollars) \(spend.currency) (\(Int(spend.percent.rounded()))%)")
                } else {
                    print("spend: (absent)")
                }
            } catch {
                print("fetch failed: \(error)")
            }
        }
        semaphore.wait()
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItemController: StatusItemController?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let controller = StatusItemController()
        controller.start()
        statusItemController = controller
    }
}
