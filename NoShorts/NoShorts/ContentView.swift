//
//  ContentView.swift
//  NoShorts
//

import SwiftUI
import WebKit
import Observation

// Runs at document start: remove WKWebView fingerprint + inject persistent CSS
private let earlyScript = """
(function() {
    // Remove fingerprint only for Google sign-in pages; keep webkit intact for YouTube
    if (window.location.hostname.includes('accounts.google')) {
        try { Object.defineProperty(window, 'webkit', { get: () => undefined, configurable: true }); } catch(e) {}
    }
    const s = document.createElement('style');
    s.id = 'no-shorts';
    s.textContent = `
        ytm-reel-shelf-renderer, ytm-shorts-lockup-view-model-v2,
        ytm-shorts-shelf-renderer, ytm-rich-section-renderer:has(ytm-reel-shelf-renderer),
        ytd-reel-shelf-renderer, ytd-rich-shelf-renderer[is-shorts],
        [aria-label="Shorts"][href="/shorts"],
        a[title="Shorts"][href="/shorts"] { display:none!important; }
    `;
    (document.head || document.documentElement).appendChild(s);
})();
"""

// Runs at document end: DOM cleanup with debounced MutationObserver (no interval)
private let shortsBlockScript = """
(function() {
    function removeShorts() {
        // Nav tab: find a[href="/shorts"] and remove nearest meaningful container
        document.querySelectorAll('a[href="/shorts"]').forEach(a => {
            let el = a;
            for (let i = 0; i < 6; i++) {
                if (!el.parentElement || el.parentElement === document.body) break;
                el = el.parentElement;
                const tag = el.tagName.toLowerCase();
                if (tag.includes('-') || tag === 'li' || el.getAttribute('role') === 'tab') {
                    el.remove(); return;
                }
            }
            a.style.display = 'none';
        });
        // Also target by aria/title attributes
        document.querySelectorAll('[aria-label="Shorts"], [title="Shorts"]').forEach(el => {
            const item = el.closest('ytd-guide-entry-renderer, ytd-mini-guide-entry-renderer, ytm-pivot-bar-item-renderer, [role="tab"], li');
            if (item) item.remove();
        });
        // Desktop sidebar
        document.querySelectorAll('ytd-mini-guide-entry-renderer, ytd-guide-entry-renderer').forEach(el => {
            if (el.querySelector('a[href="/shorts"]') || el.textContent?.trim() === 'Shorts') el.remove();
        });
        // Shelves
        document.querySelectorAll('ytm-reel-shelf-renderer, ytm-shorts-lockup-view-model-v2, ytm-shorts-shelf-renderer, ytd-reel-shelf-renderer, ytd-rich-shelf-renderer[is-shorts]').forEach(e => e.remove());
        // Feed cards
        document.querySelectorAll('ytm-video-with-context-renderer, ytm-compact-video-renderer, ytd-rich-item-renderer, ytd-video-renderer').forEach(item => {
            if (item.querySelector('a[href*="/shorts/"]')) item.remove();
        });
    }

    removeShorts();
    // Debounced observer — coalesces bursts of DOM changes into one cleanup call
    let debounce;
    new MutationObserver(() => {
        clearTimeout(debounce);
        debounce = setTimeout(removeShorts, 300);
    }).observe(document.body, { childList: true, subtree: true });
})();
"""

private let sessionDuration: TimeInterval = 30 * 60  // 30 minutes

@Observable
final class WebViewModel {
    @ObservationIgnored let webView: WKWebView
    var isLoading = false
    var canGoBack = false
    var canGoForward = false

    init() {
        let config = WKWebViewConfiguration()
        config.mediaTypesRequiringUserActionForPlayback = .video  // block video autoplay, allow user taps
        config.userContentController.addUserScript(
            WKUserScript(source: earlyScript, injectionTime: .atDocumentStart, forMainFrameOnly: false)
        )
        config.userContentController.addUserScript(
            WKUserScript(source: shortsBlockScript, injectionTime: .atDocumentEnd, forMainFrameOnly: false)
        )
        let wv = WKWebView(frame: .zero, configuration: config)
        wv.customUserAgent = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        self.webView = wv
    }

    func load(_ urlString: String) {
        guard let url = URL(string: urlString) else { return }
        webView.load(URLRequest(url: url))
    }

    func goHome() { load("https://www.youtube.com") }
}

struct YouTubeWebView: UIViewRepresentable {
    let model: WebViewModel

    func makeCoordinator() -> Coordinator { Coordinator(model: model) }

    func makeUIView(context: Context) -> WKWebView {
        let wv = model.webView
        wv.navigationDelegate = context.coordinator
        model.goHome()
        return wv
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}

    @MainActor
    final class Coordinator: NSObject, WKNavigationDelegate {
        let model: WebViewModel
        init(model: WebViewModel) { self.model = model }

        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction) async -> WKNavigationActionPolicy {
            guard let url = action.request.url else { return .allow }
            if url.path.hasPrefix("/shorts") { model.goHome(); return .cancel }
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

    var body: some View {
        ZStack(alignment: .top) {
            VStack(spacing: 0) {
                YouTubeWebView(model: model)
                toolbar
            }

            if model.isLoading {
                ProgressView()
                    .progressViewStyle(.linear)
                    .tint(.red)
                    .frame(maxWidth: .infinity)
                    .padding(.top, 4)
            }

            // Countdown badge — top right, above YouTube header
            countdownBadge
                .padding(.top, 8)
                .padding(.trailing, 12)
                .frame(maxWidth: .infinity, alignment: .trailing)
        }
        .onAppear { startTimer() }
        .onDisappear { timer?.invalidate() }
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
            if remaining > 0 {
                remaining -= 1
            } else {
                timer?.invalidate()
                exit(0)
            }
        }
    }

    private var toolbar: some View {
        HStack(spacing: 0) {
            toolbarButton("chevron.left", enabled: model.canGoBack) { model.webView.goBack() }
            toolbarButton("chevron.right", enabled: model.canGoForward) { model.webView.goForward() }
            toolbarButton("house.fill", enabled: true) { model.goHome() }
            toolbarButton("arrow.clockwise", enabled: true) { model.webView.reload() }
        }
        .frame(height: 52)
        .background(.bar)
        .overlay(alignment: .top) { Divider() }
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
