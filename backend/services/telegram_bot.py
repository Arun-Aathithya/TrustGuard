"""
Telegram bot for TrustGuard AI (standard library only - no extra pip packages).

What it does
------------
1. ALERTS   - pushes a short message to authorised chats when a new alert is raised or a machine's
              urgency rises (routine -> soon -> immediate) or recovers. Per-machine cooldown stops spam.
2. COMMANDS - authorised chats can ask for the current scenario on demand:
                /status          every machine: data source, risk, confidence, trust, urgency
                /machine <id>    one machine in detail (also /machine_1 - tappable in Telegram)
                /alerts          open alerts
                /devices         hardware devices: Online / Stale / Offline + last seen
                /mute [minutes]  pause pushed alerts (default 60, max 1440)   /unmute
                /chatid          show this chat's id (works for anyone - used for setup)
                /help

Safety rules
------------
* Only chats listed in TELEGRAM_ALLOWED_CHAT_IDS receive alerts or answers. Everyone else only gets their
  own chat id (so you can set the bot up) and a refusal. Empty list = nobody is authorised.
* The bot token is read from the environment, never logged and never sent to the frontend.
* Messages are plain text (no Markdown), always say whether data is REAL HARDWARE or SIMULATED, keep sensor
  trust / failure risk / prediction confidence as three separate numbers, and use cautious wording.
* The bot uses long polling (getUpdates). Do not also configure a webhook for the same bot.

Configuration (backend .env): see .env.example (TELEGRAM_*).
"""
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("trustguard.telegram")

API_BASE = "https://api.telegram.org"
MAX_MESSAGE_CHARS = 3900  # Telegram's hard limit is 4096
SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}
URGENCY_RANK = {"routine": 0, "soon": 1, "immediate": 2}
SOURCE_LABEL = {"hardware": "REAL HARDWARE", "simulation": "SIMULATED", "mixed": "MIXED (hardware + simulation)"}
URGENCY_ICON = {"routine": "🟢", "soon": "🟡", "immediate": "🔴"}
SEVERITY_ICON = {"info": "ℹ️", "warning": "🟡", "critical": "🔴"}
MAX_MUTE_MINUTES = 1440

HELP_TEXT = (
    "TrustGuard AI bot\n\n"
    "/status - all machines at a glance\n"
    "/machine <id> - one machine in detail (e.g. /machine 1)\n"
    "/alerts - open alerts\n"
    "/devices - hardware devices and connection state\n"
    "/mute [minutes] - pause pushed alerts (default 60, max 1440)\n"
    "/unmute - resume pushed alerts\n"
    "/chatid - show this chat's id\n"
    "/help - this message\n\n"
    "Sensor trust (is the data reliable?), failure risk (how likely is a machine problem?) and prediction "
    "confidence (how much to rely on that risk) are three separate measures. The risk model has not been "
    "validated on labelled real failures, so treat everything here as a decision aid, not a guarantee."
)


# ----------------------------------------------------------------------------- configuration
@dataclass
class TelegramConfig:
    enabled: bool = False
    token: str = ""
    allowed_chat_ids: frozenset = frozenset()
    cooldown_s: float = 600.0
    min_severity: str = "warning"
    notify_simulated: bool = True
    dashboard_url: str = ""
    check_interval_s: float = 15.0


def parse_chat_ids(raw: str) -> frozenset:
    """'123, -100456 ,abc' -> frozenset({123, -100456}); junk entries are ignored."""
    out = set()
    for part in re.split(r"[,\s;]+", raw or ""):
        part = part.strip()
        if re.fullmatch(r"-?\d+", part):
            out.add(int(part))
    return frozenset(out)


def _env_float(name: str, default: float, minimum: float) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default))))
    except ValueError:
        return default


def load_config() -> TelegramConfig:
    sev = os.getenv("TELEGRAM_MIN_SEVERITY", "warning").strip().lower()
    return TelegramConfig(
        enabled=os.getenv("TELEGRAM_ENABLED", "false").strip().lower() == "true",
        token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        allowed_chat_ids=parse_chat_ids(os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "")),
        cooldown_s=_env_float("TELEGRAM_ALERT_COOLDOWN_MINUTES", 10.0, 0.0) * 60,
        min_severity=sev if sev in SEVERITY_RANK else "warning",
        notify_simulated=os.getenv("TELEGRAM_NOTIFY_SIMULATED", "true").strip().lower() != "false",
        dashboard_url=os.getenv("TELEGRAM_DASHBOARD_URL", "").strip(),
        check_interval_s=_env_float("TELEGRAM_CHECK_INTERVAL_SECONDS", 15.0, 2.0),
    )


# ----------------------------------------------------------------------------- pure formatting
def _pct(v) -> str:
    return "n/a" if v is None else f"{v:.0f}%"


def _ago(seconds) -> str:
    if seconds is None:
        return "never"
    s = int(seconds)
    if s < 90:
        return f"{s}s ago"
    if s < 5400:
        return f"{s // 60} min ago"
    return f"{s // 3600} h ago"


def _source(src: str | None) -> str:
    return SOURCE_LABEL.get(src or "simulation", "SIMULATED")


def _clip(text: str, limit: int = MAX_MESSAGE_CHARS) -> str:
    suffix = "\n…(message shortened)"
    return text if len(text) <= limit else text[: limit - len(suffix)].rstrip() + suffix


def _link(cfg_url: str) -> str:
    return f"\nDashboard: {cfg_url}" if cfg_url else ""


def machine_summary(d: dict) -> dict:
    """MachineDashboard (as a plain dict) -> the small dict the bot works with."""
    pred = d.get("latest_prediction") or {}
    expl = d.get("explanation") or {}
    hw = [s["sensor"] for s in d.get("sensors", []) if s["sensor"].get("data_source") == "hardware"]
    counts = {"online": 0, "stale": 0, "offline": 0}
    for s in hw:
        st = s.get("device_status")
        if st in counts:
            counts[st] += 1
    return {
        "id": d["machine"]["id"], "name": d["machine"]["name"], "data_source": d.get("data_source", "simulation"),
        "failure_risk": pred.get("failure_risk"), "confidence": pred.get("prediction_confidence"),
        "trust": d.get("overall_trust"), "urgency": expl.get("urgency", "routine"),
        "fault_label": expl.get("fault_label"), "open_alerts": len(d.get("open_alerts", [])),
        "hardware_devices": len(hw), "devices": counts,
    }


def machine_detail(d: dict) -> dict:
    base = machine_summary(d)
    expl = d.get("explanation") or {}
    notes = {c["sensor_type"]: c for c in expl.get("contributors", [])}
    sensors = []
    for snap in d.get("sensors", []):
        s = snap["sensor"]
        c = notes.get(s.get("sensor_type"))
        sensors.append({
            "type": s.get("sensor_type"), "value": snap.get("latest_value"), "unit": s.get("unit", ""),
            "trust": (snap.get("trust") or {}).get("trust_score"), "status": s.get("device_status", "simulated"),
            "data_source": s.get("data_source", "simulation"), "seconds_since_seen": s.get("seconds_since_seen"),
            "note": c["note"] if c and c.get("role") != "ok" else None,
        })
    base.update(
        headline=expl.get("headline"), urgency_label=expl.get("urgency_label"), action=expl.get("action") or d.get("recommendation"),
        why_risk=expl.get("why_risk"), why_confidence=expl.get("why_confidence"), caveats=expl.get("caveats", []), sensors=sensors,
    )
    return base


def format_status(machines: list[dict]) -> str:
    if not machines:
        return "No machines found."
    lines = ["TrustGuard status", ""]
    for m in machines:
        hw = f" · devices {m['devices']['online']} online/{m['devices']['stale']} stale/{m['devices']['offline']} offline" if m["hardware_devices"] else ""
        lines.append(
            f"{URGENCY_ICON.get(m['urgency'], '⚪')} {m['name']} [{_source(m['data_source'])}]\n"
            f"   risk {_pct(m['failure_risk'])} · confidence {_pct(m['confidence'])} · sensor trust {_pct(m['trust'])}\n"
            f"   urgency: {m['urgency']} · open alerts: {m['open_alerts']}{hw}\n"
            f"   details: /machine_{m['id']}"
        )
    lines += ["", "Risk, confidence and trust are separate measures; see /help."]
    return _clip("\n".join(lines))


def format_machine(m: dict) -> str:
    lines = [
        f"{m['name']} (machine {m['id']})",
        f"Data: {_source(m['data_source'])}",
        f"Failure risk {_pct(m['failure_risk'])} · Prediction confidence {_pct(m['confidence'])} · Sensor trust {_pct(m['trust'])}",
        f"Assessment: {m.get('fault_label') or 'no prediction yet'}",
        f"Urgency: {m.get('urgency_label') or m['urgency']}",
    ]
    if m.get("headline"):
        lines.append(m["headline"])
    if m.get("action"):
        lines.append(f"Recommended action: {m['action']}")
    lines += ["", "Sensors:"]
    for s in m["sensors"]:
        val = "no reading" if s["value"] is None else f"{s['value']:.2f} {s['unit']}".strip()
        seen = f" · seen {_ago(s['seconds_since_seen'])}" if s["data_source"] == "hardware" else ""
        lines.append(f"• {s['type']}: {val} · trust {_pct(s['trust'])} · {s['status']}{seen}")
        if s["note"]:
            lines.append(f"   ⚠ {s['note']}")
    if m.get("why_risk"):
        lines += ["", f"Why this risk: {m['why_risk']}"]
    if m.get("why_confidence"):
        lines.append(f"Why this confidence: {m['why_confidence']}")
    if m.get("caveats"):
        lines += ["", "Please note:"] + [f"- {c}" for c in m["caveats"]]
    return _clip("\n".join(lines))


def format_alerts(alerts: list[dict]) -> str:
    if not alerts:
        return "No open alerts."
    lines = [f"Open alerts ({len(alerts)})", ""]
    for a in alerts[:10]:
        lines.append(f"{SEVERITY_ICON.get(a['severity'], '•')} {a['machine_name']} [{_source(a['data_source'])}] {a['severity'].upper()} / {a['alert_type']}\n   {a['message']}\n   details: /machine_{a['machine_id']}")
    if len(alerts) > 10:
        lines.append(f"…and {len(alerts) - 10} more (see the dashboard).")
    return _clip("\n".join(lines))


def format_devices(devices: list[dict]) -> str:
    if not devices:
        return "No hardware devices are registered. Everything is simulated."
    icon = {"online": "🟢", "stale": "🟡", "offline": "🔴"}
    lines = ["Hardware devices", ""]
    for d in devices:
        lines.append(f"{icon.get(d['status'], '⚪')} {d['device_id'] or '?'} → {d['machine_name']} / {d['sensor_type']}: {d['status']} · last seen {_ago(d['seconds_since_seen'])}")
    return _clip("\n".join(lines))


def format_alert_push(a: dict, url: str = "") -> str:
    return (f"{SEVERITY_ICON.get(a['severity'], '•')} TrustGuard alert [{_source(a['data_source'])}]\n"
            f"{a['machine_name']} · {a['severity'].upper()} · {a['alert_type']}\n{a['message']}\n"
            f"Details: /machine_{a['machine_id']}{_link(url)}")


def format_urgency_push(m: dict, previous: str, url: str = "") -> str:
    if URGENCY_RANK[m["urgency"]] < URGENCY_RANK[previous]:
        head = f"🟢 {m['name']} [{_source(m['data_source'])}] urgency is back to {m['urgency']} (was {previous})."
    else:
        head = f"{URGENCY_ICON[m['urgency']]} {m['name']} [{_source(m['data_source'])}] urgency rose to {m['urgency'].upper()} (was {previous})."
    return (f"{head}\nRisk {_pct(m['failure_risk'])} · confidence {_pct(m['confidence'])} · sensor trust {_pct(m['trust'])}\n"
            f"Assessment: {m.get('fault_label') or 'n/a'}\nDetails: /machine_{m['id']}{_link(url)}")


# ----------------------------------------------------------------------------- notification planning (pure)
@dataclass
class BotState:
    last_alert_id: int | None = None
    last_urgency: dict = field(default_factory=dict)
    sent_at: dict = field(default_factory=dict)       # cooldown key -> monotonic-ish time
    muted_until: dict = field(default_factory=dict)   # chat_id -> epoch seconds
    refused_at: dict = field(default_factory=dict)    # chat_id -> epoch seconds (rate-limits refusals)


def _cooldown_ok(state: BotState, key: tuple, now: float, cooldown_s: float) -> bool:
    last = state.sent_at.get(key)
    if last is not None and now - last < cooldown_s:
        return False
    state.sent_at[key] = now
    return True


def plan_notifications(new_alerts: list[dict], machines: list[dict], state: BotState, cfg: TelegramConfig, now: float) -> list[str]:
    """Decides which push messages to send. First sight of a machine only records its urgency (no startup flood)."""
    out: list[str] = []
    min_rank = SEVERITY_RANK.get(cfg.min_severity, 1)
    for a in sorted(new_alerts, key=lambda x: x["id"]):
        if a["id"] > (state.last_alert_id or 0):
            state.last_alert_id = a["id"]
            if SEVERITY_RANK.get(a["severity"], 1) < min_rank:
                continue
            if a["data_source"] == "simulation" and not cfg.notify_simulated:
                continue
            if _cooldown_ok(state, ("alert", a["machine_id"], a["alert_type"]), now, cfg.cooldown_s):
                out.append(format_alert_push(a, cfg.dashboard_url))
    for m in machines:
        prev = state.last_urgency.get(m["id"])
        state.last_urgency[m["id"]] = m["urgency"]
        if prev is None or prev == m["urgency"]:
            continue
        if m["data_source"] == "simulation" and not cfg.notify_simulated:
            continue
        rose = URGENCY_RANK[m["urgency"]] > URGENCY_RANK[prev]
        recovered = m["urgency"] == "routine" and URGENCY_RANK[prev] >= 1
        if (rose or recovered) and _cooldown_ok(state, ("urgency", m["id"], m["urgency"]), now, cfg.cooldown_s):
            out.append(format_urgency_push(m, prev, cfg.dashboard_url))
    return out


# ----------------------------------------------------------------------------- command handling (pure given a provider)
def parse_command(text: str) -> tuple[str, list[str]]:
    """'/Machine@MyBot 2' -> ('machine', ['2']);  '/machine_2' -> ('machine', ['2']);  'hello' -> ('', [])."""
    text = (text or "").strip()
    if not text.startswith("/"):
        return "", []
    head, *args = text.split()
    cmd = head[1:].split("@", 1)[0].lower()
    m = re.fullmatch(r"(machine)_(\d+)", cmd)
    if m:
        return m.group(1), [m.group(2)]
    return cmd, args


def handle_command(chat_id: int, text: str, provider, state: BotState, cfg: TelegramConfig, now: float | None = None) -> str | None:
    """Returns the reply text, or None to stay silent. `provider` supplies data (see DbProvider)."""
    now = time.time() if now is None else now
    cmd, args = parse_command(text)
    if not cmd:
        return None
    if cmd == "chatid":
        return f"This chat's id is {chat_id}. Add it to TELEGRAM_ALLOWED_CHAT_IDS in the backend .env and restart."
    if chat_id not in cfg.allowed_chat_ids:
        last = state.refused_at.get(chat_id)
        if last is not None and now - last < 60:
            return None
        state.refused_at[chat_id] = now
        return (f"This chat is not authorised for TrustGuard data. Your chat id is {chat_id}; "
                "ask the administrator to add it to TELEGRAM_ALLOWED_CHAT_IDS.")
    if cmd in ("start", "help"):
        return HELP_TEXT
    if cmd in ("status", "summary"):
        return format_status(provider.overview())
    if cmd == "machine":
        return _machine_reply(args, provider)
    if cmd == "alerts":
        return format_alerts(provider.open_alerts())
    if cmd == "devices":
        return format_devices(provider.devices())
    if cmd == "mute":
        minutes = 60
        if args:
            try:
                minutes = int(float(args[0]))
            except ValueError:
                return "Usage: /mute [minutes], for example /mute 120"
        minutes = max(1, min(MAX_MUTE_MINUTES, minutes))
        state.muted_until[chat_id] = now + minutes * 60
        return f"Pushed alerts paused for {minutes} min. You can still ask with /status. Use /unmute to resume early."
    if cmd == "unmute":
        state.muted_until.pop(chat_id, None)
        return "Pushed alerts resumed."
    return "Unknown command. Send /help for the list."


def _machine_reply(args: list[str], provider) -> str:
    machines = provider.overview()
    if not args:
        if len(machines) == 1:
            args = [str(machines[0]["id"])]
        else:
            ids = ", ".join(f"/machine_{m['id']} ({m['name']})" for m in machines) or "none"
            return f"Which machine? Try one of: {ids}"
    try:
        mid = int(args[0])
    except ValueError:
        return "Usage: /machine <id>, for example /machine 1"
    detail = provider.machine(mid)
    return format_machine(detail) if detail else f"No machine with id {mid}."


def is_muted(state: BotState, chat_id: int, now: float) -> bool:
    until = state.muted_until.get(chat_id)
    if until is None:
        return False
    if now >= until:
        state.muted_until.pop(chat_id, None)
        return False
    return True


# ----------------------------------------------------------------------------- database provider
def _v(x):
    return getattr(x, "value", x)


class DbProvider:
    """Reads the live data the dashboard uses. One short-lived session per call."""

    def overview(self) -> list[dict]:
        from database.models import Machine
        from database.session import SessionLocal
        from services.dashboard_service import build_machine_dashboard

        db = SessionLocal()
        try:
            return [machine_summary(build_machine_dashboard(db, m).model_dump(mode="json")) for m in db.query(Machine).order_by(Machine.id).all()]
        finally:
            db.close()

    def machine(self, machine_id: int) -> dict | None:
        from database.models import Machine
        from database.session import SessionLocal
        from services.dashboard_service import build_machine_dashboard

        db = SessionLocal()
        try:
            m = db.get(Machine, machine_id)
            return machine_detail(build_machine_dashboard(db, m).model_dump(mode="json")) if m else None
        finally:
            db.close()

    def open_alerts(self, after_id: int | None = None, limit: int = 50) -> list[dict]:
        from sqlalchemy import select

        from database.models import Alert
        from database.session import SessionLocal
        from services.dashboard_service import machine_data_source

        db = SessionLocal()
        try:
            q = select(Alert).where(Alert.is_resolved.is_(False))
            if after_id is not None:
                q = q.where(Alert.id > after_id)
            rows = db.execute(q.order_by(Alert.id.desc()).limit(limit)).scalars().all()
            return [{
                "id": a.id, "machine_id": a.machine_id, "machine_name": a.machine.name, "alert_type": _v(a.alert_type),
                "severity": _v(a.severity), "message": a.message, "data_source": machine_data_source(a.machine.sensors),
            } for a in rows]
        finally:
            db.close()

    def max_alert_id(self) -> int:
        from sqlalchemy import func, select

        from database.models import Alert
        from database.session import SessionLocal

        db = SessionLocal()
        try:
            return int(db.execute(select(func.max(Alert.id))).scalar() or 0)
        finally:
            db.close()

    def devices(self) -> list[dict]:
        from sqlalchemy import select

        from database.models import Sensor
        from database.session import SessionLocal
        from services import device_health

        db = SessionLocal()
        try:
            rows = db.execute(select(Sensor).where(Sensor.data_source == "hardware").order_by(Sensor.machine_id, Sensor.id)).scalars().all()
            return [{
                "device_id": s.device_id, "machine_name": s.machine.name, "sensor_type": _v(s.sensor_type),
                "status": device_health.compute_status("hardware", s.last_seen_at),
                "seconds_since_seen": device_health.seconds_since(s.last_seen_at),
            } for s in rows]
        finally:
            db.close()


# ----------------------------------------------------------------------------- Telegram HTTP (stdlib)
class TelegramError(Exception):
    pass


def api_call(token: str, method: str, payload: dict | None = None, timeout: float = 15.0) -> dict:
    """POST to the Bot API. Errors never include the token (it is part of the URL)."""
    req = urllib.request.Request(
        f"{API_BASE}/bot{token}/{method}", data=json.dumps(payload or {}).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode()).get("description", "")
        except Exception:
            pass
        raise TelegramError(f"{method} failed: HTTP {exc.code} {detail}".strip()) from None
    except Exception as exc:
        raise TelegramError(f"{method} failed: {type(exc).__name__}") from None
    if not body.get("ok"):
        raise TelegramError(f"{method} failed: {body.get('description', 'unknown error')}")
    return body.get("result") or {}


STATUS = {
    "enabled": False, "configured": False, "recipients": 0, "bot_username": None, "polling": False,
    "last_error": None, "messages_sent": 0, "commands_handled": 0, "last_sent_at": None,
}
_lock = threading.Lock()
_stop = threading.Event()
_state = BotState()
_started = False

KEYBOARD = {"keyboard": [[{"text": "/status"}, {"text": "/alerts"}], [{"text": "/devices"}, {"text": "/help"}]], "resize_keyboard": True}


def _set(**kw):
    with _lock:
        STATUS.update(kw)


def telegram_status() -> dict:
    with _lock:
        s = dict(STATUS)
    s["last_sent_at"] = s["last_sent_at"].isoformat() if s["last_sent_at"] else None
    return s


def send_message(cfg: TelegramConfig, chat_id: int, text: str, keyboard: bool = False) -> bool:
    payload = {"chat_id": chat_id, "text": _clip(text), "disable_web_page_preview": True}
    if keyboard:
        payload["reply_markup"] = KEYBOARD
    try:
        api_call(cfg.token, "sendMessage", payload)
    except TelegramError as exc:
        _set(last_error=str(exc))
        logger.warning("Telegram send failed: %s", exc)
        return False
    with _lock:
        STATUS["messages_sent"] += 1
        STATUS["last_sent_at"] = datetime.now(timezone.utc)
    return True


def broadcast(cfg: TelegramConfig, texts: list[str], state: BotState | None = None) -> int:
    """Sends each text to every authorised, un-muted chat. Returns number of successful deliveries."""
    state = state or _state
    now = time.time()
    sent = 0
    for chat_id in sorted(cfg.allowed_chat_ids):
        if is_muted(state, chat_id, now):
            continue
        for t in texts:
            sent += 1 if send_message(cfg, chat_id, t) else 0
            time.sleep(0.05)  # stay well under Telegram's per-chat rate limit
    return sent


def send_test_message(cfg: TelegramConfig | None = None) -> dict:
    cfg = cfg or load_config()
    if not (cfg.enabled and cfg.token):
        return {"ok": False, "detail": "Telegram is not enabled or TELEGRAM_BOT_TOKEN is empty."}
    if not cfg.allowed_chat_ids:
        return {"ok": False, "detail": "TELEGRAM_ALLOWED_CHAT_IDS is empty. Send /chatid to the bot, add that id to .env and restart."}
    ok = sum(1 for c in sorted(cfg.allowed_chat_ids) if send_message(cfg, c, "TrustGuard test message: the bot can reach this chat. Send /status to try it."))
    return {"ok": ok > 0, "delivered": ok, "recipients": len(cfg.allowed_chat_ids), "detail": None if ok else telegram_status()["last_error"]}


# ----------------------------------------------------------------------------- background threads
def _poll_loop(cfg: TelegramConfig, provider):
    offset = None
    backoff = 2.0
    try:  # a leftover webhook would make getUpdates fail with a conflict
        api_call(cfg.token, "deleteWebhook", {"drop_pending_updates": False})
        latest = api_call(cfg.token, "getUpdates", {"offset": -1, "timeout": 0})
        if latest:
            offset = latest[-1]["update_id"] + 1  # skip commands sent while the backend was down
    except TelegramError as exc:
        _set(last_error=str(exc))
    while not _stop.is_set():
        try:
            params = {"timeout": 25, "allowed_updates": ["message"]}
            if offset is not None:
                params["offset"] = offset
            updates = api_call(cfg.token, "getUpdates", params, timeout=40)
            _set(polling=True, last_error=None)
            backoff = 2.0
            for u in updates if isinstance(updates, list) else []:
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                text, chat = msg.get("text"), (msg.get("chat") or {}).get("id")
                if text is None or chat is None:
                    continue
                try:
                    reply = handle_command(chat, text, provider, _state, cfg)
                except Exception:
                    logger.exception("Telegram command failed")
                    reply = "Sorry, something went wrong reading the data. Please try again."
                if reply:
                    send_message(cfg, chat, reply, keyboard=chat in cfg.allowed_chat_ids)
                    with _lock:
                        STATUS["commands_handled"] += 1
        except TelegramError as exc:
            _set(polling=False, last_error=str(exc))
            logger.warning("Telegram polling problem: %s (retry in %.0fs)", exc, backoff)
            _stop.wait(backoff)
            backoff = min(backoff * 2, 60.0)
        except Exception:
            logger.exception("Unexpected Telegram polling error")
            _stop.wait(backoff)


def _notify_loop(cfg: TelegramConfig, provider):
    if not cfg.allowed_chat_ids:
        return  # nobody to notify
    try:
        _state.last_alert_id = provider.max_alert_id()  # do not announce alerts that already existed at startup
    except Exception:
        logger.exception("Could not read existing alerts; notifier not started")
        return
    while not _stop.wait(cfg.check_interval_s):
        try:
            texts = plan_notifications(provider.open_alerts(after_id=_state.last_alert_id), provider.overview(), _state, cfg, time.time())
            if texts:
                broadcast(cfg, texts)
        except Exception:
            logger.exception("Telegram notifier iteration failed")


def start_telegram_bot(provider=None):
    """No-op unless TELEGRAM_ENABLED=true and a token is set. Never raises (the API must start regardless)."""
    global _started
    cfg = load_config()
    _set(enabled=cfg.enabled, configured=bool(cfg.token), recipients=len(cfg.allowed_chat_ids))
    if not cfg.enabled:
        logger.info("Telegram bot disabled (TELEGRAM_ENABLED=false).")
        return None
    if not cfg.token:
        _set(last_error="TELEGRAM_BOT_TOKEN is empty")
        logger.error("TELEGRAM_ENABLED=true but TELEGRAM_BOT_TOKEN is empty; bot not started.")
        return None
    if _started:
        return None
    _started = True
    provider = provider or DbProvider()
    try:
        me = api_call(cfg.token, "getMe")
        _set(bot_username=me.get("username"))
        logger.info("Telegram bot @%s started; %d authorised chat(s).", me.get("username"), len(cfg.allowed_chat_ids))
    except TelegramError as exc:
        _set(last_error=str(exc))
        logger.error("Telegram token check failed: %s. The bot will keep retrying.", exc)
    if not cfg.allowed_chat_ids:
        logger.warning("TELEGRAM_ALLOWED_CHAT_IDS is empty: no alerts are sent and data commands are refused. Send /chatid to the bot.")
    threading.Thread(target=_poll_loop, args=(cfg, provider), daemon=True, name="telegram-poll").start()
    threading.Thread(target=_notify_loop, args=(cfg, provider), daemon=True, name="telegram-notify").start()
    return True
