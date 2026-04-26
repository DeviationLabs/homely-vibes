//
//  ContentView.swift
//  NoShorts
//

import SwiftUI
import WebKit
import Observation

private let shortsBlockScript = """
(function() {
    function hasShortLink(el) {
        // Check light DOM and open shadow DOM for /shorts links
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
        // Sidebar nav items (mini guide + full guide) — check shadow DOM too
        document.querySelectorAll('ytd-mini-guide-entry-renderer, ytd-guide-entry-renderer').forEach(el => {
            if (hasShortLink(el) || el.textContent?.trim() === 'Shorts') el.remove();
        });
        // Shorts shelf on home feed
        document.querySelectorAll('ytd-reel-shelf-renderer, ytd-rich-shelf-renderer[is-shorts]').forEach(e => e.remove());
        // Shorts cards in home grid
        document.querySelectorAll('ytd-rich-item-renderer').forEach(item => {
            if (item.querySelector('a#thumbnail[href*="/shorts/"]')) item.remove();
        });
        // Shorts in search results
        document.querySelectorAll('ytd-video-renderer a#thumbnail[href*="/shorts/"]').forEach(a => {
            a.closest('ytd-video-renderer')?.remove();
        });
    }

    removeShorts();
    new MutationObserver(removeShorts).observe(document.body, { childList: true, subtree: true });
    // Periodic sweep catches SPA navigations where MutationObserver may miss shadow DOM updates
    setInterval(removeShorts, 800);
})();
"""

@Observable
final class WebViewModel {
    @ObservationIgnored let webView: WKWebView
    var isLoading = false
    var canGoBack = false
    var canGoForward = false

    init() {
        let config = WKWebViewConfiguration()
        let script = WKUserScript(source: shortsBlockScript, injectionTime: .atDocumentEnd, forMainFrameOnly: false)
        config.userContentController.addUserScript(script)
        let wv = WKWebView(frame: .zero, configuration: config)
        wv.customUserAgent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
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
            if let url = action.request.url, url.path.hasPrefix("/shorts") {
                model.goHome()
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

struct ContentView: View {
    @State private var model = WebViewModel()

    var body: some View {
        ZStack(alignment: .top) {
            VStack(spacing: 0) {
                YouTubeWebView(model: model)
                    .ignoresSafeArea(edges: .top)

                toolbar
            }

            if model.isLoading {
                ProgressView()
                    .progressViewStyle(.linear)
                    .tint(.red)
                    .frame(maxWidth: .infinity)
                    .padding(.top, 55)
            }
        }
    }

    private var toolbar: some View {
        HStack(spacing: 0) {
            toolbarButton("chevron.left", enabled: model.canGoBack) {
                model.webView.goBack()
            }
            toolbarButton("chevron.right", enabled: model.canGoForward) {
                model.webView.goForward()
            }
            toolbarButton("house.fill", enabled: true) {
                model.goHome()
            }
            toolbarButton("arrow.clockwise", enabled: true) {
                model.webView.reload()
            }
        }
        .frame(height: 52)
        .background(.bar)
        .overlay(alignment: .top) {
            Divider()
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
