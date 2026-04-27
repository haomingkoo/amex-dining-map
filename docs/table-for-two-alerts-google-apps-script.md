# Table for Two Alert Signup Setup

GitHub Pages cannot store visitor emails. Use a Google Form for signup, a
linked Google Sheet for storage, and this Apps Script as the private CSV and
unsubscribe endpoint for GitHub Actions.

## Google Form Fields

Use these fields. The alert script accepts nearby names, but these are the
least ambiguous:

```text
enabled,email,name,party size,date start,date end,dates,sessions,venues,unsubscribe url
```

Recommended form questions:

- `email`: required email question.
- `name`: optional short answer.
- `party size`: dropdown from 2 to 8.
- `date start` and `date end`: optional date range.
- `dates`: optional comma-separated exact dates, e.g. `2026-05-23, 2026-06-26`.
- `sessions`: optional checkboxes for `Lunch`, `Dinner`.
- `venues`: optional checkboxes; leave blank for any venue.

Add an `enabled` column to the linked Sheet and default new rows to `true`.

## Apps Script

Open the linked Sheet, choose `Extensions > Apps Script`, paste this code, then
set Script Properties:

- `ALERT_EXPORT_TOKEN`: a long random value used only in GitHub secrets.
- `ALERT_HASH_SALT`: the same value you put in the GitHub `ALERT_HASH_SALT`
  secret.
- `SHEET_NAME`: optional; defaults to `Form Responses 1`.

Deploy as a Web App with `Execute as: Me` and `Who has access: Anyone with the
link`.

```javascript
function doGet(e) {
  const params = e.parameter || {};
  if (params.action === 'unsubscribe') {
    return unsubscribe(params);
  }

  const expectedToken = getProp_('ALERT_EXPORT_TOKEN');
  if (!expectedToken || params.token !== expectedToken) {
    return text_('Forbidden', 403);
  }

  return ContentService
    .createTextOutput(sheetToCsv_())
    .setMimeType(ContentService.MimeType.CSV);
}

function unsubscribe(params) {
  const email = String(params.email || '').trim().toLowerCase();
  const token = String(params.token || '').trim();
  const expected = saltedHash_(['unsubscribe', email], getProp_('ALERT_HASH_SALT'));

  if (!email || !token || token !== expected) {
    return text_('Invalid unsubscribe link.', 403);
  }

  const sheet = alertSheet_();
  const values = sheet.getDataRange().getValues();
  if (values.length < 2) return text_('No subscriptions found.');

  const headers = values[0].map(header_).map(String);
  const emailCol = headers.indexOf('email');
  const enabledCol = headers.indexOf('enabled');
  if (emailCol < 0 || enabledCol < 0) {
    return text_('Sheet needs email and enabled columns.', 500);
  }

  let changed = 0;
  for (let row = 1; row < values.length; row += 1) {
    if (String(values[row][emailCol] || '').trim().toLowerCase() === email) {
      sheet.getRange(row + 1, enabledCol + 1).setValue('false');
      changed += 1;
    }
  }

  return text_(changed ? 'You are unsubscribed.' : 'No matching subscription found.');
}

function sheetToCsv_() {
  return alertSheet_()
    .getDataRange()
    .getDisplayValues()
    .map(row => row.map(csvCell_).join(','))
    .join('\n');
}

function alertSheet_() {
  const sheetName = getProp_('SHEET_NAME') || 'Form Responses 1';
  const sheet = SpreadsheetApp.getActive().getSheetByName(sheetName);
  if (!sheet) throw new Error(`Missing sheet: ${sheetName}`);
  return sheet;
}

function saltedHash_(parts, salt) {
  const raw = `${salt}:${JSON.stringify(parts)}`;
  const digest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, raw, Utilities.Charset.UTF_8);
  return digest.map(byte => {
    const value = byte < 0 ? byte + 256 : byte;
    return value.toString(16).padStart(2, '0');
  }).join('');
}

function getProp_(name) {
  return PropertiesService.getScriptProperties().getProperty(name) || '';
}

function header_(value) {
  return String(value || '').trim().toLowerCase();
}

function csvCell_(value) {
  const text = String(value == null ? '' : value);
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function text_(body) {
  return ContentService
    .createTextOutput(body)
    .setMimeType(ContentService.MimeType.TEXT);
}
```

## GitHub Secrets

After deployment, set:

```text
TABLE_FOR_TWO_ALERTS_CSV_URL=https://script.google.com/macros/s/<deployment-id>/exec?token=<ALERT_EXPORT_TOKEN>
TABLE_FOR_TWO_ALERT_SIGNUP_URL=<public Google Form URL>
ALERT_UNSUBSCRIBE_BASE_URL=https://script.google.com/macros/s/<deployment-id>/exec?action=unsubscribe
ALERT_HASH_SALT=<same value as Apps Script ALERT_HASH_SALT>
```

You already need the SMTP secrets documented in the README. Do not set
`ALERT_ONE_CLICK_UNSUBSCRIBE` unless the Apps Script is extended to handle POST
requests.
