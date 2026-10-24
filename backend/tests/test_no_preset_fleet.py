"""The application must start with no machines, devices, sensors or readings: nothing is pre-loaded."""
import importlib

import pytest

from tests.conftest import ADMIN, STARTUP


def test_startup_has_no_machines_sensors_or_devices(client):
    assert STARTUP["machines"] == []
    assert STARTUP["dashboards"] == []
    assert STARTUP["devices"] == []
    s = STARTUP["hardware_summary"]
    assert s["hardware_sensors"] == 0 and s["simulated_sensors"] == 0 and s["devices_registered"] == 0


def test_seed_modules_are_gone():
    for name in ("services.seed_service", "seed_db"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(name)


def test_simulation_tick_refuses_a_machine_with_no_sensors(client):
    r = client.post("/api/machines", json={"name": "Empty machine"}, headers=ADMIN)
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    dash = client.get(f"/api/machines/{mid}/dashboard").json()
    assert dash["sensors"] == [] and dash["latest_prediction"] is None
    tick = client.post("/api/simulate/tick", json={"machine_id": mid, "scenario": "normal"})
    assert tick.status_code == 409
    assert client.get(f"/api/machines/{mid}/dashboard").json()["latest_prediction"] is None
    assert client.delete(f"/api/machines/{mid}", headers=ADMIN).status_code == 204
