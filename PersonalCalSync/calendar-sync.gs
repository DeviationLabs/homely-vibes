// ============================================================
// Personal → Enterprise Calendar Busy Blocker Sync (v4)
// ============================================================
// Uses private iCal URL to bypass enterprise restrictions.
// Expands recurring events (RRULE) into individual instances.
// Mirrors "free" (TRANSP:TRANSPARENT) and "maybe" (tentative) so
// blockers show as Free / Tentative instead of always Busy — this
// requires the advanced Calendar service (Calendar.Events), enabled
// in appsscript.json.
//
// Setup:
// 1. Get your personal calendar's secret iCal URL:
//    Personal Gmail → Calendar Settings → your calendar → Integrate calendar
//    → Copy "Secret address in iCal format"
// 2. Set PERSONAL_ICAL_URL in Project Settings → Script Properties
// 3. Set MY_EMAIL (your personal email) in Script Properties — used to
//    match your own RSVP; kept out of source to avoid committing PII.
// 4. Run initialSync() once to grant permissions
// 5. Add time-driven trigger: syncCalendar every 15 minutes
// ============================================================
var ICAL_URL_KEY = 'PERSONAL_ICAL_URL';
// My personal email, used to match my own RSVP (PARTSTAT) in attendee lines.
// Stored in Script Properties — never hardcoded — to keep PII out of source.
var MY_EMAIL_KEY = 'MY_EMAIL';

var BLOCKER_TAG = '[PERSONAL_SYNC:';
var BLOCKER_PREFIX = '[P] ';
var BLOCKER_TITLE_FALLBACK = 'Personal (Busy)';
var SYNC_DAYS_AHEAD = 180;

// Enterprise calendar the blockers live on. 'primary' == the account running the script.
var CAL_ID = 'primary';
// Tomato/red in Google's colorId scheme.
var BLOCKER_COLOR_ID = '11';

var BATCH_SIZE = 10;
var BATCH_PAUSE_MS = 2000;

function syncCalendar() {
  var now = new Date();
  var startDate = new Date(now.getTime() - 60 * 60 * 1000);
  var endDate = new Date(now.getTime() + SYNC_DAYS_AHEAD * 24 * 60 * 60 * 1000);

  var personalEvents = fetchPersonalEvents(startDate, endDate);
  if (personalEvents === null) {
    Logger.log('Failed to fetch personal events, skipping sync to preserve existing blockers.');
    return;
  }
  if (personalEvents.length === 0) {
    Logger.log('No personal events found in window.');
  }

  Logger.log('Found ' + personalEvents.length + ' personal events in window.');

  var existingBlockers = getExistingBlockers(startDate, endDate);

  var created = 0;
  var updated = 0;
  var deleted = 0;

  for (var i = 0; i < personalEvents.length; i++) {
    var pe = personalEvents[i];
    var blocker = existingBlockers[pe.uid];
    if (blocker) {
      updateBlockerIfNeeded(blocker, pe);
      updated++;
      delete existingBlockers[pe.uid];
    } else {
      createBlocker(pe);
      created++;
      if (created % BATCH_SIZE === 0) {
        Logger.log('Created ' + created + ' blockers, pausing...');
        Utilities.sleep(BATCH_PAUSE_MS);
      }
    }
  }

  for (var staleId in existingBlockers) {
    Calendar.Events.remove(CAL_ID, existingBlockers[staleId].id);
    deleted++;
    if (deleted % BATCH_SIZE === 0) {
      Utilities.sleep(BATCH_PAUSE_MS);
    }
  }

  Logger.log('Sync complete. Created: ' + created + ', Updated: ' + updated + ', Deleted: ' + deleted);
}

// --- ICS Fetching & Parsing ---

function fetchPersonalEvents(startDate, endDate) {
  var url = PropertiesService.getScriptProperties().getProperty(ICAL_URL_KEY);
  if (!url) {
    Logger.log('iCal URL not set. Run setPersonalIcalUrl("YOUR_URL") first.');
    return null;
  }
  var response;
  try {
    response = UrlFetchApp.fetch(url, {muteHttpExceptions: true});
  } catch (e) {
    Logger.log('Failed to fetch iCal URL: ' + e.message);
    return null;
  }

  if (response.getResponseCode() !== 200) {
    Logger.log('iCal fetch failed with status: ' + response.getResponseCode());
    return null;
  }

  var icsText = unfoldICSLines(response.getContentText());
  return parseICS(icsText, startDate, endDate);
}

function unfoldICSLines(text) {
  return text.replace(/\r?\n[ \t]/g, '');
}

function parseICS(icsText, startDate, endDate) {
  var events = [];
  var blocks = icsText.split('BEGIN:VEVENT');
  var exdatesByUid = {};
  var overridesByUid = {};

  // First pass: collect EXDATE exclusions and RECURRENCE-ID overrides
  for (var i = 1; i < blocks.length; i++) {
    var block = blocks[i].split('END:VEVENT')[0];
    var uid = extractICSField(block, 'UID');
    if (!uid) continue;

    var recurrenceId = extractICSDateTime(block, 'RECURRENCE-ID');
    if (recurrenceId) {
      if (!overridesByUid[uid]) overridesByUid[uid] = {};
      overridesByUid[uid][recurrenceId.getTime()] = block;
    }
  }

  // Second pass: process events
  for (var i = 1; i < blocks.length; i++) {
    var block = blocks[i].split('END:VEVENT')[0];

    var uid = extractICSField(block, 'UID');
    if (!uid) continue;

    var status = extractICSField(block, 'STATUS');
    if (status && status.toUpperCase() === 'CANCELLED') continue;
    if (isDeclinedEvent(block)) continue;

    // Skip override blocks — they'll be handled when expanding the master
    var recurrenceId = extractICSDateTime(block, 'RECURRENCE-ID');
    if (recurrenceId) continue;

    var dtStart = extractICSDateTime(block, 'DTSTART');
    var dtEnd = extractICSDateTime(block, 'DTEND');
    if (!dtStart) continue;

    var isAllDay = isAllDayEvent(block);
    var duration = getDuration(dtStart, dtEnd, isAllDay);

    var rrule = extractICSField(block, 'RRULE');
    var exdates = extractAllEXDATEs(block);
    var isFree = isFreeEvent(block);
    var isTentative = isTentativeEvent(block);

    if (rrule) {
      var masterTitle = extractICSField(block, 'SUMMARY');
      var instances = expandRRule(rrule, dtStart, duration, isAllDay, exdates, startDate, endDate, uid, overridesByUid[uid] || {}, masterTitle, isFree, isTentative);
      for (var j = 0; j < instances.length; j++) {
        events.push(instances[j]);
      }
    } else {
      if (!dtEnd) {
        dtEnd = new Date(dtStart.getTime() + duration);
      }
      if (dtEnd >= startDate && dtStart <= endDate) {
        var title = extractICSField(block, 'SUMMARY');
        events.push({
          uid: uid,
          title: title ? BLOCKER_PREFIX + title : BLOCKER_TITLE_FALLBACK,
          start: dtStart,
          end: dtEnd,
          isAllDay: isAllDay,
          isFree: isFree,
          isTentative: isTentative
        });
      }
    }
  }

  return events;
}

function getDuration(dtStart, dtEnd, isAllDay) {
  if (dtEnd) return dtEnd.getTime() - dtStart.getTime();
  return isAllDay ? 24 * 60 * 60 * 1000 : 60 * 60 * 1000;
}

function extractAllEXDATEs(block) {
  var exdates = {};
  var lines = block.split(/\r?\n/);
  for (var i = 0; i < lines.length; i++) {
    if (lines[i].indexOf('EXDATE') !== 0) continue;
    var colonIdx = lines[i].indexOf(':');
    if (colonIdx === -1) continue;
    var values = lines[i].substring(colonIdx + 1).split(',');
    for (var j = 0; j < values.length; j++) {
      var dt = parseICSDateValue(values[j].trim());
      if (dt) exdates[dt.getTime()] = true;
    }
  }
  return exdates;
}

function isDeclinedEvent(block) {
  return myPartstatIs(block, 'DECLINED');
}

// "Mark time as free" in Google Calendar exports as TRANSP:TRANSPARENT (default OPAQUE = busy).
function isFreeEvent(block) {
  var transp = extractICSField(block, 'TRANSP');
  return !!(transp && transp.toUpperCase() === 'TRANSPARENT');
}

// "Maybe" = either an event-level tentative status, or my own RSVP being tentative.
function isTentativeEvent(block) {
  var status = extractICSField(block, 'STATUS');
  if (status && status.toUpperCase() === 'TENTATIVE') return true;
  return myPartstatIs(block, 'TENTATIVE');
}

function myPartstatIs(block, partstat) {
  var myEmail = getMyEmail();
  if (!myEmail) return false;
  var needle = 'PARTSTAT=' + partstat;
  var lines = block.split(/\r?\n/);
  for (var i = 0; i < lines.length; i++) {
    if (lines[i].indexOf('ATTENDEE') !== 0) continue;
    if (lines[i].indexOf(needle) !== -1 &&
        lines[i].toLowerCase().indexOf(myEmail) !== -1) {
      return true;
    }
  }
  return false;
}

var _myEmailCache = null;
function getMyEmail() {
  if (_myEmailCache === null) {
    _myEmailCache = (PropertiesService.getScriptProperties().getProperty(MY_EMAIL_KEY) || '').toLowerCase();
    if (!_myEmailCache) {
      Logger.log('MY_EMAIL script property not set — declined/tentative RSVP detection disabled.');
    }
  }
  return _myEmailCache;
}

// --- RRULE Expansion ---

function expandRRule(rrule, dtStart, duration, isAllDay, exdates, windowStart, windowEnd, uid, overrides, masterTitle, masterFree, masterTentative) {
  var parts = parseRRuleParts(rrule);
  var freq = parts['FREQ'];
  var interval = parseInt(parts['INTERVAL'] || '1');
  var count = parts['COUNT'] ? parseInt(parts['COUNT']) : null;
  var until = parts['UNTIL'] ? parseICSDateValue(parts['UNTIL']) : null;
  var byDay = parts['BYDAY'] ? parts['BYDAY'].split(',') : null;
  var byMonthDay = parts['BYMONTHDAY'] ? parts['BYMONTHDAY'].split(',').map(function(d) { return parseInt(d); }) : null;

  var instances = [];
  var cursor = new Date(dtStart.getTime());
  var generated = 0;
  var maxIterations = 1000;
  var iterations = 0;

  while (iterations < maxIterations) {
    iterations++;

    var candidates = getCandidatesForPeriod(cursor, freq, byDay, byMonthDay, dtStart, isAllDay);

    for (var c = 0; c < candidates.length; c++) {
      var candidate = candidates[c];

      if (candidate < dtStart) continue;
      if (until && candidate > until) return instances;
      if (count !== null && generated >= count) return instances;
      if (candidate > windowEnd) return instances;

      generated++;

      if (candidate >= windowStart && !exdates[candidate.getTime()]) {
        var instanceEnd = new Date(candidate.getTime() + duration);

        // Check for override (modified instance)
        var instanceTitle = masterTitle ? BLOCKER_PREFIX + masterTitle : null;
        var instanceFree = masterFree;
        var instanceTentative = masterTentative;
        var override = overrides[candidate.getTime()];
        if (override) {
          var ovStatus = extractICSField(override, 'STATUS');
          if (ovStatus && ovStatus.toUpperCase() === 'CANCELLED') continue;
          if (isDeclinedEvent(override)) continue;
          var ovStart = extractICSDateTime(override, 'DTSTART');
          var ovEnd = extractICSDateTime(override, 'DTEND');
          if (ovStart) {
            candidate = ovStart;
            instanceEnd = ovEnd || new Date(ovStart.getTime() + duration);
          }
          var ovTitle = extractICSField(override, 'SUMMARY');
          if (ovTitle) instanceTitle = BLOCKER_PREFIX + ovTitle;
          instanceFree = isFreeEvent(override);
          instanceTentative = isTentativeEvent(override);
        }

        instances.push({
          uid: uid + '_' + candidate.getTime(),
          title: instanceTitle || BLOCKER_TITLE_FALLBACK,
          start: candidate,
          end: instanceEnd,
          isAllDay: isAllDay,
          isFree: instanceFree,
          isTentative: instanceTentative
        });
      }
    }

    cursor = advanceCursor(cursor, freq, interval, isAllDay);
  }

  return instances;
}

function parseRRuleParts(rrule) {
  var parts = {};
  var pairs = rrule.split(';');
  for (var i = 0; i < pairs.length; i++) {
    var kv = pairs[i].split('=');
    if (kv.length === 2) parts[kv[0]] = kv[1];
  }
  return parts;
}

function getCandidatesForPeriod(cursor, freq, byDay, byMonthDay, dtStart, isAllDay) {
  if (freq === 'WEEKLY' && byDay) {
    return getWeekDayCandidates(cursor, byDay, dtStart, isAllDay);
  }
  if (freq === 'MONTHLY' && byMonthDay) {
    return getMonthDayCandidates(cursor, byMonthDay, dtStart, isAllDay);
  }
  if (freq === 'MONTHLY' && byDay) {
    return getMonthByDayCandidates(cursor, byDay, dtStart, isAllDay);
  }
  return [new Date(cursor.getTime())];
}

function getWeekDayCandidates(weekStart, byDay, dtStart, isAllDay) {
  var dayMap = {'SU': 0, 'MO': 1, 'TU': 2, 'WE': 3, 'TH': 4, 'FR': 5, 'SA': 6};
  var candidates = [];

  var monday = new Date(weekStart.getTime());
  var dow = monday.getDay();
  var diff = dow === 0 ? -6 : 1 - dow;
  monday.setDate(monday.getDate() + diff);

  for (var i = 0; i < byDay.length; i++) {
    var targetDay = dayMap[byDay[i].replace(/^[+-]?\d+/, '')];
    if (targetDay === undefined) continue;

    var candidate = new Date(monday.getTime());
    var daysToAdd = targetDay === 0 ? 6 : targetDay - 1;
    candidate.setDate(candidate.getDate() + daysToAdd);

    if (isAllDay) {
      candidate.setHours(0, 0, 0, 0);
    } else {
      candidate.setHours(dtStart.getHours(), dtStart.getMinutes(), dtStart.getSeconds(), 0);
    }

    candidates.push(candidate);
  }

  candidates.sort(function(a, b) { return a.getTime() - b.getTime(); });
  return candidates;
}

function getMonthDayCandidates(cursor, byMonthDay, dtStart, isAllDay) {
  var candidates = [];
  var year = cursor.getFullYear();
  var month = cursor.getMonth();
  var daysInMonth = new Date(year, month + 1, 0).getDate();

  for (var i = 0; i < byMonthDay.length; i++) {
    var day = byMonthDay[i];
    if (day < 0) day = daysInMonth + day + 1;
    if (day < 1 || day > daysInMonth) continue;

    var candidate = new Date(year, month, day);
    if (!isAllDay) {
      candidate.setHours(dtStart.getHours(), dtStart.getMinutes(), dtStart.getSeconds(), 0);
    }
    candidates.push(candidate);
  }

  candidates.sort(function(a, b) { return a.getTime() - b.getTime(); });
  return candidates;
}

function getMonthByDayCandidates(cursor, byDay, dtStart, isAllDay) {
  var dayMap = {'SU': 0, 'MO': 1, 'TU': 2, 'WE': 3, 'TH': 4, 'FR': 5, 'SA': 6};
  var candidates = [];
  var year = cursor.getFullYear();
  var month = cursor.getMonth();

  for (var i = 0; i < byDay.length; i++) {
    var match = byDay[i].match(/^([+-]?\d+)?([A-Z]{2})$/);
    if (!match) continue;

    var nth = match[1] ? parseInt(match[1]) : 1;
    var targetDay = dayMap[match[2]];
    if (targetDay === undefined) continue;

    var candidate;
    if (nth > 0) {
      var first = new Date(year, month, 1);
      var firstDow = first.getDay();
      var daysUntil = (targetDay - firstDow + 7) % 7;
      candidate = new Date(year, month, 1 + daysUntil + (nth - 1) * 7);
    } else {
      var last = new Date(year, month + 1, 0);
      var lastDow = last.getDay();
      var daysBack = (lastDow - targetDay + 7) % 7;
      candidate = new Date(year, month + 1, -daysBack + (nth + 1) * 7);
    }

    if (candidate.getMonth() !== month) continue;

    if (!isAllDay) {
      candidate.setHours(dtStart.getHours(), dtStart.getMinutes(), dtStart.getSeconds(), 0);
    }
    candidates.push(candidate);
  }

  candidates.sort(function(a, b) { return a.getTime() - b.getTime(); });
  return candidates;
}

function advanceCursor(cursor, freq, interval, isAllDay) {
  var next = new Date(cursor.getTime());
  switch (freq) {
    case 'DAILY':
      next.setDate(next.getDate() + interval);
      break;
    case 'WEEKLY':
      next.setDate(next.getDate() + 7 * interval);
      break;
    case 'MONTHLY':
      next.setMonth(next.getMonth() + interval);
      break;
    case 'YEARLY':
      next.setFullYear(next.getFullYear() + interval);
      break;
  }
  return next;
}

// --- ICS Field Extraction ---

function extractICSField(block, fieldName) {
  var lines = block.split(/\r?\n/);
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i];
    if (line.indexOf(fieldName + ':') === 0) {
      return line.substring(fieldName.length + 1).trim();
    }
    if (line.indexOf(fieldName + ';') === 0) {
      var colonIdx = line.indexOf(':');
      if (colonIdx !== -1) return line.substring(colonIdx + 1).trim();
    }
  }
  return null;
}

function extractICSDateTime(block, fieldName) {
  var lines = block.split(/\r?\n/);
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i];
    if (line.indexOf(fieldName) !== 0) continue;

    var colonIdx = line.indexOf(':');
    if (colonIdx === -1) continue;
    var value = line.substring(colonIdx + 1).trim();
    return parseICSDateValue(value);
  }
  return null;
}

function parseICSDateValue(value) {
  if (!value) return null;

  // VALUE=DATE format: 20260408
  if (value.length === 8 && /^\d{8}$/.test(value)) {
    return new Date(
      parseInt(value.substr(0, 4)),
      parseInt(value.substr(4, 2)) - 1,
      parseInt(value.substr(6, 2))
    );
  }

  // Full datetime: 20260408T143000Z or 20260408T143000
  var match = value.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(Z?)$/);
  if (match) {
    if (match[7] === 'Z') {
      return new Date(Date.UTC(
        parseInt(match[1]), parseInt(match[2]) - 1, parseInt(match[3]),
        parseInt(match[4]), parseInt(match[5]), parseInt(match[6])
      ));
    } else {
      return new Date(
        parseInt(match[1]), parseInt(match[2]) - 1, parseInt(match[3]),
        parseInt(match[4]), parseInt(match[5]), parseInt(match[6])
      );
    }
  }

  return null;
}

function isAllDayEvent(block) {
  return block.indexOf('VALUE=DATE') !== -1 && block.indexOf('VALUE=DATE-TIME') === -1;
}

// --- Enterprise Calendar Operations ---

function getExistingBlockers(startDate, endDate) {
  var blockerMap = {};
  var pageToken = null;

  do {
    var resp = Calendar.Events.list(CAL_ID, {
      timeMin: startDate.toISOString(),
      timeMax: endDate.toISOString(),
      q: BLOCKER_TAG,
      singleEvents: true,
      showDeleted: false,
      maxResults: 2500,
      pageToken: pageToken
    });
    var items = resp.items || [];
    for (var i = 0; i < items.length; i++) {
      var id = extractPersonalEventId(items[i].description);
      if (id) {
        blockerMap[id] = items[i];
      }
    }
    pageToken = resp.nextPageToken;
  } while (pageToken);

  return blockerMap;
}

function extractPersonalEventId(description) {
  if (!description) return null;
  var startIdx = description.indexOf(BLOCKER_TAG);
  if (startIdx === -1) return null;
  var endIdx = description.indexOf(']', startIdx);
  if (endIdx === -1) return null;
  return description.substring(startIdx + BLOCKER_TAG.length, endIdx);
}

// Builds the advanced Calendar API event resource for a blocker. Classic CalendarApp
// can't set free/busy transparency or tentative status, which is why we use Calendar.Events.
function buildBlockerResource(pe) {
  var tz = Session.getScriptTimeZone();
  var resource = {
    summary: pe.title,
    description: BLOCKER_TAG + pe.uid + ']',
    visibility: 'private',
    colorId: BLOCKER_COLOR_ID,
    transparency: pe.isFree ? 'transparent' : 'opaque',
    status: pe.isTentative ? 'tentative' : 'confirmed',
    reminders: {useDefault: false, overrides: []}
  };

  if (pe.isAllDay) {
    // All-day events use exclusive end dates; ICS DTEND is already exclusive.
    resource.start = {date: Utilities.formatDate(pe.start, tz, 'yyyy-MM-dd')};
    resource.end = {date: Utilities.formatDate(pe.end, tz, 'yyyy-MM-dd')};
  } else {
    resource.start = {dateTime: Utilities.formatDate(pe.start, tz, "yyyy-MM-dd'T'HH:mm:ss"), timeZone: tz};
    resource.end = {dateTime: Utilities.formatDate(pe.end, tz, "yyyy-MM-dd'T'HH:mm:ss"), timeZone: tz};
  }

  return resource;
}

function createBlocker(pe) {
  var created = Calendar.Events.insert(buildBlockerResource(pe), CAL_ID);
  Logger.log('Created blocker: ' + pe.title + ' @ ' + pe.start + statusDebug(pe));
  return created;
}

// Debug suffix flagging source events that carry Free/Tentative intent, so the
// Executions log shows when a blocker is anything other than plain Busy.
function statusDebug(pe) {
  var flags = [];
  if (pe.isFree) flags.push('FREE (transparent)');
  if (pe.isTentative) flags.push('TENTATIVE');
  return flags.length ? ' [' + flags.join(' + ') + ']' : '';
}

function updateBlockerIfNeeded(blocker, pe) {
  var desired = buildBlockerResource(pe);
  var patch = {};
  var changed = false;

  if (!sameInstant(blocker.start, desired.start) || !sameInstant(blocker.end, desired.end)) {
    patch.start = desired.start;
    patch.end = desired.end;
    changed = true;
  }
  if (blocker.summary !== desired.summary) {
    patch.summary = desired.summary;
    changed = true;
  }
  if (blocker.colorId !== desired.colorId) {
    patch.colorId = desired.colorId;
    changed = true;
  }
  // Google omits transparency when opaque (the default), so treat missing as opaque.
  if ((blocker.transparency || 'opaque') !== desired.transparency) {
    patch.transparency = desired.transparency;
    changed = true;
  }
  if ((blocker.status || 'confirmed') !== desired.status) {
    patch.status = desired.status;
    changed = true;
  }

  if (changed) {
    Calendar.Events.patch(patch, CAL_ID, blocker.id);
    var flippedFree = (blocker.transparency || 'opaque') !== desired.transparency;
    var flippedTentative = (blocker.status || 'confirmed') !== desired.status;
    var transition = (flippedFree || flippedTentative) ? ' <- status changed' : '';
    Logger.log('Updated blocker: ' + pe.title + ' @ ' + pe.start + statusDebug(pe) + transition);
  }
}

// Compares two advanced-API event time objects as absolute instants, so the API's
// offset-qualified dateTime (e.g. ...-07:00) matches our tz-qualified local dateTime.
function sameInstant(t1, t2) {
  var m1 = eventTimeMillis(t1);
  var m2 = eventTimeMillis(t2);
  return m1 !== null && m1 === m2;
}

function eventTimeMillis(t) {
  if (!t) return null;
  if (t.dateTime) return new Date(t.dateTime).getTime();
  if (t.date) return new Date(t.date + 'T00:00:00').getTime();
  return null;
}

// --- Entry Points ---

function initialSync() {
  Logger.log('Running initial sync...');
  syncCalendar();
  Logger.log('Initial sync complete. Check your enterprise calendar.');
}

function cleanupAllBlockers() {
  var now = new Date();
  var endDate = new Date(now.getTime() + SYNC_DAYS_AHEAD * 24 * 60 * 60 * 1000);
  var blockers = getExistingBlockers(now, endDate);

  var count = 0;
  for (var id in blockers) {
    Calendar.Events.remove(CAL_ID, blockers[id].id);
    count++;
    if (count % BATCH_SIZE === 0) {
      Utilities.sleep(BATCH_PAUSE_MS);
    }
  }

  Logger.log('Cleaned up ' + count + ' blocker events.');
}
