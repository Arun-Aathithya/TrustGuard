"""
TrustGuard AI — FastAPI backend entrypoint.

    uvicorn main:app --reload --port 8000

On startup: creates tables (if missing). Nothing is pre-loaded: machines, devices and sensors are
added by the user, and every reading shown comes either from registered hardware or from an
explicitly triggered, clearly labelled simulation.
"""
import asyncio
import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from api import alerts, hardware, history, machines, maintenance, predictions, readings, sensors, simulate, telegram, trust
from database.session import SessionLocal, init_db
from hardware.mqtt_client import start_mqtt_bridge, stop_mqtt_bridge
from services.device_monitor import start_device_monitor
from services.telegram_bot import start_telegram_bot

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("trustguard")

app = FastAPI(
    title="TrustGuard AI API",
    description="Predictive maintenance with sensor-trust-aware failure prediction.",
    version="1.2.0",
)

origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(machines.router)
app.include_router(sensors.router)
app.include_router(readings.router)
app.include_router(history.router)
app.include_router(trust.router)
app.include_router(predictions.router)
app.include_router(alerts.router)
app.include_router(maintenance.router)
app.include_router(hardware.router)
app.include_router(telegram.router)
app.include_router(simulate.router)


@app.on_event("startup")
def on_startup():
    init_db()
    db = SessionLocal()
    try:
        from database.models import Machine, Sensor

        n_machines, n_sensors = db.query(Machine).count(), db.query(Sensor).count()
    finally:
        db.close()
    if n_machines == 0:
        logger.info("No machines configured yet. Add one in the dashboard (nothing is pre-loaded).")
    else:
        logger.info("Loaded %d configured machine(s) and %d sensor(s) from the database.", n_machines, n_sensors)
    from api.security import security_warnings

    for w in security_warnings():
        logger.warning("SECURITY: %s", w)
    start_mqtt_bridge()
    start_device_monitor()
    start_telegram_bot()
    logger.info("TrustGuard AI backend ready.")


@app.on_event("shutdown")
def on_shutdown():
    stop_mqtt_bridge()


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "TrustGuard AI"}


@app.websocket("/ws/live")
async def live_dashboard(websocket: WebSocket, interval_seconds: float = 5.0):
    """
    Pushes a fresh snapshot of every machine's dashboard every few seconds.
    The frontend uses this for live-updating charts/gauges without polling.
    """
    await websocket.accept()
    from database.models import Machine
    from services.dashboard_service import build_machine_dashboard

    try:
        while True:
            db = SessionLocal()
            try:
                machine_list = db.query(Machine).order_by(Machine.id).all()
                payload = [build_machine_dashboard(db, m).model_dump(mode="json") for m in machine_list]
                await websocket.send_json({"type": "dashboard_update", "machines": payload})
            finally:
                db.close()
            await asyncio.sleep(interval_seconds)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected from /ws/live")
