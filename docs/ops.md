# Ops guide (plan 09)

How to run, secure, back up, and troubleshoot the bot in production. Everything here
assumes Docker + Docker Compose; a bare-metal launchd alternative is in the last section.

## 1. Run with Docker Compose

```bash
cp .env.example .env      # then edit — at minimum set BOT_API_TOKEN for anything non-local
docker compose up -d      # builds + starts `api` and `web`
```

Open the dashboard at `http://localhost:${BOT_WEB_PORT:-8080}`. The `web` container (nginx)
serves the built frontend and reverse-proxies `/api` to the `api` container, so the browser
only ever talks to one origin.

Services:

| service | what it is | starts by default |
|---------|-----------|-------------------|
| `api`   | FastAPI + engine (uvicorn, access log off) | yes |
| `web`   | nginx serving the Vite build, proxies `/api` → `api` | yes |
| `live`  | live paper-trading runner (`bot.cli live`, plan 07) | **no** — opt-in profile |

Start the live runner too:

```bash
docker compose --profile live up -d
```

Stop / rebuild:

```bash
docker compose down                 # stop
docker compose up -d --build        # rebuild after code changes
```

All state (SQLite DBs + imported CSVs) lives in `backend/data/`, bind-mounted into the
containers, so `docker compose down` never loses data.

## 2. Auth: the API token

Set `BOT_API_TOKEN` in `.env` to require `Authorization: Bearer <token>` on every endpoint
except `/api/health`. Leave it empty for local dev (no auth).

Generate a token:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

- **Frontend**: click the 🔑 button in the nav, paste the token (stored in that browser's
  localStorage and attached to every request). A `401` auto-opens the same dialog.
- **curl without a token → 401**:

  ```bash
  curl -i http://localhost:8080/api/account          # 401 when a token is set
  curl -i -H "Authorization: Bearer $BOT_API_TOKEN" http://localhost:8080/api/account
  ```

### Rotating the token

1. Generate a new token, update `BOT_API_TOKEN` in `.env`.
2. `docker compose up -d api web` (recreates the api container with the new value).
3. In each browser, click 🔑 and paste the new token (or it will prompt on the next 401).

## 3. Backups

`backend/scripts/backup_db.sh` takes a consistent `sqlite3 .backup` snapshot of every
`*.db` in the data dir and keeps the newest 7 per database.

```bash
backend/scripts/backup_db.sh                       # -> backend/data/backups/<name>-YYYYMMDD.db
backend/scripts/backup_db.sh /path/to/data /backups   # custom dirs
```

Daily via cron (02:30, keep 7 handled by the script):

```cron
30 2 * * * /ABSOLUTE/PATH/backend/scripts/backup_db.sh >> /var/log/bot-backup.log 2>&1
```

### Restore

Stop writers first so nothing races the copy:

```bash
docker compose stop api live
cp backend/data/backups/runtime-20260724.db backend/data/runtime.db
# repeat for live.db / alerts.db as needed
docker compose start api live
```

## 4. Logs

The app logs **JSON lines to stdout**; Docker collects them.

```bash
docker compose logs -f api            # follow
docker compose logs api | grep '"event":"run_created"'
docker compose logs --since 1h live
```

Levels: `INFO` for decision/trade/run-lifecycle events, `WARNING` for degraded-but-running
(e.g. a feed falling back), `ERROR` with a stack for failures. Uvicorn's access log is
disabled in the container (too noisy) — application logs remain. Raise verbosity with
`LOG_LEVEL=DEBUG` in `.env`.

## 5. Checklist: the live runner died (plan 07)

1. **Is it down?** `docker compose ps live` — look for `Exit` / restarting. The dashboard's
   LIVE badge also shows "no live run" or a stale lag.
2. **Why?** `docker compose logs --tail=200 live` — the last `ERROR` line has the stack.
3. **Data intact?** The live runner writes its own `live.db`; the API only reads it. A crash
   cannot corrupt backtest history (`runtime.db`).
4. **Restart:** `docker compose --profile live up -d live`. A resumed run keeps its frozen
   config snapshot (there is no hot reload — that is intentional, plan 07 §3).
5. **Still crashing?** Check venue credentials (`DNSE_*` for VN, testnet vs mainnet base
   URL) and that the symbol type is supported for live. Fall back to `--profile live` off
   and investigate with `docker compose run --rm live python -m bot.cli live --iterations 5`.

## 6. Bare-metal (macOS launchd) alternative

To run the API without Docker (e.g. directly on the user's Mac), a launchd agent keeps
uvicorn alive across logout/reboot. Save as
`~/Library/LaunchAgents/com.bot.api.plist`, edit the paths, then
`launchctl load ~/Library/LaunchAgents/com.bot.api.plist`.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>          <string>com.bot.api</string>
  <key>WorkingDirectory</key><string>/ABSOLUTE/PATH/backend</string>
  <key>ProgramArguments</key>
  <array>
    <string>/ABSOLUTE/PATH/backend/.venv/bin/uvicorn</string>
    <string>bot.api.app:app</string>
    <string>--host</string><string>127.0.0.1</string>
    <string>--port</string><string>8000</string>
    <string>--no-access-log</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>BOT_API_TOKEN</key><string>REPLACE_ME</string>
  </dict>
  <key>RunAtLoad</key>      <true/>
  <key>KeepAlive</key>      <true/>
  <key>StandardOutPath</key><string>/tmp/bot-api.log</string>
  <key>StandardErrorPath</key><string>/tmp/bot-api.err.log</string>
</dict>
</plist>
```

Add a second agent (or a plain cron line) for `backup_db.sh`, and run the frontend either
via `npm run build` behind any static server or with the `web` Docker service pointed at a
host-run API.
