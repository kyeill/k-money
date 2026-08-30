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

// Your ntfy topic. Anyone who knows this string can read your reminders AND
// send notifications to your phone, so keep it out of the public repo -- it
// lives here, in a script bound to your private Sheet, and nowhere else.
var TOPIC = 'PUT-YOUR-NTFY-TOPIC-HERE';

var TZ = 'America/New_York';   // times in the Sheet are read as this zone
var GRACE_MINUTES = 15;        // how late a reminder may fire before it is skipped

// ------------------------------------------------------------------ setup

/** Run once. Installs the 5-minute trigger and asks for authorisation. */
function setup() {
  if (TOPIC === 'PUT-YOUR-NTFY-TOPIC-HERE') {
    throw new Error('Set TOPIC at the top of this file first.');
  }
  // Clear ours first, or every re-run adds another trigger and every reminder
  // fires twice.
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'tick') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('tick').timeBased().everyMinutes(5).create();
  Logger.log('Trigger installed. Reminders will be checked every 5 minutes.');
}

/** Run by hand to prove the pipe works without waiting for a real reminder. */
function sendTest() {
  push('K Money test', 'If you can see this, notifications are working.');
  Logger.log('Sent. Check your phone.');
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
  var r = UrlFetchApp.fetch('https://ntfy.sh/' + TOPIC, {
    method: 'post',
    payload: 'probe from apps script',
    headers: {'Title': 'K Money probe'},
    muteHttpExceptions: true
  });
  Logger.log('TOPIC   : %s', TOPIC);
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
var NTH = {'1st': 1, '2nd': 2, '3rd': 3, '4th': 4, '5th': 5, 'last': -1};
var MO = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
          'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
var EXPECT = ['title', 'time', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun',
              'nth', 'weekday', 'months'];

function readRules() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  // Display values, not raw ones: a time cell read raw comes back as a Date on
  // the 1899-12-30 epoch, which is a different parsing problem in every
  // timezone. The displayed "12:30 PM" is also exactly what the CSV endpoint
  // gives the web page, so both sides parse the same string.
  var grid = sheet.getDataRange().getDisplayValues();
  if (!grid.length) throw new Error('the sheet is empty');

  var header = grid[0].map(function (h) { return String(h).trim().toLowerCase(); });
  for (var i = 0; i < EXPECT.length; i++) {
    if (header[i] !== EXPECT[i]) {
      throw new Error('unexpected column ' + (i + 1) + ': found "' + header[i] +
                      '", expected "' + EXPECT[i] + '"');
    }
  }

  var rules = [];
  for (var r = 1; r < grid.length; r++) {
    var c = grid[r].map(function (x) { return String(x == null ? '' : x).trim(); });
    while (c.length < EXPECT.length) c.push('');
    var at = parseTime(c[1]);
    if (!c[0] || !at) continue;          // a reminder with no time cannot fire
    var nth = NTH[c[9].toLowerCase()];
    var weekday = title3(c[10]);
    var days = [];
    for (var d = 0; d < 7; d++) if (c[2 + d]) days.push(d);
    rules.push({
      title: c[0], hour: at[0], minute: at[1], days: days,
      nth: (nth === undefined ? null : nth), weekday: weekday,
      months: parseMonths(c[11]),
      monthly: (nth !== undefined && weekday !== '')
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

  if (rule.monthly) {
    // A row with both a monthly rule and weekly ticks is monthly. One row,
    // one schedule.
    if (rule.months.indexOf(m) < 0) return false;
    if (rule.weekday === 'Day') {
      var want = (rule.nth === -1) ? daysIn(y, m) : rule.nth;
      return want >= 1 && want <= daysIn(y, m) && want === d;
    }
    var target = WD.indexOf(rule.weekday);
    if (target < 0) return false;
    return nthWeekday(y, m, target, rule.nth) === d;
  }
  return rule.days.indexOf(weekdayOf(local)) >= 0;
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
    // Tell someone rather than failing silently every five minutes forever --
    // but if the push fails too, report the sheet problem, not the push.
    try { push('K Money: reminders sheet problem', String(err)); } catch (e) {}
    throw err;
  }

  var fired = loadFired(today);
  var sent = 0;
  rules.forEach(function (rule) {
    if (!firesOn(rule, now)) return;
    var late = minutesNow - (rule.hour * 60 + rule.minute);
    // Not yet due, or so late that firing now would be misleading rather than
    // useful -- a phone that was off all morning should not buzz at teatime.
    if (late < 0 || late > GRACE_MINUTES) return;
    if (fired.indexOf(rule.title) >= 0) return;
    try {
      push(rule.title, 'Due ' + clock(rule.hour, rule.minute));
    } catch (err) {
      // Deliberately NOT stamped as fired, so the next tick tries again. The
      // grace window is wider than the gap between ticks, so a blip costs a
      // few minutes of lateness rather than the reminder itself -- and one bad
      // send must never abort the reminders queued behind it.
      Logger.log('send failed for "%s": %s', rule.title, err);
      return;
    }
    fired.push(rule.title);
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
  var options = {
    method: 'post',
    payload: body || ' ',
    headers: {
      // ntfy takes the title from a header, and headers must be ASCII. Anything
      // exotic in a reminder title is stripped rather than breaking the send.
      'Title': String(title).replace(/[^\x20-\x7E]/g, ''),
      'Tags': 'bell'
    },
    muteHttpExceptions: true
  };
  // ntfy accepts ANY string as a topic name, so an unset TOPIC publishes
  // happily to a topic called PUT-YOUR-NTFY-TOPIC-HERE and returns 200. Every
  // reminder would then "send" successfully and never arrive.
  if (!TOPIC || TOPIC === 'PUT-YOUR-NTFY-TOPIC-HERE') {
    throw new Error('TOPIC is not set at the top of this file.');
  }
  var last = 'no attempt made';
  for (var attempt = 1; attempt <= 2; attempt++) {
    try {
      var r = UrlFetchApp.fetch('https://ntfy.sh/' + TOPIC, options);
      if (r.getResponseCode() < 400) return;
      last = 'HTTP ' + r.getResponseCode() + ' ' + r.getContentText().slice(0, 200);
    } catch (err) {
      last = String(err);
    }
    if (attempt === 1) Utilities.sleep(3000);
  }
  throw new Error('ntfy push failed after 2 tries: ' + last);
}

function pad(n) { return (n < 10 ? '0' : '') + n; }

function clock(h, m) {
  var hour = h % 12; if (hour === 0) hour = 12;
  return hour + ':' + pad(m) + ' ' + (h < 12 ? 'am' : 'pm');
}
