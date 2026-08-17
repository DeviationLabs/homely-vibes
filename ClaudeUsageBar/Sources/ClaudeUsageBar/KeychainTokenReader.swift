import Foundation
import Security

struct OAuthToken {
    let accessToken: String
    let expiresAt: Date?
}

/// Why a token read failed. These were previously all collapsed into `nil`,
/// which made a *blocked* read indistinguishable from a genuinely signed-out
/// machine — and the UI told the user to sign in while holding a valid token.
enum TokenReadError: Error, Equatable {
    case notFound
    case accessDenied(String)
    case expired
    case malformed

    /// Short phrase for the dropdown. Only `.notFound` and `.expired` are
    /// fixed by running `claude`; saying so for the others is misleading.
    var menuDetail: String {
        switch self {
        case .notFound: return "no Claude Code credentials on this Mac"
        case .accessDenied(let detail): return detail
        case .expired: return "credentials expired"
        case .malformed: return "credentials unreadable"
        }
    }

    var isFixedByRunningClaude: Bool {
        switch self {
        case .notFound, .expired: return true
        case .accessDenied, .malformed: return false
        }
    }
}

enum TokenSource: String {
    case memoryCache = "memory cache"
    case ownItem = "own Keychain item"
    case bootstrap = "bootstrap from Claude Code"
}

/// Reads the OAuth access token, following the pattern every well-behaved app
/// on macOS uses (`Chrome Safe Storage`, `Slack Safe Storage`, …): **own the
/// Keychain item you read**.
///
/// A Keychain read is gated by two independent lists — the ACL's application
/// list *and* the item's partition list. Reading Claude Code's own
/// `Claude Code-credentials` item satisfies neither durably:
///
///   * grants are recorded against a `cdhash:`, which changes on every rebuild;
///   * the `claude` CLI rewrites the item on every token rotation (its `mdat`
///     moves while `cdat` stays put), and each rewrite resets both lists.
///
/// So the consent prompt could never stop recurring. Instead we keep our own
/// item, created by us: macOS puts our stable `teamid:` in its partition list
/// at creation and nothing else ever rewrites it, so reads never prompt. Claude
/// Code's item is consulted only to (re)bootstrap ours, and only through
/// `/usr/bin/security`, which carries `apple-tool:` — present in the partition
/// list of every one of these items and preserved across every rotation.
enum KeychainTokenReader {
    private static let ownService = "com.deviationlabs.ClaudeUsageBar"
    private static let cliService = "Claude Code-credentials"
    private static let securityTool = "/usr/bin/security"

    private static let cacheLock = NSLock()
    nonisolated(unsafe) private static var cachedToken: OAuthToken?
    nonisolated(unsafe) private static var lastSourceStorage: TokenSource?

    /// Where the most recent successful read came from. Diagnostics only.
    static var lastSource: TokenSource? {
        cacheLock.lock()
        defer { cacheLock.unlock() }
        return lastSourceStorage
    }

    /// A non-expired access token: memory cache, then our own Keychain item,
    /// then a bootstrap from Claude Code's item.
    static func readValidToken() -> Result<OAuthToken, TokenReadError> {
        cacheLock.lock()
        defer { cacheLock.unlock() }

        if let cached = cachedToken, isUnexpired(cached) {
            lastSourceStorage = .memoryCache
            return .success(cached)
        }

        if let data = ownItemData(), let token = parseToken(from: data), isUnexpired(token) {
            cachedToken = token
            lastSourceStorage = .ownItem
            return .success(token)
        }

        switch readFromCLIItem() {
        case .success(let (data, token)):
            storeOwnItem(data)
            cachedToken = token
            lastSourceStorage = .bootstrap
            return .success(token)
        case .failure(let error):
            cachedToken = nil
            return .failure(error)
        }
    }

    /// Drops every cached copy so the next read re-bootstraps. Called when the
    /// API rejects the token: the CLI rotates on its own schedule, so our copy
    /// can go stale before its stated expiry. The *own item* must be dropped
    /// too — clearing only the memory cache would just re-read the same
    /// rejected token from disk on the next tick.
    static func invalidateCache() {
        cacheLock.lock()
        defer { cacheLock.unlock() }
        cachedToken = nil
        lastSourceStorage = nil
        deleteOwnItem()
    }

    private static func isUnexpired(_ token: OAuthToken) -> Bool {
        guard let expiresAt = token.expiresAt else { return true }
        return expiresAt > Date()
    }

    // MARK: - Our own Keychain item

    private static func ownItemQuery() -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: ownService,
            kSecAttrAccount as String: NSUserName(),
        ]
    }

    private static func ownItemData() -> Data? {
        var query = ownItemQuery()
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data
        else { return nil }
        return data
    }

    /// Note the deliberate absence of `kSecUseDataProtectionKeychain`: the
    /// legacy file keychain is what gives a creating app the ACL entry and
    /// `teamid:` partition entry that make later reads prompt-free.
    private static func storeOwnItem(_ data: Data) {
        let attributes = [kSecValueData as String: data] as CFDictionary
        let status = SecItemUpdate(ownItemQuery() as CFDictionary, attributes)
        guard status == errSecItemNotFound else { return }
        var insert = ownItemQuery()
        insert[kSecValueData as String] = data
        _ = SecItemAdd(insert as CFDictionary, nil)
    }

    private static func deleteOwnItem() {
        _ = SecItemDelete(ownItemQuery() as CFDictionary)
    }

    // MARK: - Bootstrap from Claude Code's item

    private static func readFromCLIItem() -> Result<(Data, OAuthToken), TokenReadError> {
        switch runSecurityTool() {
        case .failure(let error):
            return .failure(error)
        case .success(let data):
            guard let token = parseToken(from: data) else { return .failure(.malformed) }
            guard isUnexpired(token) else { return .failure(.expired) }
            return .success((data, token))
        }
    }

    /// The secret travels back over a pipe — never through `argv`, never to
    /// disk. Both pipes are drained before `waitUntilExit()` so a full buffer
    /// cannot deadlock the child.
    private static func runSecurityTool() -> Result<Data, TokenReadError> {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: securityTool)
        process.arguments = ["find-generic-password", "-s", cliService, "-w"]
        let output = Pipe()
        let errors = Pipe()
        process.standardOutput = output
        process.standardError = errors

        do {
            try process.run()
        } catch {
            return .failure(.accessDenied("cannot run \(securityTool)"))
        }

        let outputData = output.fileHandleForReading.readDataToEndOfFile()
        let errorText = String(
            data: errors.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8
        ) ?? ""
        process.waitUntilExit()

        guard process.terminationStatus == 0 else {
            return .failure(
                classifySecurityFailure(status: process.terminationStatus, stderr: errorText)
            )
        }

        // `-w` prints the secret followed by a newline.
        let text = (String(data: outputData, encoding: .utf8) ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, let data = text.data(using: .utf8) else {
            return .failure(.malformed)
        }
        return .success(data)
    }

    /// `security` surfaces the underlying `OSStatus` as its exit code, but not
    /// for every failure mode, so the message is checked too. Pure and
    /// `internal` so it can be tested without invoking the Keychain.
    static func classifySecurityFailure(status: Int32, stderr: String) -> TokenReadError {
        switch status {
        case 44: return .notFound  // errSecItemNotFound
        case 51: return .accessDenied("authorization denied")  // errSecAuthFailed
        case 25293: return .accessDenied("keychain locked")  // errSecInteractionRequired
        case 25308: return .accessDenied("interaction not allowed")  // errSecInteractionNotAllowed
        default: break
        }

        let message = stderr.lowercased()
        if message.contains("could not be found") {
            return .notFound
        }
        if message.contains("interaction")
            || message.contains("denied")
            || message.contains("cancel")
            || message.contains("authoriz")
        {
            return .accessDenied("Keychain access denied")
        }
        return .accessDenied("security exited \(status)")
    }

    // MARK: - Payload

    /// Accepts the nested `{"claudeAiOauth": {...}}` shape Claude Code stores
    /// as well as a flat `{accessToken, expiresAt}` object, which is what we
    /// write back into our own item.
    static func parseToken(from data: Data) -> OAuthToken? {
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

    /// Reports which source served the token and how the item is stored —
    /// never any secret value. `ClaudeUsageBar --probe-keychain`.
    static func probe() {
        print("own item:  \(ownService) — \(ownItemData() == nil ? "absent" : "present")")
        print("cli item:  \(cliService) — read via \(securityTool)")
        switch readValidToken() {
        case .success(let token):
            print("result:    OK via \(lastSource?.rawValue ?? "unknown")")
            print("expiresAt: \(token.expiresAt.map { ISO8601DateFormatter().string(from: $0) } ?? "none")")
            print("token:     \(token.accessToken.count) chars (value withheld)")
        case .failure(let error):
            print("result:    FAILED — \(error.menuDetail)")
            print("           run `claude` to fix? \(error.isFixedByRunningClaude ? "yes" : "no")")
        }
    }
}
