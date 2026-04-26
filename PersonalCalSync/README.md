# Personal Calendar Sync

Syncs personal Google Calendar events to your enterprise Google Calendar as private busy-blocker events (tomato colored). Prevents coworkers from booking over your personal commitments.

## Why

Enterprise Google Workspace often blocks external calendar access via `CalendarApp`, so built-in calendar sharing doesn't work for scheduling visibility. This script fetches your personal calendar's private iCal feed over HTTP and creates real blocker events on your enterprise calendar that show up in coworkers' "Find a time" / scheduling assistant.

## How it works

- Fetches your personal calendar via its secret iCal URL (HTTP, bypasses enterprise restrictions)
- Parses ICS format including RRULE expansion for recurring events
- Creates/updates/deletes blocker events on your enterprise calendar using the **real event title** from your personal calendar
- Blocker events are marked `PRIVATE` — coworkers see "Busy", only you see the title
- Skips declined events and cancelled instances
- Batches writes to avoid Google API rate limits
- Runs every 15 minutes via Apps Script trigger

## Setup

### 1. Get your secret iCal URL

1. Open [Google Calendar](https://calendar.google.com) logged in as your **personal** account
2. Settings (gear) → click your calendar name in the left sidebar
3. Scroll to **"Integrate calendar"**
4. Copy **"Secret address in iCal format"** (NOT the public one)

### 2. Create the Apps Script project

1. Open [script.google.com](https://script.google.com) logged in as your **enterprise** account
2. New Project → delete placeholder code
3. Paste contents of `calendar-sync.gs`
4. Save

### 3. Store the iCal URL in Script Properties

The URL is stored in Apps Script's encrypted Script Properties — not in the code — so it survives future `clasp push` deployments.

1. In the Apps Script editor → **Project Settings** (gear icon on left) → **Script Properties**
2. Click **Add script property**
3. Property: `PERSONAL_ICAL_URL` — Value: your secret iCal URL from step 1
4. Click **Save script properties**

Also save it in `config/local.yaml` (gitignored) so it's backed up locally:
```yaml
personal_cal_sync:
  ical_url: "your_secret_ical_url_here"
```

### 4. Run initial sync

1. Select `initialSync` from the function dropdown → click **Run**
2. Approve calendar permissions when prompted
3. Check your enterprise calendar for red blocker events

### 5. Set up automatic sync

1. Left sidebar → **Triggers** (clock icon) → **Add Trigger**
2. Function: `syncCalendar`
3. Event source: Time-driven
4. Type: Minutes timer
5. Interval: Every 15 minutes
6. Save

## Deploying updates

After initial setup, use [`clasp`](https://github.com/google/clasp) to push local edits without copy-pasting.

### One-time clasp setup

**1. Install clasp:**

```bash
npm install -g @google/clasp
```

**2. Enable the Apps Script API** on your enterprise account:

Visit [script.google.com/home/usersettings](https://script.google.com/home/usersettings) and toggle **Google Apps Script API** to **On**. Without this, `clasp push` will fail with a 403. Only needed once per Google account.

**3. Log in** (opens browser — sign in as your **enterprise** Google account, the one that owns the Apps Script project):

```bash
clasp login
```

Credentials are saved to `~/.clasprc.json`. You only need to do this once per machine.

**4. Find your Script ID:** `script.google.com` → your project → **Project Settings** → **IDs** → Script ID.

**5. Store it in `config/local.yaml`** (gitignored) so Claude can run deploys for you without being asked:

```yaml
personal_cal_sync:
  script_id: "your_script_id_here"
```

**6. Link this directory** to your Apps Script project:

```bash
cd PersonalCalSync
clasp clone <SCRIPT_ID>   # same ID as above
```

This creates `.clasp.json` (gitignored — contains your script ID) and `appsscript.json`.

### Pushing changes

```bash
cd PersonalCalSync
clasp push        # uploads calendar-sync.gs to Apps Script
```

To trigger an immediate sync after pushing (instead of waiting for the 15-minute timer), open the Apps Script editor, select `initialSync` from the function dropdown, and click **Run**.

### `.clasp.json` and secrets

`.clasp.json` contains the script ID (not sensitive) but no credentials. The iCal URL lives in Apps Script's Script Properties (encrypted, never in source code) and in `config/local.yaml` (gitignored) as a local backup.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `PERSONAL_ICAL_URL` | — | Secret iCal URL — stored in Script Properties, not source code |
| `BLOCKER_TITLE_FALLBACK` | `Personal (Busy)` | Title used only if SUMMARY is missing from iCal |
| `SYNC_DAYS_AHEAD` | `30` | How far ahead to sync |
| `BATCH_SIZE` | `10` | Events created before pausing |
| `BATCH_PAUSE_MS` | `2000` | Pause duration between batches (ms) |

## Utility functions

| Function | Description |
|---|---|
| `initialSync()` | One-time full sync with logging |
| `syncCalendar()` | Standard sync (used by trigger) |
| `cleanupAllBlockers()` | Remove all synced blocker events |

## Privacy model

| Who sees what | Value |
|---|---|
| You (calendar owner) | Real event title (e.g. "Doctor appt") |
| Coworkers scheduling you | "Busy" only — no title, no details |
| Coworkers with full calendar access | Still sees "Busy" (PRIVATE visibility) |

The secret iCal URL grants read-only access to your personal calendar. Do not share it or commit it to a public repo.

## Known limitations

- Timezone: `TZID`-qualified timestamps are parsed as local (Apps Script server) timezone. Events on personal calendars in different timezones may be off by one hour during DST transitions.
- Sync window: only the next 30 days are checked. Events beyond `SYNC_DAYS_AHEAD` that were previously synced will not be cleaned up until they fall within the window.
