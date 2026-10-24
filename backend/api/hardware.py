"""
Hardware / IoT management endpoints.

  GET  /api/hardware/summary                    data source + device counts for the dashboard
  GET  /api/hardware/broker                     MQTT broker connection state
  GET  /api/hardware/devices                    every sensor with device mapping + Online/Stale/Offline
  POST /api/hardware/devices/register   (admin) map device_id + sensor type -> machine
  POST /api/hardware/devices/{id}/unregister (admin) return a sensor to simulation
  POST /api/hardware/devices/{id}/test          test-connection checklist
  GET  /api/hardware/events                     ingestion problems (rejected / delayed / malformed ...)
  POST /api/hardware/ingest         (device key) HTTP fallback when MQTT is unavailable
"""
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.security import auth_enforced, require_admin, require_device, security_issues, security_warnings
from database.models import ConnectionStatus, IngestionEvent, Machine, Sensor, SensorType
from database.session import get_db
from hardware.mqtt_client import broker_status
from services import device_health, sensor_catalog, units
from services.dashboard_service import machine_data_source
from services.hardware_ingestion import process_hardware_message
from services.payload_validation import DEVICE_ID_RE
from simulation.simulator import BASELINES
import os

router = APIRouter(prefix="/api/hardware", tags=["hardware"])

TOPIC_RE = re.compile(r"^[A-Za-z0-9_.\-]+(/[A-Za-z0-9_.\-]+)+$")  # no MQTT wildcards (+ #)


class DeviceRegistration(BaseModel):
    device_id: str
    sensor_id: int | None = None
    machine_id: int | None = None
    sensor_type: str | None = None
    mqtt_topic: str | None = None
    unit: str | None = Field(default=None, max_length=20)


class DeviceOut(BaseModel):
    sensor_id: int
    machine_id: int
    machine_name: str
    sensor_type: str
    sensor_name: str | None = None
    unit: str
    device_id: str | None
    mqtt_topic: str | None
    data_source: str
    device_status: str
    connection_status: str
    last_seen_at: datetime | None
    last_data_at: datetime | None
    seconds_since_seen: float | None
    problems_last_hour: int
    unit_status: str = "ok"
    display_unit: str = ""
    unit_warning: str | None = None


def _problem_counts(db: Session) -> dict[int, int]:
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    rows = db.execute(
        select(IngestionEvent.sensor_id, func.count()).where(
            IngestionEvent.created_at >= since, IngestionEvent.sensor_id.is_not(None), IngestionEvent.event_type != "accepted"
        ).group_by(IngestionEvent.sensor_id)
    ).all()
    return {sid: n for sid, n in rows}


def _to_out(sensor: Sensor, problems: dict[int, int]) -> DeviceOut:
    ua = units.unit_assessment(sensor.sensor_type.value, sensor.data_source, sensor.unit, sensor.device_id)
    return DeviceOut(
        unit_status=ua["status"], display_unit=ua["display_unit"], unit_warning=ua["warning"],
        sensor_id=sensor.id, machine_id=sensor.machine_id, machine_name=sensor.machine.name,
        sensor_type=sensor.sensor_type.value, sensor_name=sensor.name, unit=sensor.unit, device_id=sensor.device_id, mqtt_topic=sensor.mqtt_topic,
        data_source=sensor.data_source, device_status=device_health.compute_status(sensor.data_source, sensor.last_seen_at),
        connection_status=sensor.connection_status.value, last_seen_at=sensor.last_seen_at, last_data_at=sensor.last_data_at,
        seconds_since_seen=device_health.seconds_since(sensor.last_seen_at) if sensor.data_source == "hardware" else None,
        problems_last_hour=problems.get(sensor.id, 0),
    )


@router.get("/broker")
def get_broker_status():
    return {**broker_status(), "admin_auth_enforced": auth_enforced("ADMIN_API_KEY"), "device_auth_enforced": auth_enforced("DEVICE_API_KEY"), "security_warnings": security_warnings(), "security_issues": security_issues()}


@router.get("/devices", response_model=list[DeviceOut])
def list_devices(registered_only: bool = False, db: Session = Depends(get_db)):
    q = select(Sensor).order_by(Sensor.machine_id, Sensor.id)
    if registered_only:
        q = q.where(Sensor.data_source == "hardware")
    problems = _problem_counts(db)
    return [_to_out(s, problems) for s in db.execute(q).scalars().all()]


@router.get("/summary")
def hardware_summary(db: Session = Depends(get_db)):
    sensors = db.execute(select(Sensor)).scalars().all()
    hw = [s for s in sensors if s.data_source == "hardware"]
    statuses = [device_health.compute_status("hardware", s.last_seen_at) for s in hw]
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    problems = db.execute(select(func.count()).select_from(IngestionEvent).where(
        IngestionEvent.created_at >= since, IngestionEvent.accepted.is_(False))).scalar() or 0
    delayed = db.execute(select(func.count()).select_from(IngestionEvent).where(
        IngestionEvent.created_at >= since, IngestionEvent.event_type == "delayed")).scalar() or 0
    return {
        "active_data_source": machine_data_source(sensors),  # hardware | simulation | mixed
        "hardware_sensors": len(hw),
        "simulated_sensors": len(sensors) - len(hw),
        "devices_registered": len({s.device_id for s in hw if s.device_id}),
        "devices_online": statuses.count(device_health.ONLINE),
        "devices_stale": statuses.count(device_health.STALE),
        "devices_offline": statuses.count(device_health.OFFLINE),
        "rejected_last_hour": problems,
        "delayed_last_hour": delayed,
        "broker": {"enabled": broker_status()["enabled"], "connected": broker_status()["connected"]},
    }


@router.post("/devices/register", response_model=DeviceOut, dependencies=[Depends(require_admin)])
def register_device(payload: DeviceRegistration, db: Session = Depends(get_db)):
    if not DEVICE_ID_RE.match(payload.device_id):
        raise HTTPException(422, "device_id must be 3-80 characters: letters, digits, _ . -")

    if payload.sensor_id is not None:
        sensor = db.get(Sensor, payload.sensor_id)
        if not sensor:
            raise HTTPException(404, "Sensor not found")
    else:
        if payload.machine_id is None or not payload.sensor_type:
            raise HTTPException(422, "Provide sensor_id, or machine_id + sensor_type.")
        machine = db.get(Machine, payload.machine_id)
        if not machine:
            raise HTTPException(404, "Machine not found")
        if not sensor_catalog.is_supported(payload.sensor_type):
            raise HTTPException(422, f"Unsupported sensor_type. Supported: {sensor_catalog.supported_list()}.")
        stype = SensorType(sensor_catalog.type_value(payload.sensor_type))
        candidates = [s for s in machine.sensors if s.sensor_type == stype]
        # Re-registering the same device is idempotent; otherwise take a sensor that is still waiting for a device
        # (e.g. one added on the website), and only create a new one if there is none.
        sensor = next((s for s in candidates if s.device_id == payload.device_id), None) \
            or next((s for s in candidates if s.data_source != "hardware" or not s.device_id), None)
        if sensor is None:
            spec = sensor_catalog.SUPPORTED_SENSORS[stype.value]
            sensor = Sensor(machine_id=machine.id, sensor_type=stype, unit=spec["unit"], hardware_model=spec["hardware_model"],
                            name=f"{spec['label']} sensor {len(candidates) + 1}" if candidates else f"{spec['label']} sensor")
            db.add(sensor)
            db.flush()

    base = os.getenv("MQTT_BASE_TOPIC", "trustguard/sensors")
    topic = payload.mqtt_topic or sensor.mqtt_topic or f"{base}/{sensor.machine_id}/{sensor.sensor_type.value}"
    if not payload.mqtt_topic and not sensor.mqtt_topic and db.execute(
            select(Sensor.id).where(Sensor.mqtt_topic == topic, Sensor.id != sensor.id)).first():
        topic = f"{topic}/{sensor.id}"  # a second sensor of the same type on this machine
    if not TOPIC_RE.match(topic) or not topic.startswith(base + "/"):
        raise HTTPException(422, f"mqtt_topic must start with '{base}/' and contain no wildcards.")

    clash = db.execute(select(Sensor).where(Sensor.mqtt_topic == topic, Sensor.id != sensor.id)).scalars().first()
    if clash:
        raise HTTPException(409, f"Topic already used by sensor {clash.id}.")
    clash = db.execute(select(Sensor).where(Sensor.device_id == payload.device_id, Sensor.id != sensor.id,
                                            Sensor.data_source == "hardware")).scalars().all()
    if any(c.sensor_type == sensor.sensor_type for c in clash):
        raise HTTPException(409, f"Device {payload.device_id} already provides a {sensor.sensor_type.value} sensor.")

    sensor.device_id = payload.device_id
    sensor.mqtt_topic = topic
    if payload.unit:
        sensor.unit = payload.unit
    sensor.data_source = "hardware"
    sensor.registered_at = datetime.now(timezone.utc)
    sensor.last_seen_at = None
    sensor.connection_status = ConnectionStatus.OFFLINE
    db.commit()
    db.refresh(sensor)
    return _to_out(sensor, {})


@router.post("/devices/{sensor_id}/unregister", response_model=DeviceOut, dependencies=[Depends(require_admin)])
def unregister_device(sensor_id: int, db: Session = Depends(get_db)):
    sensor = db.get(Sensor, sensor_id)
    if not sensor:
        raise HTTPException(404, "Sensor not found")
    sensor.data_source = "simulation"
    sensor.device_id = None
    sensor.last_seen_at = None
    sensor.registered_at = None
    sensor.connection_status = ConnectionStatus.SIMULATED
    db.commit()
    db.refresh(sensor)
    return _to_out(sensor, {})


@router.post("/devices/{sensor_id}/test")
def test_connection(sensor_id: int, db: Session = Depends(get_db)):
    sensor = db.get(Sensor, sensor_id)
    if not sensor:
        raise HTTPException(404, "Sensor not found")
    broker = broker_status()
    status = device_health.compute_status(sensor.data_source, sensor.last_seen_at)
    since = datetime.now(timezone.utc) - timedelta(minutes=10)
    recent_problems = db.execute(select(func.count()).select_from(IngestionEvent).where(
        IngestionEvent.sensor_id == sensor.id, IngestionEvent.created_at >= since, IngestionEvent.accepted.is_(False))).scalar() or 0

    checks = [
        {"name": "Registered as hardware", "ok": sensor.data_source == "hardware",
         "detail": f"device {sensor.device_id}" if sensor.data_source == "hardware" else "sensor is still simulated"},
        {"name": "MQTT broker connected", "ok": bool(broker["connected"]),
         "detail": "connected" if broker["connected"] else (broker["last_error"] or ("MQTT_ENABLED is false" if not broker["enabled"] else "not connected"))},
        {"name": "Message received", "ok": sensor.last_seen_at is not None,
         "detail": f"last message {device_health.seconds_since(sensor.last_seen_at):.0f}s ago" if sensor.last_seen_at else "no message has ever arrived"},
        {"name": "Recent data (not stale)", "ok": status == device_health.ONLINE, "detail": f"status: {status}"},
        {"name": "No rejected messages (10 min)", "ok": recent_problems == 0, "detail": f"{recent_problems} rejected"},
    ]
    ok = all(c["ok"] for c in checks) if sensor.data_source == "hardware" else False
    first_fail = next((c for c in checks if not c["ok"]), None)
    return {"sensor_id": sensor.id, "ok": ok, "device_status": status, "topic": sensor.mqtt_topic, "checks": checks,
            "message": "Device is sending valid, recent data." if ok else f"Not healthy: {first_fail['name']} - {first_fail['detail']}"}


@router.get("/events")
def list_events(sensor_id: int | None = None, only_problems: bool = True, limit: int = 100, db: Session = Depends(get_db)):
    q = select(IngestionEvent).order_by(IngestionEvent.id.desc()).limit(min(max(limit, 1), 500))
    if sensor_id is not None:
        q = q.where(IngestionEvent.sensor_id == sensor_id)
    if only_problems:
        q = q.where(IngestionEvent.event_type != "accepted")
    return [{"id": e.id, "sensor_id": e.sensor_id, "device_id": e.device_id, "topic": e.topic, "channel": e.channel,
             "event_type": e.event_type, "accepted": e.accepted, "detail": e.detail, "created_at": e.created_at}
            for e in db.execute(q).scalars().all()]


@router.post("/ingest", dependencies=[Depends(require_device)])
async def http_ingest(request: Request, db: Session = Depends(get_db)):
    """HTTP fallback for devices without MQTT. Same validation + pipeline as MQTT."""
    body = await request.body()
    result = process_hardware_message(db, channel="http", raw=body, topic=None)
    if not result.accepted:
        raise HTTPException(422, {"rejected": result.event_type, "detail": result.detail})
    return {"accepted": True, "event": result.event_type, "detail": result.detail, "sensor_id": result.sensor_id}
