# NoShorts

An iOS app that wraps YouTube in a `WKWebView` and blocks all Shorts content — navigation, feed shelves, and autoplay.

## Features

- **Shorts blocking**: removes Shorts tab, home feed shelf, and all `/shorts/` links from the DOM
- **Autoplay blocked**: JS interceptor only allows `video.play()` within 1.5s of a user tap
- **SPA navigation guard**: intercepts `pushState`/`replaceState` to prevent in-app Shorts navigation
- **Session timer**: 30-minute countdown badge (top-right); turns orange at 5min, red at 1min, exits at 0
- **Search bar**: tap the magnifying glass to expand an animated inline search field
- **Toolbar**: back, forward, search, home, reload
- **Google sign-in**: works natively in-app (no Safari handoff required)

## Requirements

- macOS with Xcode 16+
- iOS 18+ device or simulator
- Apple ID (free tier sufficient for personal sideloading)

## Setup

1. Open `NoShorts.xcodeproj` in Xcode
2. Select your team under **Signing & Capabilities** → your Apple ID
3. Connect your iPhone and select it as the run destination
4. Hit **Cmd+R** to build and install

## How It Works

Two `WKUserScript` injections run on every page:

**`atDocumentStart` (`earlyScript`)**:
- Injects CSS to hide Shorts elements before first paint (`.pivot-shorts`, `ytm-shorts-lockup-view-model`, etc.)
- Intercepts `HTMLVideoElement.prototype.play()` — blocked unless called within 1.5s of a user touch/click
- Intercepts `history.pushState`/`replaceState` to drop any navigation to `/shorts`
- Removes `window.webkit` for `accounts.google.com` only, so Google's sign-in flow doesn't detect WKWebView

**`atDocumentEnd` (`shortsBlockScript`)**:
- DOM removal of all Shorts-related elements
- Debounced `MutationObserver` (300ms) re-runs removal as YouTube's SPA loads new content

`WKNavigationDelegate` also intercepts full-page navigations to `/shorts` and redirects home.

## Architecture Notes / Gotchas

### Why mobile user agent?
YouTube's mobile site (`m.youtube.com`-style layout via user agent) renders more predictably in WKWebView than the desktop site. The app uses a standard iPhone Safari UA.

### Why `@Observable` instead of `ObservableObject`?
Swift 6 strict concurrency prevents `@MainActor` classes from conforming to `ObservableObject`. Using `@Observable` macro with `@ObservationIgnored` on the `WKWebView` property sidesteps the issue cleanly.

### Why `atDocumentStart` for CSS injection?
Injecting CSS before paint prevents the Shorts shelf from flickering in before the DOM removal JS runs. Both scripts run together — CSS hides immediately, JS removes the nodes.

### Why debounced `MutationObserver` instead of `setInterval`?
`setInterval` at 800ms caused page freezes on YouTube's heavy SPA. A debounced (300ms) `MutationObserver` fires only when the DOM actually changes and doesn't block the main thread.

### Google sign-in in WKWebView
Google detects WKWebView via `window.webkit` and blocks sign-in with a "browser not supported" error. Removing `window.webkit` (scoped to `accounts.google.com` only) makes it appear as Safari. Cookies stay in the WKWebView jar — no `SFSafariViewController` needed.

### Discovering actual mobile YouTube element names
YouTube's mobile DOM uses custom elements not documented anywhere (`ytm-shorts-lockup-view-model`, `ytm-pivot-bar-renderer`, etc.). To discover them, inject `document.querySelectorAll('*')` filtered to custom elements via `evaluateJavaScript` with a Swift completion handler — `console.log` output is not accessible from Swift.

### Xcode project settings
- `SDKROOT` must be `iphoneos`, not `auto` — `auto` resolves to macOS SDK and breaks `UIViewRepresentable`
- `SUPPORTED_PLATFORMS` must exclude `macosx` and `xros` for the same reason
- For devices running iOS newer than Xcode's symbol cache: disable "Debug executable" in scheme to avoid `dyld_shared_cache_extract_dylibs` error

### Autoplay interception
`mediaTypesRequiringUserActionForPlayback = .video` alone is insufficient — YouTube's player works around it. The JS-level `HTMLVideoElement.prototype.play()` override is the reliable fix. The 1.5s window after a touch/click allows legitimate user-initiated plays (including tap-to-play on feed thumbnails).
