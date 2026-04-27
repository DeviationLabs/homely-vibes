//
//  ContentView.swift
//  NoShorts
//

import SwiftUI
import WebKit
import Observation
import Network

// Runs at document start: fingerprint removal + CSS + autoplay block + SPA navigation guard
private let earlyScript = """
(function() {
    if (window.location.hostname.includes('accounts.google')) {
        try { Object.defineProperty(window, 'webkit', { get: () => undefined, configurable: true }); } catch(e) {}
    }

    // CSS: hide Shorts before paint
    const s = document.createElement('style');
    s.id = 'no-shorts';
    s.textContent = `
        .pivot-shorts { display:none!important; }
        ytm-shorts-lockup-view-model,
        ytm-rich-shelf-renderer:has(ytm-shorts-lockup-view-model),
        ytm-rich-section-renderer:has(ytm-shorts-lockup-view-model),
        ytm-rich-item-renderer:has(ytm-shorts-lockup-view-model) { display:none!important; }
        ytd-reel-shelf-renderer, ytd-rich-shelf-renderer[is-shorts] { display:none!important; }
        ytm-pivot-bar-renderer { display:none!important; }
    `;
    (document.head || document.documentElement).appendChild(s);

    // Block autoplay: intercept video.play() — only allow within 1.5s of a user touch/click
    let lastInteraction = 0;
    document.addEventListener('touchstart', () => { lastInteraction = Date.now(); }, { capture: true, passive: true });
    document.addEventListener('click', () => { lastInteraction = Date.now(); }, { capture: true, passive: true });
    const _play = HTMLVideoElement.prototype.play;
    HTMLVideoElement.prototype.play = function() {
        if (Date.now() - lastInteraction < 1500) return _play.call(this);
        return Promise.reject(new DOMException('Autoplay blocked', 'NotAllowedError'));
    };

    // Block SPA navigation to /shorts. Home (/) is handled in Swift via KVO on
    // webView.url so we catch it regardless of who triggered the URL change.
    const _push = history.pushState.bind(history);
    const _replace = history.replaceState.bind(history);
    const isShorts = (u) => u && String(u).startsWith('/shorts');
    history.pushState = (s,t,u) => { if (!isShorts(u)) _push(s,t,u); };
    history.replaceState = (s,t,u) => { if (!isShorts(u)) _replace(s,t,u); };
})();
"""

// Runs at document end: DOM removal + debounced MutationObserver
private let shortsBlockScript = """
(function() {
    function removeShorts() {
        document.querySelectorAll('.pivot-shorts').forEach(e => e.remove());
        document.querySelectorAll('ytd-mini-guide-entry-renderer, ytd-guide-entry-renderer').forEach(el => {
            if (el.querySelector('a[href="/shorts"]') || el.textContent?.trim() === 'Shorts') el.remove();
        });
        document.querySelectorAll('ytm-shorts-lockup-view-model').forEach(e => {
            (e.closest('ytm-rich-item-renderer, ytm-rich-section-renderer, ytm-rich-shelf-renderer') || e).remove();
        });
        document.querySelectorAll('ytm-rich-shelf-renderer').forEach(el => {
            if (el.querySelector('ytm-shorts-lockup-view-model')) el.remove();
        });
        document.querySelectorAll('ytd-reel-shelf-renderer, ytd-rich-shelf-renderer[is-shorts]').forEach(e => e.remove());
        document.querySelectorAll('ytd-rich-item-renderer, ytd-video-renderer').forEach(item => {
            if (item.querySelector('a[href*="/shorts/"]')) item.remove();
        });
    }

    removeShorts();
    let debounce;
    new MutationObserver(() => {
        clearTimeout(debounce);
        debounce = setTimeout(removeShorts, 300);
    }).observe(document.body, { childList: true, subtree: true });
})();
"""

private let sessionDuration: TimeInterval = 30 * 60

@Observable
final class WebViewModel {
    @ObservationIgnored let webView: WKWebView
    @ObservationIgnored private let proxy = LocalProxy()
    var isLoading = false
    var canGoBack = false
    var canGoForward = false

    init() {
        let config = WKWebViewConfiguration()
        config.mediaTypesRequiringUserActionForPlayback = .video
        config.userContentController.addUserScript(
            WKUserScript(source: earlyScript, injectionTime: .atDocumentStart, forMainFrameOnly: false)
        )
        config.userContentController.addUserScript(
            WKUserScript(source: shortsBlockScript, injectionTime: .atDocumentEnd, forMainFrameOnly: false)
        )

        // Route WKWebView traffic through a local DoH-backed proxy so requests
        // bypass system DNS (and any NextDNS-style filtering on youtube.com).
        if let port = try? proxy.start() {
            let endpoint = NWEndpoint.hostPort(host: "127.0.0.1", port: NWEndpoint.Port(rawValue: port)!)
            let proxyConfig = ProxyConfiguration(httpCONNECTProxy: endpoint, tlsOptions: nil)
            let dataStore = WKWebsiteDataStore.default()
            dataStore.proxyConfigurations = [proxyConfig]
            config.websiteDataStore = dataStore
            NSLog("LocalProxy listening on 127.0.0.1:\(port)")
        } else {
            NSLog("LocalProxy failed to start; WKWebView will use system DNS")
        }

        let wv = WKWebView(frame: .zero, configuration: config)
        wv.customUserAgent = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        self.webView = wv
    }

    func load(_ urlString: String) {
        guard let url = URL(string: urlString) else { return }
        webView.load(URLRequest(url: url))
    }

    func goHome() { load("https://www.youtube.com/feed/channels") }
    func goPlaylists() { load("https://www.youtube.com/feed/playlists") }
    func goLiked() { load("https://www.youtube.com/playlist?list=LL") }
    func goAccount() { load("https://www.youtube.com/account") }

    func search(_ query: String) {
        let encoded = query.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? query
        load("https://www.youtube.com/results?search_query=\(encoded)")
    }
}

struct YouTubeWebView: UIViewRepresentable {
    let model: WebViewModel

    func makeCoordinator() -> Coordinator { Coordinator(model: model) }

    func makeUIView(context: Context) -> WKWebView {
        let wv = model.webView
        wv.navigationDelegate = context.coordinator
        model.goPlaylists()
        return wv
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}

    @MainActor
    final class Coordinator: NSObject, WKNavigationDelegate {
        let model: WebViewModel
        private var urlObservation: NSKeyValueObservation?

        init(model: WebViewModel) {
            self.model = model
            super.init()
            // Catch SPA URL changes (history.pushState / replaceState). decidePolicyFor
            // does NOT fire for these, so YouTube's in-app Home tab tap can sneak past.
            urlObservation = model.webView.observe(\.url, options: [.new]) { [weak self] _, change in
                guard let self, let url = change.newValue ?? nil else { return }
                let isHome = Self.isYouTubeHome(url)
                let isWatch = Self.isWatchPage(url)
                Task { @MainActor in
                    if isHome { self.model.goPlaylists() }
                    if isWatch { Self.setOrientation(.landscape) }
                }
            }
        }

        deinit { urlObservation?.invalidate() }

        nonisolated static func isYouTubeHome(_ url: URL) -> Bool {
            (url.host?.hasSuffix("youtube.com") == true) && (url.path.isEmpty || url.path == "/")
        }

        nonisolated static func isWatchPage(_ url: URL) -> Bool {
            (url.host?.hasSuffix("youtube.com") == true) && url.path.hasPrefix("/watch")
        }

        @MainActor
        static func setOrientation(_ mask: UIInterfaceOrientationMask) {
            for case let scene as UIWindowScene in UIApplication.shared.connectedScenes {
                scene.requestGeometryUpdate(.iOS(interfaceOrientations: mask))
            }
        }

        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction) async -> WKNavigationActionPolicy {
            guard let url = action.request.url else { return .allow }
            if url.path.hasPrefix("/shorts") { model.goPlaylists(); return .cancel }
            if Self.isYouTubeHome(url) { model.goPlaylists(); return .cancel }
            return .allow
        }

        func webView(_ webView: WKWebView, didStartProvisionalNavigation _: WKNavigation!) { model.isLoading = true }

        func webView(_ webView: WKWebView, didFinish _: WKNavigation!) {
            webView.evaluateJavaScript(shortsBlockScript)
            model.isLoading = false
            model.canGoBack = webView.canGoBack
            model.canGoForward = webView.canGoForward
        }

        func webView(_ webView: WKWebView, didFail _: WKNavigation!, withError _: Error) { model.isLoading = false }
    }
}

struct ContentView: View {
    @State private var model = WebViewModel()
    @State private var remaining: TimeInterval = sessionDuration
    @State private var timer: Timer?
    @State private var searchText = ""
    @State private var isSearching = false
    @FocusState private var searchFocused: Bool

    var body: some View {
        ZStack(alignment: .top) {
            VStack(spacing: 0) {
                topToolbar
                YouTubeWebView(model: model)
                bottomToolbar
            }

            if model.isLoading {
                ProgressView()
                    .progressViewStyle(.linear)
                    .tint(.red)
                    .frame(maxWidth: .infinity)
                    .padding(.top, 52)
            }

            countdownBadge
                .padding(.top, 60)  // 52pt top toolbar + 8pt gap
                .padding(.trailing, 12)
                .frame(maxWidth: .infinity, alignment: .trailing)
        }
        .onAppear { startTimer() }
        .onDisappear { timer?.invalidate() }
    }

    private var topToolbar: some View {
        HStack(spacing: 0) {
            toolbarButton("play.square.stack.fill", enabled: true) { model.goPlaylists() }
            toolbarButton("hand.thumbsup.fill", enabled: true) { model.goLiked() }
            toolbarButton("square.grid.3x3.fill", enabled: true) { model.goHome() }
            toolbarButton("person.crop.circle.fill", enabled: true) { model.goAccount() }
        }
        .frame(height: 52)
        .background(.bar)
        .overlay(alignment: .bottom) { Divider() }
    }

    private var bottomToolbar: some View {
        HStack(spacing: 0) {
            if isSearching {
                HStack(spacing: 8) {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(.secondary)
                        .padding(.leading, 12)
                    TextField("Search YouTube", text: $searchText)
                        .focused($searchFocused)
                        .submitLabel(.search)
                        .onSubmit {
                            if !searchText.isEmpty { model.search(searchText) }
                            isSearching = false
                            searchText = ""
                        }
                    Button {
                        isSearching = false
                        searchText = ""
                        searchFocused = false
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                            .foregroundStyle(.secondary)
                            .padding(.trailing, 12)
                    }
                }
                .frame(maxWidth: .infinity)
                .frame(height: 36)
                .background(Color(.secondarySystemBackground))
                .clipShape(RoundedRectangle(cornerRadius: 10))
                .padding(.horizontal, 12)
            } else {
                toolbarButton("chevron.left", enabled: model.canGoBack) { model.webView.goBack() }
                toolbarButton("chevron.right", enabled: model.canGoForward) { model.webView.goForward() }
                toolbarButton("magnifyingglass", enabled: true) {
                    isSearching = true
                    searchFocused = true
                }
                toolbarButton("house.fill", enabled: true) { model.goHome() }
                toolbarButton("arrow.clockwise", enabled: true) { model.webView.reload() }
            }
        }
        .frame(height: 52)
        .background(.bar)
        .overlay(alignment: .top) { Divider() }
        .animation(.easeInOut(duration: 0.2), value: isSearching)
    }

    private var countdownBadge: some View {
        let minutes = Int(remaining) / 60
        let seconds = Int(remaining) % 60
        let isLow = remaining <= 5 * 60
        let isVeryLow = remaining <= 60
        return Text(String(format: "%d:%02d", minutes, seconds))
            .font(.system(size: 12, weight: .semibold, design: .monospaced))
            .foregroundStyle(isVeryLow ? .white : (isLow ? .orange : .secondary))
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(isVeryLow ? Color.red : Color(.systemBackground).opacity(0.85))
            .clipShape(Capsule())
            .shadow(radius: 2)
    }

    private func startTimer() {
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { _ in
            if remaining > 0 { remaining -= 1 } else { timer?.invalidate(); exit(0) }
        }
    }

    private func toolbarButton(_ icon: String, enabled: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: icon)
                .font(.system(size: 18, weight: .medium))
                .foregroundStyle(enabled ? Color.red : Color.secondary.opacity(0.4))
                .frame(maxWidth: .infinity)
                .frame(height: 52)
                .contentShape(Rectangle())
        }
        .disabled(!enabled)
    }
}

#Preview {
    ContentView()
}
