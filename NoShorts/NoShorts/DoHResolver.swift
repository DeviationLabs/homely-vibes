//
//  DoHResolver.swift
//  NoShorts
//
//  Minimal DNS-over-HTTPS resolver used by LocalProxy to look up hostnames
//  that NextDNS refuses to resolve on this device (only `*.youtube.com`).
//
//  Scope on purpose:
//  - Single upstream: `dns.google`. No Cloudflare fallback, no multi-endpoint
//    merge — see V2_PRD.md §7 (fail-fast) for why extra failover was cut.
//  - IPv4 (A) records only. AAAA caused ENETDOWN on carrier paths with broken
//    v6 during the 2026-07 debugging session.
//  - Returns the first A record from the cache/response, not the full set.
//    LocalProxy scope is limited to `*.youtube.com`, which resolves to Google-
//    owned IPs and doesn't need per-request failover.
//

import Foundation

actor DoHResolver {
    static let shared = DoHResolver()

    private let endpoint = URL(string: "https://dns.google/dns-query")!
    private let session: URLSession
    private var cache: [String: (ip: String, expiresAt: Date)] = [:]

    init() {
        let cfg = URLSessionConfiguration.ephemeral
        cfg.timeoutIntervalForRequest = 5
        cfg.timeoutIntervalForResource = 8
        cfg.requestCachePolicy = .reloadIgnoringLocalCacheData
        self.session = URLSession(configuration: cfg)
    }

    func resolve(_ host: String) async throws -> String {
        if let entry = cache[host], entry.expiresAt > Date() {
            return entry.ip
        }

        var req = URLRequest(url: endpoint)
        req.httpMethod = "POST"
        req.setValue("application/dns-message", forHTTPHeaderField: "Content-Type")
        req.setValue("application/dns-message", forHTTPHeaderField: "Accept")
        req.httpBody = try buildQuery(for: host)

        let (data, response) = try await session.data(for: req)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw DoHError.badResponse
        }

        let (ip, ttl) = try firstAnswer(data)
        cache[host] = (ip, Date().addingTimeInterval(min(TimeInterval(ttl), 300)))
        return ip
    }

    private func buildQuery(for host: String) throws -> Data {
        var pkt = Data()
        // Header: id=0 (DoH ignores), flags=0x0100 (standard query, RD), 1 question
        pkt.append(contentsOf: [0x00, 0x00, 0x01, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        for label in host.split(separator: ".") {
            let bytes = Array(label.utf8)
            guard bytes.count <= 63 else { throw DoHError.invalidHost }
            pkt.append(UInt8(bytes.count))
            pkt.append(contentsOf: bytes)
        }
        pkt.append(0x00)                          // root
        pkt.append(contentsOf: [0x00, 0x01])      // QTYPE A
        pkt.append(contentsOf: [0x00, 0x01])      // QCLASS IN
        return pkt
    }

    /// Walk the DNS response, return (first A record IP string, its TTL).
    private func firstAnswer(_ data: Data) throws -> (String, UInt32) {
        guard data.count >= 12 else { throw DoHError.shortPacket }
        let qd = (UInt16(data[4]) << 8) | UInt16(data[5])
        let an = (UInt16(data[6]) << 8) | UInt16(data[7])
        guard an > 0 else { throw DoHError.noAnswer }

        var idx = 12
        for _ in 0..<qd {
            idx = try skipName(data, at: idx)
            idx += 4  // QTYPE + QCLASS
        }
        for _ in 0..<an {
            idx = try skipName(data, at: idx)
            guard idx + 10 <= data.count else { throw DoHError.shortPacket }
            let type = (UInt16(data[idx]) << 8) | UInt16(data[idx + 1])
            let ttl = (UInt32(data[idx + 4]) << 24) | (UInt32(data[idx + 5]) << 16)
                    | (UInt32(data[idx + 6]) << 8)  | UInt32(data[idx + 7])
            let rdLen = Int((UInt16(data[idx + 8]) << 8) | UInt16(data[idx + 9]))
            idx += 10
            guard idx + rdLen <= data.count else { throw DoHError.shortPacket }
            if type == 1 && rdLen == 4 {
                let ip = "\(data[idx]).\(data[idx + 1]).\(data[idx + 2]).\(data[idx + 3])"
                return (ip, ttl)
            }
            idx += rdLen
        }
        throw DoHError.noAnswer
    }

    private func skipName(_ data: Data, at start: Int) throws -> Int {
        var i = start
        while i < data.count {
            let b = data[i]
            if b == 0 { return i + 1 }
            if b & 0xC0 == 0xC0 { return i + 2 }   // pointer, 2 bytes
            i += 1 + Int(b)
        }
        throw DoHError.shortPacket
    }

    enum DoHError: Error { case badResponse, noAnswer, shortPacket, invalidHost }
}
