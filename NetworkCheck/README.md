# NetworkCheck

Network uplink monitoring — speed tests and external IP tracking for the home network. Reports via email and Pushover.

## Components

### `test_uplink.py` — Speed test

Runs `speedtest-cli` and classifies the link:

| Status | Condition |
|--------|-----------|
| **Good** | DL ≥ `min_dl_bw` AND UL ≥ `min_ul_bw` |
| **Degraded** | DL ≥ 80% threshold AND UL ≥ 80% threshold |
| **Bad** | Below 80% of either threshold |

Supports `--max_retries N` (waits 60s between attempts) and `--always_email` to force email delivery.

Thresholds configured in `config/default.yaml` → `network_check`:
```yaml
network_check:
  min_dl_bw: 150  # Mbps
  min_ul_bw: 4    # Mbps
```

### `external_ip_reporter.py` — IP change monitor

Fetches the current external IP from a cascade of services (ipify → icanhazip → checkip) and reports via email + Pushover. Useful for detecting dynamic IP changes.

## Notifications

Both scripts use:
- **Email** via `lib.Mailer`
- **Pushover** via the `NetworkCheck` app token (`config/local.yaml` → `pushover.tokens.NetworkCheck`)

## Prerequisites

### Speedtest CLI

The uplink test requires the [Speedtest CLI by Ookla](https://www.speedtest.net/apps/cli). It is auto-detected via `PATH`.

**macOS:**
```bash
brew install speedtest
```

**Linux (Debian/Ubuntu):**
```bash
sudo apt-get install speedtest
```

**Linux (Raspberry Pi / snap):**
```bash
sudo snap install speedtest
```

Verify with:
```bash
speedtest --version
```

## Usage

```bash
# Speed test (single attempt)
uv run python -m NetworkCheck.test_uplink

# Speed test with 3 retries
uv run python -m NetworkCheck.test_uplink --max_retries 3

# Speed test with email
uv run python -m NetworkCheck.test_uplink --always_email

# External IP report
uv run python -m NetworkCheck.external_ip_reporter
```

---

## `uplink_watchdog.py` — Deco watchdog (deadman's switch)

Detects two independent failures and reboots the Deco **over its own local
admin API** — no power cut, no cloud, no hardware.

### The failures being fixed

**1. WAN wedge.** The Deco periodically wedges its **WAN/routing plane** (stale
WAN DHCP lease, NAT/conntrack exhaustion, DNS-proxy death) while its **switch/AP
datapath keeps working**. Symptom: LAN up, gateway pings fine, nothing routes
past it. Only a reboot clears it — and when nobody is home, nobody can pull the
plug.

**2. Radio plane death.** The mirror image, and the one nothing else notices.
The uplink is perfectly healthy — the monitoring host (the wired monitoring host) is *wired* — while
the mesh has stopped serving Wi-Fi. Every phone, camera and sensor in the house
is off the air and **every probe in the WAN path reports green**. Being on
Ethernet is exactly what makes this invisible. The signal is the Deco's own
client census: a mesh serving nobody on the radios is a mesh to reboot.

Because the LAN plane survives both, the Deco's admin API is still reachable
*during* the fault. That is the whole reason a software reboot works here.

Background: [TP-Link community — LAN client stays connected while Deco goes
red](https://community.tp-link.com/en/home/forum/topic/676614) ·
[recovery only after hours powered off, i.e. a fresh ISP
lease](https://community.tp-link.com/us/home/forum/topic/683560) ·
[TP-Link FAQ 2428](https://www.tp-link.com/us/support/faq/2428/).

### Module layout

One concern per file, so the risky part is small enough to read in one sitting:

| File | Job |
|---|---|
| `probes.py` | The only code that touches the real network |
| `modem_client.py` | The upstream gateway's admin UI. Reboot only, by construction |
| `watchdog_state.py` | What survives between cron ticks, and its atomic write |
| `watchdog_policy.py` | **When to act,** for both faults. Pure function of (state, now, config) — the entire risk surface |
| `uplink_watchdog.py` | Orchestration + CLI |
| `deco_client.py` | The Deco local admin API |
| `common.py` | Notifier + invocation banner, shared by all three NetworkCheck scripts |

### How it works

Cron runs `check` every few minutes. Each tick:

1. **Probe the internet** — raw `ip:port` TCP connects, no DNS. A DNS-based
   probe reports a false outage when only the Deco's DNS proxy died, and false
   health when a captive resolver answers.
2. **Probe the LAN** — ping the gateway via `lib.NetHelpers.ping_output`.
   *LAN up + WAN down* is the Deco-wedge signature. If the LAN is **also** down
   it is our own NIC or cable, the Deco is unreachable anyway, and rebooting
   blind would be wrong — so the watchdog alerts and stops.
3. **Decide** — `should_act()` is the entire policy surface; see below.
4. **Act** — reboot **every** unit in the mesh over the local API, in a single
   call (the router takes the whole `mac_list`). All of them, not just the
   master: a wedged mesh is not reliably a master-only fault, and satellites
   re-establish backhaul faster from a cold start than against a master that
   just restarted under them.
5. **Persist** — outage clock, action log and queued notifications go to
   `{logging_dir}/uplink_watchdog_state.json` via an atomic tmp + `os.replace`.
   A truncated state file would silently reset the outage clock.

On a **healthy** tick it instead runs the Wi-Fi cycle (below) and the daily
credential check.

### The reboot criterion, in one place

Cron runs `check` every 10 minutes. Each tick asks one question -- *does the
mesh look broken?* -- and feeds **one clock**:

1. **Internet down?** Raw `ip:port` TCP connects, no DNS. A DNS-based probe
   reports a false outage when only the Deco's DNS proxy died, and false health
   when a captive resolver answers.
2. **If the uplink is fine, are the radios?** Ask the Deco for its client list
   and count the ones that are not wired. Below `min_wireless_clients` is a
   fault. **An unreadable census counts as zero** -- see fail-closed below.
3. **Either one bad** -> the clock runs. **Fully healthy** -> the clock resets
   to zero and any queued alerts flush.
4. **Clock >= `outage_threshold_secs` (2h)** -> reboot. Then nothing for
   `retry_interval_secs` (2h).

| | check interval | dwell | onset -> reboot |
|---|---|---|---|
| Internet down | 10 min | 2h | 2h - 2h10m |
| Wi-Fi down | 10 min | 2h | 2h - 2h10m |

**Why one clock and not two.** Separate clocks each reset on their own, so a
Deco that alternates symptoms -- WAN dies for 40 min, recovers, radios die for
20 min, recover, repeat -- never accumulates enough on either one and is never
rebooted, despite being visibly sick all evening. One clock, reset only by a
fully healthy cycle, catches that. The cost is that a pure Wi-Fi fault now
waits 2h rather than 30 min; the benefit is that the flapping case is covered
at all, and the whole policy fits in a sentence.

**There is deliberately no LAN/gateway probe.** There used to be, gating the
WAN path on "does the gateway still ping." But `gateway_ip` was the Deco's own
address, so it amounted to pinging the Deco immediately before logging into it.
`_execute` already fails safe when the Deco is unreachable: the mesh listing
raises before any action is recorded, so nothing reboots and the failure is
reported. The probe only changed the wording of the alert.

> A note if you are tempted to point that probe at the upstream modem instead:
> `10.0.0.1` is one hop *past* the Deco (`ip route get` confirms `via
> 192.168.1.1`), so reaching it depends on the Deco's **routing** plane -- the
> plane that dies in a wedge. It would fail during the exact fault this exists
> for. The Deco's own address works because it exercises the **switch** plane,
> which survives.

### Failing closed on an unreadable census

If `list_clients` throws, the census returns **zero**, not "unknown" -- so an
unreadable router is treated exactly like a router serving nobody, and the
clock runs.

The alternative is worse. Treating "I could not ask" as healthy means a
permanently broken census silently disables half the watchdog forever, with no
recovery path. And a router that will not answer its own local admin API is, in
any case, a plausible reboot candidate.

No alert fires on a census failure. A transient timeout is not news -- the log
has it -- and a persistent one reaches the reboot, which has its own P1. A bad
credential still cannot cause a reboot: `_execute` lists the mesh first and
raises there.

**And no alert fires on its recovery either.** That claim above used to be true
only of the fault tick. The clock had still started, so the *next* tick sent a
P-1 reading `Recovered after 10 min (Wi-Fi down (0/25 clients on the radios))`
-- an alert that is not merely noisy but false, describing an outage that never
happened. In prod the Deco's admin API times out on roughly 2% of ticks (6 of
~260 over two days, spread across all four calls of the login handshake, never
twice in a row), so this arrived about three times a day. Upstream documents
the router behaviour and ships two knobs for it -- see
[ha-tplink-deco](https://github.com/amosyuen/ha-tplink-deco/blob/main/README.md):
*"Some routers give a lot of timeout errors... This is a problem with the
router."*

`WatchdogState.recovery_is_news` closes it. The flag is sticky for the life of
a fault window and set by anything that makes the window worth reporting: a
fault that was **not** an unreadable census (internet down, or a census that
answered honestly with too few radios), or reaching `_execute` at all -- which
covers both the reboot P1 and the "cannot reach the Deco to reboot" P1, so
neither is ever left without closure. A window made only of timeouts runs the
clock exactly as before and ends quietly.

Detection is untouched. `_census` returns `None` instead of `0` so the caller
can tell "would not answer" from "answered with nothing", and the caller
immediately maps `None` to `0`. Same clock, same threshold, same reboot, same
wording on the fault itself.

The tradeoff to know about: if a firmware update ever changes the client-list
payload so it cannot be parsed, that reads as zero clients forever. Login still
works, so it *will* reboot every 2h indefinitely. Loud, not silent -- each one
sends a P1 -- but it will not stop on its own. `max_actions_per_day` is the
brake if that ever happens.

### Rebooting the modem

When the fault is **internet down**, the upstream Xfinity gateway is restarted
first, then the mesh. On a Wi-Fi fault it is left alone: the uplink is by
definition working, so power-cycling a healthy modem helps nobody.

It is best-effort and **never fatal**. The gateway sits one hop past the Deco,
so it may be unreachable at exactly the moment we want it; a failure is logged
and the Deco reboot follows regardless. The Deco is the proven lever, the modem
is the extra swing.

The protocol was read off the live device, not guessed:

```
POST /check.jst                                  username, password -> DUKSID cookie
GET  /restore_reboot.jst                         page embeds  var token = "...."
POST /actionHandler/ajaxSet_Reset_Restore.jst    resetInfo=["btn1","Device","admin"]
                                                 csrfp_token=<scraped token>
                                                 -> {"reboot": true}
```

**The landmine.** The same endpoint, with the same payload shape, performs a
factory wipe one identifier away:

| id | title | scope |
|---|---|---|
| **`btn1`** | **Reset the Gateway** | **`Device`** -- this is the reboot |
| `btn2` | Reset Wi-Fi Module | `Wifi` |
| `btn3` | Reset the Wi-Fi Gateway | `Wifi,Router` |
| `btn4` | Restore manufacturer defaults for Wi-Fi Only | `Wifi` |
| `btn5` | **Restore Factory settings** | `Router,Wifi,VoIP,Dect,MoCA` |
| `btn6` | Reset Password | `password` |

So `modem_client.reboot()` takes **no arguments**, the button is a module
constant, and the `ModemControl` Protocol the watchdog depends on exposes that
one verb. A test parses the module's AST and fails the build if `btn4`, `btn5`
or `btn6` ever appears in an executable position -- documenting the hazard in
the docstring stays fine, shipping it does not.

That covers our half of the contract. The device's half is checked at runtime:
immediately before the POST, the scraped page must still carry
`id="btn1"` with `title="Reset the Gateway"`, or the client refuses. The ids
belong to Comcast's firmware, not to us, and it updates unattended -- a unit
test can pin the bytes we emit but can never notice that the buttons were
renumbered underneath us. Refusing is safe: the watchdog logs it and goes on to
reboot the Deco, which is the lever that matters.

The CSRF token is scraped from the page per session; the cookie of the same
name is *not* what the handler validates.

To test it deliberately (takes the uplink down for ~4 min):

```bash
uv run python -m NetworkCheck.uplink_watchdog reboot-modem 2>&1 | tee /tmp/modem-reboot.log
```

### Getting the alert out across a reboot

Rebooting the mesh cuts the very uplink Pushover needs, so delivery is not left
to luck. Three rules, each of which exists because the naive version loses the
alert:

1. **Record and persist *before* the irreversible call.** `_execute()`
   enumerates the mesh, then writes `last_action_ts` and the queued alert to
   disk, and only then issues the reboot. A crash between those two points
   loses nothing.
2. **An unconfirmed reboot still counts as an action.** The router drops our
   connection *as it goes down*, so the reboot POST routinely fails after the
   router already accepted it. Treating that as "nothing happened" leaves
   `retry_interval_secs` unarmed and the next tick reboots again -- a loop that
   never lets the mesh finish booting, and that no alert escapes to report.
3. **Send inline when there is an uplink, queue when there is not.** During a
   WAN outage a send would only time out, so alerts queue in the state file and
   flush on the first cycle with a working uplink -- including a Wi-Fi-fault
   cycle, since the internet is up then. On the Wi-Fi path the alert goes out
   inline **before** the reboot, falling back to the queue if Pushover itself
   is unreachable.

Notification bodies run through `brief()`, which strips urllib3's connection
pool preamble and caps the length. This exists because the first production
census failure pushed `Deco request to {'form': 'client_list'} failed:
HTTPConnectionPool(host='192.168.1.1', port=80): Read timed out.` to a phone --
accurate, and unreadable. `DecoAPIError` messages now name the *form*, not the
params dict.

The recovery notice names both the fault and the reboot it followed
(`Recovered after 74 min (Internet down), 6 min after the watchdog rebooted the
mesh`) -- both alerts arrive on the same tick, and without that you would be
correlating timestamps to learn whether the watchdog fixed it or just watched
it end.

### Choosing `min_wireless_clients`

Ships at `0` (radio check off). There is no safe default for someone else's
house. Measure yours:

```bash
uv run python -m NetworkCheck.uplink_watchdog clients 2>&1 | tee /tmp/deco-clients.log
```

Run it across a day -- *including overnight*, when phones sleep and the count
bottoms out -- and set the floor well under the observed minimum. A deployment that
steadies at 76-82 clients on the radios can use a floor of 25 — roughly a third.

`connection_type` is `wired` / `band2_4` / `band5`; TP-Link publishes none of
this, the values come from
[ha-tplink-deco](https://github.com/amosyuen/ha-tplink-deco#client-attributes).
**Unknown counts as wireless on purpose** -- if a firmware update adds `band6`
for Wi-Fi 6E, treating it as wired would read as zero radios and reboot a
perfectly healthy house.

`clients` deliberately never prints client names: they are the household's
device names, this lands in a cron log, and the decision does not use them.
(It does print `interface`, which returns a third value, `iot`, that the
upstream docs do not list. Nothing branches on it.)

**Why not NodeCheck's down-node count?** It is the more direct signal, but
`heartbeat_nodes.py` holds its down-set in memory with nothing on disk for
another process to read -- wiring it up means inventing a shared state file and
a staleness contract. The Deco census needs neither and comes from the device
that gets rebooted. If the census proves too blunt, that is the upgrade path.

### Options considered

Recorded so nobody re-derives this. The short version: **the failure mode of the
fix must be milder than the fault it fixes**, and cutting power to your own
router fails badly.

| # | Option | Verdict | Why |
|---|---|---|---|
| 1 | **Reboot via the Deco's local admin API** | ✅ **chosen** | Reachable during the exact fault (LAN plane survives). Fails safe — a failed call changes nothing. Zero hardware. |
| 2 | Power-cut the Deco with an eWeLink/Sonoff plug | ❌ rejected | **One-way trip.** The plug rides the WiFi the Deco serves; the instant the load dies the plug loses its AP and can never be told to switch back on. |
| 3 | Sonoff `pulse` / inching as the restore timer | ❌ rejected | Wrong polarity — it is ON-then-auto-OFF. There is no OFF-then-auto-ON and no countdown endpoint. See the [itead DIY protocol doc](https://github.com/itead/Sonoff_Devices_DIY_Tools/blob/master/SONOFF%20DIY%20MODE%20Protocol%20Doc%20v1.4.md). |
| 4 | **Shelly plug with `Switch.Set?toggle_after=`** | ⏸️ viable, not built | The device schedules its own restore, so it survives the network vanishing — the only plug approach that works. Not implemented: no such hardware in this deployment, and speculative code for absent hardware is worse than none. If one is ever bought, it is a small self-contained PR, and it must join the **main** SSID (see Landmines). |
| 5 | Flash a Sonoff to Tasmota (`Backlog Power1 OFF; Delay …; Power1 ON`) | ⚠️ viable, not taken | Genuinely solves the restore problem on hardware already owned, but needs the plug opened and UART pads soldered. |
| 6 | Power-cycle the **modem/ONT** instead of the Deco | ⚠️ viable, not taken | Safe by construction — the Deco stays up, so the plug keeps its WiFi and can be switched back on remotely. But it does not fix a Deco wedge, which is the observed fault. |
| 7 | Rescue AP on the monitoring host (`hostapd`, same SSID) so the plug re-associates after the cut | ❌ rejected | Clever and free, but many moving parts (association, DHCP, changed IP, mDNS re-announce). If any step fails the house loses LAN *and* WAN — strictly worse than the fault. |
| 8 | Inverted deadman — plug cuts power unless the host keeps pinging it | ❌ rejected | Any crash or reboot of the monitoring host power-cycles the router. Unacceptable coupling for infrastructure. |
| 9 | TP-Link cloud / phone app remote reboot | ❌ rejected | Needs the internet that is down. |
| 10 | The Deco's own scheduled nightly auto-reboot | ❌ rejected | Blind and unconditional; does not respond to the fault and reboots on good nights too. |
| 11 | Drive an existing eWeLink plug over LAN from the monitoring host | ❌ blocked | Measured: from the wired host, ARP itself returns `FAILED`/`INCOMPLETE` for every IoT device and TCP/8081 never connects. They sit on a client-isolated IoT/Guest SSID. |

### Landmines

- **IoT/Guest SSID client isolation is real and measured.** Any plug on that
  SSID is unreachable from the wired monitoring host — not slow, not filtered,
  *ARP does not resolve*. Verify reachability before trusting any plug path.
- **The Deco's request-signing RSA key is only 512-bit** (the password key is
  1024-bit). The sign text spans multiple PKCS#1 blocks, and TP-Link
  concatenates the hex of each block rather than encrypting once. Get the
  chunking wrong and login fails with an opaque error.
- **`Content-Type: application/json` with a form-encoded body.** That is what
  the router wants (`sign=<hex>&data=<urlencoded base64>`). Don't "fix" it.
- **`sign` covers `seq + len(data)`** — the length of the *base64* string,
  computed before URL-encoding.
- **The admin account is single-session.** Logging into the Deco phone app can
  invalidate the watchdog's session; it re-logs in on the next tick.
- **`btn1` reboots the modem, `btn5` factory-resets it** — same endpoint, same
  payload shape. Read "Rebooting the modem" above before touching that module.
- **`10.0.0.1` is one hop *past* the Deco, not before it.** Anything depending
  on reaching it depends on the Deco's routing plane, which is what breaks.
- **An unreadable client census means "reboot", by design.** That is the
  fail-closed choice, not an oversight. Unknown `connection_type` values still
  count as *wireless* though — the fail-safe direction differs between "I could
  not ask" (reboot) and "I do not recognise this radio" (healthy). A firmware
  change to the client-list payload therefore becomes a 2-hourly reboot loop;
  `max_actions_per_day` is the brake.
- **Never `> /dev/null` the cron entry** — a pre-logger crash (import error,
  `uv` failure) would vanish.

### Configuration

Safe defaults live in `config/default.yaml` under `network_check.uplink_watchdog`;
the **admin password goes in `config/local.yaml`** (gitignored, symlinked to the
private personal-config repo — same place every other credential in this repo
lives, alongside `august:`, `ring:`, `tesla:`, `rheem:`):

```yaml
# config/local.yaml
network_check:
  uplink_watchdog:
    enabled: true
    deco_password: your_deco_admin_password   # the TP-Link *local* admin password
    deco_host: "http://192.168.x.x"
    min_wireless_clients: 25                  # measure yours with `clients` first
    modem_host: "http://10.0.0.1"             # optional second lever
    modem_password: your_gateway_admin_password
```

The watchdog ships `enabled: false`. Nothing runs until you flip it.

| Key | Default | Meaning |
|---|---|---|
| `outage_threshold_secs` | `7200` | Confirmed downtime before the first action |
| `retry_interval_secs` | `7200` | Minimum gap between actions |
| `max_actions_per_day` | `0` | `0` = unlimited. A cap keeps a multi-day ISP outage from becoming an all-night reboot loop |
| `auth_check_interval_secs` | `86400` | Credential check cadence. Only fires when the radio check is off — with it on, every healthy cycle already logs in. `0` disables |
| `probe_targets` | 3 raw `ip:port` | DNS-free reachability targets |
| `min_wireless_clients` | `0` | Radio-check floor. `0` disables — measure yours with `clients` first |
| `modem_host` | `""` | Upstream gateway, rebooted first on an internet fault. `""` disables |
| `modem_username` / `modem_password` | `admin` / `""` | Gateway admin credential; password in `local.yaml` |

### Tuning the policy

All of the judgment lives in `watchdog_policy.py` — its own module precisely
because it is the only part where a wrong call has consequences. It is one pure
function over one clock; the policy no longer knows which symptom started it.
Two decisions are baked into the shipped default, both marked in-file:

1. **Flap handling** — `down_since` resets on a *single* fully healthy cycle.
   Fast recovery, but a Deco that flaps either symptom every few minutes still
   never accumulates enough downtime to trip the watchdog. Merging the two
   clocks narrowed that hole without closing it.
2. **Give-up** — with `max_actions_per_day: 0` it never stops, so a multi-day
   ISP outage keeps triggering reboots. Harmless while the action is a soft
   reboot; revisit if that ever changes.

### Usage

```bash
# One-shot check (this is what cron runs)
uv run python -m NetworkCheck.uplink_watchdog check

# Decide and log, never act -- also exercises the full login handshake
uv run python -m NetworkCheck.uplink_watchdog check --dry-run

# Dump persisted state; no side effects
uv run python -m NetworkCheck.uplink_watchdog status

# Credential smoke test: log in and list the mesh. Read-only -- the only
# command that exercises the full handshake without rebooting anything.
# Run this FIRST on any new host.
uv run python -m NetworkCheck.uplink_watchdog probe

# Wireless client census -- read-only. Run this before setting
# min_wireless_clients, and again overnight when the count bottoms out.
uv run python -m NetworkCheck.uplink_watchdog clients

# Operator escape hatches. Both take the network down; neither is read-only.
uv run python -m NetworkCheck.uplink_watchdog reboot-all      # the mesh, ~2-3 min
uv run python -m NetworkCheck.uplink_watchdog reboot-modem    # the gateway, ~4 min

# Operator escape hatch: reboot the whole mesh right now (~2-3 min outage)
uv run python -m NetworkCheck.uplink_watchdog reboot-all
```

Cron on the Linux prod host:

```
*/10 * * * * cd $HOMELY_VIBES && uv run python -m NetworkCheck.uplink_watchdog check >> ~/logs/uplink_watchdog.log 2>&1
```

### Alert priorities

Per the repo convention (`P{N}` == Pushover `priority=N`):

- **P1** — an action was taken (either fault); the Deco could not be reached to
  reboot it; a reboot that did not confirm.
- **P0** — Deco admin auth failure, or a failed gateway check (bad password, or
  `btn1` no longer labelled as the reboot). Both are chores, not emergencies.
- **P-1** — recovered (silent, informational). Skipped entirely when the whole
  fault window was an unreadable census — see fail-closed above.
- **silent** — a failed client census and a failed modem reboot. Both are
  logged; neither is worth a notification, because the clock keeps running and
  the reboot that follows carries its own P1.

### The daily gateway check

Every `auth_check_interval_secs` on a healthy cycle, `ModemClient.verify()`
logs into the gateway, fetches the reset page, confirms `btn1` is still
labelled "Reset the Gateway", and scrapes the CSRF token. It **never POSTs**.
Success is silent; failure sends a **P0** inline.

This matters more than the Deco equivalent. The modem stage only fires on a
sustained internet outage, so it can go months between real exercises, and two
of its failure modes are invisible until that exact moment: a rotated admin
password, and a firmware update that renumbered the reset buttons. Checking
daily surfaces both while the uplink is healthy — which is also the only time
the alert can be delivered.

`verify()` and `reboot()` share `_prepare()`, so the check exercises the
identical path minus the POST and cannot drift from the thing it checks. A test
asserts they issue the same calls; if someone adds a step to `reboot()` outside
`_prepare()`, that test fails rather than the safety net silently rotting.

It runs on its own clock (`last_modem_check_ts`). Sharing the Deco's would mean
it never ran at all — a successful client census stamps that one every tick.

### The daily auth check

Every `auth_check_interval_secs` (default 24h), a **healthy** cycle logs into
the Deco and lists the mesh. Success is silent; failure sends a **P0** inline.

This closes a genuine hole. Login otherwise happens only inside `reboot_all()`
— that is, at the moment of the emergency and never before — and a failure
*there* is queued behind the very outage it was meant to fix, so it would
surface only once the outage had resolved some other way. You would learn the
safety net had failed after you no longer needed it.

A healthy cycle is the only moment we can both authenticate **and** deliver the
alert, which is why the check is deliberately skipped while the uplink is down.

It matters here specifically because the watchdog authenticates as the **owner**
account: an owner login from the Deco phone app evicts other sessions at any
time. Using a Manager account instead would reduce (not remove) that exposure.

A persistent failure alerts once per interval, not once per tick — the clock is
stamped before the attempt.

### No periodic heartbeat

There is deliberately **no periodic heartbeat**. One was built and removed: at
12 badges a day to say "nothing happened" it was pure noise, and noise that is
always ignored is not a signal. The consequence is real and worth knowing — a
watchdog that has silently died looks exactly like one with nothing to report.
The `check` cron line writes to `~/logs/uplink_watchdog.log` on every tick, so
that file's mtime is the liveness check if you ever want one.

### Testing

```bash
uv run python -m pytest NetworkCheck/ -v
```

Fake sessions and injected probes/clients — no `patch()`, per repo convention.
The Deco tests speak the real wire format: replies are AES-encrypted with the
client's own session key and the `sign` blob is RSA-decrypted and asserted on,
so the crypto is genuinely exercised rather than mocked away.
