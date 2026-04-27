//
//  ContentView.swift
//  NoShorts
//

import SwiftUI
import WebKit
import Observation
import SafariServices

// Mobile YouTube selectors — matches ytm-* components used on mobile web
private let shortsBlockScript = """
(function() {
    function hasShortLink(el) {
        const check = (root) => {
            for (const a of root.querySelectorAll('a')) {
                const href = a.getAttribute('href') || '';
                if (href === '/shorts' || href.startsWith('/shorts/')) return true;
            }
            return false;
        };
        return check(el) || (el.shadowRoot && check(el.shadowRoot));
    }

    function removeShorts() {
        // Bottom nav Shorts tab (mobile)
        document.querySelectorAll('a.pivot-bar-item-tab[href="/shorts"]').forEach(a => a.closest('.pivot-bar-item-tab-wrapper, .pivot-bar-item-tab')?.remove());
        document.querySelectorAll('yt-tab-shape-view-model').forEach(el => {
            if (hasShortLink(el) || el.textContent?.trim() === 'Shorts') el.remove();
        });
        // Desktop sidebar (mini guide + guide)
        document.querySelectorAll('ytd-mini-guide-entry-renderer, ytd-guide-entry-renderer').forEach(el => {
            if (hasShortLink(el) || el.textContent?.trim() === 'Shorts') el.remove();
        });
        // Shorts shelf — mobile and desktop
        document.querySelectorAll('ytm-reel-shelf-renderer, ytm-shorts-lockup-view-model-v2, ytd-reel-shelf-renderer, ytd-rich-shelf-renderer[is-shorts]').forEach(e => e.remove());
        // Shorts cards in home grid
        document.querySelectorAll('ytm-video-with-context-renderer, ytd-rich-item-renderer').forEach(item => {
            if (item.querySelector('a[href*="/shorts/"]')) item.remove();
        });
        // Shorts in search results
        document.querySelectorAll('a[href*="/shorts/"]').forEach(a => {
            const card = a.closest('ytm-compact-video-renderer, ytd-video-renderer');
            if (card) card.remove();
        });
    }

    removeShorts();
    new MutationObserver(removeShorts).observe(document.body, { childList: true, subtree: true });
    setInterval(removeShorts, 800);
})();
"""

@Observable
final class WebViewModel {
    @ObservationIgnored let webView: WKWebView
    var isLoading = false
    var canGoBack = false
    var canGoForward = false
    var googleSignInURL: URL?

    init() {
        let config = WKWebViewConfiguration()
        let script = WKUserScript(source: shortsBlockScript, injectionTime: .atDocumentEnd, forMainFrameOnly: false)
        config.userContentController.addUserScript(script)
        let wv = WKWebView(frame: .zero, configuration: config)
        // Mobile Safari UA — Google allows sign-in; mobile YouTube UI
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
            if url.path.hasPrefix("/shorts") {
                model.goHome()
                return .cancel
            }
            // Open Google sign-in in SFSafariViewController so Google trusts the flow
            if url.host?.contains("accounts.google.com") == true {
                model.googleSignInURL = url
                return .cancel
            }
            return .allow
        }

        func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
            model.isLoading = true
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            webView.evaluateJavaScript(shortsBlockScript)
            model.isLoading = false
            model.canGoBack = webView.canGoBack
            model.canGoForward = webView.canGoForward
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            model.isLoading = false
        }
    }
}

struct SafariView: UIViewControllerRepresentable {
    let url: URL
    func makeUIViewController(context: Context) -> SFSafariViewController { SFSafariViewController(url: url) }
    func updateUIViewController(_ vc: SFSafariViewController, context: Context) {}
}

struct ContentView: View {
    @State private var model = WebViewModel()

    var body: some View {
        ZStack(alignment: .top) {
            VStack(spacing: 0) {
                YouTubeWebView(model: model)
                    // No ignoresSafeArea — respect Dynamic Island / notch at top

                toolbar
            }

            if model.isLoading {
                ProgressView()
                    .progressViewStyle(.linear)
                    .tint(.red)
                    .frame(maxWidth: .infinity)
                    .padding(.top, 4)
            }
        }
        .sheet(item: Binding(
            get: { model.googleSignInURL.map { IdentifiableURL($0) } },
            set: { _ in
                model.googleSignInURL = nil
                model.webView.reload()  // Reload YouTube after sign-in
            }
        )) { item in
            SafariView(url: item.url)
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

struct IdentifiableURL: Identifiable {
    let id = UUID()
    let url: URL
    init(_ url: URL) { self.url = url }
}

#Preview {
    ContentView()
}
