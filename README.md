# HKUgram

HKUgram is a local social media web app for COMP3278 Scenario 2, built with Python + SQLite and a server-rendered frontend.

## Features

- account registration/login with unique usernames
- post creation (title/body/image), feed browsing, post detail pages
- likes, comments, bookmarks, follows, and notifications
- direct messaging (1:1 and group chats)
- group chat creation with member search filter and **add user by username**
- analytics dashboard and Ask HKUgram (safe NL-to-SQL workflow)
- light/dark theme toggle with updated UI system
- concurrent request handling via `ThreadingHTTPServer` + SQLite WAL mode

## Run locally

```bash
python app.py
```

Open: `http://127.0.0.1:8000`

## Ask HKUgram (Natural Language Query)

`/query` supports:

- **default mode**: built-in rule-based NL → SQL
- **API mode**: DeepSeek-backed NL → SQL (if configured)

Set environment variables to enable API mode:

WINDOWS:
```bash
set DEEPSEEK_API_KEY=your_api_key_here
set DEEPSEEK_MODEL=deepseek-chat
python app.py
```

Mac:
```
 export DEEPSEEK_API_KEY="your_key_here"
 export DEEPSEEK_MODEL="deepseek-chat"
 python app.py
```

PowerShell:

```powershell
$env:DEEPSEEK_API_KEY="your_api_key_here"
$env:DEEPSEEK_MODEL="deepseek-chat"
python app.py
```

Safety constraints:

- only a single read-only `SELECT` query is allowed
- writes/schema changes are blocked
- automatic fallback to rule-based mode if API is unavailable

## Data persistence

Primary DB: `data/hkugram.db`

- all user/content actions are persisted in SQLite
- snapshot saved at shutdown to `data/snapshots/hkugram-latest.db`
- automatic restore from snapshot if primary DB is missing

## Troubleshooting

 If you see User not found. after starting app.py, the app is usually using a
  stale login cookie (hkugram_user) that points to a user ID no longer in the
  local database.

  Fix:

   1. Open http://127.0.0.1:8000/logout to clear the session.
   2. Refresh and log in/register again.

  If the error still appears, reset local data and reseed:

   rm -f data/hkugram.db data/snapshots/hkugram-latest.db
   python3 app.py

  This recreates a clean local database with seeded demo users.

## Deploy (Render)

The repository includes `render.yaml` for quick Render setup.

1. Push to GitHub
2. Create a new Render Web Service and connect the repo
3. Let Render detect `render.yaml`
4. Deploy and open the generated URL

> Note: this project uses local SQLite, which is fine for demos but not ideal for long-term production persistence.
