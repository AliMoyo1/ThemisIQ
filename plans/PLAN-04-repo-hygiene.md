# PLAN-04: Repo hygiene — stop tracking the dev database, add .gitignore, fix committer identity

## Goal

The repository currently:

- **Tracks the live dev SQLite database** (`oneforall/data/oneforall.db`,
  ~2 MB, contains password hashes and session rows; shows as "modified"
  in every session and bloats every commit).
- **Tracks a scratch diff dump** (`oneforall/scripts/.dry_run_diff.txt`).
- **Has NO `.gitignore`**, so demo PDFs, a pentest report DOCX, base64
  scratch files, and logo copies sit permanently in `git status` noise —
  one careless `git add .` away from being published.
- **Commits with a broken identity** (`unknown <isadmin@Omni-CS-IS...>`),
  which GitHub does not associate with the owner's account.

Outcome: dev DB and scratch files untracked and ignored, clean
`git status`, correct committer identity.

## Exact files to touch

1. `.gitignore` (new file, repo root)
2. Git index only (no source changes): `git rm --cached` two paths
3. Git config (local repo config, not a file edit)

## Step-by-step order

### Step 1 — Set the committer identity (repo-local)

```
git config user.name "Ali Moyo"
```

```
git config user.email "alimoyo58@gmail.com"
```

Use `git config` WITHOUT `--global` (repo-local) so other repos on this
shared machine are unaffected.

### Step 2 — Create `.gitignore` at the repo root

```gitignore
# ── Python ───────────────────────────────────────────────
__pycache__/
*.pyc
.venv/
venv/

# ── Local databases (dev only — prod uses PostgreSQL) ────
oneforall/data/*.db
oneforall/data/*.db-journal
oneforall/data/*.db-wal
oneforall/data/*.db-shm

# ── Scratch / generated artifacts ────────────────────────
_logo_b64.txt
oneforall/scripts/.dry_run_diff.txt
*.bak

# ── Local demo / documentation exports (kept locally, not in git) ──
ThemisIQ_Business_Case.pdf
ThemisIQ_Platform_Manual.pdf
ThemisIQ_Pentest_Report_*.docx
ThemisIQ_Demo_Script.md
ThemisIQ_User_Manual.md
ThemisIQ_Architecture.html
ThemisIQ_PreLaunch_Tracker.xlsx
themisiq-logo-clear.png
themisiq-logo-dark.png
generate_docs.py

# ── OS noise ─────────────────────────────────────────────
.DS_Store
Thumbs.db
```

Do NOT add `.claude/` to the ignore list — `.claude/launch.json` is
deliberately tracked (dev server configs shared across sessions).

### Step 3 — Untrack the two files that are already committed

```
git rm --cached "oneforall/data/oneforall.db"
```

```
git rm --cached "oneforall/scripts/.dry_run_diff.txt"
```

`--cached` removes them from the index only; the working-tree files stay
on disk. Verify with `git status`: both should show as `deleted:` in
staged changes AND stop appearing under "Changes not staged".

### Step 4 — Commit

Stage `.gitignore` plus the two deletions and commit:

```
git add .gitignore
```

```
git commit -m "Stop tracking dev database and scratch files; add .gitignore"
```

Then push to origin master.

### Step 5 — VPS pull instructions (include in your final report verbatim)

The VPS has the (now-deleted-from-git) DB file in its working tree. If it
has local modifications, `git pull` will refuse. One command per step, no
pipes, no chained commands:

```
cd /opt/themisiq
```

```
sudo git checkout -- oneforall/data/oneforall.db
```

```
sudo git pull origin master
```

The pull will delete the stale SQLite file from the VPS working tree.
This is safe: production uses PostgreSQL (`DATABASE_URL` is set;
service `themisiq-app.service`). Do NOT restart the service for this
change — nothing running depends on that file.

## Edge cases a weaker model would miss

- **`git rm --cached` vs `git rm`** — without `--cached` you delete the
  developer's live dev database from disk and the local app loses all its
  data. Never drop the flag.
- **The DB stays in git HISTORY.** This plan removes it from future
  commits only. Purging history requires `git filter-repo` plus a force
  push, which rewrites every commit SHA and breaks the VPS clone. Do NOT
  do that as part of this plan — flag it as an explicit follow-up decision
  for the user (the file contains only bcrypt hashes and dev data, so
  history purge is optional, not urgent).
- **Windows quoting** — the repo path contains spaces ("One For All").
  Always quote paths in git commands.
- **`.gitignore` does not untrack already-tracked files.** That is why
  Step 3 exists; skipping it leaves the DB tracked and the ignore rule
  silently useless.
- **Do not ignore `oneforall/data/` wholesale** — the directory may hold
  seed fixtures or uploads that should keep working; ignore only the
  SQLite file patterns.
- **The tracked `.claude/launch.json` currently has uncommitted
  modifications** (a new "architecture" dev-server entry). That is
  legitimate work — commit it separately or leave it; it is NOT part of
  this plan's staging. When committing in Step 4, stage exactly
  `.gitignore` and the two `git rm` deletions, nothing else. Run
  `git status` before `git commit` and confirm the staged list is exactly
  those three entries.
- **Do not add `plans/` to .gitignore** — the PLAN files are meant to be
  tracked so they can be executed from any machine.

## Acceptance criteria

1. `git status` after the commit shows NO mention of `oneforall.db`,
   `.dry_run_diff.txt`, the PDFs/DOCX/logos, or `_logo_b64.txt`.
2. `git ls-files oneforall/data/` returns nothing (or only non-DB files).
3. Running the app locally still works (`python -m uvicorn main:app` from
   `oneforall/` starts, login page renders) — proving the dev DB file
   itself was not deleted.
4. `git log -1 --format="%an %ae"` prints `Ali Moyo alimoyo58@gmail.com`.
5. After the VPS steps, `sudo git status` on the VPS reports a clean tree.
