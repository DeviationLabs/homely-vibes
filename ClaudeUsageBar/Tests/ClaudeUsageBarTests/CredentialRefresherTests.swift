import XCTest

@testable import ClaudeUsageBar

/// Exercises the real subprocess boundary with fake `sh` scripts rather than
/// mocking it — same approach as the Python modules' fake sidecars. The clock
/// is injected so throttling assertions are exact rather than wall-clock
/// dependent.
final class CredentialRefresherTests: XCTestCase {

    private var scratchDirectories: [URL] = []

    override func tearDownWithError() throws {
        for directory in scratchDirectories {
            try? FileManager.default.removeItem(at: directory)
        }
        scratchDirectories = []
    }

    /// Writes an executable `sh` script and returns its path.
    private func makeScript(_ body: String) throws -> String {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("ClaudeUsageBarTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        scratchDirectories.append(directory)

        let path = directory.appendingPathComponent("fake-claude").path
        try "#!/bin/sh\n\(body)\n".write(toFile: path, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: path)
        return path
    }

    /// Mutable clock so elapsed time is a test input, not a race.
    private final class Clock {
        var current = Date(timeIntervalSince1970: 1_000_000)
    }

    // MARK: - Running the CLI

    func testReportsSuccessfulExitCode() throws {
        let refresher = CredentialRefresher(executablePath: try makeScript("exit 0"))
        XCTAssertEqual(refresher.nudge(), .ran(exitCode: 0))
    }

    /// A non-zero exit still counts as "ran" — the caller re-reads the Keychain
    /// either way, because the CLI may have refreshed the token before failing
    /// on something unrelated.
    func testReportsNonZeroExitCode() throws {
        let refresher = CredentialRefresher(executablePath: try makeScript("exit 7"))
        let outcome = refresher.nudge()
        XCTAssertEqual(outcome, .ran(exitCode: 7))
        XCTAssertTrue(outcome.didRun)
    }

    /// Proves the binary is actually invoked, and with `auth status` — not
    /// something that could log the user out.
    func testInvokesBinaryWithAuthStatusArguments() throws {
        let script = try makeScript(#"echo "$@" > "$0.args""#)
        _ = CredentialRefresher(executablePath: script).nudge()

        let recorded = try String(contentsOfFile: script + ".args", encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        XCTAssertEqual(recorded, "auth status")
    }

    // MARK: - Failure modes

    func testMissingCLIIsReportedAsUnavailable() {
        let refresher = CredentialRefresher(executablePath: nil)
        XCTAssertEqual(refresher.nudge(), .unavailable("claude CLI not found"))
        XCTAssertFalse(refresher.nudge().didRun)
    }

    /// A wedged CLI must degrade to one skipped tick, never block the poll loop.
    func testHungCLITimesOut() throws {
        let refresher = CredentialRefresher(
            executablePath: try makeScript("sleep 30"), timeout: 0.5
        )
        let outcome = refresher.nudge()
        XCTAssertEqual(outcome, .timedOut)
        XCTAssertFalse(outcome.didRun)
    }

    // MARK: - Throttling

    /// An expired token stays expired until the CLI refreshes it, so without a
    /// throttle every 180s poll would fork the CLI for the whole window.
    func testSecondNudgeWithinIntervalIsThrottled() throws {
        let clock = Clock()
        let refresher = CredentialRefresher(
            executablePath: try makeScript("exit 0"),
            minimumInterval: 600,
            now: { clock.current }
        )

        XCTAssertEqual(refresher.nudge(), .ran(exitCode: 0))
        XCTAssertEqual(refresher.nudge(), .throttled(secondsRemaining: 600))

        clock.current.addTimeInterval(599)
        XCTAssertEqual(refresher.nudge(), .throttled(secondsRemaining: 1))
    }

    func testNudgeIsAllowedOnceIntervalElapses() throws {
        let clock = Clock()
        let refresher = CredentialRefresher(
            executablePath: try makeScript("exit 0"),
            minimumInterval: 600,
            now: { clock.current }
        )

        XCTAssertEqual(refresher.nudge(), .ran(exitCode: 0))
        clock.current.addTimeInterval(600)
        XCTAssertEqual(refresher.nudge(), .ran(exitCode: 0))
    }

    /// A CLI that cannot be found must not consume the throttle window — once
    /// it is installed the next tick should nudge immediately.
    func testUnavailableCLIDoesNotConsumeThrottleWindow() throws {
        let clock = Clock()
        let refresher = CredentialRefresher(
            executablePath: nil, minimumInterval: 600, now: { clock.current }
        )
        XCTAssertEqual(refresher.nudge(), .unavailable("claude CLI not found"))
        XCTAssertEqual(refresher.nudge(), .unavailable("claude CLI not found"))
    }

    // MARK: - Path resolution

    /// A GUI app inherits a minimal PATH with no Homebrew on it, so the CLI is
    /// resolved by absolute path against an ordered candidate list.
    func testResolvesFirstExecutableCandidate() {
        let resolved = CredentialRefresher.resolveCLIPath(
            candidates: ["/nope/claude", "/opt/homebrew/bin/claude", "/usr/local/bin/claude"],
            isExecutable: { $0 != "/nope/claude" }
        )
        XCTAssertEqual(resolved, "/opt/homebrew/bin/claude")
    }

    func testResolvesToNilWhenNoCandidateExists() {
        let resolved = CredentialRefresher.resolveCLIPath(
            candidates: ["/nope/claude"], isExecutable: { _ in false }
        )
        XCTAssertNil(resolved)
    }
}
