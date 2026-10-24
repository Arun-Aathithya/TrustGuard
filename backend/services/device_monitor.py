"""
Background device monitor.

Every few seconds it re-evaluates each hardware sensor's Online/Stale/Offline
status. When a device goes Offline it raises a DEVICE_OFFLINE alert and
re-runs the machine pipeline (so trust/confidence reflect the lost data);
when it comes back, the alert is resolved automatically.
"""
import logging
import os
import threading
from datetime import datetime, timezone

from sqlalchemy import select

from database.models import Alert, AlertSeverity, AlertType, ConnectionStatus, Sensor
from database.session import SessionLocal
from services import device_health
from services.ingestion_service import run_pipeline_for_machine
from simulation.simulator import BASELINES

logger = logging.getLogger("trustguard.monitor")
_stop = threading.Event()


def check_devices_once(db) -> int:
    """Returns number of status changes made (also used by tests)."""
    changes = 0
    sensors = db.execute(select(Sensor).where(Sensor.data_source == "hardware")).scalars().all()
    for sensor in sensors:
        status = device_health.compute_status("hardware", sensor.last_seen_at)
        open_alert = db.execute(
            select(Alert).where(Alert.sensor_id == sensor.id, Alert.alert_type == AlertType.DEVICE_OFFLINE,
                                Alert.is_resolved.is_(False)).limit(1)
        ).scalars().first()

        if status == device_health.OFFLINE:
            if sensor.connection_status != ConnectionStatus.OFFLINE:
                sensor.connection_status = ConnectionStatus.OFFLINE
                changes += 1
            if open_alert is None and sensor.last_seen_at is not None:  # never-seen devices are just "waiting for data"
                db.add(Alert(
                    machine_id=sensor.machine_id, sensor_id=sensor.id, alert_type=AlertType.DEVICE_OFFLINE,
                    severity=AlertSeverity.WARNING,
                    message=f"{sensor.name or sensor.sensor_type.value} (device {sensor.device_id}) stopped sending data "
                            f"(no message for over {device_health.offline_after_s()}s).",
                ))
                db.flush()
                baseline = {t: BASELINES[t]["mean"] for t in BASELINES}
                run_pipeline_for_machine(db, sensor.machine, baseline)
                changes += 1
        else:
            if status == device_health.ONLINE and sensor.connection_status == ConnectionStatus.OFFLINE:
                sensor.connection_status = ConnectionStatus.ONLINE
                changes += 1
            if open_alert is not None and status == device_health.ONLINE:
                open_alert.is_resolved = True
                open_alert.resolved_at = datetime.now(timezone.utc)
                changes += 1
    db.commit()
    return changes


def _loop(interval: float):
    while not _stop.wait(interval):
        db = SessionLocal()
        try:
            check_devices_once(db)
        except Exception:
            logger.exception("Device monitor iteration failed")
            db.rollback()
        finally:
            db.close()


def start_device_monitor():
    interval = float(os.getenv("DEVICE_MONITOR_INTERVAL_SECONDS", "10"))
    threading.Thread(target=_loop, args=(interval,), daemon=True, name="device-monitor").start()
    logger.info("Device monitor started (every %.0fs).", interval)
