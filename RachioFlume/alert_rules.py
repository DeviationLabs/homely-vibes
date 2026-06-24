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
    """Per-zone flow threshold for anomaly detection."""

    zone_number: int
    name: str
    avg_gpm: float

    def compute_threshold(self, absolute_gpm: float, percent_above: float) -> float:
        """Compute effective alert threshold.

        threshold = avg_gpm + max(absolute_gpm, percent_above/100 * avg_gpm)
        """
        deviation = max(absolute_gpm, percent_above / 100.0 * self.avg_gpm)
        return self.avg_gpm + deviation


def load_rules_from_config() -> list[AlertRule]:
    """Build AlertRule list from `cfg.rachio_flume.alerts`."""
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
        for r in alerts_cfg.rules
    ]


def load_zone_thresholds_from_config() -> dict[int, ZoneThreshold]:
    """Build zone threshold map from cfg.rachio_flume.alerts.zone_thresholds."""
    cfg = get_config()
    alerts_cfg = cfg.rachio_flume.alerts
    thresholds = {}
    for zone_num, zt_cfg in alerts_cfg.zone_thresholds.items():
        thresholds[zone_num] = ZoneThreshold(
            zone_number=zone_num,
            name=zt_cfg.name,
            avg_gpm=zt_cfg.avg_gpm,
        )
    return thresholds
