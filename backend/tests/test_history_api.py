"""Stored history: nothing is lost or replaced, and it can be filtered by sensor and time range."""
import csv
import io
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from tests.conftest import ADMIN, DEVICE


def _naive_utc(dt):
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture(scope="module")
def hist(client):
    """machine with a temperature sensor (30 hardware readings one minute apart, one of them missing, plus one
    simulated row) and a vibration sensor (10 readings), and an empty sensor named like a spreadsheet formula."""
    from database.models import SensorReading
    from database.session import SessionLocal

    mid = client.post("/api/machines", json={"name": "History machine"}, headers=ADMIN).json()["id"]

    def add(stype, name):
        r = client.post("/api/sensors", headers=ADMIN, json={"machine_id": mid, "sensor_type": stype, "name": name})
        assert r.status_code == 201, r.text
        return r.json()

    temp, vib, formula = add("temperature", "Bearing temp"), add("vibration", "Gearbox vib"), add("temperature", "=SUM(1+1)")
    base = datetime.now(timezone.utc).replace(microsecond=0)
    db = SessionLocal()
    try:
        for k in range(30):  # k=0 newest; k=29 is the missing one
            missing = k == 29
            db.add(SensorReading(sensor_id=temp["id"], value=None if missing else 20.0 + k, raw_value=None if missing else 20.0 + k,
                                 is_missing=missing, source="hardware", timestamp=_naive_utc(base - timedelta(minutes=k))))
        db.add(SensorReading(sensor_id=temp["id"], value=99.0, raw_value=99.0, source="simulation", timestamp=_naive_utc(base - timedelta(minutes=40))))
        for k in range(10):
            db.add(SensorReading(sensor_id=vib["id"], value=0.1 * (k + 1), raw_value=0.1 * (k + 1), source="hardware", timestamp=_naive_utc(base - timedelta(minutes=k))))
        db.add(SensorReading(sensor_id=formula["id"], value=1.0, raw_value=1.0, source="hardware", timestamp=_naive_utc(base)))
        db.commit()
    finally:
        db.close()
    return SimpleNamespace(mid=mid, temp=temp, vib=vib, formula=formula, base=base)


def test_sensor_list_has_names_counts_and_first_last(client, hist):
    rows = {r["id"]: r for r in client.get("/api/history/sensors", params={"machine_id": hist.mid}).json()}
    t = rows[hist.temp["id"]]
    assert t["name"] == "Bearing temp" and t["sensor_type"] == "temperature" and t["hardware_model"] == "DS18B20" and t["unit"] == "°C"
    assert t["reading_count"] == 31 and t["first_at"] < t["last_at"] and t["last_at"].endswith("Z")
    assert rows[hist.vib["id"]]["reading_count"] == 10


def test_a_sensor_without_readings_is_listed_with_zero(client, hist):
    empty = client.post("/api/sensors", headers=ADMIN, json={"machine_id": hist.mid, "sensor_type": "vibration", "name": "No data yet"}).json()
    row = next(r for r in client.get("/api/history/sensors").json() if r["id"] == empty["id"])
    assert row["reading_count"] == 0 and row["first_at"] is None and row["last_at"] is None


def test_readings_carry_sensor_identity_and_newest_comes_first(client, hist):
    r = client.get("/api/history/readings", params={"sensor_id": hist.temp["id"], "range": "7d"}).json()
    assert r["total"] == 31 and len(r["items"]) == 31 and r["has_more"] is False
    first = r["items"][0]
    assert first["sensor_id"] == hist.temp["id"] and first["sensor_name"] == "Bearing temp" and first["sensor_type"] == "temperature"
    assert first["unit"] == "°C" and first["source"] == "hardware" and first["timestamp"].endswith("Z") and first["value"] == 20.0
    stamps = [i["timestamp"] for i in r["items"]]
    assert stamps == sorted(stamps, reverse=True)


def test_time_range_filter_uses_the_exact_window(client, hist):
    start, end = hist.base - timedelta(minutes=12, seconds=30), hist.base - timedelta(minutes=7, seconds=30)  # k = 8..12
    r = client.get("/api/history/readings", params={"sensor_id": hist.temp["id"], "start": _iso(start), "end": _iso(end), "order": "asc"}).json()
    assert r["total"] == 5
    assert [i["value"] for i in r["items"]] == [32.0, 31.0, 30.0, 29.0, 28.0]  # oldest first (k = 12 .. 8 minutes ago)


def test_default_window_is_24_hours_and_all_reaches_further_back(client, hist):
    # the simulated row is 40 minutes old: inside 24h. Make a row two days old to see the difference.
    from database.models import SensorReading
    from database.session import SessionLocal

    db = SessionLocal()
    try:
        db.add(SensorReading(sensor_id=hist.vib["id"], value=5.0, raw_value=5.0, source="hardware", timestamp=_naive_utc(hist.base - timedelta(days=2))))
        db.commit()
    finally:
        db.close()
    assert client.get("/api/history/readings", params={"sensor_id": hist.vib["id"]}).json()["total"] == 10
    assert client.get("/api/history/readings", params={"sensor_id": hist.vib["id"], "range": "all"}).json()["total"] == 11


def test_source_and_missing_filters(client, hist):
    p = {"sensor_id": hist.temp["id"], "range": "7d"}
    assert client.get("/api/history/readings", params={**p, "source": "simulation"}).json()["total"] == 1
    assert client.get("/api/history/readings", params={**p, "source": "hardware"}).json()["total"] == 30
    assert client.get("/api/history/readings", params={**p, "include_missing": "false"}).json()["total"] == 30
    gap = next(i for i in client.get("/api/history/readings", params=p).json()["items"] if i["is_missing"])
    assert gap["value"] is None  # a failed read stays a gap; it is never turned into a number


def test_filter_by_machine_and_by_several_sensors(client, hist):
    by_machine = client.get("/api/history/readings", params={"machine_id": hist.mid, "range": "7d", "limit": 5000}).json()
    assert {i["sensor_id"] for i in by_machine["items"]} >= {hist.temp["id"], hist.vib["id"]}
    two = client.get("/api/history/readings", params=[("sensor_id", hist.temp["id"]), ("sensor_id", hist.vib["id"]), ("range", "7d")]).json()
    assert {i["sensor_id"] for i in two["items"]} == {hist.temp["id"], hist.vib["id"]}


def test_pagination_is_stable_and_complete(client, hist):
    p = {"sensor_id": hist.temp["id"], "range": "7d", "order": "asc", "limit": 10}
    pages = [client.get("/api/history/readings", params={**p, "offset": o}).json() for o in (0, 10, 20, 30)]
    assert [len(x["items"]) for x in pages] == [10, 10, 10, 1] and pages[0]["has_more"] and not pages[3]["has_more"]
    ids = [i["id"] for x in pages for i in x["items"]]
    assert len(ids) == 31 == len(set(ids))


@pytest.mark.parametrize("params,status", [
    ({"start": "yesterday"}, 422), ({"end": "nope"}, 422), ({"range": "2y"}, 422), ({"source": "fake"}, 422),
    ({"start": "2026-10-24T12:00:00Z", "end": "2026-10-24T11:00:00Z"}, 422),
    ({"limit": 0}, 422), ({"limit": 5001}, 422), ({"offset": -1}, 422),
    ({"sensor_id": 999999}, 404), ({"machine_id": 999999}, 404),
])
def test_bad_filters_are_rejected_not_ignored(client, hist, params, status):
    assert client.get("/api/history/readings", params=params).status_code == status


def test_series_returns_buckets_and_a_summary(client, hist):
    r = client.get(f"/api/history/sensors/{hist.temp['id']}/series", params={"range": "7d", "max_points": 10}).json()
    assert r["sensor"]["name"] == "Bearing temp" and r["sensor"]["unit"] == "°C"
    sm = r["summary"]
    assert (sm["count"], sm["missing"]) == (31, 1) and sm["min"] == 20.0 and sm["max"] == 99.0
    assert 0 < len(r["points"]) <= 10 + 1 and sum(p["count"] + p["missing"] for p in r["points"]) == 31
    assert [p["t"] for p in r["points"]] == sorted(p["t"] for p in r["points"])
    hw = client.get(f"/api/history/sensors/{hist.temp['id']}/series", params={"range": "7d", "source": "hardware"}).json()
    assert hw["summary"]["max"] == 48.0 and hw["summary"]["count"] == 30  # the simulated 99.0 is excluded


def test_series_all_range_and_unknown_sensor(client, hist):
    assert client.get(f"/api/history/sensors/{hist.vib['id']}/series", params={"range": "all"}).json()["summary"]["count"] == 11
    assert client.get("/api/history/sensors/999999/series").status_code == 404
    empty = client.post("/api/sensors", headers=ADMIN, json={"machine_id": hist.mid, "sensor_type": "temperature", "name": "Series empty"}).json()
    r = client.get(f"/api/history/sensors/{empty['id']}/series", params={"range": "all"}).json()
    assert r["points"] == [] and r["summary"]["count"] == 0 and r["summary"]["avg"] is None


def test_csv_export_matches_the_filter_and_defuses_formulas(client, hist):
    resp = client.get("/api/history/export.csv", params={"machine_id": hist.mid, "range": "7d"})
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(resp.text)))
    assert rows[0][:4] == ["timestamp_utc", "sensor_id", "sensor_name", "sensor_type"]
    api_total = client.get("/api/history/readings", params={"machine_id": hist.mid, "range": "7d", "limit": 5000}).json()["total"]
    assert len(rows) - 1 == api_total
    names = {r[2] for r in rows[1:]}
    assert "'=SUM(1+1)" in names and "=SUM(1+1)" not in names and "Bearing temp" in names


def test_database_refuses_a_second_hardware_reading_at_the_same_time(client, hist):
    from database.models import SensorReading
    from database.session import SessionLocal

    ts = _naive_utc(hist.base - timedelta(days=5))
    db = SessionLocal()
    try:
        db.add(SensorReading(sensor_id=hist.vib["id"], value=1.0, source="hardware", timestamp=ts))
        db.commit()
        db.add(SensorReading(sensor_id=hist.vib["id"], value=2.0, source="hardware", timestamp=ts))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        # simulated readings are not covered by the rule
        db.add(SensorReading(sensor_id=hist.vib["id"], value=3.0, source="simulation", timestamp=ts))
        db.commit()
    finally:
        db.close()


def test_a_duplicate_caught_by_the_database_is_rejected_cleanly(client, monkeypatch):
    """Two identical messages processed at once: the second hits the unique index and must not become a 500."""
    from services import hardware_ingestion

    mid = client.post("/api/machines", json={"name": "Race machine"}, headers=ADMIN).json()["id"]
    sid = client.post("/api/sensors", headers=ADMIN, json={"machine_id": mid, "sensor_type": "temperature", "name": "Race", "device_id": "ESP32-RACE"}).json()["id"]

    def boom(*a, **k):
        raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))

    monkeypatch.setattr(hardware_ingestion, "ingest_reading", boom)
    body = {"device_id": "ESP32-RACE", "sensor_id": sid, "sensor_type": "temperature", "value": 30.0}
    r = client.post("/api/hardware/ingest", json=body, headers=DEVICE)
    assert r.status_code == 422 and r.json()["detail"]["rejected"] == "duplicate"
    monkeypatch.undo()
    assert client.get("/api/history/readings", params={"sensor_id": sid, "range": "1h"}).json()["total"] == 0


def test_history_follows_the_sensor_when_it_is_removed(client, hist):
    sid = client.post("/api/sensors", headers=ADMIN, json={"machine_id": hist.mid, "sensor_type": "temperature", "name": "Temporary"}).json()["id"]
    assert client.delete(f"/api/sensors/{sid}", headers=ADMIN).status_code == 204
    assert client.get(f"/api/history/sensors/{sid}/series").status_code == 404
    assert client.get("/api/history/readings", params={"sensor_id": sid}).status_code == 404
