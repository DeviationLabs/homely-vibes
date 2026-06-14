#!/usr/bin/env python3
"""Scheduled WhatsApp summary job.

Runs daily via launchd. Reads the macOS WhatsApp SQLite DB, generates a
grouped summary, updates checkpoints/people-memory/todos/birthdays, and
sends a Pushover notification.

No LLM dependency — pure deterministic processing so launchd can run it
unattended at any hour.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("whatsapp_summary")

# ── Paths ──────────────────────────────────────────────────────────────────
PERSONAL = Path(os.environ.get("WA_PERSONAL_DIR", Path.home() / "bin" / "knowledge" / "personal"))
DB_SRC = (
    Path.home()
    / "Library"
    / "Group Containers"
    / "group.net.whatsapp.WhatsApp.shared"
    / "ChatStorage.sqlite"
)
DB_TMP = Path("/tmp/wa_summary.sqlite")
MSG_TMP = Path("/tmp/wa_messages.json")
CHECKPOINT = PERSONAL / "wa_summary_checkpoint"
PEOPLE_MEM = PERSONAL / "wa_people_memory.md"
TODO_FILE = PERSONAL / "wa_todo.md"
BIRTHDAY_FILE = PERSONAL / "wa_birthdays.md"
APPLE_EPOCH_BASE = 978_307_200  # 2001-01-01 00:00:00 UTC

# ── Priority people / chats ────────────────────────────────────────────────
PRIORITY_PEOPLE = {
    "Swati Butala": {
        "context": "Close family friend",
        "focus": "health, Aji eye/AMD, Shonu milestones, asks/referrals",
    },
    "Mamata Desai": {"context": "Friend + running group", "focus": "SJ Fit training, social plans"},
    "Shyamal Butala": {
        "context": "India relative",
        "focus": "health (back), Dropbox files, US trip planning",
    },
    "Karthik Iitb": {
        "context": "mastrix-ai co-founder",
        "focus": "startup milestones, tool decisions, homework",
    },
}
PA_AI_CHAT = "PA AI"

URL_RE = re.compile(r"(https?://[^\s<>\[\]]+)")


def _apple_epoch() -> int:
    return int(time.time()) - APPLE_EPOCH_BASE


def _local_dt(apple_epoch: int) -> datetime:
    return datetime.fromtimestamp(apple_epoch + APPLE_EPOCH_BASE, tz=timezone.utc).astimezone()


def _read_checkpoint() -> int | None:
    if CHECKPOINT.exists():
        try:
            return int(CHECKPOINT.read_text().strip())
        except (ValueError, OSError):
            return None
    return None


def _write_checkpoint(epoch: int) -> None:
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT.write_text(str(epoch))


def _ensure_db() -> bool:
    if not DB_SRC.exists():
        log.error("WhatsApp DB not found at %s", DB_SRC)
        return False
    shutil.copy2(DB_SRC, DB_TMP)
    return True


def _query_messages(cutoff: int) -> list[dict]:
    conn = sqlite3.connect(str(DB_TMP))
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        """
        SELECT s.ZPARTNERNAME as chat,
               CASE WHEN m.ZISFROMME = 1 THEN 'Me'
                    ELSE COALESCE(m.ZPUSHNAME, m.ZFROMJID, 'Unknown') END as sender,
               datetime(m.ZMESSAGEDATE + ?, 'unixepoch', 'localtime') as time,
               m.ZMESSAGEDATE as apple_epoch,
               m.ZTEXT as text
        FROM ZWACHATSESSION s
        JOIN ZWAMESSAGE m ON m.ZCHATSESSION = s.Z_PK
        WHERE m.ZMESSAGETYPE = 0
          AND m.ZTEXT IS NOT NULL
          AND m.ZMESSAGEDATE > ?
        ORDER BY s.ZPARTNERNAME, m.ZMESSAGEDATE
        """,
        (APPLE_EPOCH_BASE, cutoff),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    # Dump JSON for the YouTube extractor step
    if rows:
        MSG_TMP.parent.mkdir(parents=True, exist_ok=True)
        MSG_TMP.write_text(json.dumps(rows, indent=2))

    return rows


def _query_pa_ai_media(cutoff: int) -> list[dict]:
    """Query PA AI messages with media URLs for link extraction."""
    conn = sqlite3.connect(str(DB_TMP))
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        """
        SELECT m.ZTEXT as text, mi.ZMEDIAURL as media_url
        FROM ZWACHATSESSION s
        JOIN ZWAMESSAGE m ON m.ZCHATSESSION = s.Z_PK
        LEFT JOIN ZWAMEDIAITEM mi ON mi.ZMESSAGE = m.Z_PK
        WHERE s.ZPARTNERNAME = ? AND m.ZMESSAGEDATE > ?
        """,
        (PA_AI_CHAT, cutoff),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def _extract_urls(rows: list[dict]) -> list[str]:
    urls: list[str] = []
    for r in rows:
        text = r.get("text") or ""
        urls.extend(URL_RE.findall(text))
    return urls


def _extract_yt_urls(rows: list[dict]) -> list[str]:
    yt_re = re.compile(
        r"https?://(?:www\.|m\.)?"
        r"(?:youtube\.com/(?:watch\?[^\s]*v=[A-Za-z0-9_-]{11}|shorts/[A-Za-z0-9_-]{11}|embed/[A-Za-z0-9_-]{11}|v/[A-Za-z0-9_-]{11})[^\s]*"
        r"|youtu\.be/[A-Za-z0-9_-]{11}[^\s]*)"
    )
    urls: list[str] = []
    for r in rows:
        for src in (r.get("text") or "", r.get("media_url") or ""):
            urls.extend(yt_re.findall(src))
    return list(dict.fromkeys(urls))


def _extract_high_signal_urls(rows: list[dict]) -> list[str]:
    hi_re = re.compile(
        r"https?://(?:x\.com|twitter\.com|x\.ai|[a-z0-9-]+\.substack\.com|semianalysis\.com|arxiv\.org|linkedin\.com)[^\s]*"
    )
    urls: list[str] = []
    for r in rows:
        for src in (r.get("text") or "", r.get("media_url") or ""):
            urls.extend(hi_re.findall(src))
    return list(dict.fromkeys(urls))


def _is_lid_jid(text: str) -> bool:
    """WhatsApp internal placeholder messages that are only LID JIDs."""
    return bool(re.fullmatch(r"\d+@lid", text.strip())) if text else True


# ── Summary generation ─────────────────────────────────────────────────────


def _generate_summary(messages: list[dict], cutoff: int) -> str:
    """Build a markdown summary grouped by chat."""
    cutoff_dt = _local_dt(cutoff)
    parts: list[str] = [
        f"Showing messages since {cutoff_dt.strftime('%H:%M')} on {cutoff_dt.strftime('%Y-%m-%d')}\n",
    ]

    # Group by chat
    by_chat: dict[str, list[dict]] = defaultdict(list)
    for msg in messages:
        if not _is_lid_jid(msg.get("text", "")):
            by_chat[msg["chat"]].append(msg)

    # Priority order: PA AI first, then priority people, then others by recency
    chat_order: list[str] = []
    if PA_AI_CHAT in by_chat:
        chat_order.append(PA_AI_CHAT)
    for name in PRIORITY_PEOPLE:
        if name in by_chat and name not in chat_order:
            chat_order.append(name)
    # Others sorted by most recent message
    others = sorted(
        [(c, msgs) for c, msgs in by_chat.items() if c not in chat_order],
        key=lambda x: x[1][-1]["apple_epoch"],
        reverse=True,
    )
    chat_order.extend(c for c, _ in others)

    # PA AI section
    if PA_AI_CHAT in by_chat:
        msgs = by_chat[PA_AI_CHAT]
        last_active = _local_dt(int(msgs[-1]["apple_epoch"])).strftime("%H:%M")
        parts.append(f"\n## {PA_AI_CHAT} ({len(msgs)} messages, last active {last_active})")
        # Extract URLs
        yt_urls = _extract_yt_urls(_query_pa_ai_media(cutoff))
        hi_urls = _extract_high_signal_urls(_query_pa_ai_media(cutoff))
        if yt_urls:
            parts.append("\n### YouTube")
            for u in yt_urls:
                parts.append(f"  • {u}")
        if hi_urls:
            parts.append("\n### High-signal links")
            for u in hi_urls:
                parts.append(f"  • {u}")
        # Key topics from messages
        topics = _extract_topics(msgs)
        if topics:
            parts.append("\n### Key topics")
            for t in topics:
                parts.append(f"  • {t}")

    # Priority people sections
    for name, info in PRIORITY_PEOPLE.items():
        msgs = by_chat.get(name, [])
        if msgs:
            last_active = _local_dt(int(msgs[-1]["apple_epoch"])).strftime("%H:%M")
            parts.append(f"\n## {name} ({len(msgs)} messages, last active {last_active})")
            urls = _extract_urls(msgs)
            for i, msg in enumerate(msgs[-10:]):  # last 10 messages
                text = (msg.get("text") or "").strip()
                if text and not _is_lid_jid(text):
                    parts.append(f"  • [{msg['sender']}] {text[:200]}")
            if urls:
                parts.append("  ### Links")
                for u in urls[:5]:
                    parts.append(f"    • {u}")
        else:
            parts.append(f"\n## {name}")
            parts.append("  • no new messages")

    # Other chats
    for chat_name in others:
        name, msgs = chat_name
        last_active = _local_dt(int(msgs[-1]["apple_epoch"])).strftime("%H:%M")
        parts.append(f"\n## {name} ({len(msgs)} messages, last active {last_active})")
        for msg in msgs[-5:]:  # last 5 messages
            text = (msg.get("text") or "").strip()[:300]
            if text and not _is_lid_jid(text):
                parts.append(f"  • [{msg['sender']}] {text}")
        urls = _extract_urls(msgs)
        if urls:
            parts.append("  ### Links")
            for u in urls[:3]:
                parts.append(f"    • {u}")

    return "\n".join(parts)


def _extract_topics(msgs: list[dict]) -> list[str]:
    """Extract key topics from PA AI messages (simple keyword-based)."""
    topics: list[str] = []
    for msg in msgs[-20:]:  # last 20 messages
        text = (msg.get("text") or "").strip()
        if text and not _is_lid_jid(text):
            topics.append(text[:200])
    return topics


# ── People memory update ──────────────────────────────────────────────────


def _update_people_memory(messages: list[dict]) -> str:
    """Read existing memory, append new facts from messages, return updated content."""
    existing = PEOPLE_MEM.read_text() if PEOPLE_MEM.exists() else "# WhatsApp People Memory\n\n"
    lines = existing.splitlines()

    today = date.today().isoformat()
    # Simple approach: append new notable facts as a dated block
    notable_msgs = []
    for msg in messages:
        text = (msg.get("text") or "").strip()
        if text and not _is_lid_jid(text) and len(text) > 20:
            chat = msg.get("chat", "Unknown")
            if chat in PRIORITY_PEOPLE or chat == PA_AI_CHAT:
                notable_msgs.append(f"- [{today}] ({chat}) {text[:150]}")

    if notable_msgs:
        # Find last section or append
        lines.append(f"\n## Updates ({today})")
        lines.extend(notable_msgs[:20])  # cap at 20 to keep file manageable

    # Update "Last updated" line
    content = "\n".join(lines)
    content = re.sub(r"Last updated: .+", f"Last updated: {today}", content)
    if "Last updated:" not in content:
        content = f"# WhatsApp People Memory\nLast updated: {today}\n" + content

    return content


# ── Todo update ────────────────────────────────────────────────────────────


def _update_todo(messages: list[dict], summary_text: str) -> str:
    """Read existing todo, reconcile with messages, return updated content."""
    if not TODO_FILE.exists():
        return "# WhatsApp To-Do\n\n(no todo file yet)\n"

    content = TODO_FILE.read_text()

    # Extract Next ID
    match = re.search(r"Next ID: T(\d+)", content)
    next_id = int(match.group(1)) if match else 1
    updated_date = date.today().isoformat()

    # Check for event/meeting mentions in PA AI (sticky items)
    new_items: list[dict] = []
    for msg in messages:
        chat = msg.get("chat", "")
        text = (msg.get("text") or "").lower()
        if chat == PA_AI_CHAT:
            event_keywords = ["meeting", "event", "talk", "webinar", "conference", "meetup"]
            if any(kw in text for kw in event_keywords):
                # Extract date references
                date_match = re.search(r"(\d{4}-\d{2}-\d{2}|\w+ \d+|\w+day)", text)
                event_date = date_match.group(1) if date_match else "TBD"
                new_items.append(
                    {
                        "id": f"T{next_id}",
                        "added": updated_date,
                        "source": chat,
                        "item": f"Event/meeting mentioned: {msg.get('text', '')[:100]} (date: {event_date})",
                        "status": "open — attend/skip/RSVP",
                    }
                )
                next_id += 1

    # Update Next ID in content
    content = re.sub(r"Next ID: T\d+", f"Next ID: T{next_id}", content)
    content = re.sub(r"Last updated: .+", f"Last updated: {updated_date}", content)

    # Append new items before "## Done"
    if new_items:
        done_marker = "\n## Done"
        items_section = "\n".join(
            f"| {i['id']}  | {i['added']}  | {i['source']}  | {i['item']}  | {i['status']}  |"
            for i in new_items
        )
        # Find the table header and insert after it
        header_pattern = r"(\| ID  \| Added       \| Source.*?)\n"
        match = re.search(header_pattern, content)
        if match:
            insert_pos = match.end()
            content = content[:insert_pos] + items_section + "\n" + content[insert_pos:]
        else:
            # Fallback: insert before "## Done"
            if done_marker in content:
                content = content.replace(done_marker, items_section + "\n" + done_marker)

    return content


# ── Birthdays update ───────────────────────────────────────────────────────


def _update_birthdays(messages: list[dict]) -> str:
    """Scan messages for birthday references and update the tracker."""
    today = date.today().isoformat()
    if not BIRTHDAY_FILE.exists():
        content = f"# WhatsApp Birthdays Tracker\nLast updated: {today}\n\n"
    else:
        content = BIRTHDAY_FILE.read_text()

    birthday_keywords = ["birthday", "turned", "bday", "happy birthday"]
    for msg in messages:
        text = (msg.get("text") or "").lower()
        if any(kw in text for kw in birthday_keywords):
            chat = msg.get("chat", "Unknown")
            sender = msg.get("sender", "Unknown")
            # Extract birthday info
            parts = [p.strip() for p in (msg.get("text") or "").split("\n") if p.strip()]
            birthday_text = parts[0] if parts else text
            # Append as markdown row
            row = f"| {sender} | {chat} | TBD | {birthday_text[:100]} | {today} |\n"
            if row not in content:
                content += row

    content = re.sub(r"Last updated: .+", f"Last updated: {today}", content)
    return content


# ── Pushover notification ─────────────────────────────────────────────────


def _notify_pushover(status: str, body: str | None = None) -> bool:
    """Send Pushover notification."""
    try:
        # Try to import from LaunchJobs module
        from LaunchJobs.notify import notify as launch_notify

        launch_notify("whatsapp-summary", status, body)
        return True
    except ImportError:
        # Fallback: direct Pushover call
        try:
            import requests
            from lib.config import get_config

            cfg = get_config()
            token = cfg.pushover.tokens.get("WhatsAppSummary", cfg.pushover.default_token)
            requests.post(
                "https://api.pushover.net/1/messages.json",
                data={
                    "token": token,
                    "user": cfg.pushover.user,
                    "message": body or f"WhatsApp summary: {status}",
                    "title": f"[LaunchJobs] whatsapp-summary: {status}",
                },
                timeout=10,
            )
            return True
        except Exception as e:
            log.error(f"Pushover notification failed: {e}")
            return False


# ── Main ──────────────────────────────────────────────────────────────────


def main() -> int:
    log.info("WhatsApp summary job starting")

    # 1. Check WhatsApp running
    if subprocess.run(["pgrep", "-x", "WhatsApp"], capture_output=True).returncode != 0:
        log.info("WhatsApp desktop not running; skipping")
        _notify_pushover("skipped", "WhatsApp desktop not running")
        return 0

    # 2. Read checkpoint
    cutoff = _read_checkpoint()
    if cutoff is None:
        cutoff = _apple_epoch() - 24 * 3600  # last 24h default
        log.info("No checkpoint found; using 24h window")

    # 3. Copy DB
    if not _ensure_db():
        _notify_pushover("fail", "WhatsApp DB not found")
        return 1

    # 4. Query messages
    messages = _query_messages(cutoff)
    if not messages:
        log.info("No new messages since checkpoint")
        _notify_pushover("ok", "No new messages")
        _write_checkpoint(_apple_epoch())
        return 0

    log.info(f"Found {len(messages)} new messages")

    # 5. Generate summary
    summary = _generate_summary(messages, cutoff)
    summary_file = PERSONAL / "wa_daily_summary.md"
    summary_file.parent.mkdir(parents=True, exist_ok=True)
    summary_file.write_text(summary)
    log.info(f"Summary written to {summary_file}")

    # 6. Update people memory
    people_mem = _update_people_memory(messages)
    PEOPLE_MEM.parent.mkdir(parents=True, exist_ok=True)
    PEOPLE_MEM.write_text(people_mem)

    # 7. Update todos
    todo = _update_todo(messages, summary)
    TODO_FILE.parent.mkdir(parents=True, exist_ok=True)
    TODO_FILE.write_text(todo)

    # 8. Update birthdays
    birthdays = _update_birthdays(messages)
    BIRTHDAY_FILE.parent.mkdir(parents=True, exist_ok=True)
    BIRTHDAY_FILE.write_text(birthdays)

    # 9. Write checkpoint
    max_epoch = max(msg["apple_epoch"] for msg in messages)
    _write_checkpoint(max_epoch)

    # 10. Notify
    msg_count = len(messages)
    chat_count = len(set(msg["chat"] for msg in messages))
    _notify_pushover("ok", f"{msg_count} messages from {chat_count} chats summarized")

    log.info("WhatsApp summary job completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
