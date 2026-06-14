# RoPA AI Assistant — Local Setup Guide

## What's in this folder

```
ropa-app/
├── login.html      ← Login page (start here)
├── index.html      ← Main application
├── config.js       ← Credentials & settings
└── README.md       ← This file
```

---

## Option A — Open directly in browser (simplest, 30 seconds)

This works on any laptop with no installs required.

1. Open the `ropa-app` folder on your computer
2. Double-click `login.html`
3. It opens in your browser
4. Log in with the default credentials:
   - **Username:** `admin`
   - **Password:** `ropa2024`
5. Done — the app is fully functional

> **Important:** Always open `login.html`, not `index.html` directly.
> Bookmarking `login.html` in your browser is the easiest way to reopen it.

> **Data storage:** All your data is saved in your browser's localStorage.
> It persists between sessions automatically as long as you use the same browser.
> Do not use Incognito/Private mode — localStorage doesn't persist there.

---

## Option B — Run on a local web server (recommended)

Running via a local server avoids any browser security restrictions
and makes the app feel more like a real hosted product.

### Step 1 — Install Python (if you don't have it)

**Check if Python is already installed:**
Open Terminal (Mac/Linux) or Command Prompt (Windows) and type:
```
python --version
```
or
```
python3 --version
```
If you see a version number (e.g. `Python 3.11.2`), you're ready.
If not, download Python from https://python.org/downloads (it's free).

### Step 2 — Start the server

**Mac / Linux:**
```bash
cd /path/to/ropa-app
python3 -m http.server 8080
```

**Windows (Command Prompt):**
```cmd
cd C:\path\to\ropa-app
python -m http.server 8080
```

**Windows (PowerShell):**
```powershell
cd C:\path\to\ropa-app
python -m http.server 8080
```

### Step 3 — Open the app

Open your browser and go to:
```
http://localhost:8080/login.html
```

Bookmark this URL for easy access.

### Step 4 — Keep it running

The server runs while the terminal/command prompt window is open.
To stop it, press `Ctrl+C` in the terminal.

To have it start automatically when your laptop boots, see the
"Auto-start on boot" section below.

---

## Changing your password

Open `config.js` in any text editor (Notepad, TextEdit, VS Code, etc.)
and edit the credentials section:

```javascript
users: [
  {
    username:    "admin",
    password:    "MyNewPassword",   // ← Change this
    displayName: "Your Name"        // ← Change this too
  },
],
```

Save the file, then refresh the browser. New credentials take effect immediately.

### Adding more users

Copy and paste a user block in `config.js`:

```javascript
users: [
  {
    username:    "admin",
    password:    "AdminPass123",
    displayName: "Administrator"
  },
  {
    username:    "jane",
    password:    "JanePass456",
    displayName: "Jane Smith"
  },
],
```

Each user gets their own login but shares the same RoPA data
(since all data is stored in the browser's localStorage).

---

## Setting your organisation name

In `config.js`, update this line:

```javascript
orgName: "Acme Ltd",   // ← Your organisation name
```

This appears in the app header.

---

## Auto-start on boot (optional)

### Mac — using a shell script + Login Items

1. Create a file called `start-ropa.sh` in the ropa-app folder:
```bash
#!/bin/bash
cd "$(dirname "$0")"
python3 -m http.server 8080
```

2. Make it executable:
```bash
chmod +x /path/to/ropa-app/start-ropa.sh
```

3. Go to **System Settings → General → Login Items**
4. Click `+` and add `start-ropa.sh`

### Windows — using Task Scheduler

1. Open **Task Scheduler** (search for it in Start menu)
2. Click **Create Basic Task**
3. Name it `RoPA AI Assistant`
4. Trigger: **When I log on**
5. Action: **Start a program**
6. Program/script: `python`
7. Arguments: `-m http.server 8080`
8. Start in: `C:\path\to\ropa-app`
9. Click Finish

---

## Backing up your data

Your data lives in your browser's localStorage under the key `ropa_data_v1`.

**To back it up:**
1. Open the app in your browser
2. Open browser DevTools (F12 or right-click → Inspect)
3. Go to **Application** tab → **Local Storage** → `http://localhost:8080`
4. Find `ropa_data_v1`, copy the value
5. Paste it into a `.json` file and save it somewhere safe

Alternatively, use the **⬇ Export Excel** button in the app to keep
a readable backup of all your data at any time.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Login page doesn't load | Make sure you're opening `login.html`, not `index.html` |
| Clicking login does nothing | Open browser console (F12) and check for errors |
| Data disappeared after refresh | You may have used Incognito mode — use regular mode |
| Port 8080 already in use | Change `8080` to another number like `8081` or `3000` |
| Fonts not loading | You need an internet connection for Google Fonts on first load |
| App looks broken | Try a different browser (Chrome or Firefox recommended) |

---

## Browser compatibility

| Browser | Support |
|---|---|
| Chrome / Chromium | ✅ Fully supported (recommended) |
| Firefox | ✅ Fully supported |
| Edge | ✅ Fully supported |
| Safari | ✅ Works (may need server mode) |
| Internet Explorer | ❌ Not supported |
