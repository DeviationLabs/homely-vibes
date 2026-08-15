import AppKit

@MainActor
final class StatusItemController {
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private var refreshTimer: Timer?
    private var lastGoodSnapshot: UsageSnapshot?
    private let spendSettingsURL = URL(string: "https://claude.ai/new#settings/usage")!
    private static let fullFiveHourWindow = "5h"

    private enum State {
        case loading
        case ok(UsageSnapshot)
        case stale(UsageSnapshot, reason: String)
        case noToken
    }

    func start() {
        render(.loading)
        Task { await refresh() }
        scheduleTimer()
    }

    private func scheduleTimer() {
        refreshTimer?.invalidate()
        refreshTimer = Timer.scheduledTimer(
            withTimeInterval: RefreshInterval.current, repeats: true
        ) { [weak self] _ in
            Task { await self?.refresh() }
        }
    }

    private func refresh() async {
        do {
            let snapshot = try await UsageClient.fetchSnapshot()
            lastGoodSnapshot = snapshot
            render(.ok(snapshot))
        } catch UsageClientError.noToken {
            render(.noToken)
        } catch {
            if let stale = lastGoodSnapshot {
                render(.stale(stale, reason: describeError(error)))
            } else {
                render(.noToken)
            }
        }
    }

    private func describeError(_ error: Error) -> String {
        switch error {
        case UsageClientError.unauthorized: return "session expired"
        case UsageClientError.badResponse(let code): return "HTTP \(code)"
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
        case .noToken:
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
            parts.append("\(remainingPercent(fiveHour))% \(timeLeft(fiveHour.resetsAt))")
        } else {
            parts.append("100% \(Self.fullFiveHourWindow)")
        }
        if let sevenDay = snapshot.sevenDay {
            parts.append("\(remainingPercent(sevenDay))% \(timeLeft(sevenDay.resetsAt))")
        }
        return parts.joined(separator: " \u{00B7} ")
    }

    private func buildMenu(state: State) {
        let menu = NSMenu()

        switch state {
        case .loading:
            menu.addItem(NSMenuItem(title: "Loading…", action: nil, keyEquivalent: ""))
        case .noToken:
            menu.addItem(NSMenuItem(title: "No Claude Code session found", action: nil, keyEquivalent: ""))
            menu.addItem(NSMenuItem(title: "Run \u{2018}claude\u{2019} once to sign in", action: nil, keyEquivalent: ""))
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
            let title = "\(label): \(pct)% \u{2014} resets \(relative(window.resetsAt))"
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

    private func relative(_ date: Date) -> String {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        return formatter.localizedString(for: date, relativeTo: Date())
    }

    // Largest non-zero unit only. Integer division floors, so this understates
    // time left rather than overstating it, and max(0:) keeps a snapshot whose
    // reset has already passed from rendering a negative. `now` is injected so
    // this stays testable without mocking the clock.
    private func timeLeft(_ date: Date, now: Date = Date()) -> String {
        let seconds = Int(max(0, date.timeIntervalSince(now)))
        if seconds >= 86400 { return "\(seconds / 86400)d" }
        if seconds >= 3600 { return "\(seconds / 3600)h" }
        return "\(seconds / 60)m"
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
