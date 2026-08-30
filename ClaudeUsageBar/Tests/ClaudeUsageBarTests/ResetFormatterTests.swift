import XCTest

@testable import ClaudeUsageBar

/// `now` is injected throughout, so none of these touch the wall clock.
/// Absolute-time assertions are avoided where they would depend on the host's
/// locale; the countdown half is locale-independent and asserted exactly.
final class ResetFormatterTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_786_940_000)

    private func later(_ seconds: TimeInterval) -> Date {
        now.addingTimeInterval(seconds)
    }

    // MARK: - countdown (dropdown register)

    func testCountdownUsesTwoUnitsBelowADay() {
        XCTAssertEqual(ResetFormatter.countdown(to: later(3600 + 43 * 60), now: now), "1h 43m")
        XCTAssertEqual(ResetFormatter.countdown(to: later(3600), now: now), "1h 0m")
    }

    func testCountdownUsesDaysAndHoursAboveADay() {
        XCTAssertEqual(ResetFormatter.countdown(to: later(86400), now: now), "1d 0h")
        XCTAssertEqual(ResetFormatter.countdown(to: later(86400 + 3 * 3600 + 1800), now: now), "1d 3h")
    }

    func testCountdownFallsBackToMinutesOnly() {
        XCTAssertEqual(ResetFormatter.countdown(to: later(43 * 60), now: now), "43m")
        XCTAssertEqual(ResetFormatter.countdown(to: later(60), now: now), "1m")
    }

    /// Floors rather than rounds, so it never claims more time than remains.
    func testCountdownFloorsSubMinuteRemainder() {
        XCTAssertEqual(ResetFormatter.countdown(to: later(59), now: now), "0m")
    }

    func testCountdownClampsElapsedResetToZero() {
        XCTAssertEqual(ResetFormatter.countdown(to: later(-9999), now: now), "0m")
    }

    // MARK: - compactTimeLeft (menu bar register)

    func testCompactTimeLeftKeepsLargestUnitOnly() {
        XCTAssertEqual(ResetFormatter.compactTimeLeft(later(3600 + 43 * 60), now: now), "1h")
        XCTAssertEqual(ResetFormatter.compactTimeLeft(later(86400 + 3 * 3600), now: now), "1d")
        XCTAssertEqual(ResetFormatter.compactTimeLeft(later(43 * 60), now: now), "43m")
    }

    func testCompactTimeLeftClampsElapsedResetToZero() {
        XCTAssertEqual(ResetFormatter.compactTimeLeft(later(-9999), now: now), "0m")
    }

    // MARK: - description

    func testDescriptionEmbedsCountdown() {
        let target = later(3600 + 43 * 60)
        XCTAssertTrue(
            ResetFormatter.description(for: target, now: now).hasSuffix("(in 1h 43m)"),
            "dropdown row should carry the two-unit countdown"
        )
    }

    /// Same-day resets stay short; cross-day ones need the weekday or "10:00 PM"
    /// is ambiguous between tonight and a week out.
    func testDescriptionAddsWeekdayOnlyWhenResetIsAnotherDay() {
        let sameDay = ResetFormatter.description(for: later(60), now: now)
        let nextDay = ResetFormatter.description(for: later(86400), now: now)
        XCTAssertLessThan(
            sameDay.count, nextDay.count,
            "cross-day row should be longer by its weekday prefix"
        )
    }
}
