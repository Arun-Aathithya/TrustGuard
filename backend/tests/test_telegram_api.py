"""Integration tests (need the full backend deps): database provider + HTTP endpoints. Run: pytest -q"""
from tests.conftest import ADMIN


def test_db_provider_reads_configured_machines(client):
    from services import telegram_bot as tb

    p = tb.DbProvider()
    machines = p.overview()
    assert machines and {"id", "name", "data_source", "failure_risk", "confidence", "trust", "urgency"} <= set(machines[0])
    detail = p.machine(machines[0]["id"])
    assert detail and detail["sensors"] and "headline" in detail
    assert p.machine(999999) is None
    assert isinstance(p.max_alert_id(), int)
    for a in p.open_alerts():
        assert {"id", "machine_id", "machine_name", "alert_type", "severity", "message", "data_source"} <= set(a)
    assert isinstance(p.devices(), list)
    text = tb.format_status(machines) + tb.format_machine(detail) + tb.format_alerts(p.open_alerts()) + tb.format_devices(p.devices())
    assert "SIMULATED" in text or "REAL HARDWARE" in text or "MIXED" in text


def test_status_endpoint_has_no_secrets(client):
    r = client.get("/api/telegram/status")
    assert r.status_code == 200
    body = r.json()
    assert {"enabled", "configured", "recipients", "polling", "last_error"} <= set(body)
    assert "token" not in str(body).lower().replace("telegram_bot_token", "")


def test_test_endpoint_requires_admin_and_reports_disabled(client):
    assert client.post("/api/telegram/test").status_code == 401
    r = client.post("/api/telegram/test", headers=ADMIN)
    assert r.status_code == 200 and r.json()["ok"] is False and "not enabled" in r.json()["detail"]
