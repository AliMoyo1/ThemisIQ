# G.R.I.D AI — Microsoft Integration Setup

## What's configured automatically
- ✅ **Email** — AliCompliance@outlook.com (Outlook SMTP, app password set)
- ✅ **Teams** — Add your webhook URL in Settings → Microsoft Teams
- ✅ **OneDrive** — Requires one extra step below (free Microsoft app registration)

---

## Setting up OneDrive sync (5 minutes)

OneDrive requires a Microsoft Azure app registration to get an API token.
This is free — you just need a Microsoft account (which you already have).

### Step 1 — Register an app
1. Go to **https://portal.azure.com**
2. Sign in with **AliCompliance@outlook.com**
3. Search for **"App registrations"** → click **"New registration"**
4. Name: `GRID-AI`
5. Supported account types: **"Personal Microsoft accounts only"**
6. Redirect URI: `http://localhost:3000/auth/callback`
7. Click **Register**

### Step 2 — Get your Client ID
- On the app overview page, copy the **Application (client) ID**
- Paste it into your `.env` file:
  ```
  MS_CLIENT_ID=paste-your-client-id-here
  ```

### Step 3 — Add API permissions
1. In your app → **API permissions** → **Add a permission**
2. Choose **Microsoft Graph** → **Delegated permissions**
3. Add: `Files.ReadWrite`, `User.Read`
4. Click **Grant admin consent**

### Step 4 — Restart the server
```
start.bat   (Windows)
./start.sh  (Mac/Linux)
```

OneDrive sync will now work from **Settings → OneDrive Sync**.

---

## Setting up Teams notifications

1. In Microsoft Teams, go to the channel you want alerts in
2. Click **···** (More options) → **Connectors**
3. Find **Incoming Webhook** → **Configure**
4. Name: `G.R.I.D AI`, upload a logo → **Create**
5. Copy the webhook URL
6. In G.R.I.D AI → **Settings** → **Microsoft Teams** → paste URL → **Save**
7. Click **Send Test Notification** to verify

---

## Email configuration (already set)
Your `.env` is pre-configured with:
```
MS_EMAIL=AliCompliance@outlook.com
MS_APP_PASSWORD=vttegbfmbgkwqryn
MS_SMTP_HOST=smtp-mail.outlook.com
MS_SMTP_PORT=587
```
Emails are sent from AliCompliance@outlook.com for:
- Evidence reminders (daily/weekly/monthly)
- Approval requests
- Approval decisions
- Escalations (controls 7+ days overdue)
- Evidence expiry alerts (30 days before expiry)
- Weekly compliance digest (Mondays 07:00 CAT)
- Auditor share link invitations
- Non-conformance assignments

---

## Scheduled jobs (automatic, Africa/Harare timezone)
| Time | Job |
|------|-----|
| 08:00 daily | Send evidence reminders |
| 08:30 daily | Evidence expiry alerts |
| 09:00 daily | Escalate overdue controls (7+ days, Critical/High) |
| 07:00 Monday | Weekly compliance digest |
| 00:00 daily | Record compliance score snapshot |
| 02:00 daily | Backup database + evidence files |
