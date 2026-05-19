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
