# HKUgram

Local social media web app for COMP3278 Scenario 2.

## Included

- unique usernames
- image posts with captions and timestamps
- direct image visualization in the feed
- like and unlike
- comments
- automatic like and comment count maintenance via triggers
- sorting by latest, popularity, discussion, and trending score
- user-specific post history
- analytics dashboard
- tagging, bookmarks, search, and a safe Text-to-SQL console
- concurrent access via `ThreadingHTTPServer` and SQLite WAL mode

## Run

```bash
python app.py
```

Then open `http://127.0.0.1:8000`.

## API-Backed Natural Language Queries

The `Ask HKUgram` page supports two modes:

- default: built-in rule-based query translation
- with DeepSeek configured: model-backed natural language to SQL

Set these environment variables to enable the API-backed mode:

```bash
set DEEPSEEK_API_KEY=your_api_key_here
set DEEPSEEK_MODEL=deepseek-chat
python app.py
```

In PowerShell, use:

```powershell
$env:DEEPSEEK_API_KEY="your_api_key_here"
$env:DEEPSEEK_MODEL="deepseek-chat"
python app.py
```

Who should enter the key:

- the person running or deploying the app
- not normal end users in the browser UI

The key is read from the server environment before the app starts.

Safety rules:

- the app only accepts a single read-only `SELECT` query
- write operations and schema changes are rejected
- if the API is unavailable, the app falls back to the built-in rule-based behavior

## Local Persistence

The local version saves all data to `data/hkugram.db`.

- user registrations, posts, comments, likes, and bookmarks are written to SQLite immediately
- when the app shuts down, it also saves a snapshot to `data/snapshots/hkugram-latest.db`
- if the main database file is missing on the next start, the app restores from that snapshot automatically

For normal local use, you can stop the server and start it again later without losing your data.

## Free Public Deployment

The repo now includes [render.yaml](/c:/Users/Duckt/Desktop/COMP3278%20Project/render.yaml) so it can be deployed as a free Render web service with a public URL.

### Render Steps

1. Push this project to GitHub.
2. Create a new Web Service on Render and connect the repository.
3. Render should detect `render.yaml` automatically.
4. Deploy and open the generated `onrender.com` URL.

### Important Limitation

This project currently uses local SQLite (`data/hkugram.db`). On a free public host, that means user-created data is not production-safe:

- good enough for a course demo
- not reliable for long-term public usage

If you need persistent public data later, the next step is moving from SQLite to PostgreSQL.
