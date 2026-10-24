"""
API-key access control.

  ADMIN_API_KEY   header X-API-Key     -> device registration & other admin actions
  DEVICE_API_KEY  header X-Device-Key  -> HTTP hardware ingestion (/api/hardware/ingest)

Keys live only in backend environment variables - never in frontend code.
If a key is not configured: APP_ENV != "production" allows the call (with a
warning, so the local demo works out of the box); APP_ENV=production refuses it.
"""
import logging
import os
import secrets

from fastapi import Header, HTTPException

logger = logging.getLogger("trustguard.security")
_warned: set[str] = set()


def auth_enforced(env_name: str = "ADMIN_API_KEY") -> bool:
    return bool(os.getenv(env_name, ""))


def _check(provided: str | None, env_name: str, label: str) -> None:
    expected = os.getenv(env_name, "")
    if not expected:
        if os.getenv("APP_ENV", "development").lower() == "production":
            raise HTTPException(503, f"{label} is not configured on the server (set {env_name}).")
        if env_name not in _warned:
            _warned.add(env_name)
            logger.warning("%s is not set - %s endpoints are OPEN. Set it before exposing the API.", env_name, label)
        return
    if not provided or not secrets.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(401, f"Missing or invalid {label}.", headers={"WWW-Authenticate": "ApiKey"})


def require_admin(x_api_key: str | None = Header(default=None)) -> None:
    _check(x_api_key, "ADMIN_API_KEY", "admin API key")


def require_device(x_device_key: str | None = Header(default=None)) -> None:
    _check(x_device_key, "DEVICE_API_KEY", "device API key")


def security_issues() -> list[dict]:
    """
    Structured version for the UI: {id, kind, message, fix}. kind is "security" (fix before a shared network)
    or "setup" (the app works, but hardware cannot). Never contains secret values.
    """
    out = [{"id": "legacy", "kind": "security", "message": m, "fix": None} for m in security_warnings()]
    fixes = {
        "ADMIN_API_KEY": "Generate a key: python -c \"import secrets;print(secrets.token_urlsafe(32))\" , put ADMIN_API_KEY=<key> in backend/.env, restart, then enter it under Hardware > Admin access.",
        "DEVICE_API_KEY": "Generate a key the same way, set DEVICE_API_KEY=<key> in backend/.env and send it as X-Device-Key from devices using HTTP ingestion.",
        "MQTT_TLS": "Use a TLS listener (port 8883): MQTT_TLS=true and MQTT_CA_CERTS=/path/ca.crt. See docs/HARDWARE_SETUP.md section 1.",
        "MQTT_CA_CERTS": "Set MQTT_CA_CERTS to your broker's CA certificate file.",
        "MQTT_USERNAME": "Create a broker user (mosquitto_passwd) and set MQTT_USERNAME / MQTT_PASSWORD.",
        "APP_ENV": "Set APP_ENV=production once keys, TLS and credentials are configured.",
        "TELEGRAM": "See docs/TELEGRAM_BOT.md.",
    }
    for issue in out:
        for key, fix in fixes.items():
            if issue["message"].startswith(key) or (key == "TELEGRAM" and issue["message"].startswith("TELEGRAM")):
                issue["fix"] = fix
                break
        issue["id"] = issue["message"].split(" ")[0].rstrip(":").lower()
    if os.getenv("MQTT_ENABLED", "false").lower() != "true":
        out.insert(0, {"id": "mqtt_enabled", "kind": "setup",
                       "message": "MQTT is disabled (MQTT_ENABLED=false): ESP32 readings cannot arrive over MQTT.",
                       "fix": "Set MQTT_ENABLED=true plus the broker settings in backend/.env and restart. Until then only simulation (or the HTTP fallback) supplies data."})
    return out


def security_warnings() -> list[str]:
    """Configuration problems worth fixing before using this on a shared network. Never contains secret values."""
    prod = os.getenv("APP_ENV", "development").lower() == "production"
    out = []
    for name, label in (("ADMIN_API_KEY", "admin actions (device registration, alert resolve) are OPEN"), ("DEVICE_API_KEY", "HTTP hardware ingestion is OPEN")):
        if not os.getenv(name):
            out.append(f"{name} is not set: {label}.")
    if os.getenv("MQTT_ENABLED", "false").lower() == "true":
        if os.getenv("MQTT_TLS", "false").lower() != "true":
            out.append("MQTT_TLS is off: broker traffic and credentials are unencrypted.")
        elif not os.getenv("MQTT_CA_CERTS"):
            out.append("MQTT_CA_CERTS is empty: the broker certificate is checked against system CAs only (fine for public CAs, not for a private broker CA).")
        if not os.getenv("MQTT_USERNAME"):
            out.append("MQTT_USERNAME is not set: the backend connects to the broker anonymously.")
    if os.getenv("TELEGRAM_ENABLED", "false").lower() == "true":
        if not os.getenv("TELEGRAM_BOT_TOKEN"):
            out.append("TELEGRAM_BOT_TOKEN is empty: the Telegram bot cannot start.")
        if not os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").strip():
            out.append("TELEGRAM_ALLOWED_CHAT_IDS is empty: the bot sends no alerts and refuses data commands (send /chatid to the bot to find your id).")
    if not prod:
        out.append("APP_ENV is not 'production'.")
    return out
