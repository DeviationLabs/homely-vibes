"""Alert rule model, config loader, and shared Pushover formatting for
RachioFlume usage alerts.

This module also owns two helpers used by both the controller-zone path
(alert_engine) and the hose-timer path (hose_timer_processor):
- `compact_zone_label` — drops the descriptive tail from a raw valve/zone
  name so displays and Pushover headers stay short and consistent.
- `send_zone_outcome_pushover` — the shared zone-end notification format,
  so anomaly title/priority/message layout stays locked in one place.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from lib.config import get_config
from lib.notifications import Notifier


class AlertRule(BaseModel):
    """One sustained-flow alert rule.

    The rule fires when water flow has been >= `min_gpm` for every minute of
    the trailing `duration_minutes` window. While the condition holds, the
    engine re-fires every `retrigger_minutes`. A normal-priority "all clear"
    is emitted once on transition active -> clear.
    """

    name: str = Field(
        ..., description="Human-readable rule label, used in alert title and state keys"
    )
    min_gpm: float = Field(..., ge=0.0, description="Minimum gallons-per-minute threshold")
    duration_minutes: int = Field(..., ge=1, description="Sustained-flow window required to fire")
    retrigger_minutes: int = Field(
        ..., ge=1, description="Cadence to re-fire while condition persists"
    )


class ZoneThreshold(BaseModel):
    """Per-zone flow baseline for anomaly detection.

    `zone_key` is the device-local identifier — stringified zone_number for
    controllers (e.g. "1") or the raw valve name for hose timers (e.g.
    "Z13 FS - Upper Deck Planters"). Device scope is tracked separately by
    the caller's keying strategy (see load_zone_thresholds_from_config).

    Display names are derived from the raw key via `compact_zone_label` at
    render time — the config no longer stores a separate display `name`.
    """

    zone_key: str
    avg_gpm: float

    def compute_threshold(self, absolute_gpm: float, percent_above: float) -> float:
        """Compute effective alert threshold.

        threshold = avg_gpm + max(absolute_gpm, percent_above/100 * avg_gpm)
        """
        deviation = max(absolute_gpm, percent_above / 100.0 * self.avg_gpm)
        return self.avg_gpm + deviation


def compact_zone_label(raw_name: str) -> str:
    """Return the segment before " - " in a raw zone or valve name.

    Controller names ("Z1 FS") pass through unchanged; hose valve names
    ("Z13 FS - Upper Deck Planters") lose their descriptive tail so display
    strings and Pushover headers stay short and consistent between the two
    device families.
    """
    return raw_name.split(" - ", 1)[0].strip()


def load_rules_from_config() -> list[AlertRule]:
    """Build non-Rachio flow-rule list from `cfg.rachio_flume.alerts`.

    These are whole-house sustained-flow rules (Pipe Break / High Flow / Mid
    Flow / Leak) that apply to Flume readings independent of Rachio activity.
    Suppressed during/just-after any Rachio activity (controller or hose timer).
    """
    cfg = get_config()
    alerts_cfg = cfg.rachio_flume.alerts
    default_retrigger = alerts_cfg.default_retrigger_minutes
    return [
        AlertRule(
            name=r.name,
            min_gpm=r.min_gpm,
            duration_minutes=r.duration_minutes,
            retrigger_minutes=default_retrigger,
        )
        for r in alerts_cfg.default_flow_rules
    ]


def load_zone_thresholds_from_config() -> dict[str, dict[str, ZoneThreshold]]:
    """Build {device_label -> {zone_key -> ZoneThreshold}} from config.

    `zone_key` is a stringified zone_number for controllers, or the valve name
    for hose timers — matches the structure of
    cfg.rachio_flume.alerts.zone_anomaly.zone_thresholds.

    Inner entries arrive as plain dicts (OmegaConf does not auto-construct
    dataclasses at depth-2 of Dict[Dict[...]]). Read fields by key.
    """
    cfg = get_config()
    za_cfg = cfg.rachio_flume.alerts.zone_anomaly
    out: dict[str, dict[str, ZoneThreshold]] = {}
    for device_label, zones in za_cfg.zone_thresholds.items():
        out[device_label] = {}
        for zone_key, zt_cfg in zones.items():
            zk = str(zone_key)
            # zt_cfg may be a dict (depth-2 OmegaConf) or a ZoneThresholdConfig
            # (if the loader was ever extended). Accept both.
            if isinstance(zt_cfg, dict):
                avg_gpm = zt_cfg["avg_gpm"]
            else:
                avg_gpm = zt_cfg.avg_gpm
            out[device_label][zk] = ZoneThreshold(zone_key=zk, avg_gpm=avg_gpm)
    return out


def send_zone_outcome_pushover(
    *,
    pushover: Notifier,
    logger: logging.Logger,
    log_label: str,
    header: str,
    runtime_min: float,
    avg_gpm: float,
    total_gal: float,
    baseline: float,
    threshold: float,
    min_runtime_minutes: float,
    extra_lines: list[str] | None = None,
) -> None:
    """Emit at most one zone-end Pushover with the shared RachioFlume format.

    Both the controller-zone path (alert_engine._send_zone_outcome) and the
    hose-timer path (hose_timer_processor._send_zone_outcome) delegate here
    so the message layout, anomaly title/priority routing, and short-run
    silence gate stay locked in one place.

    Short runs (`runtime_min <= min_runtime_minutes`) are silenced entirely
    — they're test cycles, brief manual triggers, or noise, and firing a
    Pushover for each floods the feed. Above the gate the routine sends
    Zone Report (P-1) or Zone Anomaly (P2) depending on whether the flow
    exceeded the configured baseline's anomaly threshold.

    Args:
        header: caller-formatted first line, e.g. "'Z1 FS' (Cycle 2)" for
            controllers, "'Z13 FS' @ Hose Drip Jasmine" for hose valves.
        log_label: string used only in the skip/success log lines.
        baseline: 0 when the zone is not configured for anomaly detection;
            disables the "(thresh X.XX)" suffix and anomaly routing.
        extra_lines: appended after the anomaly deviation line, before send.
    """
    if runtime_min <= min_runtime_minutes:
        logger.info(
            f"Skipping zone outcome for {log_label}: "
            f"runtime {runtime_min:.0f}min ≤ min_runtime_minutes {min_runtime_minutes}min"
        )
        return

    is_anomaly = baseline > 0 and avg_gpm > threshold
    flow_line = (
        f"Avg flow: {avg_gpm:.2f} GPM (thresh {threshold:.2f})"
        if baseline > 0
        else f"Avg flow: {avg_gpm:.2f} GPM"
    )
    lines = [
        header,
        f"Runtime: {runtime_min:.0f} min",
        flow_line,
        f"Total: {total_gal:.1f} gal",
    ]
    if is_anomaly:
        deviation = avg_gpm - baseline
        deviation_pct = (deviation / baseline * 100) if baseline > 0 else 0
        lines.append(f"Deviation: +{deviation:.2f} GPM ({deviation_pct:.0f}%)")
    if extra_lines:
        lines.extend(line for line in extra_lines if line)

    if is_anomaly:
        title, priority = "Rachio Zone Anomaly", 2
    else:
        title, priority = "Rachio Zone Report", -1

    pushover.send_message("\n".join(lines), title=title, priority=priority)
    logger.info(
        f"Zone outcome sent for {log_label}: {runtime_min:.0f} min, "
        f"{avg_gpm:.2f} GPM, {total_gal:.1f} gal, anomaly={is_anomaly}"
    )


def get_controller_zone_thresholds(
    all_thresholds: dict[str, dict[str, ZoneThreshold]],
    device_label: str,
) -> dict[int, ZoneThreshold]:
    """Filter to controller thresholds for one device, keyed by zone_number (int).

    Convenience for AlertEngine which historically keys by int zone_number.
    """
    out: dict[int, ZoneThreshold] = {}
    for zone_key, zt in all_thresholds.get(device_label, {}).items():
        try:
            out[int(zone_key)] = zt
        except ValueError:
            # Non-integer keys belong to hose timers; skip.
            continue
    return out
