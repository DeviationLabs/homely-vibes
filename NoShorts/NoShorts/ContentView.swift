//
//  ContentView.swift
//  NoShorts
//

import SwiftUI
import WebKit

private let shortsBlockScript = """
(function() {
    function removeShorts() {
        document.querySelectorAll('ytd-reel-shelf-renderer').forEach(e => e.remove());
        document.querySelectorAll('ytd-rich-item-renderer').forEach(item => {
            if (item.querySelector('a#thumbnail[href*="/shorts/"]')) item.remove();
        });
        document.querySelectorAll('a[href="/shorts"]').forEach(a => {
            (a.closest('ytd-guide-entry-renderer') || a.closest('ytd-mini-guide-entry-renderer'))?.remove();
        });
        document.querySelectorAll('ytd-video-renderer a#thumbnail[href*="/shorts/"]').forEach(a => {
            a.closest('ytd-video-renderer')?.remove();
        });
    }
    removeShorts();
    new MutationObserver(removeShorts).observe(document.body, { childList: true, subtree: true });
})();
"""

@MainActor
final class WebViewModel: ObservableObject {
    let webView: WKWebView

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
}

struct YouTubeWebView: UIViewRepresentable {
    let webView: WKWebView

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: UIViewRepresentableContext<YouTubeWebView>) -> WKWebView {
        webView.navigationDelegate = context.coordinator
        webView.load(URLRequest(url: URL(string: "https://www.youtube.com")!))
        return webView
    }

    func updateUIView(_ uiView: WKWebView, context: UIViewRepresentableContext<YouTubeWebView>) {}

    @MainActor
    final class Coordinator: NSObject, WKNavigationDelegate {
        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction) async -> WKNavigationActionPolicy {
            if let url = action.request.url, url.path.hasPrefix("/shorts") {
                webView.load(URLRequest(url: URL(string: "https://www.youtube.com")!))
                return .cancel
            }
            return .allow
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            webView.evaluateJavaScript(shortsBlockScript)
        }
    }
}

struct ContentView: View {
    @StateObject private var model = WebViewModel()

    var body: some View {
        VStack(spacing: 0) {
            YouTubeWebView(webView: model.webView)
                .ignoresSafeArea(edges: .top)

            Divider()

            HStack {
                Button { model.webView.goBack() } label: {
                    Image(systemName: "chevron.left").frame(maxWidth: .infinity).padding(.vertical, 12)
                }
                Button { model.webView.goForward() } label: {
                    Image(systemName: "chevron.right").frame(maxWidth: .infinity).padding(.vertical, 12)
                }
                Button { model.load("https://www.youtube.com") } label: {
                    Image(systemName: "house").frame(maxWidth: .infinity).padding(.vertical, 12)
                }
                Button { model.webView.reload() } label: {
                    Image(systemName: "arrow.clockwise").frame(maxWidth: .infinity).padding(.vertical, 12)
                }
            }
            .background(Color(.systemBackground))
        }
    }
}

#Preview {
    ContentView()
}
