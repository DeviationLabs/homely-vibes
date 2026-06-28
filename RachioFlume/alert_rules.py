"""Alert rule model and config loader for RachioFlume usage alerts."""

from pydantic import BaseModel, Field

from lib.config import get_config


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
    controllers (e.g. "1") or the valve name for hose timers
    (e.g. "Upper Deck Planters"). Device scope is tracked separately by the
    caller's keying strategy (see load_zone_thresholds_from_config).
    """

    zone_key: str
    name: str
    avg_gpm: float

    def compute_threshold(self, absolute_gpm: float, percent_above: float) -> float:
        """Compute effective alert threshold.

        threshold = avg_gpm + max(absolute_gpm, percent_above/100 * avg_gpm)
        """
        deviation = max(absolute_gpm, percent_above / 100.0 * self.avg_gpm)
        return self.avg_gpm + deviation


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
                name = zt_cfg["name"]
                avg_gpm = zt_cfg["avg_gpm"]
            else:
                name = zt_cfg.name
                avg_gpm = zt_cfg.avg_gpm
            out[device_label][zk] = ZoneThreshold(
                zone_key=zk,
                name=name,
                avg_gpm=avg_gpm,
            )
    return out


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
