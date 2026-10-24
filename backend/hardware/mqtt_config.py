"""
MQTT settings read from environment variables, validated before anything connects (no I/O besides a
file-exists check, no third-party imports, so it is easy to test).

    MQTT_ENABLED            true | false (default false)
    MQTT_BROKER_HOST        default localhost
    MQTT_BROKER_PORT        default 1883, or 8883 when MQTT_TLS=true
    MQTT_USERNAME / MQTT_PASSWORD
    MQTT_TLS                true | false. TLS is only reported as ON when this is true AND the client was set up.
    MQTT_CA_CERTS           path to the broker's CA certificate (empty = system CAs only)
    MQTT_BASE_TOPIC         default trustguard/sensors
    MQTT_CLIENT_ID          default trustguard-backend (must be unique per connection to the broker)
    MQTT_KEEPALIVE_SECONDS  default 30
    MQTT_MAX_MESSAGES_PER_SECOND  default 100, 0 = unlimited (flood protection)
"""
import os
import re
import time
from dataclasses import dataclass, field
from typing import Mapping

TOPIC_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"", "0", "false", "no", "off"}


class MqttConfigError(ValueError):
    """The MQTT settings are unusable. The message says which variable and what to do."""


@dataclass(frozen=True)
class MqttConfig:
    host: str
    port: int
    username: str
    password: str = field(repr=False)  # never shown in logs or reprs
    use_tls: bool
    ca_certs: str
    base_topic: str
    client_id: str
    keepalive: int
    max_messages_per_second: int
    warnings: tuple[str, ...] = ()


def _flag(env: Mapping[str, str], name: str, default: bool = False) -> bool:
    raw = str(env.get(name, "") or "").strip().lower()
    if raw == "":
        return default
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    raise MqttConfigError(f"{name} must be true or false (got '{raw}').")


def _int(env: Mapping[str, str], name: str, default: int, lo: int, hi: int) -> int:
    raw = str(env.get(name, "") or "").strip()
    if raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise MqttConfigError(f"{name} must be a whole number (got '{raw}').") from None
    if not lo <= value <= hi:
        raise MqttConfigError(f"{name} must be between {lo} and {hi} (got {value}).")
    return value


def is_enabled(env: Mapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return _flag(env, "MQTT_ENABLED", False)


def validate_base_topic(base: str) -> str:
    base = (base or "").strip()
    if not base or base.startswith("/") or base.endswith("/"):
        raise MqttConfigError("MQTT_BASE_TOPIC must not be empty or start/end with '/'.")
    if not all(TOPIC_SEGMENT_RE.match(seg) for seg in base.split("/")):
        raise MqttConfigError("MQTT_BASE_TOPIC may only contain letters, digits, _ . - and '/' (no MQTT wildcards + #).")
    return base


def load_config(env: Mapping[str, str] | None = None) -> MqttConfig:
    """Validate everything up front. Raises MqttConfigError instead of failing later inside the MQTT thread."""
    env = os.environ if env is None else env
    warnings: list[str] = []

    host = str(env.get("MQTT_BROKER_HOST", "") or "localhost").strip()
    if not host or any(c.isspace() for c in host) or "/" in host:
        raise MqttConfigError("MQTT_BROKER_HOST must be a host name or IP address (no spaces, no scheme such as mqtt://).")

    use_tls = _flag(env, "MQTT_TLS", False)
    port = _int(env, "MQTT_BROKER_PORT", 8883 if use_tls else 1883, 1, 65535)
    username = str(env.get("MQTT_USERNAME", "") or "").strip()
    password = str(env.get("MQTT_PASSWORD", "") or "")
    ca_certs = str(env.get("MQTT_CA_CERTS", "") or "").strip()
    base_topic = validate_base_topic(str(env.get("MQTT_BASE_TOPIC", "") or "trustguard/sensors"))
    client_id = str(env.get("MQTT_CLIENT_ID", "") or "trustguard-backend").strip()
    if not client_id:
        raise MqttConfigError("MQTT_CLIENT_ID must not be empty.")
    keepalive = _int(env, "MQTT_KEEPALIVE_SECONDS", 30, 5, 600)
    max_rate = _int(env, "MQTT_MAX_MESSAGES_PER_SECOND", 100, 0, 100000)

    if password and not username:
        raise MqttConfigError("MQTT_PASSWORD is set but MQTT_USERNAME is empty. Set both or neither.")
    if username and not password:
        warnings.append("MQTT_USERNAME is set but MQTT_PASSWORD is empty.")
    if use_tls and ca_certs and not os.path.isfile(ca_certs):
        raise MqttConfigError(f"MQTT_CA_CERTS points to a file that does not exist: {ca_certs}")
    if ca_certs and not use_tls:
        warnings.append("MQTT_CA_CERTS is set but MQTT_TLS=false, so TLS is NOT enabled and the certificate is ignored.")
    if use_tls and port == 1883:
        warnings.append("MQTT_TLS=true with port 1883: 1883 is normally the plain-text port (TLS is usually 8883).")
    if not use_tls and port == 8883:
        warnings.append("Port 8883 is normally the TLS port but MQTT_TLS=false; the connection will probably fail.")

    if str(env.get("APP_ENV", "development")).strip().lower() == "production" and not _flag(env, "ALLOW_INSECURE_MQTT", False):
        problems = []
        if not use_tls:
            problems.append("MQTT_TLS must be true")
        if not username:
            problems.append("MQTT_USERNAME/MQTT_PASSWORD must be set")
        if problems:
            raise MqttConfigError("refusing to start MQTT in production: " + "; ".join(problems)
                                  + " (or set ALLOW_INSECURE_MQTT=true for an isolated lab network)")

    return MqttConfig(host=host, port=port, username=username, password=password, use_tls=use_tls, ca_certs=ca_certs,
                      base_topic=base_topic, client_id=client_id, keepalive=keepalive,
                      max_messages_per_second=max_rate, warnings=tuple(warnings))


class RateLimiter:
    """Token bucket: allows `rate` messages per second with a burst of `rate`. rate <= 0 means unlimited."""

    def __init__(self, rate: float, clock=time.monotonic):
        self.rate = float(rate)
        self._clock = clock
        self._tokens = self.rate
        self._last = clock()

    def allow(self) -> bool:
        if self.rate <= 0:
            return True
        now = self._clock()
        self._tokens = min(self.rate, self._tokens + (now - self._last) * self.rate)
        self._last = now
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False
