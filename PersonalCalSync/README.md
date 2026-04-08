# Personal Calendar Sync

Syncs personal Google Calendar events to your enterprise Google Calendar as "busy" blocker events (Tomato colored). Prevents coworkers from booking over your personal commitments.

## Why

Enterprise Google Workspace often blocks external calendar access via `CalendarApp`, so built-in calendar sharing doesn't work for scheduling visibility. This script fetches your personal calendar's private iCal feed over HTTP and creates real blocker events on your enterprise calendar that show up in coworkers' "Find a time" / scheduling assistant.

## How it works

- Fetches your personal calendar via its secret iCal URL (HTTP, bypasses enterprise restrictions)
- Parses ICS format including RRULE expansion for recurring events
- Creates/updates/deletes "Personal (Busy)" blocker events on your enterprise calendar
- Skips declined events and cancelled instances
- Batches writes to avoid Google API rate limits
- Runs every 15 minutes via Apps Script trigger

## Setup

### 1. Get your secret iCal URL

1. Open [Google Calendar](https://calendar.google.com) logged in as your **personal** account
2. Settings (gear) > click your calendar name in the left sidebar
3. Scroll to **"Integrate calendar"**
4. Copy **"Secret address in iCal format"** (NOT the public one)

### 2. Create the Apps Script project

1. Open [script.google.com](https://script.google.com) logged in as your **enterprise** account
2. New Project > delete placeholder code
3. Paste contents of `calendar-sync.gs`
4. Replace `PASTE_YOUR_SECRET_ICAL_URL_HERE` with your secret iCal URL
5. Save

### 3. Run initial sync

1. Select `initialSync` from the function dropdown > click **Run**
2. Approve calendar permissions when prompted
3. Check your enterprise calendar for red "Personal (Busy)" events

### 4. Set up automatic sync

1. Left sidebar > **Triggers** (clock icon) > **Add Trigger**
2. Function: `syncCalendar`
3. Event source: Time-driven
4. Type: Minutes timer
5. Interval: Every 15 minutes
6. Save

## Configuration

| Variable | Default | Description |
|---|---|---|
| `PERSONAL_ICAL_URL` | — | Your secret iCal URL |
| `BLOCKER_TITLE` | `Personal (Busy)` | Title shown on enterprise calendar |
| `SYNC_DAYS_AHEAD` | `30` | How far ahead to sync |
| `BATCH_SIZE` | `10` | Events created before pausing |
| `BATCH_PAUSE_MS` | `2000` | Pause duration between batches (ms) |

## Utility functions

| Function | Description |
|---|---|
| `initialSync()` | One-time full sync with logging |
| `syncCalendar()` | Standard sync (used by trigger) |
| `cleanupAllBlockers()` | Remove all synced blocker events |

## Security

- The secret iCal URL grants read-only access to your personal calendar. Do not share it or commit it to a public repo.
- Blocker events are created with `Visibility.PRIVATE` — coworkers see "Busy" but not the blocker title.
