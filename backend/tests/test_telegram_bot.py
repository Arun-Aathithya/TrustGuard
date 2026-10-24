"""Telegram bot tests: stdlib only (no database, no internet). A tiny local HTTP server stands in for api.telegram.org."""
import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from services import telegram_bot as tb

ALLOWED = 111


def cfg(**kw):
    base = dict(enabled=True, token="123:SECRET", allowed_chat_ids=frozenset({ALLOWED}), cooldown_s=600.0)
    base.update(kw)
    return tb.TelegramConfig(**base)


def summary(mid=1, urgency="routine", source="simulation", risk=20.0, conf=90.0, trust=95.0, alerts=0):
    return {"id": mid, "name": f"Machine {mid}", "data_source": source, "failure_risk": risk, "confidence": conf, "trust": trust,
            "urgency": urgency, "fault_label": "No fault indicated", "open_alerts": alerts, "hardware_devices": 0,
            "devices": {"online": 0, "stale": 0, "offline": 0}}


def alert(aid=1, mid=1, severity="warning", kind="sensor_fault", source="simulation"):
    return {"id": aid, "machine_id": mid, "machine_name": f"Machine {mid}", "alert_type": kind, "severity": severity,
            "message": "temperature sensor looks unreliable", "data_source": source}


class FakeProvider:
    def __init__(self):
        self.machines = [summary(1), summary(2, urgency="soon", risk=72.0, conf=48.0, trust=55.0, alerts=1)]

    def overview(self):
        return self.machines

    def machine(self, mid):
        m = next((x for x in self.machines if x["id"] == mid), None)
        if not m:
            return None
        return {**m, "headline": "A sensor may be faulty; check it before acting on the risk figure.", "urgency_label": "Soon - plan action this shift or day",
                "action": "Check the flagged sensor, then keep monitoring", "why_risk": "Failure risk is high (72%).", "why_confidence": "Confidence is only 48%.",
                "caveats": ["Data shown is simulated; injected faults are artificial."],
                "sensors": [{"type": "temperature", "value": 71.234, "unit": "°C", "trust": 55.0, "status": "simulated", "data_source": "simulation",
                             "seconds_since_seen": None, "note": "Data from this sensor may be unreliable (shows drift); trust 55%."}]}

    def open_alerts(self, after_id=None, limit=50):
        return [alert(5)]

    def devices(self):
        return [{"device_id": "ESP32-A1", "machine_name": "Machine 1", "sensor_type": "vibration", "status": "stale", "seconds_since_seen": 45}]

    def max_alert_id(self):
        return 0


# ---------------------------------------------------------------- parsing / config
@pytest.mark.parametrize("raw,expected", [("123, -100456 ,abc", {123, -100456}), ("", set()), ("  ", set()), ("1;2 3", {1, 2, 3})])
def test_parse_chat_ids(raw, expected):
    assert tb.parse_chat_ids(raw) == frozenset(expected)


def test_parse_command_variants():
    assert tb.parse_command("/Machine@MyBot 2") == ("machine", ["2"])
    assert tb.parse_command("/machine_7") == ("machine", ["7"])
    assert tb.parse_command("/status") == ("status", [])
    assert tb.parse_command("hello") == ("", [])
    assert tb.parse_command(None) == ("", [])


def test_load_config_defaults_and_bad_values(monkeypatch):
    import os
    for k in [k for k in os.environ if k.startswith("TELEGRAM_")]:
        monkeypatch.delenv(k)
    c = tb.load_config()
    assert not c.enabled and c.allowed_chat_ids == frozenset() and c.min_severity == "warning" and c.notify_simulated
    monkeypatch.setenv("TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_MIN_SEVERITY", "nonsense")
    monkeypatch.setenv("TELEGRAM_ALERT_COOLDOWN_MINUTES", "abc")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "5, 6")
    c = tb.load_config()
    assert c.enabled and c.min_severity == "warning" and c.cooldown_s == 600 and c.allowed_chat_ids == frozenset({5, 6})


# ---------------------------------------------------------------- command handling + authorisation
def test_unauthorised_chat_gets_only_its_id_and_a_refusal():
    st, c, p = tb.BotState(), cfg(), FakeProvider()
    assert "999" in tb.handle_command(999, "/chatid", p, st, c)
    refusal = tb.handle_command(999, "/status", p, st, c, now=1000)
    assert "not authorised" in refusal and "Machine" not in refusal
    assert tb.handle_command(999, "/status", p, st, c, now=1010) is None      # refusals are rate-limited
    assert tb.handle_command(999, "/machine 1", p, st, c, now=1100) is not None


def test_empty_allow_list_authorises_nobody():
    out = tb.handle_command(ALLOWED, "/status", FakeProvider(), tb.BotState(), cfg(allowed_chat_ids=frozenset()))
    assert "not authorised" in out


def test_status_shows_three_separate_measures_and_source():
    out = tb.handle_command(ALLOWED, "/status", FakeProvider(), tb.BotState(), cfg())
    assert "SIMULATED" in out and "risk 72%" in out and "confidence 48%" in out and "sensor trust 55%" in out
    assert "/machine_2" in out


def test_machine_detail_separates_sensor_note_and_has_caveat():
    out = tb.handle_command(ALLOWED, "/machine_2", FakeProvider(), tb.BotState(), cfg())
    assert "Failure risk 72%" in out and "Prediction confidence 48%" in out and "Sensor trust 55%" in out
    assert "may be unreliable" in out and "Recommended action" in out and "injected faults are artificial" in out


def test_machine_usage_and_unknown_id():
    st, c, p = tb.BotState(), cfg(), FakeProvider()
    assert "Which machine" in tb.handle_command(ALLOWED, "/machine", p, st, c)
    assert "No machine with id 9" in tb.handle_command(ALLOWED, "/machine 9", p, st, c)
    assert "Usage" in tb.handle_command(ALLOWED, "/machine abc", p, st, c)


def test_alerts_devices_help_unknown_and_plain_text():
    st, c, p = tb.BotState(), cfg(), FakeProvider()
    assert "temperature sensor looks unreliable" in tb.handle_command(ALLOWED, "/alerts", p, st, c)
    assert "ESP32-A1" in tb.handle_command(ALLOWED, "/devices", p, st, c) and "stale" in tb.handle_command(ALLOWED, "/devices", p, st, c)
    assert "/status" in tb.handle_command(ALLOWED, "/help", p, st, c)
    assert "Unknown command" in tb.handle_command(ALLOWED, "/frobnicate", p, st, c)
    assert tb.handle_command(ALLOWED, "just chatting", p, st, c) is None


def test_no_alerts_and_no_devices_messages():
    assert tb.format_alerts([]) == "No open alerts."
    assert "simulated" in tb.format_devices([]).lower()


def test_mute_unmute_and_cap():
    st, c, p = tb.BotState(), cfg(), FakeProvider()
    assert "120 min" in tb.handle_command(ALLOWED, "/mute 120", p, st, c, now=1000)
    assert tb.is_muted(st, ALLOWED, 1000 + 119 * 60) and not tb.is_muted(st, ALLOWED, 1000 + 121 * 60)
    assert "1440 min" in tb.handle_command(ALLOWED, "/mute 99999", p, st, c, now=0)
    assert "Usage" in tb.handle_command(ALLOWED, "/mute soon", p, st, c)
    tb.handle_command(ALLOWED, "/unmute", p, st, c, now=0)
    assert not tb.is_muted(st, ALLOWED, 1)


def test_long_messages_are_clipped():
    assert len(tb._clip("x" * 10000)) <= tb.MAX_MESSAGE_CHARS


# ---------------------------------------------------------------- push notification planning
def test_new_alert_is_pushed_once_then_cooled_down():
    st, c = tb.BotState(last_alert_id=0), cfg()
    first = tb.plan_notifications([alert(1)], [], st, c, now=1000)
    assert len(first) == 1 and "SIMULATED" in first[0] and "/machine_1" in first[0]
    assert tb.plan_notifications([alert(1)], [], st, c, now=1001) == []                       # same alert id: not repeated
    assert tb.plan_notifications([alert(2)], [], st, c, now=1100) == []                       # same machine+type inside cooldown
    assert len(tb.plan_notifications([alert(3)], [], st, c, now=1000 + 601)) == 1             # cooldown over
    assert len(tb.plan_notifications([alert(4, kind="high_risk")], [], st, c, now=1000 + 602)) == 1   # different type is independent


def test_severity_filter_and_simulated_filter():
    st = tb.BotState(last_alert_id=0)
    assert tb.plan_notifications([alert(1, severity="info")], [], st, cfg(), now=1) == []
    st = tb.BotState(last_alert_id=0)
    assert tb.plan_notifications([alert(1)], [], st, cfg(notify_simulated=False), now=1) == []
    st = tb.BotState(last_alert_id=0)
    assert len(tb.plan_notifications([alert(1, source="hardware")], [], st, cfg(notify_simulated=False), now=1)) == 1
    st = tb.BotState(last_alert_id=0)
    assert tb.plan_notifications([alert(1, severity="warning")], [], st, cfg(min_severity="critical"), now=1) == []


def test_urgency_rise_and_recovery_but_never_on_first_sight():
    st, c = tb.BotState(last_alert_id=0), cfg(cooldown_s=0)
    assert tb.plan_notifications([], [summary(urgency="soon")], st, c, now=1) == []           # startup: only records
    up = tb.plan_notifications([], [summary(urgency="immediate", risk=90.0)], st, c, now=2)
    assert len(up) == 1 and "IMMEDIATE" in up[0] and "was soon" in up[0]
    assert tb.plan_notifications([], [summary(urgency="immediate")], st, c, now=3) == []      # unchanged
    back = tb.plan_notifications([], [summary(urgency="routine")], st, c, now=4)
    assert len(back) == 1 and "back to routine" in back[0]


def test_urgency_flapping_is_limited_by_cooldown():
    st, c = tb.BotState(last_alert_id=0), cfg(cooldown_s=600)
    tb.plan_notifications([], [summary(urgency="routine")], st, c, now=0)
    sent = 0
    for i, u in enumerate(["soon", "routine", "soon", "routine", "soon"]):
        sent += len(tb.plan_notifications([], [summary(urgency=u)], st, c, now=10 + i))
    assert sent == 2   # one "soon" and one "recovered"; the repeats are suppressed


# ---------------------------------------------------------------- fake Telegram server
class FakeTelegram:
    def __init__(self):
        self.sent, self.updates, self.calls = [], queue.Queue(), []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                method = self.path.rsplit("/", 1)[-1]
                outer.calls.append((self.path, method, body))
                if "SECRET" not in self.path:
                    return self._reply({"ok": False, "description": "Unauthorized"}, 401)
                if method == "getMe":
                    return self._reply({"ok": True, "result": {"username": "tg_test_bot"}})
                if method == "getUpdates":
                    if body.get("offset") == -1:
                        return self._reply({"ok": True, "result": []})
                    try:
                        return self._reply({"ok": True, "result": [outer.updates.get(timeout=0.3)]})
                    except queue.Empty:
                        return self._reply({"ok": True, "result": []})
                if method == "sendMessage":
                    outer.sent.append(body)
                    return self._reply({"ok": True, "result": {"message_id": len(outer.sent)}})
                return self._reply({"ok": True, "result": True})

            def _reply(self, obj, code=200):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def _wait(cond, seconds=5.0):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_send_message_and_error_never_leaks_token(monkeypatch):
    fake = FakeTelegram()
    monkeypatch.setattr(tb, "API_BASE", fake.url)
    try:
        assert tb.send_message(cfg(), ALLOWED, "hello")
        assert fake.sent[-1]["chat_id"] == ALLOWED and fake.sent[-1]["text"] == "hello"
        with pytest.raises(tb.TelegramError) as exc:
            tb.api_call("bad-token", "getMe")
        assert "bad-token" not in str(exc.value) and "401" in str(exc.value)
        assert not tb.send_message(cfg(token="bad-token"), ALLOWED, "x")
    finally:
        fake.close()


def test_send_test_message_reports_missing_configuration():
    assert "not enabled" in tb.send_test_message(cfg(enabled=False))["detail"]
    assert "ALLOWED_CHAT_IDS" in tb.send_test_message(cfg(allowed_chat_ids=frozenset()))["detail"]


def test_broadcast_skips_muted_chats(monkeypatch):
    fake = FakeTelegram()
    monkeypatch.setattr(tb, "API_BASE", fake.url)
    try:
        st = tb.BotState(muted_until={ALLOWED: time.time() + 100})
        assert tb.broadcast(cfg(), ["a"], st) == 0 and fake.sent == []
        assert tb.broadcast(cfg(allowed_chat_ids=frozenset({ALLOWED, 222})), ["a"], tb.BotState()) == 2
    finally:
        fake.close()


def test_polling_loop_answers_commands_end_to_end(monkeypatch):
    fake = FakeTelegram()
    monkeypatch.setattr(tb, "API_BASE", fake.url)
    tb._stop.clear()
    tb._state = tb.BotState()
    t = threading.Thread(target=tb._poll_loop, args=(cfg(), FakeProvider()), daemon=True)
    t.start()
    try:
        fake.updates.put({"update_id": 10, "message": {"chat": {"id": ALLOWED}, "text": "/status"}})
        fake.updates.put({"update_id": 11, "message": {"chat": {"id": 999}, "text": "/status"}})
        fake.updates.put({"update_id": 12, "edited_message": {}})                       # ignored update types must not crash it
        assert _wait(lambda: len(fake.sent) >= 2)
        by_chat = {m["chat_id"]: m["text"] for m in fake.sent}
        assert "Machine 2" in by_chat[ALLOWED] and "not authorised" in by_chat[999]
        assert fake.sent[0]["reply_markup"]["keyboard"]                                    # authorised chat gets the quick buttons
        assert "reply_markup" not in next(m for m in fake.sent if m["chat_id"] == 999)
        assert tb.telegram_status()["polling"] is True
    finally:
        tb._stop.set()
        t.join(timeout=5)
        tb._stop.clear()
        fake.close()
    assert not t.is_alive()


# ---------------------------------------------------------------- dashboard dict -> bot dicts (shape of MachineDashboard.model_dump)
def _dashboard_dict():
    def sensor(stype, unit, src, status, seen, value, trust):
        return {"sensor": {"id": 1, "sensor_type": stype, "unit": unit, "data_source": src, "device_status": status, "seconds_since_seen": seen},
                "latest_value": value, "trust": {"trust_score": trust} if trust is not None else None}
    return {
        "machine": {"id": 3, "name": "Pump 3"}, "data_source": "mixed", "overall_trust": 58.0,
        "latest_prediction": {"failure_risk": 66.0, "prediction_confidence": 47.0},
        "open_alerts": [{"id": 1}, {"id": 2}], "recommendation": "Inspect",
        "sensors": [sensor("temperature", "°C", "hardware", "stale", 80, 64.2, 41.0), sensor("vibration", "mm/s", "hardware", "online", 2, 2.6, 90.0),
                    sensor("pressure", "kPa", "simulation", "simulated", None, 101.0, 95.0)],
        "explanation": {"urgency": "soon", "urgency_label": "Soon - plan action this shift or day", "fault_label": "Suspected sensor fault",
                        "headline": "A sensor may be faulty.", "action": "Check the flagged sensor", "why_risk": "r", "why_confidence": "c", "caveats": ["cav"],
                        "contributors": [{"sensor_type": "temperature", "role": "sensor_suspect", "note": "Data may be unreliable (data is stale); trust 41%."},
                                         {"sensor_type": "vibration", "role": "ok", "note": "Reading within normal range."}]},
    }


def test_summary_and_detail_from_dashboard_dict():
    s = tb.machine_summary(_dashboard_dict())
    assert s["id"] == 3 and s["failure_risk"] == 66.0 and s["confidence"] == 47.0 and s["trust"] == 58.0 and s["open_alerts"] == 2
    assert s["hardware_devices"] == 2 and s["devices"] == {"online": 1, "stale": 1, "offline": 0} and s["urgency"] == "soon"
    text = tb.format_machine(tb.machine_detail(_dashboard_dict()))
    assert "MIXED" in text and "temperature: 64.20 °C" in text and "stale · seen 80s ago" in text
    assert "data is stale" in text and "Reading within normal range" not in text      # only problem notes are shown


def test_summary_without_prediction_does_not_crash():
    d = _dashboard_dict()
    d["latest_prediction"], d["explanation"], d["sensors"] = None, None, []
    s = tb.machine_summary(d)
    assert s["failure_risk"] is None and s["urgency"] == "routine"
    assert "risk n/a" in tb.format_status([s]) and "n/a" in tb.format_machine(tb.machine_detail(d))
