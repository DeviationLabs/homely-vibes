import Foundation

/// What a nudge attempt did. Reported back so the caller can log it — the
/// whole point of this type is that the next expiry window proves, in the
/// unified log, whether the mechanism works.
enum NudgeOutcome: Equatable {
    case throttled(secondsRemaining: Int)
    case ran(exitCode: Int32)
    case timedOut
    case unavailable(String)

    /// Only a completed run is worth re-reading the Keychain for.
    var didRun: Bool {
        if case .ran = self { return true }
        return false
    }

    var logDescription: String {
        switch self {
        case .throttled(let remaining): return "throttled(\(remaining)s left)"
        case .ran(let code): return "ran(exit=\(code))"
        case .timedOut: return "timedOut"
        case .unavailable(let reason): return "unavailable(\(reason))"
        }
    }
}

/// Asks the `claude` CLI to refresh its own expired OAuth token.
///
/// We must never run the OAuth refresh ourselves. Anthropic **rotates the
/// refresh token on use** — confirmed by decompiling the CLI: its refresh
/// response carries a new `refreshToken` *and* a `refreshTokenExpiresAt`, and
/// the write-back aborts when the stored token changed underneath it
/// (`if (y && y !== c) …`), a guard that only exists because the old token
/// dies on use. Spending that single-use token here would leave the CLI
/// holding a dead one — i.e. log the user out.
///
/// So we nudge rather than refresh. `claude auth status` is non-interactive,
/// prints no secrets, returns in ~0.2s, and the CLI's refresh path is
/// expiry-driven (`if (!force && !isExpired(expiresAt)) return "not_needed"`),
/// so on an expired token the CLI performs the refresh itself — holding its
/// own `oauth_refresh_lock`, serialised against its other sessions instead of
/// racing them. We never write the CLI's Keychain item; it does.
final class CredentialRefresher: @unchecked Sendable {
    /// A GUI app launched from Finder inherits a minimal `PATH`
    /// (`/usr/bin:/bin:/usr/sbin:/sbin`) with no Homebrew on it, so spawning
    /// `claude` by bare name fails. Resolve an absolute path instead.
    static let defaultCandidatePaths = [
        "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude",
        NSHomeDirectory() + "/.local/bin/claude",
    ]

    private let executablePath: String?
    private let arguments: [String]
    private let minimumInterval: TimeInterval
    private let timeout: TimeInterval
    private let now: () -> Date

    private let lock = NSLock()
    private var lastAttempt: Date?

    /// `executablePath` and `arguments` are injected so tests can point at a
    /// fake `sh` script and exercise real subprocess semantics rather than
    /// mocking the boundary.
    init(
        executablePath: String? = CredentialRefresher.resolveCLIPath(),
        arguments: [String] = ["auth", "status"],
        minimumInterval: TimeInterval = 600,
        timeout: TimeInterval = 20,
        now: @escaping () -> Date = Date.init
    ) {
        self.executablePath = executablePath
        self.arguments = arguments
        self.minimumInterval = minimumInterval
        self.timeout = timeout
        self.now = now
    }

    static func resolveCLIPath(
        candidates: [String] = defaultCandidatePaths,
        isExecutable: (String) -> Bool = { FileManager.default.isExecutableFile(atPath: $0) }
    ) -> String? {
        candidates.first(where: isExecutable)
    }

    /// Spawns the CLI at most once per `minimumInterval`. Throttling matters:
    /// an expired token stays expired until the CLI refreshes it, so an
    /// unthrottled nudge would fork a 256MB binary on every 180s poll for as
    /// long as the window lasts.
    func nudge() -> NudgeOutcome {
        guard let executablePath else {
            return .unavailable("claude CLI not found")
        }

        lock.lock()
        let current = now()
        if let lastAttempt {
            let elapsed = current.timeIntervalSince(lastAttempt)
            if elapsed < minimumInterval {
                lock.unlock()
                return .throttled(secondsRemaining: Int((minimumInterval - elapsed).rounded()))
            }
        }
        lastAttempt = current
        lock.unlock()

        return run(path: executablePath)
    }

    private func run(path: String) -> NudgeOutcome {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: path)
        process.arguments = arguments
        // The CLI's own output is of no use to us and must never reach our
        // logs — the refresh happens as a side effect on the Keychain item.
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice

        // Assigned before `run()`: a process that exits faster than we can set
        // the handler would otherwise never signal, and this one returns in
        // roughly 0.2s.
        let finished = DispatchSemaphore(value: 0)
        process.terminationHandler = { _ in finished.signal() }

        do {
            try process.run()
        } catch {
            return .unavailable("cannot launch \(path)")
        }

        // `waitUntilExit()` cannot time out, so a wedged CLI would block the
        // poll loop forever. Cap it and move on.
        if finished.wait(timeout: .now() + timeout) == .timedOut {
            process.terminate()
            return .timedOut
        }
        return .ran(exitCode: process.terminationStatus)
    }
}
