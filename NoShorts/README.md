# NoShorts

An iOS app that wraps YouTube in a `WKWebView`, blocks all Shorts content (navigation, feed shelves, autoplay), and lands on the Subscriptions feed instead of the algorithmic home page.

## Features

- **Shorts blocking**: removes Shorts tab, home feed shelf, and all `/shorts/` links from the DOM
- **Subscriptions as default landing**: app launches into `/feed/subscriptions`. Any navigation to `/` (algorithmic home feed) — including the Home button and the YouTube logo — is rewritten back to Subscriptions, in the navigation delegate and the SPA `pushState`/`replaceState` interceptors.
- **Autoplay blocked**: JS interceptor only allows `video.play()` within 1.5s of a user tap
- **SPA navigation guard**: intercepts `pushState`/`replaceState` to prevent in-app Shorts navigation and to rewrite home → subscriptions
- **Session timer**: 30-minute countdown badge (top-right); turns orange at 5min, red at 1min, exits at 0
- **Search bar**: tap the magnifying glass to expand an animated inline search field
- **Toolbar**: back, forward, search, home (→ Subscriptions), reload
- **Google sign-in**: works natively in-app (no Safari handoff required)
- **DNS bypass**: in-app DoH proxy lets WKWebView reach `youtube.com` even when system DNS (e.g. NextDNS) blocks it — used to block YouTube in Chrome while keeping it accessible here

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
- Intercepts `history.pushState`/`replaceState` to drop any navigation to `/shorts` and rewrite navigations to `/` (home) → `/feed/subscriptions`
- Removes `window.webkit` for `accounts.google.com` only, so Google's sign-in flow doesn't detect WKWebView

**`atDocumentEnd` (`shortsBlockScript`)**:
- DOM removal of all Shorts-related elements
- Debounced `MutationObserver` (300ms) re-runs removal as YouTube's SPA loads new content

`WKNavigationDelegate` also intercepts full-page navigations to `/shorts` (→ Subscriptions) and to `/` or empty paths on `*.youtube.com` (→ Subscriptions).

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

## Block-YouTube-in-Chrome Setup (DNS bypass)

The goal: YouTube blocked in Chrome (and Safari, and every other browser on the device), but still accessible inside this app.

### Why this is hard on iOS
- Chrome on iOS has no extensions and no per-site content blocking
- Screen Time's "Never Allow" list requires "Limit Adult Websites" enabled, which has collateral damage
- DNS-level blocking (NextDNS, Pi-hole, etc.) is system-wide — it affects WKWebView too, since WKWebView runs in a separate process and uses system DNS
- iOS has no per-app DNS routing on a free developer account (`NEAppProxyProvider` requires paid entitlements)

### How this app works around it
1. **System level**: install [NextDNS](https://nextdns.io) as a **DNS profile** and add `youtube.com` (+ subdomains) to the deny list. This blocks YouTube in Chrome, Safari, and any other browser. Full setup steps below.
2. **App level**: this app runs an **in-process HTTP CONNECT proxy** on `127.0.0.1`. The proxy resolves hostnames via **DoH** (`https://dns.google/dns-query`) instead of system DNS, so it returns YouTube's real IP regardless of NextDNS filtering.
3. **WKWebView wiring**: `WKWebsiteDataStore.proxyConfigurations` (iOS 17+) points the web view at the local proxy. All TLS traffic is tunneled through it.

### NextDNS setup (full instructions)

**1. Create a NextDNS account**
- Go to [nextdns.io](https://nextdns.io) and sign up (free tier is sufficient — 300K queries/month per profile)
- A new "config" is created automatically with a random ID like `abc123`

**2. Configure the denylist**
- In the NextDNS dashboard, open your config → **Denylist** tab
- Add each of these entries (one per line):
  - `youtube.com`
  - `www.youtube.com`
  - `m.youtube.com`
  - `youtu.be`
  - `youtubei.googleapis.com` (optional — blocks the YouTube app's API; only add if you want to also kill the native YouTube app)
- NextDNS does **not** auto-block subdomains, so list the variants explicitly. Wildcards aren't supported in the basic denylist.

**3. Install the NextDNS profile on iOS**

Two options — pick one.

*Option A: NextDNS iOS app (easiest)*
- Install **NextDNS** from the App Store
- Open the app, sign in with your NextDNS account (or paste your config ID)
- Tap the big toggle to enable. iOS will prompt to install a DNS profile — tap **Allow**, then go to Settings and confirm install (Face ID / passcode)
- Verify in Settings → General → **VPN & Device Management** → **DNS** — NextDNS should show as the active DNS profile

*Option B: Configuration profile (no app)*
- In the NextDNS dashboard → **Setup** tab → **iOS** section → tap **Download Configuration Profile**
- Open the downloaded `.mobileconfig` on the iPhone, install via Settings prompt
- Same end result; doesn't install an app

**4. Verify NextDNS is active**
- Settings → General → VPN & Device Management → DNS → should list NextDNS (not "Automatic")
- Open Chrome/Safari → navigate to `youtube.com` → expect a "This site can't be reached" / DNS-failure error
- Open NextDNS dashboard → **Logs** tab → you should see blocked queries for `youtube.com`

**5. Verify the NoShorts app still works**
- Launch this app — it should load YouTube successfully despite the system-wide block
- If it doesn't, check Console.app (with iPhone connected) for `LocalProxy:` log lines:
  - `LocalProxy listening on 127.0.0.1:NNNNN` — proxy started successfully (port should be > 0)
  - `LocalProxy: incoming connection` — WKWebView reached the proxy
  - `LocalProxy: CONNECT www.youtube.com:443 -> <ip>` — DoH resolved the host

**Troubleshooting**
- **YouTube loads in Chrome too**: NextDNS not active, or denylist not saved. Re-check step 4.
- **App shows blank page**: proxy didn't bind (check logs for port 0 or `listener failed`); reinstall app.
- **App loads YouTube but Chrome also loads it**: device might be on cellular with no NextDNS rules for cellular profile — set up the same NextDNS config for cellular in NextDNS dashboard → **Settings** → **iOS** → enable for both Wi-Fi and cellular.

### Components
- [`DoHResolver.swift`](NoShorts/DoHResolver.swift) — minimal DNS-over-HTTPS client, raw DNS wire format over `URLSession`. Handles A records with TTL caching.
- [`LocalProxy.swift`](NoShorts/LocalProxy.swift) — `NWListener` HTTP CONNECT proxy. Parses `CONNECT host:port`, resolves via DoH, opens an `NWConnection` to the IP, tunnels bytes both ways.
- [`ContentView.swift`](NoShorts/ContentView.swift) — starts the proxy on `WebViewModel.init()` and assigns `WKWebsiteDataStore.default().proxyConfigurations = [ProxyConfiguration(httpCONNECTProxy:)]`.

### Why DoH bypasses NextDNS
NextDNS as a DNS profile reroutes the system DNS resolver. But it does **not** intercept arbitrary HTTPS traffic. A POST to `https://dns.google/dns-query` is just regular HTTPS — the request body happens to contain a DNS wire-format query. NextDNS sees an HTTPS connection to `dns.google`, not a DNS query, so it doesn't filter the response.

### Threat model (what this does and doesn't defend against)
- ✅ Defends against: typing `youtube.com` in Chrome, clicking a YouTube link in any other app, tapping the YouTube app's web bridge
- ❌ Does not defend against: someone with the device disabling NextDNS in Settings, or installing a different browser, or using cellular data with the NextDNS profile only configured for Wi-Fi
- This is a self-control tool, not a hardened parental control. Determined bypass is trivial. The friction is the point.

### Why not Network Extension / `NEAppProxyProvider`?
Per-app VPN via `NEAppProxyProvider` would be the textbook iOS solution. It requires `com.apple.developer.networking.networkextension` with `app-proxy-provider`, which is gated behind a **paid** Apple Developer account ($99/yr). The DoH-proxy-in-app approach above achieves the same outcome on a free account.

### Why DoH (DNS wire format), not DoH (JSON)?
Google's DoH endpoint accepts both `application/dns-message` (RFC 1035 wire format) and `application/dns-json`. Wire format is ~50 bytes vs JSON's ~500 bytes per query, and avoids JSON parsing of arbitrary RDATA.

### Why HTTP CONNECT, not full HTTP proxy?
WKWebView using `proxyConfigurations` sends `CONNECT host:443` for HTTPS targets and tunnels TLS verbatim afterward. Since YouTube is HTTPS-only, supporting only CONNECT is sufficient. Plain HTTP requests (which would arrive without CONNECT) get a `405 Method Not Allowed`.
