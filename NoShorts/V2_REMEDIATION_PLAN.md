# NoShorts — Playback Remediation Plan (iOS 26.5.2)

Date: 2026-07-09 · Author: Claude Code · Owner: Amit · **Status: RESOLVED — see §3a (playback restored on iOS 26.5.2)**
Moved into the repo 2026-07-09 (formerly `~/.claude/plans/noshorts-v2-plan.md`) so history rides with the code.
Predecessor scoping draft: [`V2_SCOPING_ARCHIVE.md`](V2_SCOPING_ARCHIVE.md). Companion: [`V2_PRD.md`](V2_PRD.md).

## TL;DR — the thesis has changed

`V2_PRD.md §8` concluded "iOS 26.5.2 blocks outbound TCP from third-party WKWebView app bundles"
and shelved V2. **Re-reading the session evidence (console screenshots) contradicts that conclusion.**
The dominant failure signal is `Connection reset by peer` — a **remote** RST arriving *after* the TCP
tunnel was established and data flowed. An OS sandbox gate would refuse connections locally
(no SYN / EPERM-style errors); it would not serve you a few seconds of video and then RST from the peer.

The most likely root cause is **Google server-side enforcement** (SABR-only streaming + per-video
PoToken attestation, actively rolling out to web clients in 2025–2026 — see References), which is
known to kill media streams after initial bytes for clients that fail attestation. NoShorts trips it because:

- it pins a **fake Safari iOS 17.0 UA** (2023-era) on a real iOS 26.5 WebKit — a contradiction bot-scoring sees;
- it **tampers with `HTMLVideoElement.prototype.play`** and hides `window.webkit` — prototype tampering is BotGuard-visible;
- "ads play, content doesn't" is the classic PoToken-enforcement signature (ad serving has separate attestation);
- the break "**feels like it recently started**" while the app was unchanged — server-side rollouts do that; OS updates don't retroactively break an untouched app *sometimes*.

The plan: **do not write remediation code yet.** Run Phase 0 (half a day of decisive diagnostics),
which cleanly separates the three competing theories, then execute the matching track.

## 1. Evidence inventory

| # | Observation | Source |
|---|-------------|--------|
| E-a | V1 (proxy-everything): CONNECT tunnels to `manifest.googlevideo.com` on **Google-owned IPs (142.251.x) succeed** | screenshot 2026-07-06T18:42 |
| E-b | V1: tunnels to `rr*---sn-*.googlevideo.com` **ISP GGC edges (68.105.28.x) get `recvmsg failed [54: Connection reset by peer]` mid-tunnel** — established, data flowed, then remote RST | same |
| E-c | V1 UX: video plays **a few seconds, subtitles render**, then dies. Subtitles come from `youtube.com/api/timedtext` (proxied, works); media dies mid-stream | Amit, 2026-07-09 |
| E-d | V2 (matchDomains-scoped): **ads play, preview loads**, player spins, "An error occurred". Zero googlevideo CONNECTs (scoping worked) | PR #231 test plan; screenshot 2026-07-08T22:07 |
| E-e | V2 second video, same session: `Socket SO_ERROR [54: Connection reset by peer]` on the **youtube.com** tunnel to 142.251.218.238 — same IP that worked minutes earlier. "Network is down" is the teardown error *after* the RST | screenshot 2026-07-08T22:09 |
| E-f | Same failure on Comcast Wi-Fi and cellular (different edges) | PRD App. A |
| E-g | Simulator, no proxy, Mac DNS: watch page renders fully | PRD App. B |
| E-h | Both V1 and V2 pin `customUserAgent` = Safari **iOS 17.0** (identical string). PRD notes bumping it to iOS 26 made failure *immediate* instead of after ~2 s | ContentView.swift (pre-596a9fa), PRD App. A |
| E-i | Worked on iOS 26.0; broken on 26.5.2. But also "feels like it recently started" with app unchanged | Amit |
| E-j | No public reports of an iOS 26.5 WKWebView `proxyConfigurations` lockdown (searched 2026-07-09). A platform gate on WebView outbound TCP would break Chrome/Firefox iOS (both WKWebView) — no such reports either | web search |
| E-k | YouTube web client is now SABR-only (adaptive-format URLs removed from player response) with per-video PoToken experiments — yt-dlp/YouTube.js communities hit this through 2025–2026 | yt-dlp #12482, #13968; YouTube.js #724 |

## 2. Theories, ranked

**T1 — Google server-side enforcement (SABR/PoToken/bot-score). LIKELY.**
Explains E-b/E-c (stream killed after initial bytes), E-d (ads attested separately), E-e (IP/session
reputation escalates within a session), E-f (IP-independent), E-i ("recently started"), E-k (documented
rollout). The E-h UA experiment reads as: UA selects which player stack YouTube serves — iOS 26 UA →
SABR-only → fails at start; iOS 17 UA → legacy URLs → served, then enforcement kills the stream.
*Kill criterion: signed-in + honest-UA + untampered build still RSTs AND Web Inspector shows no 403s.*

**T2 — iOS 26.5.2 `proxyConfigurations` regression poisons the whole WebContent networking path. POSSIBLE.**
Would explain why the app broke "at" the OS update. Weakened by E-d (ads stream fine direct from
googlevideo in the same WebContent process) and E-j. Cannot explain E-c's few-seconds-then-RST shape.
*Kill criterion: control build with zero proxy config still fails identically.*

**T3 — iOS app-bundle outbound-TCP sandbox gate (the PRD §8 conclusion). MOSTLY DEAD.**
Contradicted by E-a (some googlevideo tunnels succeed), E-b/E-e (remote RSTs, not local refusals),
E-d (ads stream), E-j (would be world-breaking news). Keep only as the fallback explanation if
Phase 0 shows connections failing with **no SYN on the wire**.

## 3. Phase 0 — decisive diagnostics (half a day, mostly no code)

Run in order; each step's outcome prunes the tree.

**D0. Make the WebView inspectable (1 line, biggest payoff).**
`webView.isInspectable = true` in `ContentView.swift` (debug builds). Enable Web Inspector on the
phone (Settings → Safari → Advanced). Mac Safari → Develop → iPhone → NoShorts. Reproduce the failure
and read the **HTTP status codes of the failing googlevideo requests** and the player's JS console.
- `403` (or `429`) on media segments → **T1 confirmed.** Go to Track A.
- Requests die with generic network errors, no HTTP response → T2/T3 still alive → D1.

**D1. Packet capture via rvictl (no app change).**
`rvictl -s <device-udid>` on the Mac, `sudo tcpdump -i rvi0 -w noshorts.pcap`, reproduce, open in Wireshark.
For the failing googlevideo flows check: Is there a SYN? Does TLS complete? How many bytes before RST,
and **who sends the RST** (direction)?
- SYN → TLS → data → RST *from server* → **T1.**
- No SYN ever leaves the phone → local block → **T3** (PRD was right after all; go to Track C).
- SYN leaves, no SYN-ACK / RST injected at low TTL → middlebox/ISP weirdness (unlikely; note and continue).

**D2. Signed-in retry (5 min, no code).**
Sign into the Google account inside NoShorts, replay the same video. Enforcement is materially laxer
for signed-in sessions. Any improvement is a T1 fingerprint.

**D3. Control build — pristine WebView (30 min).**
Temporarily remove from NextDNS the `youtube.com` deny (my.nextdns.io, remember to restore).
Build variant with: **no proxy config, no customUserAgent, no injected scripts.** Just a WKWebView
loading a watch page.
- Plays → the app environment is the trigger → bisect one axis at a time: (1) add back UA-pin,
  (2) add back `earlyScript`, (3) add back proxy w/ matchDomains. The first re-added piece that
  breaks playback is the offender. T1 vs T2 resolved precisely.
- Doesn't play even pristine → T2 eliminated too; re-test in Chrome iOS (D4).

**D4. Third-party browser control (5 min, while NextDNS allow is still on).**
Chrome or Firefox iOS on the same phone (both are WKWebView shells) → youtube.com → play.
- Plays → T3 is dead permanently, on the record.
- Fails the same way → something device-wide (NextDNS profile interaction, Screen Time, network) — re-examine assumptions.

**Exit artifact:** update `V2_PRD.md §8` with the Phase-0 verdict.

## 3a. PHASE-0 VERDICT (2026-07-09) — T1 confirmed, T3 disproven

Ran D0 (Web Inspector via `isInspectable`, branch `abutala/noshorts-diag-inspectable`):

- `manifest.googlevideo.com` m3u8 fetches: h2, direct from WebContent, succeed continuously → no OS TCP block. **T3 dead.**
- `rr12---sn-*` seg.ts fetches: http/1.1, first few succeed (up to 162 KB), then all fail in 1–42 ms.
  One inspected failure: **HTTP 200 + full headers (`Server: gvs 1.0`), zero body** — server killed the stream mid-response.
- Segment URLs carry **no `pot=`** and **`playerfallback/1`**, on a **signed-in** session (D2 moot — V1 cookies persisted; login does not fix it).
- Protocol column shows no h3 anywhere → QUIC theory dead.

→ Google-side stream enforcement. Track A executed: commit `596a9fa` (honest UA via
`applicationNameForUserAgent`, earlyScript stripped to CSS-only).

**RESULT (2026-07-09, on-device, NextDNS active): PLAYBACK RESTORED. ✅**
A1 alone fixed it — no player-surface change (A2), no off-device proxy (A3), no extractor (A4) needed.
Root cause confirmed: YouTube stream attestation reacting to the fake iOS-17 UA + BotGuard-visible JS
tampering, not any iOS networking change. `V2_PRD.md §8` amended accordingly.
Follow-up: [#232](https://github.com/DeviationLabs/homely-vibes/issues/232) — restore /shorts SPA guard
+ autoplay gesture-gate Swift-side (attestation-safe), and the sign-in `window.webkit` hide if a fresh
login ever needs it.

## 4. Remediation tracks

### Track A — T1 confirmed (Google enforcement). Goal: pass attestation like a normal browser.
Ordered by effort; stop at the first one that works.

1. **A1 — Stop masquerading.** Drop the iOS-17 UA pin (use the real WebKit UA, optionally via
   `applicationNameForUserAgent` to keep the Safari token with the *true* OS version). Remove the
   `window.webkit`-hiding hack and the `HTMLVideoElement.prototype.play` wrapper (autoplay control is
   already provided natively by `mediaTypesRequiringUserActionForPlayback = .video` — test whether the
   wrapper is actually needed on iOS 26; its "load-bearing" claim dates from the broken-proxy era).
   Keep CSS/DOM shorts-hiding (cosmetic, low bot-score risk). Test signed-in.
2. **A2 — Switch player surface.** If A1 insufficient: try `m.youtube.com` as mweb, and the
   `/embed/<id>` player (different client IDs, different enforcement tiers).
3. **A3 — Off-device CONNECT proxy on the home Linux box.** Point `proxyConfigurations` at a proxy on
   the prod host (LAN + Tailscale for cellular) instead of loopback; the host resolves DNS itself
   (NextDNS bypass intact, G2 intact — only NoShorts is configured; egress stays residential so no
   IP-reputation hit). Also fully de-risks any loopback-proxy interplay (helps T2 as a bonus).
   ~50 lines of config (tinyproxy/squid), zero new Swift beyond the endpoint.
4. **A4 — Self-hosted extractor (last resort).** `yt-dlp` + PoToken provider (bgutil) behind a small
   HTTP API on the home box; app plays via AVPlayer or a minimal page. Note the SABR client
   implementations now exist in the open (YouTube.js `SabrStream`), so this path is viable but is the
   ops treadmill the PRD explicitly deprioritized. Requires Amit to sign up for maintenance.

### Track B — T2 confirmed (proxyConfigurations poison).
1. **B1 = A3** (off-device proxy) — removes the loopback proxy while keeping per-app scoping. First choice.
2. **B2 — Device-wide DoH `.mobileconfig`** scoped override (PRD Tier 4). Defeats G2 — Safari gets
   YouTube back too. Honest fallback; Amit's call. (Verify a DNSSettings payload can actually scope
   per-domain before promising this — flagged unverified.)
3. **B3 — `NEDNSProxyProvider`** with `sourceAppSigningIdentifier`-based per-app answers. Verify first
   whether DNS-proxy extensions activate on unsupervised personal devices — historically MDM-only,
   which would kill this. Don't start code before that check.

### Track C — T3 confirmed (real OS gate; PRD §8 stands).
Shelve per PRD §8 re-attempt triggers. A3/A4 remain the only workarounds (traffic terminating at a
home host looks like plain HTTPS and dodges whatever gate exists). Re-check at each iOS point release.

## 5. Recommended sequence

1. D0 + D2 in one build/session → likely verdict same afternoon. ✅ done — see §3a.
2. If 403s: A1 bisect (1–2 h) → A2 (1 h) → A3 (an evening incl. proxy setup). ◄ **A1 in flight (596a9fa)**
3. If not 403s: D1 capture → D3/D4 controls → pick track by the matrix above.
4. Timebox: if A1–A3 all fail, decide **A4 vs shelve** — that decision belongs to Amit (§6).
5. Whatever the outcome: update `V2_PRD.md §8` + file a `gh issue` for the chosen follow-up work.

## 6. Decisions Amit owns (answer before Track A/B code continues)

1. ~~Sign in to Google inside NoShorts?~~ Moot — already signed in (V1 cookies persisted); doesn't fix it.
2. **NextDNS console access mid-test** — OK to temporarily lift the youtube.com deny for D3/D4? (Restore after.)
3. **Home box as network dependency** (A3/B1): acceptable ops surface? (Proxy is dumb + stateless; but
   cellular playback then rides home upload bandwidth.)
4. **If it comes to it: A4 treadmill vs shelve?**

## 7. Follow-up plan — issue #232 (post-resolution TODO)

Restoring the behaviors stripped by the attestation fix, Swift-side only (hard constraint: no
page-JS prototype/history tampering — §3a). Parts ordered by priority; 2 and 3 are evidence-gated.

- [x] **P1 — `/shorts` SPA guard. DONE 2026-07-10 (this branch).** Full-page navs to `/shorts` were
  still cancelled in `decidePolicyFor`, but YouTube's SPA routing bypassed it. Fix as planned: a
  `/shorts` case in the existing KVO observer on `webView.url` in the Coordinator —
  `goBack()` if possible, else `goPlaylists()`. Swift-side only, zero page-JS.
  On-device verification (Shorts unreachable via search/channel tabs; playback unaffected) is the
  post-merge check — the mechanism is identical to the proven YouTube-home KVO redirect.
- [ ] **P2 — autoplay-next gate (evidence-gated, likely moot).** We rely on the native
  `mediaTypesRequiringUserActionForPlayback = .video` gate. The old claim that YouTube bypasses it
  dates from the broken-proxy era. Gate: observe real usage — does the next video ever auto-play
  after one ends? (Fullscreen auto-exits on `ended`, landing on the endscreen in portrait, which
  already breaks the binge flow.) Only if a leak is observed: design a Swift-side countermeasure
  (e.g., video-event heuristic → `evaluateJavaScript` pause), design TBD on evidence.
- [ ] **P3 — fresh sign-in workaround (deferred until it bites).** The `window.webkit` hide on
  `accounts.google.com` was removed. Existing session cookies persist, so this only matters after a
  sign-out/data wipe. If a fresh login is ever blocked: restore the hide scoped to
  `accounts.google.com` only, then re-verify playback attestation (the hide never ran on
  youtube.com pages, so risk is low — but verify, don't assume).
- [ ] **Housekeeping:** issue #232 is authored by `mastrix-tech` (wrong-hat account was active).
  Either accept it or recreate under `abutala` and update references (README ×3, this file, PR #233 body).

## References

- [`V2_PRD.md`](V2_PRD.md) (esp. §7 fail-fast ladder, §8 outcome — to be amended per §3a)
- [`V2_SCOPING_ARCHIVE.md`](V2_SCOPING_ARCHIVE.md) (pre-PRD scoping draft, preserved for history)
- PR [#230](https://github.com/DeviationLabs/homely-vibes/pull/230) (PRD), PR [#231](https://github.com/DeviationLabs/homely-vibes/pull/231) (V2 rewrite + on-device test log)
- Debug session transcript: local Claude Code session `8d0e15c8` (2026-07-06 → 07-09), incl. 16 device
  console screenshots; key frames: 2026-07-06T18:42 (V1 RST-mid-tunnel), 2026-07-08T22:07/22:09 (V2 failures)
- Web Inspector evidence (2026-07-09): seg.ts 200-then-killed with `Server: gvs 1.0`, no `pot=`, `playerfallback/1`; protocol matrix h2/http1.1, no h3
- [yt-dlp #12482 — web client only has SABR formats](https://github.com/yt-dlp/yt-dlp/issues/12482)
- [yt-dlp #13968 — YouTube forcing SABR despite cookies](https://github.com/yt-dlp/yt-dlp/issues/13968)
- [YouTube.js #724 — streaming URLs failing due to PoToken experiment](https://github.com/LuanRT/YouTube.js/issues/724)
- [YouTube.js SabrStream API](https://ytjs.dev/googlevideo/api/exports/sabr-stream/classes/SabrStream) (open SABR client impl — keeps A4 viable)
- [Apple forums: "Network is down" in WebView networking](https://developer.apple.com/forums/thread/714908) (precedent that NW "network is down" ≠ literal sandbox verdict)
