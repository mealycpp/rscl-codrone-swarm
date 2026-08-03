from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from math import sqrt
from typing import Any, Sequence


def _enum_text(value: Any) -> str:
    if value is None:
        return "UNKNOWN"
    name = getattr(value, "name", None)
    if name:
        return str(name)
    text = str(value)
    return text.split(".")[-1] if "." in text else text


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class TelemetrySnapshot:
    drone_id: str
    port: str
    role: str = "AGENT"
    accent: str = "#00E5FF"
    connected: bool = False
    airborne: bool = False
    last_command: str = "IDLE"
    command_state: str = "READY"
    updated_iso: str = ""
    telemetry_age_ms: int = 0

    altitude_timestamp: float = 0.0
    temperature_c: float = 0.0
    pressure_pa: float = 0.0
    elevation_m: float = 0.0
    height_cm: float = 0.0

    motion_timestamp: float = 0.0
    accel_x: float = 0.0
    accel_y: float = 0.0
    accel_z: float = 0.0
    accel_magnitude: float = 0.0
    gyro_roll: float = 0.0
    gyro_pitch: float = 0.0
    gyro_yaw: float = 0.0
    angular_magnitude: float = 0.0
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0

    position_timestamp: float = 0.0
    pos_x_m: float = 0.0
    pos_y_m: float = 0.0
    pos_z_m: float = 0.0

    range_timestamp: float = 0.0
    front_range_cm: float = 0.0
    bottom_range_cm: float = 0.0
    front_range_valid: bool = False
    bottom_range_valid: bool = False

    state_timestamp: float = 0.0
    system_mode: str = "UNKNOWN"
    flight_mode: str = "UNKNOWN"
    control_mode: str = "UNKNOWN"
    movement_state: str = "UNKNOWN"
    headless_state: str = "UNKNOWN"
    sensor_orientation: str = "UNKNOWN"
    battery: int = 0
    speed_setting: int = 0

    error_state: str = "NONE"
    front_color: str = "UNKNOWN"
    back_color: str = "UNKNOWN"
    sensor_status: str = "WAITING"
    raw: list[Any] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def empty_snapshot(drone_id: str, port: str, role: str, accent: str) -> TelemetrySnapshot:
    return TelemetrySnapshot(
        drone_id=drone_id,
        port=port,
        role=role,
        accent=accent,
        updated_iso=datetime.now(timezone.utc).isoformat(),
    )


def parse_sensor_bundle(
    drone_id: str,
    port: str,
    role: str,
    accent: str,
    data: Sequence[Any],
    *,
    connected: bool,
    airborne: bool,
    last_command: str,
    command_state: str,
    error_state: str = "NONE",
    colors: Sequence[Any] | None = None,
) -> TelemetrySnapshot:
    if len(data) < 31:
        raise ValueError(f"Expected 31 sensor fields, received {len(data)}")

    # Robolink documents acceleration as an Int16 scaled by 10.
    ax = _number(data[6]) / 10.0
    ay = _number(data[7]) / 10.0
    az = _number(data[8]) / 10.0
    gr = _number(data[9])
    gp = _number(data[10])
    gy = _number(data[11])

    front_mm = _number(data[20])
    bottom_mm = _number(data[21])
    front_cm = front_mm / 10.0
    bottom_cm = bottom_mm / 10.0

    # 0 and negative values are invalid. Values at/above 1500 mm are out of
    # the documented ToF sensing envelope and should not be treated as walls.
    front_valid = 0.0 < front_mm < 1500.0
    bottom_valid = 0.0 < bottom_mm < 1500.0

    front_color = "UNKNOWN"
    back_color = "UNKNOWN"
    if colors:
        if len(colors) > 0:
            front_color = _enum_text(colors[0]).upper()
        if len(colors) > 1:
            back_color = _enum_text(colors[1]).upper()

    return TelemetrySnapshot(
        drone_id=drone_id,
        port=port,
        role=role,
        accent=accent,
        connected=connected,
        airborne=airborne,
        last_command=last_command,
        command_state=command_state,
        updated_iso=datetime.now(timezone.utc).isoformat(),
        altitude_timestamp=_number(data[0]),
        temperature_c=_number(data[1]),
        pressure_pa=_number(data[2]),
        elevation_m=_number(data[3]),
        height_cm=_number(data[4]) * 100.0,
        motion_timestamp=_number(data[5]),
        accel_x=ax,
        accel_y=ay,
        accel_z=az,
        accel_magnitude=sqrt(ax * ax + ay * ay + az * az),
        gyro_roll=gr,
        gyro_pitch=gp,
        gyro_yaw=gy,
        angular_magnitude=sqrt(gr * gr + gp * gp + gy * gy),
        roll=_number(data[12]),
        pitch=_number(data[13]),
        yaw=_number(data[14]),
        position_timestamp=_number(data[15]),
        pos_x_m=_number(data[16]),
        pos_y_m=_number(data[17]),
        pos_z_m=_number(data[18]),
        range_timestamp=_number(data[19]),
        front_range_cm=front_cm,
        bottom_range_cm=bottom_cm,
        front_range_valid=front_valid,
        bottom_range_valid=bottom_valid,
        state_timestamp=_number(data[22]),
        system_mode=_enum_text(data[23]).upper(),
        flight_mode=_enum_text(data[24]).upper(),
        control_mode=_enum_text(data[25]).upper(),
        movement_state=_enum_text(data[26]).upper(),
        headless_state=_enum_text(data[27]).upper(),
        sensor_orientation=_enum_text(data[28]).upper(),
        battery=int(_number(data[29])),
        speed_setting=int(_number(data[30])),
        error_state=(error_state or "NONE").strip() or "NONE",
        front_color=front_color,
        back_color=back_color,
        sensor_status="LIVE",
        raw=list(data),
    )
