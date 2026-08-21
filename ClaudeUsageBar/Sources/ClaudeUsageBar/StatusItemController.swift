import AppKit
import os.log

@MainActor
final class StatusItemController {
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private var refreshTimer: Timer?
    private var lastGoodSnapshot: UsageSnapshot?
    private let spendSettingsURL = URL(string: "https://claude.ai/new#settings/usage")!
    private static let fullFiveHourWindow = "5h"

    // Diagnostics for the "stuck on a stale error for hours" failure mode
    // (seen 2026-08, fixed by a restart, root cause unconfirmed — could be
    // App Nap throttling the repeating Timer, or something else). None of
    // this changes behavior; it only makes the next occurrence diagnosable
    // via `log show --predicate 'subsystem == "com.deviationlabs.ClaudeUsageBar"' --last 3d`.
    private let logger = Logger(subsystem: "com.deviationlabs.ClaudeUsageBar", category: "refresh")
    private var refreshTickCount = 0
    private var lastRefreshFireDate: Date?

    private enum State {
        case loading
        case ok(UsageSnapshot)
        case stale(UsageSnapshot, reason: String)
        case tokenUnavailable(TokenReadError)
        case unavailable(String)
    }

    func start() {
        render(.loading)
        Task { await refresh() }
        scheduleTimer()
        observeSleepWake()
    }

    private func scheduleTimer() {
        refreshTimer?.invalidate()
        let interval = RefreshInterval.current
        logger.info("scheduleTimer: interval=\(interval, privacy: .public)s")
        refreshTimer = Timer.scheduledTimer(
            withTimeInterval: interval, repeats: true
        ) { [weak self] _ in
            Task { await self?.refresh() }
        }
    }

    /// Log-only — correlates a stuck display with a sleep/wake cycle without
    /// changing polling behavior. If the timer silently stops firing across a
    /// sleep, the gap between `willSleep` and the next `refresh: tick=` entry
    /// tells us so.
    private func observeSleepWake() {
        let center = NSWorkspace.shared.notificationCenter
        // `queue: .main` guarantees these run on the main thread at runtime,
        // but the closure type itself isn't statically MainActor-isolated —
        // hence the explicit assumeIsolated to touch `self` state safely.
        center.addObserver(forName: NSWorkspace.willSleepNotification, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.logSleepWake(event: "willSleep") }
        }
        center.addObserver(forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.logSleepWake(event: "didWake") }
        }
    }

    private func logSleepWake(event: String) {
        let last = lastRefreshFireDate?.description ?? "never"
        logger.info("\(event, privacy: .public): lastRefreshFireDate=\(last, privacy: .public)")
    }

    /// A failed refresh must never blank a display that was working. The old
    /// ordering checked `noToken` *before* `lastGoodSnapshot`, so a single
    /// blocked Keychain read wiped good numbers and replaced them with a
    /// sign-in prompt — while the token was still valid. Every failure now
    /// prefers the last good snapshot; only a cold start falls through to an
    /// error-only view.
    private func refresh() async {
        refreshTickCount += 1
        let tick = refreshTickCount
        let now = Date()
        let gap = lastRefreshFireDate.map { now.timeIntervalSince($0) }
        lastRefreshFireDate = now
        logger.info("refresh: tick=\(tick, privacy: .public) gapSinceLastTick=\(gap.map { String(format: "%.0f", $0) } ?? "n/a", privacy: .public)s")

        do {
            let snapshot = try await UsageClient.fetchSnapshot()
            lastGoodSnapshot = snapshot
            logger.info("refresh: tick=\(tick, privacy: .public) OK")
            render(.ok(snapshot))
        } catch {
            let reason = describeError(error)
            logger.error("refresh: tick=\(tick, privacy: .public) FAILED reason=\(reason, privacy: .public) hadLastGood=\(self.lastGoodSnapshot != nil, privacy: .public)")
            if let stale = lastGoodSnapshot {
                render(.stale(stale, reason: reason))
            } else if case UsageClientError.tokenUnavailable(let reason) = error {
                render(.tokenUnavailable(reason))
            } else {
                render(.unavailable(reason))
            }
        }
    }

    private func describeError(_ error: Error) -> String {
        switch error {
        case UsageClientError.unauthorized: return "session expired"
        case UsageClientError.badResponse(let code): return "HTTP \(code)"
        case UsageClientError.tokenUnavailable(let reason): return reason.menuDetail
        case UsageClientError.decodeFailed: return "unexpected response"
        default: return "network error"
        }
    }

    private func render(_ state: State) {
        switch state {
        case .loading:
            statusItem.button?.title = "Claude: …"
        case .ok(let snapshot):
            statusItem.button?.title = titleText(for: snapshot)
        case .stale(let snapshot, _):
            statusItem.button?.title = titleText(for: snapshot) + " \u{26A0}\u{FE0E}"
        case .tokenUnavailable, .unavailable:
            statusItem.button?.title = "Claude: \u{2014}"
        }
        buildMenu(state: state)
    }

    // Title reports what is *left* (budget and clock); the dropdown reports what
    // was consumed. An absent five_hour window means nothing has been spent yet,
    // so it reads as a full budget on a full clock — but only when the response
    // is otherwise healthy, hence the guard.
    private func titleText(for snapshot: UsageSnapshot) -> String {
        guard snapshot.fiveHour != nil || snapshot.sevenDay != nil else {
            return "Claude: \u{2014}"
        }
        var parts: [String] = []
        if let fiveHour = snapshot.fiveHour {
            parts.append("\(remainingPercent(fiveHour))% \(ResetFormatter.compactTimeLeft(fiveHour.resetsAt))")
        } else {
            parts.append("100% \(Self.fullFiveHourWindow)")
        }
        if let sevenDay = snapshot.sevenDay {
            parts.append("\(remainingPercent(sevenDay))% \(ResetFormatter.compactTimeLeft(sevenDay.resetsAt))")
        }
        return parts.joined(separator: " \u{00B7} ")
    }

    private func buildMenu(state: State) {
        let menu = NSMenu()

        switch state {
        case .loading:
            menu.addItem(NSMenuItem(title: "Loading…", action: nil, keyEquivalent: ""))
        case .tokenUnavailable(let reason):
            menu.addItem(NSMenuItem(title: "\u{26A0}\u{FE0E} \(reason.menuDetail)", action: nil, keyEquivalent: ""))
            // "Run claude to sign in" is only true advice when the credentials
            // are absent or expired. Offering it for a *blocked* read sends the
            // user chasing a sign-in they have already completed.
            if reason.isFixedByRunningClaude {
                menu.addItem(NSMenuItem(title: "Run \u{2018}claude\u{2019} once to sign in", action: nil, keyEquivalent: ""))
            } else {
                menu.addItem(NSMenuItem(title: retryNote(), action: nil, keyEquivalent: ""))
            }
        case .unavailable(let reason):
            menu.addItem(NSMenuItem(title: "\u{26A0}\u{FE0E} Unavailable (\(reason))", action: nil, keyEquivalent: ""))
            menu.addItem(NSMenuItem(title: retryNote(), action: nil, keyEquivalent: ""))
        case .ok(let snapshot):
            appendWindowItems(to: menu, snapshot: snapshot)
        case .stale(let snapshot, let reason):
            menu.addItem(NSMenuItem(title: "\u{26A0}\u{FE0E} Stale data (\(reason))", action: nil, keyEquivalent: ""))
            menu.addItem(NSMenuItem(title: "As of \(formatted(snapshot.fetchedAt))", action: nil, keyEquivalent: ""))
            menu.addItem(.separator())
            appendWindowItems(to: menu, snapshot: snapshot)
        }

        menu.addItem(.separator())
        let refreshItem = NSMenuItem(title: "Refresh Now", action: #selector(refreshNow), keyEquivalent: "r")
        refreshItem.target = self
        menu.addItem(refreshItem)
        menu.addItem(intervalMenuItem())
        let quitItem = NSMenuItem(title: "Quit", action: #selector(quit), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)

        statusItem.menu = menu
    }

    private func appendWindowItems(to menu: NSMenu, snapshot: UsageSnapshot) {
        let rows: [(String, UsageWindow?)] = [
            ("5-hour session", snapshot.fiveHour),
            ("7-day (all models)", snapshot.sevenDay),
            ("7-day (Opus)", snapshot.sevenDayOpus),
            ("7-day (Sonnet)", snapshot.sevenDaySonnet),
        ]
        for (label, window) in rows {
            guard let window else { continue }
            let pct = Int(window.utilization.rounded())
            let title = "\(label): \(pct)% \u{2014} resets \(ResetFormatter.description(for: window.resetsAt))"
            menu.addItem(NSMenuItem(title: title, action: nil, keyEquivalent: ""))
        }

        if let spend = snapshot.spend {
            menu.addItem(.separator())
            let pct = Int(spend.percent.rounded())
            let spendTitle = "Spend: \(currencyString(spend.usedDollars, currency: spend.currency)) / \(currencyString(spend.limitDollars, currency: spend.currency)) (\(pct)%)"
            menu.addItem(NSMenuItem(title: spendTitle, action: nil, keyEquivalent: ""))

            let updateItem = NSMenuItem(title: "Update Spend Limit\u{2026}", action: #selector(openSpendSettings), keyEquivalent: "")
            updateItem.target = self
            menu.addItem(updateItem)
        }
    }

    private func currencyString(_ amount: Double, currency: String) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = currency
        return formatter.string(from: NSNumber(value: amount)) ?? String(format: "%.2f %@", amount, currency)
    }

    private func retryNote() -> String {
        "Retrying every \(RefreshInterval.label(for: RefreshInterval.current))"
    }

    private func remainingPercent(_ window: UsageWindow) -> Int {
        Int((100 - window.utilization).rounded())
    }

    private func formatted(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.timeStyle = .short
        return formatter.string(from: date)
    }

    @objc private func refreshNow() {
        Task { await refresh() }
    }

    @objc private func quit() {
        NSApplication.shared.terminate(nil)
    }

    @objc private func openSpendSettings() {
        NSWorkspace.shared.open(spendSettingsURL)
    }

    private func intervalMenuItem() -> NSMenuItem {
        let current = RefreshInterval.current
        let parent = NSMenuItem(
            title: "Refresh Every: \(RefreshInterval.label(for: current))", action: nil, keyEquivalent: ""
        )
        let submenu = NSMenu()
        for seconds in RefreshInterval.choices {
            let item = NSMenuItem(
                title: RefreshInterval.label(for: seconds),
                action: #selector(setRefreshInterval(_:)),
                keyEquivalent: ""
            )
            item.target = self
            item.representedObject = seconds
            item.state = (seconds == current) ? .on : .off
            submenu.addItem(item)
        }
        parent.submenu = submenu
        return parent
    }

    @objc private func setRefreshInterval(_ sender: NSMenuItem) {
        guard let seconds = sender.representedObject as? TimeInterval else { return }
        RefreshInterval.current = seconds
        scheduleTimer()
        // Rebuild so the parent title and checkmark reflect the new choice
        // without waiting for the next poll to redraw the menu.
        render(lastGoodSnapshot.map { State.ok($0) } ?? .loading)
    }
}
