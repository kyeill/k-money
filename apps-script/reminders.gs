/**
 * K Money reminders -> ntfy.
 *
 * This is the ONLY thing that sends notifications. The K Money page is a view;
 * a static site cannot wake a phone. Paste this into the Apps Script editor
 * bound to the reminders Sheet (Extensions -> Apps Script), fill in TOPIC
 * below, then run setup() once.
 *
 * The rules here must match reminders.py in the k-money repo. If you change
 * one, change both -- selftest.py and the browser cross-check compare the
 * Python and JS copies, but nothing can reach in here and check this one.
 */

// ---------------------------------------------------------------- settings

// 'pushover' or 'ntfy'.
//
// ntfy.sh was the first choice and does not work from here. Its free tier
// meters per SOURCE IP, and Apps Script egresses from shared Google
// infrastructure, so the daily quota is spent by thousands of other people's
// scripts before you send anything:
//
//   429  {"code":42908,"error":"limit reached: daily message quota reached"}
//
// Nothing in this file can fix that -- it is not your usage. Pushover is a
// paid, per-account service built for server-side senders, so its limits are
// yours alone. The ntfy path is kept below because it works fine from a normal
// machine, and because a self-hosted or paid ntfy would work from here too.
var PROVIDER = 'pushover';

// Pushover: both come from pushover.net once you have an account. The user key
// is on the dashboard; the app token comes from creating an Application.
var PUSHOVER_USER = 'PUT-YOUR-PUSHOVER-USER-KEY-HERE';
var PUSHOVER_TOKEN = 'PUT-YOUR-PUSHOVER-APP-TOKEN-HERE';

// ntfy: anyone who knows this string can read your reminders AND send
// notifications to your phone, so keep it out of the public repo -- it lives
// here, in a script bound to your private Sheet, and nowhere else.
var TOPIC = 'PUT-YOUR-NTFY-TOPIC-HERE';

var TZ = 'America/New_York';   // times in the Sheet are read as this zone
var GRACE_MINUTES = 15;        // how late a reminder may fire before it is skipped

// Ticks live in a second tab so every device sees them and this script can too.
// setup() creates it; nothing to do by hand.
var REMINDERS_TAB = 'Reminders';
var DONE_TAB = 'Done';
var DONE_HEADER = ['Date', 'Key', 'Done', 'Updated'];
var KEEP_DONE_DAYS = 30;       // older rows are pruned on write

// ------------------------------------------------------------------ setup

/** Run once. Installs the 5-minute trigger and asks for authorisation. */
function setup() {
  // Prove credentials work before installing a trigger that would otherwise
  // fail silently every five minutes.
  push('K Money', 'Reminders are set up. This is the only message you get now.');
  // Clear ours first, or every re-run adds another trigger and every reminder
  // fires twice.
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'tick') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('tick').timeBased().everyMinutes(5).create();
  doneSheet(true);          // create the Done tab if it is not there yet
  Logger.log('Trigger installed, Done tab ready. Checking every 5 minutes.');
  Logger.log('Now deploy this as a web app so the page can tick things off:');
  Logger.log('  Deploy > New deployment > Web app,'
             + ' execute as ME, access ANYONE, then put the /exec URL into'
             + ' config.json as reminders_webapp.');
}

/** Run by hand to prove the pipe works without waiting for a real reminder. */
function sendTest() {
  push('K Money test', 'If you can see this, notifications are working.');
  Logger.log('Sent. Check your phone.');
}

/**
 * Run by hand when Pushover refuses the credentials.
 *
 * The two keys are both ~30 characters and come from different pages, so
 * swapping them is the obvious mistake -- and the API's own validate endpoint
 * settles it without either value leaving this script.
 */
function checkCredentials() {
  Logger.log('user  : %s chars, starts "%s"  (dashboard key, usually u...)',
             PUSHOVER_USER.length, PUSHOVER_USER.charAt(0));
  Logger.log('token : %s chars, starts "%s"  (Application token, usually a...)',
             PUSHOVER_TOKEN.length, PUSHOVER_TOKEN.charAt(0));
  if (PUSHOVER_USER !== PUSHOVER_USER.trim() ||
      PUSHOVER_TOKEN !== PUSHOVER_TOKEN.trim()) {
    Logger.log('WARNING: one of them has leading or trailing whitespace.');
  }
  if (PUSHOVER_USER.charAt(0) === 'a' && PUSHOVER_TOKEN.charAt(0) === 'u') {
    Logger.log('LIKELY SWAPPED: these look the wrong way round.');
  }
  var r = UrlFetchApp.fetch('https://api.pushover.net/1/users/validate.json', {
    method: 'post',
    payload: {token: PUSHOVER_TOKEN, user: PUSHOVER_USER},
    muteHttpExceptions: true
  });
  Logger.log('validate: HTTP %s  %s',
             r.getResponseCode(), r.getContentText().slice(0, 300));
}

/**
 * Run by hand when a send reports success but nothing arrives.
 *
 * push() hides the status once it is happy; this prints it. ntfy accepts any
 * string as a topic and answers 200, so "no error" has never meant "delivered"
 * -- and ntfy.sh rate-limits per source IP, which on Apps Script is shared
 * Google infrastructure, so a 429 here can be somebody else's traffic.
 */
function probe() {
  Logger.log('provider: %s', PROVIDER);
  var r;
  if (PROVIDER === 'pushover') {
    r = UrlFetchApp.fetch('https://api.pushover.net/1/messages.json', {
      method: 'post',
      payload: {token: PUSHOVER_TOKEN, user: PUSHOVER_USER,
                title: 'K Money probe', message: 'probe from apps script'},
      muteHttpExceptions: true
    });
  } else {
    r = UrlFetchApp.fetch('https://ntfy.sh/' + TOPIC, {
      method: 'post',
      payload: 'probe from apps script',
      headers: {'Title': 'K Money probe'},
      muteHttpExceptions: true
    });
  }
  Logger.log('status  : %s', r.getResponseCode());
  Logger.log('body    : %s', r.getContentText().slice(0, 400));
}

/**
 * Run by hand when a send fails with "Address unavailable".
 *
 * That error is a CONNECTION failure, not an HTTP status -- muteHttpExceptions
 * would have swallowed a 4xx or 5xx. So the question is which layer is broken,
 * and example.com is the control: if that fails too, Apps Script cannot reach
 * anything; if only the ntfy rows fail, Google cannot reach ntfy specifically
 * and the answer is a different delivery service, not a different URL.
 */
function diagnose() {
  var tries = [
    ['control (example.com)', 'https://example.com/'],
    ['ntfy health          ', 'https://ntfy.sh/v1/health'],
    ['your topic           ', 'https://ntfy.sh/' + TOPIC + '/json?poll=1']
  ];
  tries.forEach(function (t) {
    var began = new Date().getTime();
    try {
      var r = UrlFetchApp.fetch(t[1], {muteHttpExceptions: true});
      Logger.log('%s  OK    HTTP %s  (%sms)',
                 t[0], r.getResponseCode(), new Date().getTime() - began);
    } catch (err) {
      Logger.log('%s  FAIL  %s  (%sms)', t[0], err, new Date().getTime() - began);
    }
  });
}

/** Run by hand to see what today looks like without sending anything. */
function preview() {
  var rules = readRules();
  var today = new Date();
  Logger.log('%s rule(s) in the sheet', rules.length);
  rules.forEach(function (r) {
    Logger.log('  %s  %s  fires today: %s',
               pad(r.hour) + ':' + pad(r.minute), r.title, firesOn(r, today));
  });
}

// ------------------------------------------------------------------ input

var WD = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
var WORDN = {first: 1, second: 2, third: 3, fourth: 4, fifth: 5, last: -1};

/**
 * A LIST of occurrences: "1st, 3rd" is two of them, "Second" is one.
 *
 * This used to return a single number by stripping non-digits, which made
 * "1st, 3rd" into 13 -- and no month has a thirteenth Tuesday, so those
 * reminders fired NEVER. Word forms parsed to nothing, which dropped the row
 * out of monthly entirely and fell back to its weekly ticks, firing four or
 * five times a month instead of once. Both failed in silence.
 */
function parseNths(t) {
  t = String(t || '').trim().toLowerCase();
  if (!t) return [];
  var out = [];
  t.replace(/,/g, ' ').split(/\s+/).forEach(function (p) {
    if (!p) return;
    var v;
    if (WORDN[p] !== undefined) {
      v = WORDN[p];
    } else {
      var d = p.replace(/[^0-9]/g, '');
      v = d ? parseInt(d, 10) : null;
      if (v !== null && (v < 1 || v > 31)) v = null;
    }
    if (v !== null && v !== undefined && out.indexOf(v) < 0) out.push(v);
  });
  return out;
}
var MO = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
          'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
// Columns up to and including nth are fixed. The Weekday column after them is
// OPTIONAL -- both layouts are accepted, because the sheet gets edited while
// this is live and a schema change must not take the notifications down.
// Title, Time and the seven day columns are positional. EVERYTHING after them
// is located BY NAME, so columns can be added, removed or reordered without
// breaking anything -- hard-coded indices have taken this system down twice.
var EXPECT = ['title', 'time', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
var OPTIONAL = ['nth', 'weekday', 'every', 'starting', 'months'];

function readRules() {
  // BY NAME, not position. There are other tabs in this spreadsheet now, and
  // reordering them would otherwise silently point this at the wrong one. The
  // fallback keeps it working if the tab is renamed -- the header check below
  // is what actually guarantees we are reading reminders and not something
  // else.
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(REMINDERS_TAB) || ss.getSheets()[0];
  // Display values, not raw ones: a time cell read raw comes back as a Date on
  // the 1899-12-30 epoch, which is a different parsing problem in every
  // timezone. The displayed "12:30 PM" is also exactly what the CSV endpoint
  // gives the web page, so both sides parse the same string.
  var grid = sheet.getDataRange().getDisplayValues();
  if (!grid.length) throw new Error('the sheet is empty');

  // Match on the FIRST WORD of each heading. He labels sections in the sheet
  // and put one in the header cell itself -- A1 read "Title DAILY", which broke
  // every reader at once: the page showed an error and nothing could fire.
  // Being forgiving about a label costs nothing and still refuses the Done tab,
  // whose first heading is "date".
  var header = grid[0].map(function (h) {
    return String(h).trim().toLowerCase().split(/\s+/)[0];
  });
  for (var i = 0; i < EXPECT.length; i++) {
    if (header[i] !== EXPECT[i]) {
      throw new Error('unexpected column ' + (i + 1) + ': found "' + header[i] +
                      '", expected "' + EXPECT[i] + '"');
    }
  }
  var COL = {};
  for (var h = EXPECT.length; h < header.length; h++) {
    if (OPTIONAL.indexOf(header[h]) >= 0 && COL[header[h]] === undefined) {
      COL[header[h]] = h;
    }
  }
  function cell(row, name) {
    var i = COL[name];
    return (i === undefined || i >= row.length) ? '' : row[i];
  }

  var rules = [];
  for (var r = 1; r < grid.length; r++) {
    var c = grid[r].map(function (x) { return String(x == null ? '' : x).trim(); });
    while (c.length < header.length) c.push('');
    var at = parseTime(c[1]);
    if (!c[0] || !at) continue;          // a reminder with no time cannot fire
    var nths = parseNths(cell(c, 'nth'));
    var weekday = title3(cell(c, 'weekday'));
    var every = parseEvery(cell(c, 'every'));
    var start = parseDate(cell(c, 'starting'));
    var days = [];
    for (var d = 0; d < 7; d++) if (c[2 + d]) days.push(d);
    // "4th" with Sun ticked and Weekday left blank is the obvious intent, and
    // it is the natural way to write it. Without this the nth is silently
    // dropped and the row fires EVERY Sunday -- four times too often.
    // One day ticked means that weekday; none ticked means day of the month,
    // which is what lets the Weekday column be deleted entirely.
    if (nths.length && weekday === '') {
      if (days.length === 1) weekday = WD[days[0]];
      else if (!days.length) weekday = 'Day';
    }
    rules.push({
      title: c[0], hour: at[0], minute: at[1], days: days,
      nths: nths, weekday: weekday,
      every: every, start: start,
      months: parseMonths(cell(c, 'months')),
      monthly: (nths.length > 0 && weekday !== '')
    });
  }
  return rules;
}

function title3(s) {
  s = String(s || '').trim();
  return s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : '';
}

function parseTime(t) {
  t = String(t || '').trim().toUpperCase().replace(/\./g, '');
  if (!t) return null;
  var suffix = null;
  if (/AM$/.test(t)) { suffix = 'AM'; t = t.slice(0, -2).trim(); }
  else if (/PM$/.test(t)) { suffix = 'PM'; t = t.slice(0, -2).trim(); }
  var bits = t.split(':');
  var h = parseInt(bits[0], 10);
  var m = bits.length > 1 ? parseInt(bits[1], 10) : 0;
  if (isNaN(h) || isNaN(m) || m < 0 || m > 59) return null;
  if (suffix === 'PM' && h < 12) h += 12;
  else if (suffix === 'AM' && h === 12) h = 0;
  return (h >= 0 && h < 24) ? [h, m] : null;
}

/** "4 weeks" -> 28. A unit is required; a bare number could mean either. */
function parseEvery(t) {
  t = String(t || '').trim().toLowerCase();
  var d = t.replace(/[^0-9]/g, '');
  if (!d) return null;
  var n = parseInt(d, 10);
  if (n < 1) return null;
  var letters = t.replace(/[^a-z]/g, '');
  if (letters.charAt(0) === 'w') return n * 7;
  if (letters.charAt(0) === 'd') return n;
  return null;
}

/** Sheets renders dates in the viewer's locale, so ISO and US slash both. */
function parseDate(t) {
  t = String(t || '').trim();
  if (!t) return null;
  var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(t);
  if (m) return new Date(+m[1], +m[2] - 1, +m[3]);
  m = /^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/.exec(t);
  if (m) { var y = +m[3]; if (y < 100) y += 2000; return new Date(y, +m[1] - 1, +m[2]); }
  return null;
}

function dayNum(d) {
  return Math.floor(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / 864e5);
}

function parseMonths(t) {
  t = String(t || '').trim();
  var all = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];
  if (!t || t.toLowerCase() === 'all') return all;
  if (t.toLowerCase() === 'quarterly') return [1, 4, 7, 10];
  var out = [];
  t.replace(/,/g, ' ').split(/\s+/).forEach(function (p) {
    if (!p) return;
    var i = MO.indexOf(title3(p.slice(0, 3)));
    if (i >= 0 && out.indexOf(i + 1) < 0) out.push(i + 1);
  });
  return out.length ? out : all;
}

// ------------------------------------------------------------------ rules

/** Sheet and Python are Monday-first; JavaScript's getDay() is Sunday-first. */
function weekdayOf(date) { return (date.getDay() + 6) % 7; }
function daysIn(y, m) { return new Date(y, m, 0).getDate(); }

function nthWeekday(y, m, target, nth) {
  var first = new Date(y, m - 1, 1);
  var offset = (target - weekdayOf(first) + 7) % 7;
  var total = daysIn(y, m);
  var day = (nth === -1)
    ? 1 + offset + Math.floor((total - 1 - offset) / 7) * 7
    : 1 + offset + (nth - 1) * 7;
  return (day >= 1 && day <= total) ? day : null;
}

function firesOn(rule, date) {
  // Ask the calendar in OUR timezone, not the server's.
  var y = Number(Utilities.formatDate(date, TZ, 'yyyy'));
  var m = Number(Utilities.formatDate(date, TZ, 'MM'));
  var d = Number(Utilities.formatDate(date, TZ, 'dd'));
  var local = new Date(y, m - 1, d);

  // Months gates BOTH kinds of rule, so "Sat ticked, Months = Sep, Oct, Nov,
  // Dec" is a weekly reminder with a season. A blank Months means all twelve,
  // so existing rows are unaffected.
  if (rule.months.indexOf(m) < 0) return false;

  // Interval beats everything; whole days from the anchor, so DST cannot
  // drift it.
  if (rule.every && rule.start) {
    var a = dayNum(rule.start), b = dayNum(local);
    return b >= a && ((b - a) % rule.every) === 0;
  }
  if (rule.monthly) {
    // A row with both a monthly rule and weekly ticks is monthly. One row,
    // one schedule.
    var i;
    if (rule.weekday === 'Day') {
      for (i = 0; i < rule.nths.length; i++) {
        var want = (rule.nths[i] === -1) ? daysIn(y, m) : rule.nths[i];
        if (want >= 1 && want <= daysIn(y, m) && want === d) return true;
      }
      return false;
    }
    var target = WD.indexOf(rule.weekday);
    if (target < 0) return false;
    for (i = 0; i < rule.nths.length; i++) {
      if (nthWeekday(y, m, target, rule.nths[i]) === d) return true;
    }
    return false;
  }
  return rule.days.indexOf(weekdayOf(local)) >= 0;
}

// ------------------------------------------------------------ done ticks

/**
 * The identity of one occurrence: "Laundry@12:30".
 *
 * The SAME string is built by reminders.py and by the page's JS. If this
 * changes, all three change, or a tick made on the page stops matching the
 * reminder it was meant to silence.
 */
function doneKey(rule) {
  return rule.title + '@' + pad(rule.hour) + ':' + pad(rule.minute);
}

function doneSheet(create) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(DONE_TAB);
  if (!sheet && create) {
    sheet = ss.insertSheet(DONE_TAB);
    sheet.getRange(1, 1, 1, DONE_HEADER.length).setValues([DONE_HEADER]);
  }
  return sheet;
}

/** {"2026-08-30|Laundry@12:30": true} for everything currently ticked. */
function loadDone() {
  var sheet = doneSheet(false);
  var out = {};
  if (!sheet) return out;
  var grid = sheet.getDataRange().getDisplayValues();
  for (var r = 1; r < grid.length; r++) {
    var date = String(grid[r][0] || '').trim();
    var key = String(grid[r][1] || '').trim();
    if (date && key && String(grid[r][2] || '').trim()) {
      out[date + '|' + key] = true;
    }
  }
  return out;
}

/**
 * Record (or clear) one tick. Returns true if it was accepted.
 *
 * The web app is public, so this validates rather than trusting: the date has
 * to look like a date and be within a couple of days, and the key has to match
 * a reminder that actually exists. That bounds what a stranger who finds the
 * URL can do to "toggle one of Kyle's checkboxes" rather than "append anything
 * to the sheet forever".
 */
function setDone(date, key, done) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(date || ''))) return false;
  var today = Utilities.formatDate(new Date(), TZ, 'yyyy-MM-dd');
  if (Math.abs(dayDiff(date, today)) > 2) return false;

  var known = false;
  readRules().forEach(function (r) { if (doneKey(r) === key) known = true; });
  if (!known) return false;

  var sheet = doneSheet(true);
  var grid = sheet.getDataRange().getDisplayValues();
  var stamp = Utilities.formatDate(new Date(), TZ, 'yyyy-MM-dd HH:mm');
  for (var r = 1; r < grid.length; r++) {
    if (String(grid[r][0]).trim() === date && String(grid[r][1]).trim() === key) {
      sheet.getRange(r + 1, 3, 1, 2).setValues([[done ? 'x' : '', stamp]]);
      return true;
    }
  }
  sheet.appendRow([date, key, done ? 'x' : '', stamp]);
  pruneDone(sheet);
  return true;
}

/** Keeps the tab bounded: one row per reminder per day, 30 days back. */
function pruneDone(sheet) {
  var cutoff = Utilities.formatDate(
    new Date(new Date().getTime() - KEEP_DONE_DAYS * 86400000), TZ, 'yyyy-MM-dd');
  var grid = sheet.getDataRange().getDisplayValues();
  for (var r = grid.length - 1; r >= 1; r--) {
    if (String(grid[r][0]).trim() < cutoff) sheet.deleteRow(r + 1);
  }
}

function dayDiff(a, b) {
  return Math.round((new Date(a + 'T00:00:00Z') - new Date(b + 'T00:00:00Z')) / 86400000);
}

/**
 * The public endpoint the page calls when you tick a box.
 *
 * The page fetches this with mode:'no-cors' and ignores the response -- an
 * Apps Script web app redirects, which browsers will not follow for a
 * cross-origin readable request. The tick is therefore fire-and-forget, and
 * the Sheet is reconciled on the page's next read.
 */
function doGet(e) {
  var p = (e && e.parameter) || {};
  var out = {ok: false};
  try {
    if (p.action === 'done') {
      out.ok = setDone(p.date, p.key, p.done === '1');
    } else {
      out.error = 'unknown action';
    }
  } catch (err) {
    out.error = String(err);
  }
  return ContentService.createTextOutput(JSON.stringify(out))
    .setMimeType(ContentService.MimeType.JSON);
}

// ----------------------------------------------------------------- firing

/** The 5-minute trigger lands here. */
function tick() {
  var now = new Date();
  var today = Utilities.formatDate(now, TZ, 'yyyy-MM-dd');
  var minutesNow = Number(Utilities.formatDate(now, TZ, 'HH')) * 60 +
                   Number(Utilities.formatDate(now, TZ, 'mm'));

  var rules;
  try {
    rules = readRules();
  } catch (err) {
    // Tell someone rather than failing silently -- but ONCE A DAY, not every
    // five minutes. The trigger runs 288 times a day, and a broken sheet would
    // otherwise turn one problem into a notification storm.
    var props = PropertiesService.getScriptProperties();
    if (props.getProperty('lastComplaint') !== today) {
      props.setProperty('lastComplaint', today);
      try { push('K Money: reminders sheet problem', String(err)); } catch (e) {}
    }
    throw err;
  }

  var fired = loadFired(today);
  // Ticked on any device, via the Done tab -- which is the whole reason the
  // ticks live in the Sheet rather than in one phone's localStorage.
  var done = loadDone();
  var sent = 0;
  rules.forEach(function (rule) {
    if (!firesOn(rule, now)) return;
    var late = minutesNow - (rule.hour * 60 + rule.minute);
    // Not yet due, or so late that firing now would be misleading rather than
    // useful -- a phone that was off all morning should not buzz at teatime.
    if (late < 0 || late > GRACE_MINUTES) return;
    // Keyed by title AND time, not title alone: two rows can share a name at
    // different hours ("Take pills" at 8am and 8pm), and keying on the title
    // silently suppressed the second one for the rest of the day.
    var key = doneKey(rule);
    if (fired.indexOf(key) >= 0) return;
    if (done[today + '|' + key]) return;      // already ticked off
    try {
      // The day and time go in the TITLE, not just the body: Android's own
      // snooze re-shows a notification hours later with no hint of which
      // occurrence it was, and a bare "Laundry" then tells you nothing.
      push(rule.title + ' (' + stamp(now) + ')',
           'Due ' + clock(rule.hour, rule.minute));
    } catch (err) {
      // Deliberately NOT stamped as fired, so the next tick tries again. The
      // grace window is wider than the gap between ticks, so a blip costs a
      // few minutes of lateness rather than the reminder itself -- and one bad
      // send must never abort the reminders queued behind it.
      Logger.log('send failed for "%s": %s', rule.title, err);
      return;
    }
    fired.push(key);
    sent++;
  });
  if (sent) saveFired(today, fired);
}

/**
 * One property holding today's fired titles, reset when the date rolls over.
 * A key per reminder per day would grow without bound and eventually hit the
 * properties quota.
 */
function loadFired(today) {
  var raw = PropertiesService.getScriptProperties().getProperty('fired');
  if (!raw) return [];
  try {
    var data = JSON.parse(raw);
    return data.date === today ? data.titles : [];
  } catch (err) {
    return [];
  }
}

function saveFired(today, titles) {
  PropertiesService.getScriptProperties()
    .setProperty('fired', JSON.stringify({date: today, titles: titles}));
}

/**
 * Send one notification, or throw.
 *
 * Tried twice: the first real send failed with "Address unavailable" after a
 * 50-second hang, while ntfy answered fine from elsewhere at the same moment
 * and every diagnostic passed minutes later. That is a transient connection
 * blip, and a reminder is worth a second attempt.
 *
 * muteHttpExceptions means a 4xx or 5xx comes back as a response rather than
 * an exception, so the status has to be checked by hand -- otherwise a
 * rejected send would look exactly like a delivered one.
 */
function push(title, body) {
  var url, options;
  if (PROVIDER === 'pushover') {
    if (PUSHOVER_USER.indexOf('PUT-YOUR') === 0 ||
        PUSHOVER_TOKEN.indexOf('PUT-YOUR') === 0) {
      throw new Error('PUSHOVER_USER / PUSHOVER_TOKEN are not set.');
    }
    url = 'https://api.pushover.net/1/messages.json';
    options = {
      method: 'post',
      payload: {token: PUSHOVER_TOKEN, user: PUSHOVER_USER,
                title: String(title), message: String(body || ' ')},
      muteHttpExceptions: true
    };
  } else {
    // ntfy accepts ANY string as a topic name, so an unset TOPIC publishes
    // happily to a topic called PUT-YOUR-NTFY-TOPIC-HERE and returns 200.
    // Every reminder would then "send" successfully and never arrive.
    if (!TOPIC || TOPIC.indexOf('PUT-YOUR') === 0) {
      throw new Error('TOPIC is not set at the top of this file.');
    }
    url = 'https://ntfy.sh/' + TOPIC;
    options = {
      method: 'post',
      payload: body || ' ',
      headers: {
        // ntfy takes the title from a header, and headers must be ASCII.
        // Anything exotic in a title is stripped rather than failing the send.
        'Title': String(title).replace(/[^\x20-\x7E]/g, ''),
        'Tags': 'bell'
      },
      muteHttpExceptions: true
    };
  }

  var last = 'no attempt made';
  for (var attempt = 1; attempt <= 2; attempt++) {
    try {
      var r = UrlFetchApp.fetch(url, options);
      var code = r.getResponseCode();
      var text = r.getContentText();
      // Pushover answers 200 with {"status":1}; anything else is a refusal
      // dressed as success, which is how the ntfy 429 hid for so long.
      if (code < 400 && (PROVIDER !== 'pushover' || text.indexOf('"status":1') >= 0)) {
        return;
      }
      last = 'HTTP ' + code + ' ' + text.slice(0, 200);
    } catch (err) {
      last = String(err);
    }
    if (attempt === 1) Utilities.sleep(3000);
  }
  throw new Error(PROVIDER + ' push failed after 2 tries: ' + last);
}

function pad(n) { return (n < 10 ? '0' : '') + n; }

/** "Sun 8/30" -- which occurrence this notification was for. */
function stamp(date) {
  return Utilities.formatDate(date, TZ, 'EEE') + ' ' +
         Number(Utilities.formatDate(date, TZ, 'MM')) + '/' +
         Number(Utilities.formatDate(date, TZ, 'dd'));
}

function clock(h, m) {
  var hour = h % 12; if (hour === 0) hour = 12;
  return hour + ':' + pad(m) + ' ' + (h < 12 ? 'am' : 'pm');
}
