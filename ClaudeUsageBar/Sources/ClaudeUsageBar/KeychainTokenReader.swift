import Foundation
import Security

struct OAuthToken {
    let accessToken: String
    let expiresAt: Date?
}

enum KeychainTokenReader {
    // The bare "Claude Code-credentials" item holds the CLI's own OAuth
    // access/refresh token. The hash-suffixed siblings
    // ("Claude Code-credentials-<hash>") are per-workspace MCP OAuth caches
    // (`{"mcpOAuth": {...}}`) for third-party integrations, not the
    // Anthropic API token — confirmed via `--probe-keychain` during
    // development, which showed only `mcpOAuth` keys in every hashed item.
    private static let primaryService = "Claude Code-credentials"
    private static let servicePrefix = "Claude Code-credentials-"

    /// Service names (not secrets) of every Keychain item that looks like a
    /// Claude Code credential, primary item first. Safe to log.
    static func candidateServices() -> [String] {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecMatchLimit as String: kSecMatchLimitAll,
            kSecReturnAttributes as String: true,
        ]
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess, let items = result as? [[String: Any]] else {
            return []
        }
        let services = items.compactMap { $0[kSecAttrService as String] as? String }
            .filter { $0 == primaryService || $0.hasPrefix(servicePrefix) }
        return services.sorted { ($0 == primaryService ? 0 : 1) < ($1 == primaryService ? 0 : 1) }
    }

    private static func secretData(forService service: String) -> Data? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess, let data = result as? Data else { return nil }
        return data
    }

    /// Accepts either the flat shape `{accessToken, refreshToken, expiresAt}`
    /// or the nested shape `{claudeAiOauth: {...}}` (the latter matches the
    /// CLI's on-disk `~/.claude/.credentials.json`; the Keychain payload
    /// shape wasn't independently confirmed during planning, so both are
    /// supported until `--probe-keychain` output confirms one).
    private static func parseToken(from data: Data) -> OAuthToken? {
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }
        let payload = (json["claudeAiOauth"] as? [String: Any]) ?? json
        guard let accessToken = payload["accessToken"] as? String else { return nil }

        var expiresAt: Date?
        if let millis = payload["expiresAt"] as? Double {
            expiresAt = Date(timeIntervalSince1970: millis / 1000)
        } else if let millis = payload["expiresAt"] as? Int {
            expiresAt = Date(timeIntervalSince1970: Double(millis) / 1000)
        }
        return OAuthToken(accessToken: accessToken, expiresAt: expiresAt)
    }

    private static let cacheLock = NSLock()
    nonisolated(unsafe) private static var cachedToken: OAuthToken?

    private static func isUnexpired(_ token: OAuthToken) -> Bool {
        guard let expiresAt = token.expiresAt else { return true }
        return expiresAt > Date()
    }

    /// A non-expired access token, read from the Keychain at most once per
    /// token lifetime.
    ///
    /// Every `secretData` call requests `kSecReturnData`, and that is what
    /// triggers the macOS consent prompt — so reading on each refresh tick made
    /// the prompt recur every few minutes. The token only changes when the CLI
    /// refreshes it, so it is cached until its own `expiresAt`.
    ///
    /// The primary item is read alone when it exists: a *denied* read must not
    /// cascade into a separate prompt for every MCP sibling. The broad scan is
    /// kept only for the case where the primary item is absent entirely, which
    /// `candidateServices()` can determine without prompting.
    static func readValidToken() -> OAuthToken? {
        cacheLock.lock()
        defer { cacheLock.unlock() }

        if let cached = cachedToken, isUnexpired(cached) { return cached }

        let services = candidateServices()
        let ordered = services.contains(primaryService) ? [primaryService] : services
        for service in ordered {
            guard let data = secretData(forService: service),
                  let token = parseToken(from: data),
                  isUnexpired(token) else { continue }
            cachedToken = token
            return token
        }
        cachedToken = nil
        return nil
    }

    /// Drops the cached token so the next read goes back to the Keychain.
    /// Called when the API rejects the token, since the CLI may have rotated it
    /// before the copy we hold reached its own expiry.
    static func invalidateCache() {
        cacheLock.lock()
        defer { cacheLock.unlock() }
        cachedToken = nil
    }

    /// Prints the *keys* (never values) of each matching Keychain item so
    /// the payload shape can be confirmed by a human without ever exposing
    /// the token. Run via `swift run ClaudeUsageBar --probe-keychain`.
    static func probe() {
        let services = candidateServices()
        guard !services.isEmpty else {
            print("No Keychain items found with service prefix '\(servicePrefix)'.")
            return
        }
        for service in services {
            print("service: \(service)")
            guard let data = secretData(forService: service) else {
                print("  (denied or unreadable — check Keychain Access consent prompt)")
                continue
            }
            guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                print("  (not a JSON object; \(data.count) bytes)")
                continue
            }
            let payload = (json["claudeAiOauth"] as? [String: Any]) ?? json
            print("  top-level keys: \(json.keys.sorted())")
            print("  payload keys: \(payload.keys.sorted())")
        }
    }
}
