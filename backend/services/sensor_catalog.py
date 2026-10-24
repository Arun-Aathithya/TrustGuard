"""The only sensor types a user can add. Everything about them lives here so API, UI and firmware agree."""

SUPPORTED_SENSORS: dict[str, dict[str, str]] = {
    "temperature": {"label": "Temperature", "hardware_model": "DS18B20", "unit": "°C"},
    # The firmware reports the RMS of the dynamic acceleration magnitude (gravity removed), in m/s^2.
    "vibration": {"label": "Vibration", "hardware_model": "MPU6050", "unit": "m/s²"},
}

NAME_MAX_LENGTH = 60


def type_value(sensor_type) -> str:
    """Enum or plain str -> plain lower-case str."""
    return str(getattr(sensor_type, "value", sensor_type) or "").lower()


def is_supported(sensor_type) -> bool:
    return type_value(sensor_type) in SUPPORTED_SENSORS


def default_label(sensor_type) -> str:
    t = type_value(sensor_type)
    return SUPPORTED_SENSORS.get(t, {}).get("label") or t.capitalize()


def supported_list() -> str:
    return ", ".join(SUPPORTED_SENSORS)
