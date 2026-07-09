# NoShorts V2 — pre-PRD scoping draft (ARCHIVE)

Preserved for history 2026-07-09 (formerly `~/.claude/plans/noshorts-v2-plan.md`, the working draft
that evolved into [V2_PRD.md](V2_PRD.md)). Superseded; see [V2_REMEDIATION_PLAN.md](V2_REMEDIATION_PLAN.md) for the current state.


Session mode: **iterate the plan until every open question is answered. No code until the plan is settled.**

## 0. Diagnostic finding that reshapes everything (2026-07-07)

Ran a simulator experiment: took V1's `ContentView.swift`, stripped out the `LocalProxy` setup entirely, loaded `https://www.youtube.com/watch?v=jNQXAC9IVRw` directly in the WKWebView. On iOS 26.5.2 Simulator (iPhone 17 Pro), the watch page loaded fully — video preview, title, uploader, view count, comments, related videos, all rendered normally. V1 could never get to this state on-device.

**Reinterpretation of the whole V1 saga:** V1's on-device failure was not FairPlay DRM, not Apple-only entitlements, not third-party WKWebView being fundamentally locked out of YouTube. **It was the LocalProxy configuration interacting badly with iOS 26.5.2's outbound-TCP handling.** Remove the LocalProxy, WKWebView plays YouTube like it always did.

The `Playback ID` error I saw when I forced autoplay in that same experiment is expected — YouTube's player refuses to autoplay content that wasn't triggered by a user gesture, in every browser. Not evidence of anything blocking us.

**Which means V2 is not a rewrite. V2 is V1 minus the LocalProxy.**

The Piped / yt-dlp / AVPlayer detour I was exploring earlier is no longer needed. The V1 UI was fine. The V1 WKWebView-plays-YouTube pattern was fine. The only architectural mistake was routing traffic through a local `NWConnection`-based proxy for DNS purposes when iOS 26.5.2 doesn't tolerate that.

## 0a. Revised V2 architecture

- V1's SwiftUI shell stays: playlist-first home, session timer, orientation lock, hide-shorts JS, chevrons, search bar, everything.
- **Delete `LocalProxy.swift` and `DoHResolver.swift` in their entirety.** WKWebView gets a plain default `WKWebsiteDataStore` — no proxy configuration.
- **Move the DNS bypass responsibility to the phone level**, off the app. The app assumes DNS resolves cleanly for `*.youtube.com` and everything else. How that resolution happens is a phone-level configuration concern, not an in-app one.
- Add `config.allowsInlineMediaPlayback = true` (confirmed useful for consistent inline playback).
- Keep the existing user scripts (early script's autoplay wrapper, shorts hiding, video event script, pushState guard).

## 0b. New primary open question

**Q11: how do we bypass NextDNS's `*.youtube.com` deny at the phone level, off the app?** Options, ranked by simplicity:

1. **`.mobileconfig` configuration profile installed via iOS Settings.** Standard Apple mechanism. Says: "for `*.youtube.com`, use dns.google DoH; for everything else, use whatever the phone's set to." Zero code. Cross-app: Safari benefits too, which is a nice side-effect. Install once via mail attachment or served over HTTPS. My default: this.
2. **A tiny companion iOS app that installs a `NEDNSSettingsManager` DoH profile.** Same effect but managed by an app on the phone. Needs the `com.apple.developer.networking.custom-dns` entitlement, which Apple sometimes gates for personal apps.
3. **Adjust NextDNS itself** to exempt the phone from the `*.youtube.com` block. Simplest of all, but only works if we're OK letting all traffic on that phone see YouTube.
4. **A DNS proxy `NEPacketTunnelProvider`** app. Heavier than #2, more control.

I strongly recommend #1 (`.mobileconfig`) — it's the least code, most standard, and Apple-supported. If it works on-device with your NextDNS setup, V2 is done: install the profile, run V1 with the LocalProxy code deleted.

## 0c. Remaining unknowns / risks

- **On-device confirmation.** Simulator uses the Mac's DNS, so we haven't proven the `.mobileconfig` approach works with NextDNS active on the phone. This is testable in one session with a physical device.
- **NextDNS on Amit's phone may itself be a DNS profile.** If so, iOS DNS profile priority rules apply — the most-recently-installed profile might win, or system might allow multiple domain-scoped profiles to compose. We won't know without trying.
- **We haven't confirmed video actually plays end-to-end in simulator.** Only that the watch page renders and the video preview appears. Simulator's HTML5 video / HLS support has known quirks. Real proof requires on-device testing. But if V1 played briefly-then-errored on-device (which it did), the mechanism is basically there.

## 0d. If Q11 solution works — reduced V2 scope

MVP becomes trivially small:

1. Delete `NoShorts/NoShorts/LocalProxy.swift`.
2. Delete `NoShorts/NoShorts/DoHResolver.swift`.
3. Edit `NoShorts/NoShorts/ContentView.swift` to remove the `proxy` property and its start-plus-config block. Add `config.allowsInlineMediaPlayback = true`.
4. Craft a `noshorts.mobileconfig` that scopes `dns.google` DoH to `*.youtube.com` only.
5. Install profile on Amit's phone.
6. Install V2 on Amit's phone (fresh bundle ID `com.deviationlabs.NoShortsV2` to coexist with V1 for A/B comparison, then swap once confirmed).
7. Verify.

That's an afternoon, not a project. Everything in §5 (must-have MVP: playlists-home, hide shorts, session timer, orientation lock) is already there in V1 code — we're just stripping the broken proxy layer.

---

**Everything below this line is the previous plan draft, kept for reference. All the Piped / yt-dlp / self-host discussion is moot now that we know the actual problem was the LocalProxy configuration.**

## 1. Why V2 exists

V1 is architected as WKWebView-hosts-YouTube-mobile-web + local DoH proxy to bypass NextDNS deny of `*.youtube.com`. This pattern:

- Depends on WKWebView successfully playing YouTube's HLS+FairPlay-protected content, which requires entitlements only Safari holds.
- Broke on iOS 26.5.2 in a way that also blocks non-Google outbound TCP from the app entirely.
- Cannot be fixed at the app layer — Apple has been squeezing this pattern shut across iOS releases.

V2 abandons the "wrap YouTube web" pattern. It talks to YouTube's actual media pipeline itself and plays with `AVPlayer`. The playback path becomes: our code → YouTube extractor → DASH/HLS URL → AVPlayer. No WKWebView in the media path.

## 2. Constraints and hard truths I'm assuming (please confirm/correct)

- **Users**: right now, one — Amit. Not a public product. Not App Store. Dev-signed / TestFlight scope only.
- **Devices**: iPhone (13 Pro was in this session). iOS 26.5.2+. No need for iPad-optimized layout, tvOS, or macOS Catalyst — unless corrected.
- **DRM**: V2 will *not* support DRM'd content. YouTube premium requires Widevine or FairPlay handshake we cannot provide as a third-party app. Public/unencrypted content only. This is an accepted limitation.
- **Ads**: because we're going direct to media segments, we skip the ad pipeline entirely. Not accidentally — deliberately, and this is a feature.
- **Google sign-in**: needed for personalized data (subscriptions, Watch Later, Likes). But signing in through a third-party client is itself detectable by Google and gets accounts flagged/blocked. This is a hard tradeoff.
- **Legal / TOS**: this pattern (extractor-based YouTube client) violates YouTube TOS. All open-source alternatives operate in this same gray zone. Not distributed to App Store. Amit accepts this.

## 3. Big architectural fork — must be decided first

**Option A — Direct extraction (SmartTubeIOS-style):**

App itself talks to YouTube's servers, parses player configs, extracts DASH manifest URLs, feeds AVPlayer.

- Pro: fully self-contained. No dependency on anyone else's server. Works everywhere with just an internet connection.
- Con: YouTube changes their extractor-facing surface every few weeks. Someone (Amit) has to patch. This is the well-known "extractor treadmill."
- Con: age-gated content, live streams, signed URLs, throttling, PoT (Proof-of-Origin Token) checks — each is its own workstream.

**Option B — Backend proxy (Yattee-style, Piped/Invidious):**

App calls out to a Piped or Invidious server (hosted by community or self-hosted) which does the extraction and returns clean URLs / manifests. App plays the result with AVPlayer.

- Pro: extractor maintenance is someone else's problem.
- Pro: consistent API surface. Client code stays small and clean.
- Con: dependence on external service — public instances get rate-limited, go down, or ban traffic.
- Con: adds ~10–20ms latency to every request.
- Con: if we self-host, that's a whole ops surface (backend infra, SSL, uptime).

**Option C — Hybrid:**

Try direct extraction first; fall back to a configured Piped/Invidious backend on extractor failure. Best of both, most complex.

**Decision needed from Amit:** A, B, or C? My default recommendation is **B (Yattee-style, Piped backend)**. Reasons:

- Amit already has a track record of maintaining IoT projects (homely_vibes). Adding "keep YouTube extractor working" to that list is real burden.
- The whole session today shows Amit values *working* over *perfectly-architected-but-fragile*.
- Piped is stable enough that Yattee ships on the App Store using it.
- If Piped instances start being untrustworthy, we can self-host one — it's a well-documented Docker deploy.

If Amit prefers self-hosting the extraction: pick B and plan to run a personal Piped instance.

## 4. Fork existing app vs. start from scratch

**Option 1 — Fork SmartTubeIOS:**

Clone [milika/SmartTubeIOS](https://github.com/milika/SmartTubeIOS). Rebrand. Delete features we don't want. Add NoShorts's opinionated behavior (shorts hiding, playlist-first home, 30-min session timer).

- Pro: shortest path to working. Days, not weeks.
- Pro: SmartTubeIOS already handles extraction, AVPlayer wiring, SponsorBlock, quality picker, subtitles, PIP, background audio, etc.
- Con: inherits their architectural decisions; some may not match what we'd want.
- Con: harder to keep in sync with upstream if we want to pull fixes later. Fork drift.

**Option 2 — Fork Yattee:**

Clone [Yattee](https://github.com/yattee/yattee). Different starting point — assumes Piped/Invidious backend.

- Pro: matches Option B architecture from §3 if that's what we pick.
- Pro: on the App Store, so proven distribution model.
- Con: more feature-heavy than we want; feels heavier.

**Option 3 — Build from scratch:**

New Xcode project. Pull in libraries as needed (extractor, player).

- Pro: exact fit to NoShorts's product spec.
- Pro: no accidental inherited complexity.
- Con: weeks. Every capability (subtitles, PIP, background, quality picker) has to be built.

**Decision needed:** 1, 2, or 3? My recommendation is **Option 1 (fork SmartTubeIOS)** if we pick §3-A (direct extraction), or **Option 2 (fork Yattee)** if we pick §3-B. Not Option 3 — the incremental cost per feature is too high.

## 5. Product spec — what NoShorts V2 IS

Carrying forward from V1's intent, but reduced to what's non-negotiable:

**Must-have MVP:**

- Sign in with Google, browse your subscribed channels.
- Play videos in `AVPlayer` (no WKWebView involved in playback).
- Home screen defaults to Playlists (not Trending).
- Shorts are hidden across the app.
- 30-minute session timer — app becomes unusable after that until next launch.
- Landscape lock rotates on play, portrait on pause/end.

**Nice-to-have V2.1:**

- Watch Later playlist support.
- Search.
- Subtitles.
- Playback speed control.
- Background audio (locked screen, other apps).

**Explicitly deferred / cut:**

- iPad-optimized layout.
- Apple TV.
- Live streams.
- Comments.
- Ad support (deliberately none).
- DRM content playback.
- Downloading videos for offline.

Amit confirm the MVP list matches your intent.

## 6. Open technical questions I need answered before scaffolding

**Extraction / networking:**

1. If §3-A: which extractor library will we use? Options: (a) invoke SmartTubeIOS's built-in extractor, (b) port NewPipeExtractor from Java, (c) embed [yt-dlp](https://github.com/yt-dlp/yt-dlp) via a shell / Python — probably not viable on iOS.
2. If §3-B: use a public Piped instance, self-host one, or a fallback list?
3. Handle "YouTube rate-limits our IP" gracefully — what's the UX?
4. Handle "video is age-gated / region-locked" — surface error or silently skip?

**Auth:**

5. Google sign-in via OAuth requires a WebView-based flow at some step (Google's own sign-in page). Are we OK with a one-shot WKWebView JUST for sign-in? Or do we go anonymous-only and skip subscriptions?
6. If signing in: how do we persist credentials? iOS Keychain, standard OAuth refresh flow.

**Player:**

7. AVPlayer + HLS: which quality tiers matter? 720p enough, or need 1080p/4K?
8. Do we need FFmpeg wrapping (KSPlayer style) for exotic codecs, or is AVPlayer alone enough for public YouTube content?
9. Background audio + PIP entitlement — need `UIBackgroundModes` = `audio`.

**UI / design:**

10. SwiftUI (V2 code style) or UIKit (SmartTubeIOS may be UIKit-heavy)?
11. Reuse V1's SwiftUI patterns? (session timer, orientation lock, red-accent design) — these are small and worth pulling forward.

**Distribution / build:**

12. TestFlight / Ad-Hoc / dev-signed only? (Assuming dev-signed until proven otherwise.)
13. Bundle ID — reuse `com.deviationlabs.NoShorts` or new one for V2?
14. Repo layout — new repo, or under homely_vibes as `NoShortsV2/`?

**V1 fate:**

15. What do we do with V1's uncommitted changes on `abutala/noshorts-playback-and-nav-fixes`? Options: (a) commit the two real wins (`allowsInlineMediaPlayback`, `matchDomains`) and ship a small PR that at least de-clunks V1, (b) discard everything, (c) leave the branch dangling forever.
16. Is V1 archived / kept installed as a fallback, or actively deleted from Amit's phone?

## 7. Milestones once questions are answered

- **M0 — Repo scaffold:** decide fork target (SmartTubeIOS or Yattee), clone, get it building locally, run once on device to prove baseline.
- **M1 — Rebrand:** bundle ID, name, launch screen, app icon. Prove the fork installs alongside V1 without conflict.
- **M2 — MVP feature strip:** remove features not in §5's MVP. Add NoShorts's shorts-hiding, playlist-home, session timer, orientation lock.
- **M3 — Ship internally:** installed on Amit's phone via Xcode, used daily for a week.
- **M4 — Iterate on V2.1 features:** subtitles, search, background audio, etc.

Rough calendar (assuming Option 1 fork of SmartTubeIOS + Option B backend):

- M0–M1: 1 weekend.
- M2: 1–2 weekends.
- M3: continuous starting after M2.
- M4: as need arises.

## 8. Risks / kill-switches

- **Extractor treadmill (if we pick A):** if patching becomes >1 hour every two weeks, switch to B.
- **Piped instance untrustworthy (if we pick B):** switch to self-hosted Piped on personal infra.
- **Google account gets flagged for third-party client use (if we sign in):** decide whether to accept anonymous-only mode.
- **iOS 27 tightens further and blocks even native `AVPlayer` from reaching non-Google IPs from third-party apps:** at that point, the app is unsalvageable regardless of architecture. But nothing in the current signals suggests this — the block affects the WKWebView + WebContent pipeline, not raw NWConnection or AVPlayer.

## 9. Questions to Amit — resolve these before I write code

Numbered for easy reply:

1. Direct extraction (A) or Piped-style backend (B) or hybrid (C)? (My default: B.)
2. Fork SmartTubeIOS (1), fork Yattee (2), or from scratch (3)? (My default: 1 if A, 2 if B.)
3. Google sign-in in MVP, or anonymous-first? (My default: anonymous-first for MVP, sign-in for V2.1.)
4. Any features on §5's "must have MVP" list you'd cut or add?
5. What to do with V1's uncommitted changes — commit the two wins as a small PR, or discard?
6. Repo location — under `homely_vibes/NoShortsV2/`, or a new top-level repo?
7. Bundle ID — reuse `com.deviationlabs.NoShorts` (installs on top of V1, replaces it) or new (`com.deviationlabs.NoShortsV2`, coexists)?
8. Anything I've mis-assumed in §2? (One user, iPhone-only, no DRM, no App Store, TOS violation accepted.)

I'll iterate this plan file with each answer. No code until every question here has an answer AND the plan reads self-consistently.
