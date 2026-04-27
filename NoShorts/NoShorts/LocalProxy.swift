//
//  LocalProxy.swift
//  NoShorts
//
//  HTTP CONNECT proxy on 127.0.0.1. Resolves hostnames via DoHResolver (bypassing
//  system DNS / NextDNS), then tunnels TLS bytes verbatim. Pointed at by
//  WKWebsiteDataStore.proxyConfigurations so all WKWebView traffic flows through it.
//

import Foundation
import Network

final class LocalProxy: @unchecked Sendable {
    private let queue = DispatchQueue(label: "LocalProxy")
    private var listener: NWListener?
    private(set) var port: UInt16 = 0

    func start() throws -> UInt16 {
        let params = NWParameters.tcp
        let l = try NWListener(using: params, on: .any)
        l.newConnectionHandler = { [weak self] conn in self?.handle(conn) }

        let sem = DispatchSemaphore(value: 0)
        var didSignal = false
        l.stateUpdateHandler = { state in
            switch state {
            case .ready, .failed, .cancelled:
                if !didSignal { didSignal = true; sem.signal() }
                if case .failed(let e) = state { NSLog("LocalProxy listener failed: \(e)") }
            default: break
            }
        }
        l.start(queue: queue)

        guard sem.wait(timeout: .now() + 3) == .success,
              let p = l.port, p.rawValue > 0 else {
            l.cancel()
            throw NSError(domain: "LocalProxy", code: -1, userInfo: [NSLocalizedDescriptionKey: "listener not ready or port invalid"])
        }

        self.listener = l
        self.port = p.rawValue
        return p.rawValue
    }

    private func handle(_ client: NWConnection) {
        NSLog("LocalProxy: incoming connection")
        client.start(queue: queue)
        readConnect(client, accumulated: Data())
    }

    private func readConnect(_ client: NWConnection, accumulated: Data) {
        client.receive(minimumIncompleteLength: 1, maximumLength: 4096) { [weak self] data, _, isComplete, error in
            guard let self else { return }
            if let error { NSLog("CONNECT read error: \(error)"); client.cancel(); return }
            var buf = accumulated
            if let data { buf.append(data) }
            if let endRange = buf.range(of: Data([0x0D, 0x0A, 0x0D, 0x0A])) {
                let header = buf.prefix(upTo: endRange.lowerBound)
                self.processConnect(client, header: header)
                return
            }
            if isComplete || buf.count > 16384 { client.cancel(); return }
            self.readConnect(client, accumulated: buf)
        }
    }

    private func processConnect(_ client: NWConnection, header: Data) {
        guard let line = String(data: header, encoding: .utf8)?.split(separator: "\r\n").first else {
            sendError(client, "400 Bad Request"); return
        }
        let parts = line.split(separator: " ")
        guard parts.count >= 2, parts[0] == "CONNECT" else {
            sendError(client, "405 Method Not Allowed"); return
        }
        let target = String(parts[1])
        guard let colon = target.lastIndex(of: ":"),
              let port = UInt16(target[target.index(after: colon)...]) else {
            sendError(client, "400 Bad Request"); return
        }
        let host = String(target[..<colon])

        Task { [weak self] in
            guard let self else { return }
            do {
                let ip = try await DoHResolver.shared.resolve(host)
                NSLog("LocalProxy: CONNECT \(host):\(port) -> \(ip)")
                self.openTunnel(client: client, host: host, ip: ip, port: port)
            } catch {
                NSLog("LocalProxy: DoH resolve failed for \(host): \(error)")
                self.sendError(client, "502 Bad Gateway")
            }
        }
    }

    private func openTunnel(client: NWConnection, host: String, ip: String, port: UInt16) {
        let endpoint = NWEndpoint.hostPort(host: NWEndpoint.Host(ip), port: NWEndpoint.Port(rawValue: port)!)
        let upstream = NWConnection(to: endpoint, using: .tcp)
        upstream.stateUpdateHandler = { [weak self] state in
            guard let self else { return }
            switch state {
            case .ready:
                let ok = "HTTP/1.1 200 Connection Established\r\n\r\n".data(using: .utf8)!
                client.send(content: ok, completion: .contentProcessed { error in
                    if let error { NSLog("client send 200 failed: \(error)"); client.cancel(); upstream.cancel(); return }
                    self.pump(from: client, to: upstream)
                    self.pump(from: upstream, to: client)
                })
            case .failed(let e):
                NSLog("upstream failed \(host)->\(ip): \(e)")
                self.sendError(client, "502 Bad Gateway")
                upstream.cancel()
            case .cancelled:
                client.cancel()
            default: break
            }
        }
        upstream.start(queue: queue)
    }

    private func pump(from src: NWConnection, to dst: NWConnection) {
        src.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] data, _, isComplete, error in
            if let data, !data.isEmpty {
                dst.send(content: data, completion: .contentProcessed { sendErr in
                    if sendErr != nil { src.cancel(); dst.cancel(); return }
                    self?.pump(from: src, to: dst)
                })
            } else if isComplete || error != nil {
                dst.send(content: nil, contentContext: .finalMessage, isComplete: true, completion: .contentProcessed { _ in
                    src.cancel()
                })
            } else {
                self?.pump(from: src, to: dst)
            }
        }
    }

    private func sendError(_ client: NWConnection, _ status: String) {
        let resp = "HTTP/1.1 \(status)\r\nContent-Length: 0\r\n\r\n".data(using: .utf8)!
        client.send(content: resp, completion: .contentProcessed { _ in client.cancel() })
    }
}
