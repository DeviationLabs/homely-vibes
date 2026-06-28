"""Stale-zone monitoring.

Fires a P-1 heads-up if any enabled controller zone or connected hose-timer
valve hasn't run within `stale_zone_days`. Catches accidentally-disabled
schedules, offline hose-timer hubs, dead valve batteries, etc.

Dedup: at most one notification per zone per day (stored in metadata).
Cadence: gated to once per hour from the collector cycle (no need to spam
on every 5-minute poll).
"""

from datetime import datetime, timedelta
from typing import Optional

from RachioFlume.data_storage import WaterTrackingDB
from lib.MyPushover import Pushover
from lib.logger import get_logger

_LAST_RUN_KEY = "stale_zone::last_run"
_NOTIFIED_KEY_TMPL = "stale_zone::notified::{source}::{zone_key}::{date}"
_CHECK_INTERVAL = timedelta(hours=1)


class StaleZoneChecker:
    """Once-an-hour scan for zones that haven't run within N days."""

    def __init__(
        self,
        db: WaterTrackingDB,
        pushover: Pushover,
        stale_zone_days: int = 7,
    ) -> None:
        self.db = db
        self.pushover = pushover
        self.stale_zone_days = stale_zone_days
        self.logger = get_logger(__name__)

    def maybe_evaluate(self, *, dry_run: bool = False, now: Optional[datetime] = None) -> bool:
        """Run the stale-zone scan if at least 1 hour has elapsed since the
        last run. Returns True if the scan actually ran this call.
        """
        if now is None:
            now = datetime.now()
        last_run_blob = self.db.get_metadata(_LAST_RUN_KEY)
        if last_run_blob:
            try:
                last_run = datetime.fromisoformat(last_run_blob)
                if now - last_run < _CHECK_INTERVAL:
                    return False
            except ValueError:
                pass  # corrupt timestamp — treat as never-run
        self.evaluate(dry_run=dry_run, now=now)
        if not dry_run:
            self.db.set_metadata(_LAST_RUN_KEY, now.isoformat())
        return True

    def evaluate(self, *, dry_run: bool = False, now: Optional[datetime] = None) -> list[dict]:
        """Scan all enabled zones; alert any stale beyond the threshold."""
        if now is None:
            now = datetime.now()
        cutoff = now - timedelta(days=self.stale_zone_days)
        results: list[dict] = []
        date_str = now.strftime("%Y-%m-%d")

        # --- Controller zones ---
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT zone_number, name FROM zones WHERE enabled = 1 ORDER BY zone_number"
            )
            controller_zones = [(int(r["zone_number"]), r["name"]) for r in cursor.fetchall()]
            cursor.execute(
                """
                SELECT zone_number, MAX(start_time) AS last_start
                FROM zone_sessions
                GROUP BY zone_number
                """
            )
            controller_last = {
                int(r["zone_number"]): datetime.fromisoformat(r["last_start"])
                for r in cursor.fetchall()
                if r["last_start"]
            }

        for zone_number, zone_name in controller_zones:
            last_seen = controller_last.get(zone_number)
            if last_seen and last_seen >= cutoff:
                continue
            entry = self._maybe_notify(
                source="controller",
                zone_key=str(zone_number),
                zone_label=zone_name,
                location="",
                last_seen=last_seen,
                now=now,
                date_str=date_str,
                dry_run=dry_run,
            )
            results.append(entry)

        # --- Hose-timer valves ---
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, name, base_station_label FROM hose_valves
                WHERE connected = 1
                """
            )
            valves = [(r["id"], r["name"], r["base_station_label"]) for r in cursor.fetchall()]
            cursor.execute(
                """
                SELECT valve_id, MAX(start_time) AS last_start
                FROM hose_zone_sessions
                GROUP BY valve_id
                """
            )
            hose_last = {
                r["valve_id"]: datetime.fromisoformat(r["last_start"])
                for r in cursor.fetchall()
                if r["last_start"]
            }

        for valve_id, valve_name, base_label in valves:
            last_seen = hose_last.get(valve_id)
            if last_seen and last_seen >= cutoff:
                continue
            entry = self._maybe_notify(
                source="hose",
                zone_key=valve_id,
                zone_label=valve_name,
                location=f" @ {base_label}",
                last_seen=last_seen,
                now=now,
                date_str=date_str,
                dry_run=dry_run,
            )
            results.append(entry)

        return results

    def _maybe_notify(
        self,
        *,
        source: str,
        zone_key: str,
        zone_label: str,
        location: str,
        last_seen: Optional[datetime],
        now: datetime,
        date_str: str,
        dry_run: bool,
    ) -> dict:
        dedup_key = _NOTIFIED_KEY_TMPL.format(source=source, zone_key=zone_key, date=date_str)
        already_notified = bool(self.db.get_metadata(dedup_key))

        entry = {
            "source": source,
            "zone": zone_label,
            "last_seen": last_seen.isoformat() if last_seen else None,
            "notified": False,
        }

        if already_notified or dry_run:
            if dry_run:
                self.logger.info(
                    f"[DRY RUN] Would alert stale {source} zone "
                    f"'{zone_label}'{location} (last_seen={last_seen})"
                )
            return entry

        last_seen_str = last_seen.strftime("%Y-%m-%d %H:%M") if last_seen else "never"
        msg = (
            f"'{zone_label}'{location} — no run in {self.stale_zone_days}+ days\n"
            f"Last seen: {last_seen_str}"
        )
        self.pushover.send_message(msg, title="RachioFlume: Stale Zone", priority=-1)
        self.db.set_metadata(dedup_key, now.isoformat())
        self.logger.info(
            f"Stale-zone alert sent: {source} '{zone_label}' last_seen={last_seen_str}"
        )
        entry["notified"] = True
        return entry
