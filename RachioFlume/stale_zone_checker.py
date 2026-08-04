"""Stale-zone monitoring.

Fires a P1 alert if any enabled controller zone or known hose-timer valve
hasn't run within `stale_zone_days`. Catches accidentally-disabled
schedules, offline hose-timer hubs, dead valve batteries, etc.

Hose valves are checked regardless of their reported `connected` state — a
disconnected valve is exactly the failure mode that stops it running, so it
must never drop out of this check. Disconnection and roster staleness (valve
no longer appearing in the API response) are surfaced as extra lines in the
alert instead. Whole-feed death is owned by the Rachio data-outage watchdog
in alert_engine.

Dedup: at most one notification per zone per day (stored in metadata).
Cadence: gated to once per hour from the collector cycle (no need to spam
on every 5-minute poll).
"""

from datetime import datetime, timedelta
from typing import Optional

from RachioFlume.data_storage import WaterTrackingDB
from lib.notifications import Notifier
from lib.logger import get_logger

_LAST_RUN_KEY = "stale_zone::last_run"
_NOTIFIED_KEY_TMPL = "stale_zone::notified::{source}::{zone_key}::{date}"
_CHECK_INTERVAL = timedelta(hours=1)
# A valve missing from the roster poll for this long gets a "not seen" note.
_ROSTER_STALE = timedelta(hours=24)


class StaleZoneChecker:
    """Once-an-hour scan for zones that haven't run within N days."""

    def __init__(
        self,
        db: WaterTrackingDB,
        pushover: Notifier,
        stale_zone_days: int = 10,
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

        # --- Hose-timer valves (connected or not — see module docstring) ---
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, name, base_station_label, connected, updated_at
                FROM hose_valves
                """
            )
            valves = [
                (r["id"], r["name"], r["base_station_label"], r["connected"], r["updated_at"])
                for r in cursor.fetchall()
            ]
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

        for valve_id, valve_name, base_label, connected, updated_at in valves:
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
                status_notes=self._valve_status_notes(connected, updated_at, now),
            )
            results.append(entry)

        return results

    def _valve_status_notes(
        self, connected: object, updated_at: Optional[str], now: datetime
    ) -> list[str]:
        """Actionable context for a stale hose valve: disconnection points at
        battery/BLE range; a stale roster timestamp means the valve stopped
        appearing in API responses (removed/renamed, or the hose feed is down).
        """
        notes: list[str] = []
        if not connected:
            notes.append("Valve reporting DISCONNECTED — check battery / BLE range")
        if updated_at:
            try:
                seen = datetime.fromisoformat(updated_at)
                if now - seen >= _ROSTER_STALE:
                    notes.append(f"Not seen in valve roster since {seen:%Y-%m-%d %H:%M}")
            except ValueError:
                pass  # unparsable timestamp — skip the note
        return notes

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
        status_notes: Optional[list[str]] = None,
    ) -> dict:
        dedup_key = _NOTIFIED_KEY_TMPL.format(source=source, zone_key=zone_key, date=date_str)
        already_notified = bool(self.db.get_metadata(dedup_key))

        entry = {
            "source": source,
            "zone": zone_label,
            "last_seen": last_seen.isoformat() if last_seen else None,
            "status_notes": status_notes or [],
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
        lines = [
            f"'{zone_label}'{location} — no run in {self.stale_zone_days}+ days",
            f"Last seen: {last_seen_str}",
        ]
        if status_notes:
            lines.extend(status_notes)
        self.pushover.send_message("\n".join(lines), title="RachioFlume: Stale Zone", priority=1)
        self.db.set_metadata(dedup_key, now.isoformat())
        self.logger.info(
            f"Stale-zone alert sent: {source} '{zone_label}' last_seen={last_seen_str}"
        )
        entry["notified"] = True
        return entry
