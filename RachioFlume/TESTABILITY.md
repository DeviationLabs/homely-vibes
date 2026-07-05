# RachioFlume — Testability

Canonical reference for how the alert engine is tested, how to run the
synthetic simulator, how to replay against production data, and how to tune
rules. The user-facing operator README ([README.md](README.md)) carries
deployment + day-to-day commands; this doc carries the testing surface.

## Layers of testing

Each layer catches a different class of bug. All but the last run in CI with
no credentials.

| Layer | File(s) | Targets | Run cost |
|-------|---------|---------|----------|
| Unit — controller engine | `test_alert_engine.py` | Predicate logic, state machine, mute, CV filter, zone-end dispatch | <0.2s |
| Unit — hose timer | `test_hose_timer.py` | Action-field parse, run start/end detection, anomaly dispatch, hose→suppression-key stamp | <0.2s |
| Unit — stale zone | `test_stale_zone_checker.py` | Fresh/stale/never-run/disabled zones, hose-valve path, daily dedup, hourly gate | <0.2s |
| Unit — zone thresholds | `test_zone_thresholds.py` | `_get_zone_threshold` math, `_send_zone_outcome` Report-vs-Anomaly routing, optionally against a SCP'd prod DB | <0.2s (skips DB tests if `prod_controller` unset) |
| Scenario — synthetic timeline | `test_alert_simulation.py` | End-to-end engine behavior across multi-day YAML scenarios | ~5s |
| Replay — production DB | `rfmanager alerts replay` | The engine re-evaluated against real `water_readings` + `watering_events`. Output only, no Pushover. | seconds |
| Live dry-run | `rfmanager alerts test` | Real Flume + Rachio APIs, no Pushover | network-bound |
| Live dispatch | actual collector cycle | Pushover delivery, hose-timer cloud calls | seconds |

## Why a synthetic simulator (not VCR replay)

Recording real Flume responses (the typical "VCR" approach) only captures
what already happened. The interesting failure modes — *what does the engine
do during a pipe break, or 60 minutes after irrigation ends, or when a zone
that should fire goes 7 days without a run* — never appear in a recording of
a normal week.

The simulator solves this by:

- Encoding scenarios as **plain YAML** ([config/synthetic_alerts.yaml](../config/synthetic_alerts.yaml))
- Generating per-minute `WaterReading`s and Rachio active-zone responses on
  the fly from the scenario
- Stepping the AlertEngine through simulated time at the same 5-min cadence
  the collector uses in production
- Capturing every Pushover send instead of dispatching it — events stream to
  stdout

**Bugs become assertable**, not just observable. A scenario test like *"Pipe
Break should fire within 15 min of injection"* (see
[test_alert_simulation.py](test_alert_simulation.py)) is impossible to
express against a recorded tape; it's natural here.

The DB-replay path complements: synthetic exercises pathological scenarios
the engine has to handle; DB-replay verifies the engine doesn't false-fire
on real (boring) data.

## Scenario authoring

Scenarios are built in-code via [SyntheticDataset](synthetic_data.py) builders
inside [test_alert_simulation.py](test_alert_simulation.py). Each scenario
is a pytest function that constructs a fresh timeline, runs it through
`run_simulation`, and asserts on the captured pushover stream.

```python
ds = SyntheticDataset(start=datetime(2026, 5, 1), days=10)
ds.add_household(day=0, hour=7, kind="shower")
ds.add_irrigation(day=2, hour=6, minute=1, zone_name="Front Yard",
                  duration_minutes=30, gpm=4.2, zone_number=3)
ds.add_slow_leak(start_day=3, hour=0, duration_hours=72, gpm=0.18)
ds.add_pipe_break(day=7, hour=14, duration_minutes=20, gpm=9.0)

result = await run_simulation(ds, _rules(), poll_interval_minutes=5)
```

GPM at any minute is the **sum of all events active at that minute**, so you
can stack: a shower running during a slow leak just adds the two flow rates.

The AlertEngine constructed by `run_simulation` reads its knobs (zone
thresholds, `absolute_gpm`, `percent_above`, `min_runtime_minutes`) from
your real merged config (`default.yaml` + `local.yaml`) — same values the
production collector runs with. Running a scenario therefore also exercises
the config loader end-to-end. In CI (no `local.yaml`), the defaults apply
and `zone_thresholds` is empty, which means the Zone Anomaly path stays
silent; sustained-flow rule scenarios still exercise fully.

**Coverage gaps** (verified separately):

- **Hose-timer dispatch + suppression** — [test_hose_timer.py](test_hose_timer.py) covers them. The synthetic harness only drives `AlertEngine.evaluate`; `HoseTimerProcessor` is a separate code path that needs its own mock-client harness.
- **Stale-zone monitor** — [test_stale_zone_checker.py](test_stale_zone_checker.py) covers time-jump semantics that are awkward to express in the synthetic event timeline.
- **Hose-timer activity → Flume rule suppression** — `test_hose_timer.py::TestHoseActivitySuppression` writes the shared metadata key and verifies the cross-component contract.

## What scenario tests assert

[test_alert_simulation.py](test_alert_simulation.py) wraps the simulator in
assertions:

- `test_pipe_break_fires_within_window` — Pipe Break fires within `duration_minutes + poll_interval` of injection, then clears once
- `test_slow_leak_fires_leak_rule_not_mid_or_high` — a 0.18 gpm leak triggers Leak but never Mid/High/Pipe (threshold gating)
- `test_slow_leak_fires_once_per_day` — daily dedup holds across the 72h leak window
- `test_irrigation_suppresses_concurrent_high_flow` — flow during Rachio irrigation does not fire, and post-irrigation slack prevents tail-window false fires
- `test_short_shower_does_not_fire_mid_flow` — events too short to cross any window are silent
- `test_pipe_break_clear_arrives_only_after_active_to_clear` — exactly one clear per active→clear transition

## DB replay — verify the engine on real data

Replay the production `water_readings` + `watering_events` tables through
the same `AlertEngine.evaluate` loop. No Flume/Rachio calls, no Pushover.

```bash
# A. Against the LOCAL DB (whatever's at cfg.paths.logging_dir/water_tracking.db)
uv run python RachioFlume/rfmanager.py alerts replay --hours 168     # 7 days

# B. Against a COPY of the prod DB (safest — no risk of writes to prod)
scp <user>@<prod-host>:~/logs/water_tracking.db /tmp/prod_water_tracking.db
uv run python RachioFlume/rfmanager.py alerts replay \
    --hours 168 --db /tmp/prod_water_tracking.db
```

Output is tab-aligned and uses the same label set as the synthetic
simulator: `REPORT` (P-1), `FIRE` (P2), `CLEAR` (P0). Suppressed cycles
(controller OR hose-timer recent) are summarized at the bottom.

**Expected on a healthy 7-day replay** against current prod: roughly
24 `Zone Report` entries (12 active zones × ~2 cycles/week), zero `Zone
Anomaly` fires (unless you've actually had a leaking zone), zero false
`Pipe Break` / `Leak` fires during irrigation windows, and ~half the cycles
flagged as suppressed by Rachio during the morning irrigation hours.

## What we deliberately do NOT test

- **Network errors from real Flume / Rachio** — handled by `try/except` in
  the engine and collector; engine doesn't crash without side effects.
- **Pushover delivery** — relies on Pushover's own retry semantics for
  priority 2; not under our control.
- **Exact wall-clock timing** — the engine accepts `now` as a parameter, so
  all tests pass deterministic timestamps.
- **Hose-timer live API contract** — the cloud-rest.rach.io shape was
  verified once via live probe (see the original PR description on #199);
  the unit tests use captured response shapes.

## Rachio post-active slack: a tradeoff exposed by the simulator

When the simulator was first run, it immediately surfaced a real bug: the
cycle right after Rachio finished irrigating queried Flume readings that
still overlapped the irrigation window, and the engine fired a false alarm.

Fix: `RACHIO_POST_ACTIVE_SLACK_MINUTES = 10` in
[alert_engine.py](alert_engine.py). The engine remembers when Rachio (or
the hose timer) was last seen active and suppresses any rule whose lookback
window plus 10-min slack overlaps that timestamp.

**Tradeoff**: after a 30-min irrigation, the Leak rule (120 min window) is
suppressed for ~130 min. A leak forming *immediately* after irrigation
would be detected ~130 + 120 = 250 min (~4 hr) late. Acceptable because the
more common failure is irrigation→false-alarm, not leak-right-after-
irrigation.

If this tradeoff turns out wrong in practice, the proper fix is to record a
per-minute Rachio-active log and trim Flume readings to non-Rachio minutes
before running the predicate. That's ~30 lines of additional state,
deferred until evidence demands it.

## Tuning rules with the simulator

Workflow:

1. Add a new test in [test_alert_simulation.py](test_alert_simulation.py)
   that constructs a `SyntheticDataset`, exercises the path you care about,
   and asserts on the captured pushover stream.
2. Run `uv run pytest RachioFlume/test_alert_simulation.py -v -s` and
   inspect output (the `-s` flag streams the simulator's per-cycle prints).
3. Adjust rule thresholds in `config/local.yaml` if needed (the simulator
   reads them from your real config — same values production uses).
4. Verify against real data with `alerts replay --hours 168 --db <copy of prod>`.

## Test invocations cheat-sheet

```bash
# Fast unit pass (all engine + hose-timer + stale-zone)
uv run python -m pytest RachioFlume/test_alert_engine.py RachioFlume/test_hose_timer.py RachioFlume/test_stale_zone_checker.py -v 2>&1 | tee /tmp/rf_unit.log

# Scenario pass (synthetic timeline)
uv run python -m pytest RachioFlume/test_alert_simulation.py -v 2>&1 | tee /tmp/rf_scenario.log

# Full RachioFlume regression
uv run python -m pytest RachioFlume/ -v 2>&1 | tee /tmp/rf_full.log

# DB replay against a SCP'd prod copy
scp <user>@<prod-host>:~/logs/water_tracking.db /tmp/prod_water_tracking.db
uv run python RachioFlume/rfmanager.py alerts replay \
    --hours 168 --db /tmp/prod_water_tracking.db 2>&1 | tee /tmp/rf_replay.log

# Live dry-run against real APIs (no Pushover)
uv run python RachioFlume/rfmanager.py alerts test 2>&1 | tee /tmp/rf_live.log
```
