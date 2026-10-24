# Telegram bot: alerts and machine status on your phone

Free, uses only the Telegram Bot API. Nothing extra to install: the bot is part of the backend.

> **Status: tested against a local fake of Telegram's server, not against the real Telegram service.**
> Follow "First run" below and check that the test message arrives before relying on it.

## What it does
**Pushed to your phone** (only for authorised chats):
- a new alert (sensor fault, high risk, low confidence, sensors disagree, device offline);
- a machine's urgency rising (routine → soon → immediate) or recovering.

A per-machine cooldown (default 10 min) stops a flapping sensor from spamming you. Alerts that already existed when the backend started are not re-announced.

**On demand** (send these to the bot):

| Command | Answer |
|---|---|
| `/status` | every machine: data source, failure risk, prediction confidence, sensor trust, urgency, open alerts, device counts |
| `/machine 1` or `/machine_1` | one machine in detail: assessment (sensor fault vs machine fault), urgency, recommended action, each sensor with value/trust/status/last seen, why the risk and confidence are what they are, caveats |
| `/alerts` | open alerts |
| `/devices` | hardware devices: Online / Stale / Offline and last seen |
| `/mute 60` / `/unmute` | pause / resume pushed alerts for your chat (max 24 h) |
| `/chatid` | shows your chat id (works for anyone; needed for setup) |
| `/help` | list of commands |

Every message says whether the data is **REAL HARDWARE**, **SIMULATED** or **MIXED**, and keeps sensor trust, failure risk and prediction confidence as three separate numbers. The bot is **read-only**: it cannot register devices, resolve alerts or change anything.

## Setup
1. In Telegram, open **@BotFather** → `/newbot` → follow the prompts → copy the **token**.
2. In `backend/.env`:
   ```
   TELEGRAM_ENABLED=true
   TELEGRAM_BOT_TOKEN=<token from BotFather>
   TELEGRAM_ALLOWED_CHAT_IDS=
   ```
3. Restart the backend. Open your new bot in Telegram, press **Start**, send `/chatid`. It replies with a number.
4. Put that number in `TELEGRAM_ALLOWED_CHAT_IDS` (several: `123456,789012`) and restart the backend.
5. Send `/status`. Or open the **Hardware** page → *Telegram bot* card → **Send test message** (needs the admin key if `ADMIN_API_KEY` is set).

For a group, add the bot to the group, send `/chatid` there and use that id (group ids are negative, e.g. `-1001234567890`).

## Settings (`backend/.env`)
| Setting | Meaning |
|---|---|
| `TELEGRAM_ALLOWED_CHAT_IDS` | who may receive alerts and use commands. **Empty = nobody** (the bot only answers `/chatid`) |
| `TELEGRAM_ALERT_COOLDOWN_MINUTES` | minimum gap between pushes for the same machine + alert type (default 10) |
| `TELEGRAM_MIN_SEVERITY` | `info`, `warning` (default) or `critical` |
| `TELEGRAM_NOTIFY_SIMULATED` | `false` = no pushes for simulated data, so only real hardware alerts reach your phone. Commands still work |
| `TELEGRAM_DASHBOARD_URL` | optional link appended to pushes, e.g. `http://192.168.1.20:5173` |
| `TELEGRAM_CHECK_INTERVAL_SECONDS` | how often the backend looks for new alerts (default 15) |

## Security
- The token lives only in the backend environment. It is never sent to the frontend, never logged, and error messages never contain it. If it leaks, revoke it in @BotFather (`/revoke`).
- Strangers who find your bot can only get their own chat id and a refusal; they never see machine data.
- The bot needs outbound HTTPS to `api.telegram.org`. It makes no inbound connections, so no port needs to be opened.
- Telegram messages are not end-to-end encrypted (bot chats are not "secret chats"). Do not treat them as confidential industrial data.

## Things to know
- **Run one backend process** (no `--workers 2`+). Each process would poll Telegram and they would fight over the same bot (HTTP 409 errors, duplicate answers). Two machines using the same token conflict in the same way.
- Mutes and cooldowns are kept in memory: they reset when the backend restarts.
- The bot does not announce "alert resolved" (only urgency recovery) and has no inline buttons yet.
- Messages are only as reliable as the underlying model: failure risk comes from a model that has not been validated on labelled real failures, and injected faults are artificial. Messages say so.

## Troubleshooting
| Symptom | Check |
|---|---|
| Card says "Not connected" | token wrong or no internet; the card shows the last error (e.g. `HTTP 401` = bad token) |
| Bot says "not authorised" | your id is not in `TELEGRAM_ALLOWED_CHAT_IDS`, or you did not restart after changing it |
| No pushes for demo data | `TELEGRAM_NOTIFY_SIMULATED=false`, you muted yourself (`/unmute`), the severity filter is too high, or the cooldown is still running |
| `HTTP 409` in the card | another process or a webhook is using the same bot token |
