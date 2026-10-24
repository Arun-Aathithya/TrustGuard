"""
ORM models covering the 7 tables from the architecture doc:
machines, sensors, sensor_readings, sensor_trust, predictions, alerts, maintenance
"""
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import relationship

from database.session import Base


def utcnow():
    return datetime.now(timezone.utc)


class MachineStatus(str, enum.Enum):
    OPERATIONAL = "operational"
    AT_RISK = "at_risk"
    DOWN = "down"


class SensorType(str, enum.Enum):
    TEMPERATURE = "temperature"
    VIBRATION = "vibration"
    PRESSURE = "pressure"
    CURRENT = "current"
    RPM = "rpm"


class ConnectionStatus(str, enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    FAULTY = "faulty"
    SIMULATED = "simulated"


class AlertType(str, enum.Enum):
    SENSOR_FAULT = "sensor_fault"
    HIGH_RISK = "high_risk"
    LOW_CONFIDENCE = "low_confidence"
    CROSS_DISAGREEMENT = "cross_disagreement"
    DEVICE_OFFLINE = "device_offline"


class AlertSeverity(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class MaintenanceStatus(str, enum.Enum):
    PENDING = "pending"
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    DISMISSED = "dismissed"


class Machine(Base):
    __tablename__ = "machines"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    machine_type = Column(String(120), nullable=False, default="generic")
    location = Column(String(120), nullable=True)
    status = Column(Enum(MachineStatus), default=MachineStatus.OPERATIONAL, nullable=False)
    installed_at = Column(DateTime, default=utcnow)
    created_at = Column(DateTime, default=utcnow)

    sensors = relationship("Sensor", back_populates="machine", cascade="all, delete-orphan")
    predictions = relationship("Prediction", back_populates="machine", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="machine", cascade="all, delete-orphan")
    maintenance_records = relationship("Maintenance", back_populates="machine", cascade="all, delete-orphan")


class Sensor(Base):
    __tablename__ = "sensors"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False)
    sensor_type = Column(Enum(SensorType), nullable=False)
    name = Column(String(80), nullable=True)  # user-chosen custom name (older sensors have none)
    hardware_model = Column(String(40), nullable=True)  # DS18B20 / MPU6050
    unit = Column(String(20), nullable=False, default="")
    device_id = Column(String(80), nullable=True)  # ESP32 / IoT hardware ID
    mqtt_topic = Column(String(160), nullable=True)
    connection_status = Column(Enum(ConnectionStatus), default=ConnectionStatus.SIMULATED)
    data_source = Column(String(20), default="simulation", nullable=False, server_default="simulation")  # simulation | hardware
    last_data_at = Column(DateTime, nullable=True)  # timestamp of the newest reading's measurement
    last_seen_at = Column(DateTime, nullable=True)  # server time the last hardware message arrived (device health)
    registered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    machine = relationship("Machine", back_populates="sensors")
    readings = relationship("SensorReading", back_populates="sensor", cascade="all, delete-orphan")
    trust_scores = relationship("SensorTrust", back_populates="sensor", cascade="all, delete-orphan")


class SensorReading(Base):
    __tablename__ = "sensor_readings"

    id = Column(Integer, primary_key=True, index=True)
    sensor_id = Column(Integer, ForeignKey("sensors.id"), nullable=False)
    value = Column(Float, nullable=True)  # null => missing reading
    raw_value = Column(Float, nullable=True)  # pre-cleaning value
    is_missing = Column(Boolean, default=False)
    is_outlier = Column(Boolean, default=False)
    is_delayed = Column(Boolean, default=False)
    source = Column(String(20), default="simulation", index=True)  # simulation | hardware
    timestamp = Column(DateTime, default=utcnow, index=True)

    sensor = relationship("Sensor", back_populates="readings")

    __table_args__ = (
        # fast "this sensor between t1 and t2" queries (history API, charts)
        Index("ix_sensor_readings_sensor_ts", "sensor_id", "timestamp"),
        # The database itself refuses a second hardware reading of the same sensor at the same measurement time, so a
        # retransmitted or replayed message (even two arriving at once) can never be stored twice.
        Index("uq_sensor_readings_hw_sensor_ts", "sensor_id", "timestamp", unique=True,
              sqlite_where=text("source = 'hardware'"), postgresql_where=text("source = 'hardware'")),
    )


class SensorTrust(Base):
    __tablename__ = "sensor_trust"

    id = Column(Integer, primary_key=True, index=True)
    sensor_id = Column(Integer, ForeignKey("sensors.id"), nullable=False)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False)
    trust_score = Column(Float, nullable=False)  # 0-100
    consistency_score = Column(Float, default=100.0)
    noise_score = Column(Float, default=100.0)
    drift_score = Column(Float, default=100.0)
    missing_score = Column(Float, default=100.0)
    cross_agreement_score = Column(Float, default=100.0)
    communication_score = Column(Float, default=100.0)
    computed_at = Column(DateTime, default=utcnow, index=True)

    sensor = relationship("Sensor", back_populates="trust_scores")


class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False)
    failure_risk = Column(Float, nullable=False)  # 0-100 (%)
    prediction_confidence = Column(Float, nullable=False)  # 0-100 (%)
    overall_trust = Column(Float, nullable=False, default=100.0)
    model_version = Column(String(40), default="rf-v3")
    inputs_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, index=True)

    machine = relationship("Machine", back_populates="predictions")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False)
    sensor_id = Column(Integer, ForeignKey("sensors.id"), nullable=True)
    alert_type = Column(Enum(AlertType), nullable=False)
    severity = Column(Enum(AlertSeverity), default=AlertSeverity.WARNING)
    message = Column(String(300), nullable=False)
    is_resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow, index=True)
    resolved_at = Column(DateTime, nullable=True)

    machine = relationship("Machine", back_populates="alerts")


class Maintenance(Base):
    __tablename__ = "maintenance"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False)
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=True)
    recommendation_type = Column(String(80), nullable=False)
    description = Column(String(400), nullable=False)
    status = Column(Enum(MaintenanceStatus), default=MaintenanceStatus.PENDING)
    scheduled_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    machine = relationship("Machine", back_populates="maintenance_records")


class IngestionEvent(Base):
    """Audit log of hardware ingestion problems and notable events (rejected, duplicate, delayed, ...)."""
    __tablename__ = "ingestion_events"

    id = Column(Integer, primary_key=True, index=True)
    sensor_id = Column(Integer, ForeignKey("sensors.id", ondelete="SET NULL"), nullable=True, index=True)
    device_id = Column(String(80), nullable=True)
    topic = Column(String(160), nullable=True)
    channel = Column(String(10), nullable=False, default="mqtt")  # mqtt | http
    event_type = Column(String(40), nullable=False, index=True)
    accepted = Column(Boolean, default=False)
    detail = Column(String(300), nullable=True)
    created_at = Column(DateTime, default=utcnow, index=True)
