import Foundation

struct UsageWindow {
    let utilization: Double // percent, 0-100
    let resetsAt: Date
}

struct SpendInfo {
    let usedDollars: Double
    let limitDollars: Double
    let percent: Double
    let currency: String
}

struct UsageSnapshot {
    let fiveHour: UsageWindow?
    let sevenDay: UsageWindow?
    let sevenDayOpus: UsageWindow?
    let sevenDaySonnet: UsageWindow?
    let spend: SpendInfo?
    let fetchedAt: Date
}

enum UsageClientError: Error {
    case noToken
    case unauthorized
    case badResponse(Int)
    case decodeFailed
}

enum UsageClient {
    // Reverse-engineered from the `claude` CLI binary (fetchUtilization /
    // loadPlanRateLimits) — same call the `/usage` slash command makes.
    private static let endpoint = URL(string: "https://api.anthropic.com/api/oauth/usage")!

    static func fetchSnapshot() async throws -> UsageSnapshot {
        guard let token = KeychainTokenReader.readValidToken() else {
            throw UsageClientError.noToken
        }
        var request = URLRequest(url: endpoint)
        request.httpMethod = "GET"
        request.setValue("Bearer \(token.accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("oauth-2025-04-20", forHTTPHeaderField: "anthropic-beta")

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw UsageClientError.decodeFailed }
        if ProcessInfo.processInfo.environment["CLAUDE_USAGE_DEBUG"] != nil {
            FileHandle.standardError.write("UsageClient: status=\(http.statusCode) bytes=\(data.count) body=\(String(data: data, encoding: .utf8) ?? "<non-utf8>")\n".data(using: .utf8)!)
        }
        if http.statusCode == 401 { throw UsageClientError.unauthorized }
        guard http.statusCode == 200 else { throw UsageClientError.badResponse(http.statusCode) }

        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw UsageClientError.decodeFailed
        }

        // Confirmed via CLAUDE_USAGE_DEBUG=1 against the live endpoint:
        // `utilization` is already a 0-100 percent (not a 0-1 fraction, as
        // the decompiled CLI's `*100` scaling of *header*-sourced data had
        // suggested), and `resets_at` is an ISO-8601 string, not epoch
        // seconds.
        let isoFormatter = ISO8601DateFormatter()
        isoFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let isoFormatterNoFraction = ISO8601DateFormatter()

        func window(_ key: String) -> UsageWindow? {
            guard let w = json[key] as? [String: Any],
                  let utilization = w["utilization"] as? Double,
                  let resetsAtString = w["resets_at"] as? String,
                  let resetsAt = isoFormatter.date(from: resetsAtString) ?? isoFormatterNoFraction.date(from: resetsAtString)
            else { return nil }
            return UsageWindow(utilization: utilization, resetsAt: resetsAt)
        }

        // `spend.used`/`spend.limit` are minor-unit integers (cents) + an
        // exponent, standard for money APIs — divide by 10^exponent to get
        // dollars. `spend.percent` is already 0-100.
        func spendInfo() -> SpendInfo? {
            guard let spend = json["spend"] as? [String: Any],
                  let used = spend["used"] as? [String: Any],
                  let limit = spend["limit"] as? [String: Any],
                  let usedMinor = used["amount_minor"] as? Int,
                  let limitMinor = limit["amount_minor"] as? Int,
                  let exponent = used["exponent"] as? Int,
                  let currency = used["currency"] as? String,
                  let percent = spend["percent"] as? Double
            else { return nil }
            let scale = pow(10.0, Double(exponent))
            return SpendInfo(
                usedDollars: Double(usedMinor) / scale,
                limitDollars: Double(limitMinor) / scale,
                percent: percent,
                currency: currency
            )
        }

        return UsageSnapshot(
            fiveHour: window("five_hour"),
            sevenDay: window("seven_day"),
            sevenDayOpus: window("seven_day_opus"),
            sevenDaySonnet: window("seven_day_sonnet"),
            spend: spendInfo(),
            fetchedAt: Date()
        )
    }
}
