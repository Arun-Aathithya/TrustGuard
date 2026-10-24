"""
MQTT bridge for real IoT hardware (ESP32).

    ESP32 --publish--> Mosquitto --subscribe--> this module
        --> services.hardware_ingestion.process_hardware_message()
        --> database + the trust / prediction / recommendation pipeline.

Topics and message format are documented in docs/MQTT.md. In short:

    <MQTT_BASE_TOPIC>/<machine_id>/<sensor_type>/<sensor_id>      (one topic per configured sensor)
    {"device_id": "ESP32-A1", "value": 71.4, "timestamp": "2026-10-18T12:00:00Z"}

Lifecycle: start_mqtt_bridge() is called once at application startup and stop_mqtt_bridge() at shutdown. Calling
start twice returns the existing client, so there is never a second connection with the same client id (a broker
disconnects the older one, which would make the two flap forever). Settings are validated up front
(hardware/mqtt_config.py); a bad setting is reported in /api/hardware/broker and the log instead of crashing startup.
Run the backend with a single worker: each worker would open its own broker connection.

The frontend never talks to the broker or the device, only to FastAPI.
"""
import logging
import os
import ssl
import threading
from datetime import datetime, timezone

from database.session import SessionLocal
from hardware.mqtt_config import MqttConfig, MqttConfigError, RateLimiter, is_enabled, load_config
from services.hardware_ingestion import process_hardware_message

logger = logging.getLogger("trustguard.mqtt")

MAX_TOPIC_LENGTH = 200
_STATE_DEFAULTS = {
    "enabled": False, "connected": False, "host": None, "port": None, "tls": False, "authenticated": False,
    "client_id": None, "last_message_at": None, "last_connect_at": None, "last_disconnect_at": None,
    "last_error": None, "messages_received": 0, "messages_dropped": 0, "disconnects": 0, "config_warnings": [],
}
STATE = dict(_STATE_DEFAULTS)
_client = None
_config: MqttConfig | None = None
_limiter: RateLimiter | None = None
_lock = threading.Lock()
_last_drop_log = 0.0


def broker_status() -> dict:
    with _lock:
        s = dict(STATE)
    for k in ("last_message_at", "last_connect_at", "last_disconnect_at"):
        s[k] = s[k].isoformat() if s[k] else None
    s["base_topic"] = _config.base_topic if _config else os.getenv("MQTT_BASE_TOPIC", "trustguard/sensors")
    return s


def _set(**kw):
    with _lock:
        STATE.update(kw)


def _bump(name: str, by: int = 1):
    with _lock:
        STATE[name] += by


def _is_failure(reason_code) -> bool:
    if hasattr(reason_code, "is_failure"):
        return bool(reason_code.is_failure)
    try:
        return int(reason_code) != 0
    except (TypeError, ValueError):
        return reason_code is not None


def _refusal_hint(reason: str) -> str:
    low = reason.lower()
    if "not authorized" in low or "bad user name" in low or "bad username" in low:
        return " - the broker rejected the credentials: check MQTT_USERNAME / MQTT_PASSWORD against the broker's password file and ACL"
    return ""


def _on_connect(client, userdata, flags, reason_code, properties=None):
    if _is_failure(reason_code):
        reason = str(reason_code)
        _set(connected=False, last_error=f"broker refused the connection: {reason}{_refusal_hint(reason)}")
        logger.error("MQTT connection refused: %s", reason)
        return
    base = _config.base_topic if _config else os.getenv("MQTT_BASE_TOPIC", "trustguard/sensors")
    client.subscribe(f"{base}/#", qos=1)  # (re)subscribe on every connect so reconnects keep working
    _set(connected=True, last_connect_at=datetime.now(timezone.utc), last_error=None)
    logger.info("MQTT connected to %s:%s as '%s', subscribed to %s/#", STATE["host"], STATE["port"], STATE["client_id"], base)


def _on_disconnect(client, userdata, *args):
    # paho 2.x: (disconnect_flags, reason_code, properties); paho 1.x: (rc,)
    reason = args[1] if len(args) >= 2 else (args[0] if args else None)
    unexpected = reason is not None and _is_failure(reason)
    _set(connected=False, last_disconnect_at=datetime.now(timezone.utc))
    _bump("disconnects")
    if unexpected:
        _set(last_error=f"connection to the broker was lost ({reason}); reconnecting automatically")
        logger.warning("MQTT connection lost (%s). Auto-reconnect is active.", reason)
    else:
        logger.info("MQTT disconnected.")


def _on_message(client, userdata, msg):
    if msg.retain:
        # A retained message is an old value replayed on (re)subscribe - it is not proof the device is alive now.
        logger.debug("Ignoring retained message on %s", msg.topic)
        return
    if _limiter is not None and not _limiter.allow():
        _bump("messages_dropped")
        _log_drop()
        return
    topic = msg.topic if isinstance(msg.topic, str) else str(msg.topic)
    if len(topic) > MAX_TOPIC_LENGTH:
        _bump("messages_dropped")
        logger.warning("Dropped MQTT message: topic longer than %d characters", MAX_TOPIC_LENGTH)
        return
    _set(last_message_at=datetime.now(timezone.utc))
    _bump("messages_received")
    db = SessionLocal()
    try:
        process_hardware_message(db, channel="mqtt", raw=bytes(msg.payload), topic=topic)
    except Exception:
        logger.exception("Unhandled error processing MQTT message on %s", topic)
        db.rollback()
    finally:
        db.close()


def _log_drop():
    """At most one warning every 10 s, however large the flood."""
    import time

    global _last_drop_log
    now = time.monotonic()
    if now - _last_drop_log >= 10:
        _last_drop_log = now
        logger.warning("MQTT messages are arriving faster than MQTT_MAX_MESSAGES_PER_SECOND; extra messages are dropped (%d so far).",
                       STATE["messages_dropped"])


def _fail(message: str):
    _set(last_error=message)
    logger.error(message)
    return None


def start_mqtt_bridge(env=None):
    """Start the MQTT client in a background thread. No-op unless MQTT_ENABLED=true. Safe to call twice."""
    global _client, _config, _limiter
    with _lock:
        if _client is not None:
            logger.info("MQTT bridge already running; not starting a second connection.")
            return _client
    environ = os.environ if env is None else env
    try:
        enabled = is_enabled(environ)
    except MqttConfigError as exc:
        _set(enabled=True)
        return _fail(f"MQTT not started: {exc}")
    if not enabled:
        _set(**_STATE_DEFAULTS)
        logger.info("MQTT bridge disabled (MQTT_ENABLED=false). No hardware data can arrive over MQTT.")
        return None
    _set(enabled=True)
    try:
        cfg = load_config(environ)
    except MqttConfigError as exc:
        return _fail(f"MQTT not started: {exc}")
    for w in cfg.warnings:
        logger.warning("MQTT config: %s", w)
    if int(os.getenv("WEB_CONCURRENCY", "1") or 1) > 1:
        logger.warning("WEB_CONCURRENCY > 1: every worker would open its own MQTT connection. Run a single worker.")

    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        return _fail("MQTT not started: paho-mqtt is not installed (pip install -r requirements.txt)")

    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cfg.client_id)
    except AttributeError:  # paho-mqtt 1.x
        client = mqtt.Client(client_id=cfg.client_id)
    if cfg.username:
        client.username_pw_set(cfg.username, cfg.password)
    tls_active = False
    if cfg.use_tls:
        try:
            client.tls_set(ca_certs=cfg.ca_certs or None)  # certificate verification stays ON
            tls_active = True
        except (OSError, ssl.SSLError, ValueError) as exc:
            return _fail(f"MQTT not started: could not set up TLS ({exc}). Check MQTT_CA_CERTS.")
    elif cfg.username:
        logger.warning("MQTT credentials are being sent WITHOUT TLS. Set MQTT_TLS=true outside a trusted LAN.")

    client.on_connect = _on_connect
    client.on_disconnect = _on_disconnect
    client.on_message = _on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    _config = cfg
    _limiter = RateLimiter(cfg.max_messages_per_second)
    _set(host=cfg.host, port=cfg.port, tls=tls_active, authenticated=bool(cfg.username), client_id=cfg.client_id,
         config_warnings=list(cfg.warnings), last_error=None)
    try:
        client.connect_async(cfg.host, cfg.port, keepalive=cfg.keepalive)  # never raises if the broker is down; retries in the loop
        client.loop_start()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Could not start MQTT client")
        return _fail(f"MQTT not started: {exc}")
    with _lock:
        _client = client
    logger.info("MQTT client started (%s:%s, TLS %s, user %s).", cfg.host, cfg.port, "on" if tls_active else "OFF",
                cfg.username or "none")
    return client


def stop_mqtt_bridge() -> None:
    """Close the broker connection (application shutdown). Safe when MQTT was never started."""
    global _client
    with _lock:
        client, _client = _client, None
    if client is None:
        return
    try:
        client.loop_stop()
        client.disconnect()
    except Exception:  # noqa: BLE001
        logger.exception("Error while stopping the MQTT client")
    _set(connected=False)
    logger.info("MQTT client stopped.")
