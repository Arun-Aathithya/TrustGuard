"""Pydantic schemas used by the API layer."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, computed_field

from services import device_health, sensor_catalog, units


# ---------- Machines ----------
class MachineBase(BaseModel):
    name: str
    machine_type: str = "generic"
    location: Optional[str] = None


class MachineCreate(MachineBase):
    pass


class MachineOut(MachineBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    installed_at: datetime
    created_at: datetime


# ---------- Sensors ----------
class SensorBase(BaseModel):
    sensor_type: str
    unit: str = ""
    device_id: Optional[str] = None
    mqtt_topic: Optional[str] = None


class SensorCreate(BaseModel):
    """What the website sends to add a sensor. Only the types in services/sensor_catalog.py are accepted."""
    machine_id: int
    sensor_type: str
    name: str
    device_id: Optional[str] = None  # ESP32 that will report for this sensor; can be linked later


class SensorUpdate(BaseModel):
    name: Optional[str] = None
    device_id: Optional[str] = None  # "" clears the link


class SensorOut(SensorBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    machine_id: int
    name: Optional[str] = None
    hardware_model: Optional[str] = None
    connection_status: str
    data_source: str = "simulation"
    last_data_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    registered_at: Optional[datetime] = None
    created_at: datetime

    @computed_field
    @property
    def display_name(self) -> str:
        """The user's custom name, or the type label for sensors created before names existed."""
        return self.name or sensor_catalog.default_label(self.sensor_type)

    @computed_field
    @property
    def device_status(self) -> str:
        """online | stale | offline (hardware) or simulated."""
        return device_health.compute_status(self.data_source, self.last_seen_at)

    def _units(self) -> dict:
        return units.unit_assessment(self.sensor_type, self.data_source, self.unit, self.device_id)

    @computed_field
    @property
    def unit_status(self) -> str:
        """ok | calibrated_index | unconverted (see services/units.py)."""
        return self._units()["status"]

    @computed_field
    @property
    def display_unit(self) -> str:
        return self._units()["display_unit"]

    @computed_field
    @property
    def unit_warning(self) -> Optional[str]:
        return self._units()["warning"]

    @computed_field
    @property
    def unit_note(self) -> Optional[str]:
        return self._units()["note"]

    @computed_field
    @property
    def seconds_since_seen(self) -> Optional[float]:
        return device_health.seconds_since(self.last_seen_at) if self.data_source == "hardware" else None


# ---------- Sensor Readings ----------
class SensorReadingCreate(BaseModel):
    sensor_id: int
    value: Optional[float] = None
    timestamp: Optional[datetime] = None


class SensorReadingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sensor_id: int
    value: Optional[float]
    raw_value: Optional[float]
    is_missing: bool
    is_outlier: bool
    is_delayed: bool = False
    source: str = "simulation"
    timestamp: datetime


# ---------- Sensor Trust ----------
class SensorTrustOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sensor_id: int
    machine_id: int
    trust_score: float
    consistency_score: float
    noise_score: float
    drift_score: float
    missing_score: float
    cross_agreement_score: float
    communication_score: float
    computed_at: datetime


# ---------- Predictions ----------
class PredictionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    machine_id: int
    failure_risk: float
    prediction_confidence: float
    overall_trust: float
    model_version: str
    created_at: datetime


# ---------- Alerts ----------
class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    machine_id: int
    sensor_id: Optional[int]
    alert_type: str
    severity: str
    message: str
    is_resolved: bool
    created_at: datetime
    resolved_at: Optional[datetime] = None


# ---------- Maintenance ----------
class MaintenanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    machine_id: int
    alert_id: Optional[int]
    recommendation_type: str
    description: str
    status: str
    scheduled_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime


class MaintenanceUpdate(BaseModel):
    status: str
    scheduled_at: Optional[datetime] = None


# ---------- Dashboard aggregate ----------
class SensorSnapshot(BaseModel):
    sensor: SensorOut
    latest_value: Optional[float]
    trust: Optional[SensorTrustOut]


class MachineDashboard(BaseModel):
    machine: MachineOut
    sensors: list[SensorSnapshot]
    latest_prediction: Optional[PredictionOut]
    overall_trust: float
    open_alerts: list[AlertOut]
    recommendation: Optional[str]
    cross_sensor_disagreement: bool
    cross_sensor_verdict: str = "insufficient"  # agree | machine_change | sensor_suspect | ambiguous | insufficient
    cross_sensor_detail: Optional[str] = None
    cross_sensor_moved: list[str] = []      # sensor types that moved away from normal
    cross_sensor_suspects: list[str] = []   # only those outvoted by 2+ others (never set for a two-sensor tie)
    data_source: str = "simulation"  # hardware | simulation | mixed
    explanation: Optional[dict] = None  # see recommendation/explain.py


class SimulationTick(BaseModel):
    machine_id: Optional[int] = None
    scenario: str = "normal"  # normal | noisy | drift | failure | missing | machine_fault
