// ============================================================
// Personal → Enterprise Calendar Busy Blocker Sync (v3 - RRULE)
// ============================================================
// Uses private iCal URL to bypass enterprise restrictions.
// Expands recurring events (RRULE) into individual instances.
//
// Setup:
// 1. Get your personal calendar's secret iCal URL:
//    Personal Gmail → Calendar Settings → your calendar → Integrate calendar
//    → Copy "Secret address in iCal format"
// 2. Run setPersonalIcalUrl('YOUR_URL_HERE') once to store it in Script Properties
// 3. Run initialSync() once to grant permissions
// 4. Add time-driven trigger: syncCalendar every 15 minutes
// ============================================================
var ICAL_URL_KEY = 'PERSONAL_ICAL_URL';

var BLOCKER_TAG = '[PERSONAL_SYNC:';
var BLOCKER_PREFIX = '[P] ';
var BLOCKER_TITLE_FALLBACK = 'Personal (Busy)';
var SYNC_DAYS_AHEAD = 30;

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

  var enterpriseCal = CalendarApp.getDefaultCalendar();
  var existingBlockers = getExistingBlockers(enterpriseCal, startDate, endDate);

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
      createBlocker(enterpriseCal, pe);
      created++;
      if (created % BATCH_SIZE === 0) {
        Logger.log('Created ' + created + ' blockers, pausing...');
        Utilities.sleep(BATCH_PAUSE_MS);
      }
    }
  }

  for (var staleId in existingBlockers) {
    existingBlockers[staleId].deleteEvent();
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

    if (rrule) {
      var masterTitle = extractICSField(block, 'SUMMARY');
      var instances = expandRRule(rrule, dtStart, duration, isAllDay, exdates, startDate, endDate, uid, overridesByUid[uid] || {}, masterTitle);
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
          isAllDay: isAllDay
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
  var lines = block.split(/\r?\n/);
  for (var i = 0; i < lines.length; i++) {
    if (lines[i].indexOf('ATTENDEE') !== 0) continue;
    if (lines[i].indexOf('PARTSTAT=DECLINED') !== -1 &&
        lines[i].toLowerCase().indexOf('abutala@gmail.com') !== -1) {
      return true;
    }
  }
  return false;
}

// --- RRULE Expansion ---

function expandRRule(rrule, dtStart, duration, isAllDay, exdates, windowStart, windowEnd, uid, overrides, masterTitle) {
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
        var override = overrides[candidate.getTime()];
        if (override) {
          var ovStart = extractICSDateTime(override, 'DTSTART');
          var ovEnd = extractICSDateTime(override, 'DTEND');
          var ovStatus = extractICSField(override, 'STATUS');
          if (ovStatus && ovStatus.toUpperCase() === 'CANCELLED') continue;
          if (isDeclinedEvent(override)) continue;
          if (ovStart) {
            candidate = ovStart;
            instanceEnd = ovEnd || new Date(ovStart.getTime() + duration);
          }
          var ovTitle = extractICSField(override, 'SUMMARY');
          if (ovTitle) instanceTitle = BLOCKER_PREFIX + ovTitle;
        }

        instances.push({
          uid: uid + '_' + candidate.getTime(),
          title: instanceTitle || BLOCKER_TITLE_FALLBACK,
          start: candidate,
          end: instanceEnd,
          isAllDay: isAllDay
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

function getExistingBlockers(calendar, startDate, endDate) {
  var events = calendar.getEvents(startDate, endDate, {search: BLOCKER_TAG});
  var blockerMap = {};

  for (var i = 0; i < events.length; i++) {
    var desc = events[i].getDescription();
    var id = extractPersonalEventId(desc);
    if (id) {
      blockerMap[id] = events[i];
    }
  }

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

function createBlocker(enterpriseCal, pe) {
  var description = BLOCKER_TAG + pe.uid + ']';
  var blocker;

  if (pe.isAllDay) {
    blocker = enterpriseCal.createAllDayEvent(pe.title, pe.start, pe.end);
  } else {
    blocker = enterpriseCal.createEvent(pe.title, pe.start, pe.end);
  }

  blocker.setDescription(description);
  blocker.setColor(CalendarApp.EventColor.RED);
  blocker.setVisibility(CalendarApp.Visibility.PRIVATE);
  blocker.removeAllReminders();

  Logger.log('Created blocker: ' + pe.title + ' @ ' + pe.start);
  return blocker;
}

function updateBlockerIfNeeded(blocker, pe) {
  var changed = false;

  if (pe.isAllDay) {
    if (blocker.getAllDayStartDate().getTime() !== pe.start.getTime() ||
        blocker.getAllDayEndDate().getTime() !== pe.end.getTime()) {
      blocker.setAllDayDates(pe.start, pe.end);
      changed = true;
    }
  } else {
    if (blocker.getStartTime().getTime() !== pe.start.getTime() ||
        blocker.getEndTime().getTime() !== pe.end.getTime()) {
      blocker.setTime(pe.start, pe.end);
      changed = true;
    }
  }

  if (blocker.getTitle() !== pe.title) {
    blocker.setTitle(pe.title);
    changed = true;
  }

  if (blocker.getColor() !== CalendarApp.EventColor.RED) {
    blocker.setColor(CalendarApp.EventColor.RED);
    changed = true;
  }

  if (changed) {
    Logger.log('Updated blocker: ' + pe.title + ' @ ' + pe.start);
  }
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
  var enterpriseCal = CalendarApp.getDefaultCalendar();
  var blockers = enterpriseCal.getEvents(now, endDate, {search: BLOCKER_TAG});

  for (var i = 0; i < blockers.length; i++) {
    if (extractPersonalEventId(blockers[i].getDescription())) {
      blockers[i].deleteEvent();
    }
  }

  Logger.log('Cleaned up ' + blockers.length + ' blocker events.');
}
