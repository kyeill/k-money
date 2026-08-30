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
  Logger.log('Trigger installed. Reminders will be checked every 5 minutes.');
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
    // "4th" with Sun ticked and Weekday left blank is the obvious intent, and
    // it is the natural way to write it. Without this the nth is silently
    // dropped and the row fires EVERY Sunday -- four times too often.
    if (nth !== undefined && weekday === '' && days.length === 1) {
      weekday = WD[days[0]];
    }
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

  // Months gates BOTH kinds of rule, so "Sat ticked, Months = Sep, Oct, Nov,
  // Dec" is a weekly reminder with a season. A blank Months means all twelve,
  // so existing rows are unaffected.
  if (rule.months.indexOf(m) < 0) return false;

  if (rule.monthly) {
    // A row with both a monthly rule and weekly ticks is monthly. One row,
    // one schedule.
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
    // Keyed by title AND time, not title alone: two rows can share a name at
    // different hours ("Take pills" at 8am and 8pm), and keying on the title
    // silently suppressed the second one for the rest of the day.
    var key = rule.title + '@' + pad(rule.hour) + ':' + pad(rule.minute);
    if (fired.indexOf(key) >= 0) return;
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
