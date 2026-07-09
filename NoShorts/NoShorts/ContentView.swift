//
//  ContentView.swift
//  NoShorts
//
//  V2 architecture: WKWebView, LocalProxy scoped to *.youtube.com via
//  ProxyConfiguration.matchDomains. All other traffic (googlevideo, ytimg,
//  doubleclick, googleapis, etc.) goes direct from the WebContent process
//  via system DNS. See V2_PRD.md §5 for the full rationale.
//

import SwiftUI
import WebKit
import Observation
import Network

// MARK: - Injected user scripts

/// Runs at document start in every frame: CSS that hides Shorts affordances
/// before first paint. CSS-only BY DESIGN — the former window.webkit hide,
/// HTMLVideoElement.play() wrapper, and pushState wrappers were BotGuard-visible
/// tampering that tripped YouTube's stream attestation and killed playback
/// (V2_REMEDIATION_PLAN.md §3a). Do not reintroduce page-JS tampering here.
/// /shorts SPA navs are currently unguarded — Swift-side replacement: issue #232.
private let earlyScript = """
(function() {
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
})();
"""

/// Report HTML5 video lifecycle back to Swift so we can lock orientation,
/// and enter fullscreen when a video starts. Deliberately NOT listening for
/// `error`/`stalled` — those fire on every buffer hiccup and previously
/// caused portrait↔landscape flapping.
///
/// Fullscreen entry calls native webkitEnterFullscreen() directly from the
/// play/playing listeners — sim probe (2026-07-09) showed element fullscreen
/// is unavailable in iOS WKWebView (document.fullscreenEnabled undefined even
/// with isElementFullscreenEnabled) and synthetic clicks on YouTube's button
/// are ignored (untrusted). webkitEnterFullscreen throws InvalidStateError
/// until media is loaded, hence the retry on 'playing'.
/// No prototype/history tampering here — that trips stream attestation
/// (V2_REMEDIATION_PLAN.md §3a).
private let videoEventScript = """
(function() {
    const post = (kind) => {
        try { window.webkit.messageHandlers.video.postMessage(kind); } catch(e) {}
    };
    let wantFS = false;
    const tryFS = (v) => {
        if (!wantFS || v.webkitDisplayingFullscreen) { wantFS = false; return; }
        try { v.webkitEnterFullscreen(); wantFS = false; } catch (e) { /* retry on 'playing' */ }
    };
    document.addEventListener('play', (e) => {
        const v = e.target;
        if (!(v instanceof HTMLVideoElement)) return;
        post('play');
        // Only on fresh starts (content or ad begin), not on pause→resume —
        // re-entering after a manual fullscreen exit would fight the user.
        if (v.currentTime < 1) { wantFS = true; tryFS(v); }
    }, true);
    document.addEventListener('playing', (e) => {
        if (e.target instanceof HTMLVideoElement) tryFS(e.target);
    }, true);
    document.addEventListener('pause', (e) => {
        if (!(e.target instanceof HTMLVideoElement)) return;
        wantFS = false;
        post('pause');
    }, true);
    document.addEventListener('ended', (e) => {
        const v = e.target;
        if (!(v instanceof HTMLVideoElement)) return;
        post('ended');
        try { if (v.webkitDisplayingFullscreen) v.webkitExitFullscreen(); } catch (err) {}
    }, true);
    // pagehide covers SPA-back navigating away from /watch without a pause event.
    window.addEventListener('pagehide', () => post('pause'));
})();
"""

/// Runs at document end + as a MutationObserver: yank any Shorts DOM nodes
/// that survived the CSS in earlyScript.
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

// MARK: - Model

@Observable
final class WebViewModel {
    @ObservationIgnored let webView: WKWebView
    @ObservationIgnored private let proxy = LocalProxy()
    var isLoading = false
    var canGoBack = false
    var canGoForward = false
    var proxyReady = false

    init() {
        let config = WKWebViewConfiguration()
        config.mediaTypesRequiringUserActionForPlayback = .video
        // YouTube's adaptive-streaming pipeline expects inline <video>. Without
        // this, playback on iOS 26 hits a limited fullscreen-only codepath.
        config.allowsInlineMediaPlayback = true
        // Honest UA: WebKit generates the true OS/WebKit prefix and appends
        // this Safari-shaped suffix. Replaces the pinned iOS-17 customUserAgent
        // lie, which contradicted the real WebKit fingerprint (Track A).
        config.applicationNameForUserAgent = "Version/26.5 Mobile/15E148 Safari/604.1"

        config.userContentController.addUserScript(
            WKUserScript(source: earlyScript, injectionTime: .atDocumentStart, forMainFrameOnly: false)
        )
        config.userContentController.addUserScript(
            WKUserScript(source: shortsBlockScript, injectionTime: .atDocumentEnd, forMainFrameOnly: false)
        )
        config.userContentController.addUserScript(
            WKUserScript(source: videoEventScript, injectionTime: .atDocumentEnd, forMainFrameOnly: false)
        )

        // Route ONLY *.youtube.com through the local DoH-backed proxy. Every
        // other host (googlevideo, ytimg, doubleclick, googleapis, ...) goes
        // direct via WKWebView's own networking + system DNS. This is the
        // critical scoping that V1 got wrong on iOS 26.5.2 — see V2_PRD.md §5.
        if let port = try? proxy.start() {
            let endpoint = NWEndpoint.hostPort(host: "127.0.0.1",
                                               port: NWEndpoint.Port(rawValue: port)!)
            var proxyConfig = ProxyConfiguration(httpCONNECTProxy: endpoint, tlsOptions: nil)
            proxyConfig.matchDomains = ["youtube.com"]
            let dataStore = WKWebsiteDataStore.default()
            dataStore.proxyConfigurations = [proxyConfig]
            config.websiteDataStore = dataStore
            self.proxyReady = true
            NSLog("LocalProxy started on 127.0.0.1:\(port), scoped to *.youtube.com")
        } else {
            NSLog("LocalProxy failed to start; NoShorts cannot reach youtube.com")
            self.proxyReady = false
        }

        let wv = WKWebView(frame: .zero, configuration: config)
        #if DEBUG
        // Phase-0 diagnostics: attach Mac Safari Web Inspector (Develop menu)
        // to observe googlevideo request statuses. Never ships in Release.
        wv.isInspectable = true
        #endif
        self.webView = wv
    }

    // MARK: - Navigation helpers

    func load(_ urlString: String) {
        guard let url = URL(string: urlString) else { return }
        webView.load(URLRequest(url: url))
    }

    func goPlaylists() { load("https://www.youtube.com/feed/playlists") }
    func goLiked()     { load("https://www.youtube.com/playlist?list=LL") }
    func goHome()      { load("https://www.youtube.com/feed/channels") }
    func goAccount()   { load("https://www.youtube.com/account") }

    func search(_ query: String) {
        let encoded = query.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? query
        load("https://www.youtube.com/results?search_query=\(encoded)")
    }
}

// MARK: - WKWebView bridge & delegate

struct YouTubeWebView: UIViewRepresentable {
    let model: WebViewModel

    func makeCoordinator() -> Coordinator { Coordinator(model: model) }

    func makeUIView(context: Context) -> WKWebView {
        model.webView.navigationDelegate = context.coordinator
        model.goPlaylists()
        return model.webView
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}

    @MainActor
    final class Coordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
        let model: WebViewModel
        private var urlObs: NSKeyValueObservation?
        private var canBackObs: NSKeyValueObservation?
        private var canFwdObs: NSKeyValueObservation?
        private var orientationTask: Task<Void, Never>?
        private var currentOrientation: UIInterfaceOrientationMask = .portrait

        init(model: WebViewModel) {
            self.model = model
            super.init()
            model.webView.configuration.userContentController.add(self, name: "video")

            // Catch SPA URL changes (history.pushState / replaceState). decidePolicyFor
            // does NOT fire for these, so a YouTube-in-page Home tap can sneak past
            // without KVO on the url property.
            urlObs = model.webView.observe(\.url, options: [.new]) { [weak self] _, change in
                guard let self, let url = change.newValue ?? nil else { return }
                if Self.isYouTubeHome(url) {
                    Task { @MainActor in self.model.goPlaylists() }
                }
            }
            // Mirror the history-stack flags live. Reading them only in didFinish
            // leaves the toolbar chevrons stale whenever a nav is cancelled — which
            // our /shorts and home intercepts do frequently.
            canBackObs = model.webView.observe(\.canGoBack, options: [.new, .initial]) { [weak self] wv, _ in
                Task { @MainActor in self?.model.canGoBack = wv.canGoBack }
            }
            canFwdObs = model.webView.observe(\.canGoForward, options: [.new, .initial]) { [weak self] wv, _ in
                Task { @MainActor in self?.model.canGoForward = wv.canGoForward }
            }
        }

        deinit {
            urlObs?.invalidate()
            canBackObs?.invalidate()
            canFwdObs?.invalidate()
            model.webView.configuration.userContentController.removeScriptMessageHandler(forName: "video")
        }

        nonisolated static func isYouTubeHome(_ url: URL) -> Bool {
            (url.host?.hasSuffix("youtube.com") == true) && (url.path.isEmpty || url.path == "/")
        }

        // MARK: WKScriptMessageHandler — video events → orientation

        nonisolated func userContentController(_ controller: WKUserContentController,
                                               didReceive message: WKScriptMessage) {
            guard let kind = message.body as? String else { return }
            Task { @MainActor in
                let target: UIInterfaceOrientationMask
                switch kind {
                case "play":           target = .landscapeRight
                case "pause", "ended": target = .portrait
                default: return
                }
                self.scheduleOrientation(target)
            }
        }

        /// 400 ms coalesce. YouTube's player fires transient pause→play during
        /// buffering; without coalescing, the screen orientation flaps.
        private func scheduleOrientation(_ target: UIInterfaceOrientationMask) {
            if target == currentOrientation && orientationTask == nil { return }
            orientationTask?.cancel()
            orientationTask = Task { @MainActor [weak self] in
                try? await Task.sleep(nanoseconds: 400_000_000)
                guard let self, !Task.isCancelled else { return }
                self.orientationTask = nil
                guard target != self.currentOrientation else { return }
                self.currentOrientation = target
                Self.setOrientation(target)
            }
        }

        @MainActor
        static func setOrientation(_ mask: UIInterfaceOrientationMask) {
            AppDelegate.orientationLock = mask
            for case let scene as UIWindowScene in UIApplication.shared.connectedScenes {
                for window in scene.windows {
                    window.rootViewController?.setNeedsUpdateOfSupportedInterfaceOrientations()
                }
                scene.requestGeometryUpdate(.iOS(interfaceOrientations: mask)) { error in
                    NSLog("NoShorts.setOrientation(\(mask.rawValue)) failed: \(error)")
                }
            }
        }

        // MARK: WKNavigationDelegate

        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction) async -> WKNavigationActionPolicy {
            guard let url = action.request.url else { return .allow }
            // /shorts: cancel silently. No follow-up load() — pushing playlists
            // onto history destroys any forward stack.
            if url.path.hasPrefix("/shorts") { return .cancel }
            // youtube.com/ (algorithmic home): redirect to Playlists, but only
            // on forward navs. Backward/Forward navs must be preserved or the
            // toolbar chevrons appear broken.
            if Self.isYouTubeHome(url) {
                if action.navigationType != .backForward { model.goPlaylists() }
                return .cancel
            }
            return .allow
        }

        func webView(_ webView: WKWebView, didStartProvisionalNavigation _: WKNavigation!) {
            model.isLoading = true
        }

        func webView(_ webView: WKWebView, didFinish _: WKNavigation!) {
            webView.evaluateJavaScript(shortsBlockScript)
            model.isLoading = false
            // canGoBack / canGoForward are mirrored via KVO in init.
        }

        func webView(_ webView: WKWebView, didFail _: WKNavigation!, withError _: Error) {
            model.isLoading = false
        }
    }
}

// MARK: - Root view

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
                .padding(.top, 60)
                .padding(.trailing, 12)
                .frame(maxWidth: .infinity, alignment: .trailing)

            if !model.proxyReady {
                proxyErrorBanner
                    .padding(.top, 60)
                    .frame(maxWidth: .infinity, alignment: .center)
            }
        }
        .onAppear { startTimer() }
        .onDisappear { timer?.invalidate() }
    }

    // MARK: Toolbars

    private var topToolbar: some View {
        HStack(spacing: 0) {
            toolbarButton("play.square.stack.fill",  enabled: true) { model.goPlaylists() }
            toolbarButton("hand.thumbsup.fill",      enabled: true) { model.goLiked() }
            toolbarButton("square.grid.3x3.fill",    enabled: true) { model.goHome() }
            toolbarButton("person.crop.circle.fill", enabled: true) { model.goAccount() }
        }
        .frame(height: 52)
        .background(.bar)
        .overlay(alignment: .bottom) { Divider() }
    }

    private var bottomToolbar: some View {
        HStack(spacing: 0) {
            if isSearching {
                searchField
            } else {
                toolbarButton("chevron.left",  enabled: model.canGoBack)    { model.webView.goBack() }
                toolbarButton("chevron.right", enabled: model.canGoForward) { model.webView.goForward() }
                toolbarButton("magnifyingglass", enabled: true) {
                    isSearching = true
                    searchFocused = true
                }
                toolbarButton("house.fill",      enabled: true) { model.goHome() }
                toolbarButton("arrow.clockwise", enabled: true) { model.webView.reload() }
            }
        }
        .frame(height: 52)
        .background(.bar)
        .overlay(alignment: .top) { Divider() }
        .animation(.easeInOut(duration: 0.2), value: isSearching)
    }

    private var searchField: some View {
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
    }

    // MARK: Session countdown

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

    private var proxyErrorBanner: some View {
        Text("DoH proxy unavailable — restart NoShorts")
            .font(.system(size: 12, weight: .semibold))
            .foregroundStyle(.white)
            .padding(.horizontal, 10)
            .padding(.vertical, 4)
            .background(Color.red)
            .clipShape(Capsule())
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
