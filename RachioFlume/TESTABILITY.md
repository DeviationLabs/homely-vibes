# RachioFlume — Testability

How the alert engine is tested, why we settled on this approach, and how to use
the synthetic simulator when tuning rules.

## Layers of testing

There are three layers — each catches a different class of bug:

| Layer | File | Targets | Run cost |
|-------|------|---------|----------|
| Unit | `test_alert_engine.py` | Predicate logic, state machine, mute, dry-run | <0.2s |
| Scenario | `test_alert_simulation.py` | End-to-end engine behavior across multi-day timelines | ~5s |
| Live | `rfmanager alerts test` | Real Flume + Rachio APIs, no Pushover | network-bound |

The unit + scenario layers run in CI with no credentials. The live layer is
manual — for sanity-checking against your actual house's water pattern.

## Why a synthetic simulator (not VCR replay)

Recording real Flume responses (the typical "VCR" approach) only captures what
already happened. The interesting failure modes — *what does the engine do
during a pipe break, or 60 minutes after irrigation ends* — never appear in a
recording from a normal week.

The simulator solves this by:
- Encoding scenarios as **plain YAML** (`config/synthetic_alerts.yaml`)
- Generating per-minute `WaterReading`s and Rachio active-zone responses on the fly from the scenario
- Stepping the AlertEngine through simulated time at the same 5-min cadence the collector uses in production
- Capturing every Pushover send instead of dispatching it — events stream to stdout

This means **bugs are assertable**, not just observable. A scenario test like
*"Pipe Break should fire within 15 min of injection"* (see [test_alert_simulation.py:30](test_alert_simulation.py#L30))
is impossible to express against a tape; it's natural here.

## Scenario YAML schema

`config/synthetic_alerts.yaml` is the default. Schema:

```yaml
start_date: "2026-05-01"   # any ISO date — day 0 of the simulation
days: 10                    # how long the timeline runs

events:                     # list of overlapping water-using events
  # Household recipes (duration + gpm baked into RachioFlume/synthetic_data.py:HOUSEHOLD_RECIPES):
  - {day: 0, hour: 7,  minute: 0,  kind: shower}     # 8 min @ 2.4 gpm
  - {day: 0, hour: 19, minute: 30, kind: dishwasher} # 60 min @ 0.8 gpm
  - {day: 1, hour: 21, minute: 0,  kind: laundry}    # 45 min @ 1.5 gpm
  - {day: 1, hour: 12, minute: 0,  kind: sink}       # 3 min @ 1.2 gpm
  - {day: 1, hour: 18, minute: 0,  kind: hose}       # 10 min @ 3.5 gpm
  - {day: 1, hour: 13, minute: 0,  kind: toilet}     # 1 min @ 4.0 gpm

  # Rachio irrigation — Rachio reports the zone active during the window
  - {day: 2, hour: 6, minute: 1, kind: irrigation,
     zone: "Front Yard", duration_minutes: 30, gpm: 4.2, zone_number: 3}

  # Synthetic failure modes
  - {day: 3, hour: 0,  minute: 0, kind: slow_leak,  duration_hours: 72,  gpm: 0.18}
  - {day: 7, hour: 14, minute: 0, kind: pipe_break, duration_minutes: 20, gpm: 9.0}
```

GPM at any minute is the **sum of all events active at that minute**, so you can
stack: a shower running during a slow leak just adds the two flow rates.

## Worked example: running the default scenario

```bash
uv run python -m RachioFlume.rfmanager simulate
```

This streams alert events to stdout as the simulation steps forward. Excerpt
from `config/synthetic_alerts.yaml`:

```
========================================================================
Simulation: 10 days from 2026-05-01  poll every 5 min
------------------------------------------------------------------------
Alerts fired (priority 2 = FIRE; priority 0 = CLEAR):
  2026-05-01 20:00  P2  FIRE   RachioFlume: Low Flow        # dishwasher (30min @ 0.8gpm)
  2026-05-01 20:35  P0  CLEAR  RachioFlume: Low Flow cleared
  2026-05-04 02:00  P2  FIRE   RachioFlume: Leak            # slow leak crosses 120min mark
  2026-05-04 02:30  P2  FIRE   RachioFlume: Leak            # retrigger (30min)
  ... 140 more retriggers over 72h ...
  2026-05-07 00:05  P0  CLEAR  RachioFlume: Leak cleared
  2026-05-08 14:05  P2  FIRE   RachioFlume: High Flow       # pipe break: 4min window first
  2026-05-08 14:10  P2  FIRE   RachioFlume: Pipe Break      # 10min window second
  2026-05-08 14:15  P2  FIRE   RachioFlume: Mid Flow        # 14min window third
  2026-05-08 14:25  P0  CLEAR  RachioFlume: Pipe Break cleared
  2026-05-08 14:25  P0  CLEAR  RachioFlume: High Flow cleared
  2026-05-08 14:25  P0  CLEAR  RachioFlume: Mid Flow cleared
------------------------------------------------------------------------
Summary: 2881 cycles, 298 pushes (291 fires, 7 clears), 96 suppressed by Rachio
```

Read this as: in a 10-day simulation, the engine produces 298 notifications and
suppresses 96 cycles' worth of rule evaluation during Rachio irrigation. The
ordering of fires during the pipe break (High Flow → Pipe Break → Mid Flow at
+5 / +10 / +15 min) is by design: shorter windows latch first.

## What scenario tests assert

[`test_alert_simulation.py`](test_alert_simulation.py) wraps the simulator in
assertions:

- `test_pipe_break_fires_within_window` — Pipe Break fires within `duration_minutes + poll_interval` of injection, then clears once
- `test_slow_leak_fires_leak_rule_not_mid_or_high` — a 0.18 gpm leak triggers Leak and Low Flow but never Mid/High/Pipe (threshold gating)
- `test_slow_leak_retriggers_multiple_times` — re-trigger fires repeatedly while condition holds (verifies "until muted" semantics)
- `test_irrigation_suppresses_concurrent_high_flow` — flow during Rachio irrigation does not fire, and post-irrigation slack prevents tail-window false fires
- `test_short_shower_does_not_fire_mid_flow` — events too short to cross any window are silent
- `test_pipe_break_clear_arrives_only_after_active_to_clear` — exactly one clear per active→clear transition

## What we deliberately do NOT test

- **Network errors from real Flume / Rachio** — handled by `try/except` in the engine and the collector; covered by `test_evaluate_dry_run_does_not_send_or_persist` (engine doesn't crash without side effects)
- **Pushover delivery** — relies on Pushover's own retry semantics for priority 2; not under our control
- **Exact wall-clock timing** — the engine accepts `now` as a parameter, so all tests pass deterministic timestamps

## Rachio post-active slack: a tradeoff exposed by the simulator

When the simulator was first run, it immediately surfaced a real bug: the cycle
right after Rachio finished irrigating queried Flume readings that still
overlapped the irrigation window, and the engine fired a false alarm.

Fix: `RACHIO_POST_ACTIVE_SLACK_MINUTES = 10` in
[alert_engine.py](alert_engine.py). The engine remembers when Rachio was last
seen active, and suppresses any rule whose lookback window plus 10-min slack
overlaps that timestamp.

**Tradeoff**: after a 30-min irrigation, the Leak rule (120 min window) is
suppressed for ~130 min. A leak forming *immediately* after irrigation would be
detected ~130 + 120 = 250 min (~4 hr) late. This is acceptable because the more
common failure is irrigation→false-alarm, not leak-right-after-irrigation.

If this tradeoff turns out wrong in practice, the proper fix is to record a
per-minute Rachio-active log and trim Flume readings to non-Rachio minutes
before running the predicate. That's ~30 lines of additional state, deferred
until evidence demands it.

## Tuning rules with the simulator

Workflow:

1. Edit `config/synthetic_alerts.yaml` to add or stress the scenario you care about
2. Optionally edit `config/local.yaml` `rachio_flume.alerts.rules` to try a different threshold or window
3. Run `uv run python -m RachioFlume.rfmanager simulate` and inspect the summary
4. Iterate until the alert count / timing looks right
5. Capture the expectation as an assertion in `test_alert_simulation.py` so the tuning sticks

## Test invocations cheat-sheet

```bash
# Fast unit pass
uv run python -m pytest RachioFlume/test_alert_engine.py -v 2>&1 | tee /tmp/alert_unit.log

# Scenario pass
uv run python -m pytest RachioFlume/test_alert_simulation.py -v 2>&1 | tee /tmp/alert_scenario.log

# Full RachioFlume regression
uv run python -m pytest RachioFlume/ -v 2>&1 | tee /tmp/rf_full.log

# Visual playback for ad-hoc tuning
uv run python -m RachioFlume.rfmanager simulate 2>&1 | tee /tmp/alert_sim.log

# Live dry-run against real APIs (no Pushover)
uv run python -m RachioFlume.rfmanager alerts test 2>&1 | tee /tmp/alert_live.log
```
