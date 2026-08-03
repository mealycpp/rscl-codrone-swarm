from __future__ import annotations

import argparse
import asyncio
import csv
import glob
import itertools
import json
import math
import queue
import random
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = PROJECT_ROOT / "web"
ASSETS_ROOT = PROJECT_ROOT / "assets"
LOG_ROOT = PROJECT_ROOT / "logs"

ROLE_NAMES = ["LEADER", "FOLLOWER", "SUPPORT", "RESERVE"]
ACCENTS = ["#ff2aa1", "#28d7ff", "#69ff9a", "#ffbd3f", "#b785ff", "#ff6f61", "#7efff5", "#f8ef42"]
PALETTE = [
    (255, 42, 161),
    (40, 215, 255),
    (105, 255, 154),
    (255, 189, 63),
    (183, 133, 255),
    (255, 80, 80),
    (126, 255, 245),
    (248, 239, 66),
]

_STANDARD_ASYNCIO_SLEEP = asyncio.sleep
_CODRONE_IMPORT_LOCK = threading.Lock()
_CODRONE_CLASS: Any | None = None


def get_codrone_class() -> Any:
    """Import CoDrone safely without allowing its asyncio monkey patch to break Uvicorn."""
    global _CODRONE_CLASS
    with _CODRONE_IMPORT_LOCK:
        try:
            import codrone_edu.drone as codrone_module

            if not hasattr(codrone_module, "checkInterrupt"):
                codrone_module.checkInterrupt = lambda: None
            _CODRONE_CLASS = codrone_module.Drone
            return _CODRONE_CLASS
        except ImportError as exc:
            raise RuntimeError("codrone-edu is not installed in this virtual environment") from exc
        finally:
            asyncio.sleep = _STANDARD_ASYNCIO_SLEEP


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def hex_color(red: int, green: int, blue: int) -> str:
    return f"#{red:02x}{green:02x}{blue:02x}"


def finite_float(value: Any, default: float | None = None) -> float | None:
    """Convert genuine numeric telemetry without coercing protocol enums."""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        candidate = float(value)
    elif isinstance(value, str):
        try:
            candidate = float(value.strip())
        except (TypeError, ValueError):
            return default
    else:
        return default
    return candidate if math.isfinite(candidate) else default


def telemetry_text(value: Any, default: str = "UNKNOWN") -> str:
    if value is None:
        return default
    name = getattr(value, "name", None)
    if name:
        return str(name)
    text = str(value)
    return text if text else default


def parse_hex_rgb(value: Any, default: tuple[int, int, int] = (40, 215, 255)) -> tuple[int, int, int]:
    """Parse #RGB/#RRGGBB theme colors without accepting malformed input."""
    if not isinstance(value, str):
        return default
    clean = value.strip().lstrip("#")
    if len(clean) == 3:
        clean = "".join(character * 2 for character in clean)
    if len(clean) != 6:
        return default
    try:
        return tuple(int(clean[index:index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return default


def normalize_palette(value: Any) -> list[tuple[int, int, int]]:
    colors: list[tuple[int, int, int]] = []
    if isinstance(value, list):
        for item in value[:16]:
            colors.append(parse_hex_rgb(item, PALETTE[len(colors) % len(PALETTE)]))
    return colors or list(PALETTE)


@dataclass(frozen=True)
class DeviceInfo:
    key: str
    port: str
    label: str
    vid: int | None = None
    pid: int | None = None
    serial_number: str | None = None
    location: str | None = None


def discover_devices() -> list[DeviceInfo]:
    """Discover every attached controller without collapsing identical USB metadata."""
    found: list[DeviceInfo] = []
    try:
        from serial.tools import list_ports

        candidates = list(list_ports.comports())
        codrone_candidates = [p for p in candidates if p.vid == 0x0483 and p.pid == 0x5740]
        selected = codrone_candidates or [
            p for p in candidates if p.device.startswith("/dev/ttyACM") or p.device.startswith("/dev/ttyUSB")
        ]

        serial_counts: dict[str, int] = {}
        for port in selected:
            if port.serial_number:
                serial_counts[str(port.serial_number)] = serial_counts.get(str(port.serial_number), 0) + 1

        used_keys: set[str] = set()
        for port in selected:
            serial = str(port.serial_number or "")
            if port.location:
                identity = f"location:{port.location}"
            elif serial and serial_counts.get(serial, 0) == 1:
                identity = f"serial:{serial}"
            else:
                identity = f"path:{port.device}"

            base_key = f"{port.vid or 0:04x}:{port.pid or 0:04x}:{identity}"
            key = base_key if base_key not in used_keys else f"{base_key}:{port.device}"
            used_keys.add(key)
            found.append(
                DeviceInfo(
                    key=key,
                    port=port.device,
                    label=port.description or "Serial controller",
                    vid=port.vid,
                    pid=port.pid,
                    serial_number=port.serial_number,
                    location=port.location,
                )
            )
    except Exception:
        found = []

    if not found:
        for port in sorted(set(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))):
            found.append(DeviceInfo(key=f"path:{port}", port=port, label="Serial controller"))

    return sorted(found, key=lambda device: device.port)


@dataclass
class DroneState:
    drone_id: str
    port: str
    device_key: str
    device_label: str
    role: str
    accent: str
    present: bool = True
    connected: bool = False
    flight_state: str = "STANDBY"
    movement_state: str = "IDLE"
    last_command: str = "NONE"
    battery: float = 0.0
    temperature_c: float = 0.0
    pressure_pa: float = 0.0
    elevation_m: float = 0.0
    bottom_height_m: float = 0.0
    acceleration_x: float = 0.0
    acceleration_y: float = 0.0
    acceleration_z: float = 0.0
    gyro_roll: float = 0.0
    gyro_pitch: float = 0.0
    gyro_yaw: float = 0.0
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    x_m: float = 0.0
    y_m: float = 0.0
    z_m: float = 0.0
    position_valid: bool = False
    position_frame: str = "LOCAL-OPTICAL-FLOW"
    position_quality: str = "UNKNOWN"
    speed_source: str = "UNKNOWN"
    front_range_mm: float = 0.0
    bottom_range_mm: float = 0.0
    system_mode: str = "UNKNOWN"
    flight_mode: str = "UNKNOWN"
    control_flight_mode: str = "UNKNOWN"
    headless: str = "UNKNOWN"
    sensor_orientation: str = "UNKNOWN"
    speed: float = 0.0
    front_color: str = "UNKNOWN"
    back_color: str = "UNKNOWN"
    led_color: str = "#28d7ff"
    led_mode: str = "SOLID"
    error_state: str = "NONE"
    last_update: str = field(default_factory=utc_now)


class DroneWorker(threading.Thread):
    def __init__(
        self,
        index: int,
        device: DeviceInfo,
        simulate: bool,
        publish: Callable[[str, dict[str, Any]], None],
    ):
        super().__init__(name=f"drone-worker-{index}", daemon=True)
        self.index = index
        self.simulate = simulate
        self.publish = publish
        self.commands: queue.PriorityQueue[tuple[int, int, str, dict[str, Any], threading.Event]] = queue.PriorityQueue()
        self._sequence = itertools.count()
        self.stop_event = threading.Event()
        self.drone: Any = None
        self.state_lock = threading.RLock()
        self.state = DroneState(
            drone_id=f"D{index}",
            port=device.port,
            device_key=device.key,
            device_label=device.label,
            role=ROLE_NAMES[index] if index < len(ROLE_NAMES) else f"MEMBER-{index}",
            accent=ACCENTS[index % len(ACCENTS)],
            battery=94.0 - index * 2 if simulate else 0.0,
            led_color=ACCENTS[index % len(ACCENTS)],
        )
        self._log_file: Any = None
        self._csv_writer: csv.DictWriter | None = None
        self._last_colors = 0.0
        self._last_position_sample: tuple[float, float, float, float] | None = None

    @property
    def drone_id(self) -> str:
        return self.state.drone_id

    @property
    def device_key(self) -> str:
        return self.state.device_key

    @property
    def port(self) -> str:
        return self.state.port

    def enqueue(self, command: str, priority: int = 10, **kwargs: Any) -> threading.Event:
        done = threading.Event()
        self.commands.put((priority, next(self._sequence), command, kwargs, done))
        return done

    def attach(self, device: DeviceInfo) -> None:
        with self.state_lock:
            old_port = self.state.port
            self.state.port = device.port
            self.state.device_key = device.key
            self.state.device_label = device.label
            self.state.present = True
            if not self.state.connected:
                self.state.flight_state = "STANDBY"
        if old_port != device.port:
            self.publish(
                "event",
                {"level": "HOTPLUG", "message": f"{self.drone_id} rebound {old_port} -> {device.port}"},
            )
        self._publish_state()

    def detach(self) -> None:
        with self.state_lock:
            if not self.state.present:
                return
            self.state.present = False
            self.state.connected = False
            self.state.flight_state = "DETACHED"
            self.state.error_state = "CONTROLLER DETACHED"
        self.enqueue("disconnect", priority=-1)
        self._publish_state()

    def run(self) -> None:
        self._open_log()
        self.publish("event", {"level": "STATE", "message": f"{self.drone_id} worker ready on {self.port}"})
        next_telemetry = time.monotonic()
        try:
            while not self.stop_event.is_set():
                try:
                    _, _, command, kwargs, done = self.commands.get(timeout=0.03)
                    try:
                        self._execute(command, kwargs)
                    finally:
                        done.set()
                except queue.Empty:
                    pass
                except Exception as exc:
                    with self.state_lock:
                        self.state.error_state = f"COMMAND: {exc}"
                    self.publish("event", {"level": "ERROR", "message": f"{self.drone_id}: {exc}"})

                now = time.monotonic()
                if now >= next_telemetry:
                    self._poll()
                    next_telemetry = now + 0.18
        finally:
            self._disconnect()
            if self._log_file:
                self._log_file.close()

    def stop(self) -> None:
        self.stop_event.set()

    def snapshot(self) -> dict[str, Any]:
        with self.state_lock:
            return asdict(self.state)

    def _publish_state(self) -> None:
        self.publish("telemetry", self.snapshot())

    def _open_log(self) -> None:
        LOG_ROOT.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = LOG_ROOT / f"telemetry-{self.drone_id}-{stamp}.csv"
        self._log_file = path.open("w", newline="", encoding="utf-8")
        fields = list(asdict(self.state).keys())
        self._csv_writer = csv.DictWriter(self._log_file, fieldnames=fields)
        self._csv_writer.writeheader()

    def _execute(self, command: str, kwargs: dict[str, Any]) -> None:
        with self.state_lock:
            self.state.last_command = command.upper()
        self.publish("event", {"level": "COMMAND", "message": f"{self.drone_id} <- {command.upper()}"})

        if command == "connect":
            self._connect()
            return
        if command == "disconnect":
            self._disconnect()
            return
        if command == "wait":
            time.sleep(clamp(float(kwargs.get("duration", 0.5)), 0.0, 10.0))
            return
        if not self.state.present:
            raise RuntimeError("controller is detached")
        if not self.state.connected:
            raise RuntimeError("not connected")

        if self.simulate:
            self._execute_simulated(command, kwargs)
            return

        d = self.drone
        if command == "takeoff":
            self.state.flight_state = "TAKING OFF"
            d.takeoff()
            self.state.flight_state = "AIRBORNE"
        elif command == "hover":
            duration = clamp(float(kwargs.get("duration", 2.0)), 0.2, 10.0)
            self.state.flight_state = "HOVER"
            d.hover(duration)
            self.state.flight_state = "AIRBORNE"
        elif command == "land":
            self.state.flight_state = "LANDING"
            d.land()
            self.state.flight_state = "LANDED"
        elif command == "emergency_stop":
            d.emergency_stop()
            self.state.flight_state = "MOTORS STOPPED"
        elif command in {"forward", "backward", "left", "right"}:
            distance = clamp(float(kwargs.get("distance_cm", 30)), 5.0, 200.0)
            speed_percent = clamp(float(kwargs.get("speed", 40)), 10.0, 100.0)
            speed_mps = clamp(speed_percent / 50.0, 0.2, 2.0)
            fn = {
                "forward": d.move_forward,
                "backward": d.move_backward,
                "left": d.move_left,
                "right": d.move_right,
            }[command]
            self.state.movement_state = command.upper()
            fn(distance, "cm", speed_mps)
            self.state.movement_state = "IDLE"
        elif command in {"turn_left", "turn_right"}:
            degrees = int(clamp(float(kwargs.get("degrees", 45)), 1, 360))
            fn = d.turn_left if command == "turn_left" else d.turn_right
            self.state.movement_state = command.upper()
            fn(degrees)
            self.state.movement_state = "IDLE"
        elif command == "set_led":
            red = int(clamp(float(kwargs.get("red", 40)), 0, 255))
            green = int(clamp(float(kwargs.get("green", 215)), 0, 255))
            blue = int(clamp(float(kwargs.get("blue", 255)), 0, 255))
            brightness = int(clamp(float(kwargs.get("brightness", 100)), 0, 100))
            d.set_drone_LED(red, green, blue, brightness)
            self.state.led_color = hex_color(red, green, blue)
            self.state.led_mode = "SOLID"
        elif command == "set_led_mode":
            red = int(clamp(float(kwargs.get("red", 255)), 0, 255))
            green = int(clamp(float(kwargs.get("green", 255)), 0, 255))
            blue = int(clamp(float(kwargs.get("blue", 255)), 0, 255))
            mode = str(kwargs.get("mode", "rainbow"))
            mode_speed = int(clamp(float(kwargs.get("mode_speed", 6)), 1, 10))
            d.set_drone_LED_mode(red, green, blue, mode, mode_speed)
            self.state.led_color = hex_color(red, green, blue)
            self.state.led_mode = mode.upper()
        elif command == "led_off":
            d.drone_LED_off()
            self.state.led_color = "#000000"
            self.state.led_mode = "OFF"
        else:
            raise RuntimeError(f"unsupported command: {command}")

    def _connect(self) -> None:
        if self.state.connected:
            return
        if not self.state.present:
            raise RuntimeError("controller is detached")
        if self.simulate:
            time.sleep(0.15)
            self.state.connected = True
            self.state.flight_state = "READY"
            self.state.error_state = "NONE"
            self.publish("event", {"level": "PASS", "message": f"{self.drone_id} simulation link established"})
            return

        Drone = get_codrone_class()
        drone = Drone()
        asyncio.sleep = _STANDARD_ASYNCIO_SLEEP
        drone.pair(self.port)
        battery = float(drone.get_battery())
        if battery <= 0:
            try:
                drone.close()
            except Exception:
                pass
            raise RuntimeError(f"pairing failed on {self.port}")
        self.drone = drone
        self.state.connected = True
        self.state.battery = battery
        self.state.flight_state = "READY"
        self.state.error_state = "NONE"
        self.publish("event", {"level": "PASS", "message": f"{self.drone_id} paired on {self.port} at {battery:.0f}%"})

    def _disconnect(self) -> None:
        if self.drone is not None:
            try:
                self.drone.close()
            except Exception:
                pass
        self.drone = None
        with self.state_lock:
            self.state.connected = False
            self.state.flight_state = "STANDBY" if self.state.present else "DETACHED"

    def _execute_simulated(self, command: str, kwargs: dict[str, Any]) -> None:
        if command == "takeoff":
            self.state.flight_state = "AIRBORNE"
            self.state.bottom_height_m = 0.75
            self.state.z_m = 0.75
        elif command == "hover":
            self.state.flight_state = "HOVER"
            time.sleep(min(float(kwargs.get("duration", 2.0)), 0.35))
            self.state.flight_state = "AIRBORNE"
        elif command == "land":
            self.state.flight_state = "LANDED"
            self.state.bottom_height_m = 0.0
            self.state.z_m = 0.0
        elif command == "emergency_stop":
            self.state.flight_state = "MOTORS STOPPED"
            self.state.bottom_height_m = 0.0
            self.state.z_m = 0.0
        elif command == "forward":
            self.state.x_m += float(kwargs.get("distance_cm", 30)) / 100.0
        elif command == "backward":
            self.state.x_m -= float(kwargs.get("distance_cm", 30)) / 100.0
        elif command == "left":
            self.state.y_m += float(kwargs.get("distance_cm", 30)) / 100.0
        elif command == "right":
            self.state.y_m -= float(kwargs.get("distance_cm", 30)) / 100.0
        elif command == "turn_left":
            self.state.yaw = (self.state.yaw - float(kwargs.get("degrees", 45))) % 360
        elif command == "turn_right":
            self.state.yaw = (self.state.yaw + float(kwargs.get("degrees", 45))) % 360
        elif command == "set_led":
            red = int(kwargs.get("red", 40))
            green = int(kwargs.get("green", 215))
            blue = int(kwargs.get("blue", 255))
            self.state.led_color = hex_color(red, green, blue)
            self.state.led_mode = "SOLID"
        elif command == "set_led_mode":
            self.state.led_mode = str(kwargs.get("mode", "rainbow")).upper()
            self.state.led_color = hex_color(
                int(kwargs.get("red", 255)), int(kwargs.get("green", 255)), int(kwargs.get("blue", 255))
            )
        elif command == "led_off":
            self.state.led_color = "#000000"
            self.state.led_mode = "OFF"
        else:
            raise RuntimeError(f"unsupported command: {command}")

    def _poll(self) -> None:
        if self.simulate:
            self._poll_simulated()
        elif self.state.connected and self.drone is not None:
            self._poll_live()
        self.state.last_update = utc_now()
        row = self.snapshot()
        if self._csv_writer:
            self._csv_writer.writerow(row)
            self._log_file.flush()
        self.publish("telemetry", row)

    def _poll_simulated(self) -> None:
        t = time.monotonic() + self.index
        self.state.temperature_c = 24.5 + math.sin(t / 5) * 0.6
        self.state.pressure_pa = 101325 + math.sin(t / 3) * 30
        self.state.roll = math.sin(t * 1.4) * 2.5
        self.state.pitch = math.cos(t * 1.1) * 2.2
        self.state.gyro_roll = math.sin(t * 2.0) * 4
        self.state.gyro_pitch = math.cos(t * 1.7) * 4
        self.state.gyro_yaw = math.sin(t) * 3
        self.state.acceleration_x = math.sin(t * 1.3) * 0.05
        self.state.acceleration_y = math.cos(t * 1.2) * 0.05
        self.state.acceleration_z = 1.0 + math.sin(t * 2.1) * 0.02
        self.state.front_range_mm = 720 + math.sin(t / 2) * 90
        self.state.bottom_range_mm = max(0, self.state.bottom_height_m * 1000)
        self.state.system_mode = "SIMULATION"
        self.state.flight_mode = self.state.flight_state
        self.state.control_flight_mode = "POSITION"
        self.state.headless = "OFF"
        self.state.sensor_orientation = "NORMAL"
        self.state.speed = abs(math.sin(t)) * 0.2
        self.state.position_valid = True
        self.state.position_frame = "SIMULATED-LOCAL-XY"
        self.state.position_quality = "SIMULATED"
        self.state.speed_source = "SIMULATED"
        self.state.battery = max(0, self.state.battery - 0.002)
        self.state.front_color = "CYAN"
        self.state.back_color = "MAGENTA"
        self.state.error_state = "NONE"

    def _poll_live(self) -> None:
        try:
            values = self.drone.get_sensor_data(0.03)
            if values and len(values) >= 31:
                def update_numeric(attribute: str, index: int, scale: float = 1.0) -> float | None:
                    current = float(getattr(self.state, attribute))
                    parsed = finite_float(values[index], None)
                    if parsed is None:
                        return None
                    parsed *= scale
                    setattr(self.state, attribute, parsed)
                    return parsed

                update_numeric("temperature_c", 1)
                update_numeric("pressure_pa", 2)
                update_numeric("elevation_m", 3)
                update_numeric("bottom_height_m", 4)
                update_numeric("acceleration_x", 6, 0.1)
                update_numeric("acceleration_y", 7, 0.1)
                update_numeric("acceleration_z", 8, 0.1)
                update_numeric("gyro_roll", 9)
                update_numeric("gyro_pitch", 10)
                update_numeric("gyro_yaw", 11)
                update_numeric("roll", 12)
                update_numeric("pitch", 13)
                update_numeric("yaw", 14)

                x = update_numeric("x_m", 16)
                y = update_numeric("y_m", 17)
                z = update_numeric("z_m", 18)
                position_ok = x is not None and y is not None and z is not None
                self.state.position_valid = position_ok
                self.state.position_frame = "LOCAL-OPTICAL-FLOW"
                self.state.position_quality = "MEASURED" if position_ok else "UNAVAILABLE"

                update_numeric("front_range_mm", 20)
                update_numeric("bottom_range_mm", 21)
                self.state.system_mode = telemetry_text(values[23])
                self.state.flight_mode = telemetry_text(values[24])
                self.state.control_flight_mode = telemetry_text(values[25])
                self.state.movement_state = telemetry_text(values[26])
                self.state.headless = telemetry_text(values[27])
                self.state.sensor_orientation = telemetry_text(values[28])
                update_numeric("battery", 29)

                # Library 2.8 can return a protocol enum at index 30. Use it only
                # when it is genuinely numeric; otherwise derive ground speed
                # from consecutive local-position samples.
                reported_speed = finite_float(values[30], None)
                now_sample = time.monotonic()
                derived_speed: float | None = None
                if position_ok:
                    if self._last_position_sample is not None:
                        previous_time, previous_x, previous_y, previous_z = self._last_position_sample
                        dt = now_sample - previous_time
                        if 0.04 <= dt <= 2.0:
                            displacement = math.sqrt(
                                (x - previous_x) ** 2
                                + (y - previous_y) ** 2
                                + (z - previous_z) ** 2
                            )
                            if displacement <= 3.0:
                                derived_speed = displacement / dt
                    self._last_position_sample = (now_sample, x, y, z)

                if reported_speed is not None:
                    self.state.speed = reported_speed
                    self.state.speed_source = "REPORTED"
                elif derived_speed is not None:
                    # Gentle smoothing prevents optical-flow jitter from dominating.
                    self.state.speed = 0.65 * self.state.speed + 0.35 * derived_speed
                    self.state.speed_source = "DERIVED-XYZ"
                else:
                    self.state.speed_source = "UNAVAILABLE"

                # A successful frame clears stale parser failures. Hardware error
                # data is collected independently below.
                if self.state.error_state.startswith("TELEMETRY:"):
                    self.state.error_state = "NONE"

            try:
                hardware_error = telemetry_text(self.drone.get_error_data(0.02), "NONE")
                if hardware_error not in {"", "None", "NONE", "ErrorNone", "0"}:
                    self.state.error_state = hardware_error
                elif not self.state.error_state.startswith("COMMAND:"):
                    self.state.error_state = "NONE"
            except Exception:
                pass

            now = time.monotonic()
            if now - self._last_colors > 2.5:
                try:
                    colors = self.drone.get_colors()
                    if isinstance(colors, (tuple, list)) and len(colors) >= 2:
                        self.state.front_color = telemetry_text(colors[0])
                        self.state.back_color = telemetry_text(colors[1])
                except Exception:
                    pass
                self._last_colors = now
        except Exception as exc:
            self.state.position_quality = "STALE"
            self.state.error_state = f"TELEMETRY: {exc}"


class FleetController:
    def __init__(self, simulate: bool, loop: asyncio.AbstractEventLoop):
        self.simulate = simulate
        self.loop = loop
        self.workers: dict[str, DroneWorker] = {}
        self.device_to_id: dict[str, str] = {}
        self.states: dict[str, dict[str, Any]] = {}
        self.websockets: set[WebSocket] = set()
        self.events: list[dict[str, Any]] = []
        self.lock = threading.RLock()
        self.next_index = 0
        self.stop_event = threading.Event()
        self.monitor_thread: threading.Thread | None = None
        self.mission_thread: threading.Thread | None = None
        self.mission_abort_event = threading.Event()
        self.mission = {
            "active": False,
            "name": "IDLE",
            "target": "ALL",
            "step_index": 0,
            "total_steps": 0,
            "status": "READY",
            "started_at": None,
        }
        self.scan(announce=True)
        if not self.simulate:
            self.monitor_thread = threading.Thread(target=self._auto_detect_loop, name="controller-hotplug-monitor", daemon=True)
            self.monitor_thread.start()

    def _simulation_devices(self) -> list[DeviceInfo]:
        return [
            DeviceInfo(key=f"sim:D{index}", port=f"SIM-D{index}", label="Simulated CoDrone")
            for index in range(3)
        ]

    def scan(self, announce: bool = False) -> list[str]:
        devices = self._simulation_devices() if self.simulate else discover_devices()
        seen_keys = {device.key for device in devices}
        added: list[str] = []
        restored: list[str] = []
        removed: list[str] = []

        with self.lock:
            for device in devices:
                existing_id = self.device_to_id.get(device.key)
                if existing_id is not None:
                    worker = self.workers[existing_id]
                    was_present = worker.state.present
                    worker.attach(device)
                    if not was_present:
                        restored.append(existing_id)
                    continue

                index = self.next_index
                self.next_index += 1
                worker = DroneWorker(index, device, self.simulate, self.publish_from_thread)
                self.workers[worker.drone_id] = worker
                self.device_to_id[device.key] = worker.drone_id
                self.states[worker.drone_id] = worker.snapshot()
                worker.start()
                added.append(worker.drone_id)

            for device_key, drone_id in list(self.device_to_id.items()):
                if device_key in seen_keys:
                    continue
                worker = self.workers.get(drone_id)
                if worker and worker.state.present:
                    worker.detach()
                    removed.append(drone_id)

        if announce or added or restored or removed:
            ports = [d.port for d in devices]
            self.publish_from_thread(
                "event",
                {
                    "level": "SCAN" if announce else "HOTPLUG",
                    "message": (
                        f"Controllers now {len(ports)}: {', '.join(ports) if ports else 'none'}"
                        + (f" | added {', '.join(added)}" if added else "")
                        + (f" | restored {', '.join(restored)}" if restored else "")
                        + (f" | detached {', '.join(removed)}" if removed else "")
                    ),
                },
            )
        return [d.port for d in devices]

    def _auto_detect_loop(self) -> None:
        while not self.stop_event.wait(1.0):
            try:
                self.scan(announce=False)
            except Exception as exc:
                self.publish_from_thread("event", {"level": "ERROR", "message": f"Auto-detect: {exc}"})

    def publish_from_thread(self, kind: str, payload: dict[str, Any]) -> None:
        if kind == "telemetry":
            with self.lock:
                self.states[payload["drone_id"]] = payload
        elif kind == "event":
            payload = {**payload, "timestamp": utc_now()}
            with self.lock:
                self.events.append(payload)
                self.events = self.events[-300:]
        elif kind == "mission":
            with self.lock:
                self.mission = {**self.mission, **payload}
        try:
            asyncio.run_coroutine_threadsafe(self.broadcast(kind, payload), self.loop)
        except RuntimeError:
            pass

    async def broadcast(self, kind: str, payload: dict[str, Any]) -> None:
        message = json.dumps({"type": kind, "payload": payload})
        dead: list[WebSocket] = []
        for ws in tuple(self.websockets):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.websockets.discard(ws)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            drones = [self.states[k] for k in sorted(self.states, key=lambda x: int(x[1:]))]
            events = list(self.events[-100:])
            mission = dict(self.mission)
        return {
            "simulate": self.simulate,
            "auto_detect": not self.simulate,
            "drones": drones,
            "events": events,
            "mission": mission,
            "ports": [w.port for w in self.workers.values() if w.state.present],
        }

    def targets(self, target: str, require_present: bool = True) -> list[DroneWorker]:
        if target == "ALL":
            workers = list(self.workers.values())
        else:
            worker = self.workers.get(target)
            if not worker:
                raise KeyError(target)
            workers = [worker]
        if require_present:
            workers = [worker for worker in workers if worker.state.present]
        return workers

    def command(self, target: str, command: str, params: dict[str, Any]) -> None:
        priority = 0 if command == "emergency_stop" else (1 if command in {"land", "hover"} else 10)
        workers = self.targets(target)
        if not workers:
            raise RuntimeError("no present controllers match the target")
        for worker in workers:
            worker.enqueue(command, priority=priority, **params)

    def apply_led_map(self, mapping: dict[str, Any], brightness: int = 100) -> None:
        brightness = int(clamp(float(brightness), 0, 100))
        if not mapping:
            raise RuntimeError("the LED map is empty")
        applied = 0
        for drone_id, color in mapping.items():
            worker = self.workers.get(str(drone_id).upper())
            if worker is None or not worker.state.present or not worker.state.connected:
                continue
            red, green, blue = parse_hex_rgb(color)
            worker.enqueue(
                "set_led",
                priority=5,
                red=red,
                green=green,
                blue=blue,
                brightness=brightness,
            )
            applied += 1
        if not applied:
            raise RuntimeError("no present drones matched the LED map")
        self.publish_from_thread(
            "event",
            {"level": "LIGHT", "message": f"Applied independent LED colors to {applied} drone(s)"},
        )

    def _preset_steps(self, preset: str, params: dict[str, Any], count: int) -> list[dict[str, Any]]:
        distance = int(clamp(float(params.get("distance_cm", 30)), 10, 80))
        speed = int(clamp(float(params.get("speed", 35)), 10, 70))
        degrees = int(clamp(float(params.get("degrees", 45)), 15, 120))
        repetitions = int(clamp(float(params.get("repetitions", 2)), 1, 6))
        phase_ms = int(clamp(float(params.get("phase_ms", 220)), 0, 1200))
        led_brightness = int(clamp(float(params.get("led_brightness", 100)), 0, 100))
        auto_takeoff = bool(params.get("auto_takeoff", False))
        auto_land = bool(params.get("auto_land", False))
        palette = normalize_palette(params.get("palette"))
        steps: list[dict[str, Any]] = []

        if auto_takeoff:
            steps.extend([
                {"action": "takeoff", "params": {}, "label": "Synchronized takeoff"},
                {"action": "hover", "params": {"duration": 1.5}, "label": "Flight stabilization"},
            ])

        def color_step(rgb: tuple[int, int, int], label: str) -> dict[str, Any]:
            return {
                "action": "set_led",
                "params": {"red": rgb[0], "green": rgb[1], "blue": rgb[2], "brightness": led_brightness},
                "label": label,
            }

        def led_map(offset: int, label: str, stagger_ms: int = 0) -> dict[str, Any]:
            return {
                "action": "fleet_led_map",
                "params": {
                    "colors": [hex_color(*palette[(offset + member) % len(palette)]) for member in range(count)],
                    "stagger_ms": stagger_ms,
                    "brightness": led_brightness,
                },
                "label": label,
            }

        def indexed_motion(
            motions: list[dict[str, Any]],
            label: str,
            stagger_ms: int = 0,
            reverse_order: bool = False,
        ) -> dict[str, Any]:
            return {
                "action": "indexed_motion",
                "params": {
                    "motions": motions,
                    "stagger_ms": stagger_ms,
                    "reverse_order": reverse_order,
                },
                "label": label,
            }

        def lateral_split(outward: bool) -> list[dict[str, Any]]:
            center = (count - 1) / 2.0
            motions: list[dict[str, Any]] = []
            for member in range(count):
                offset = member - center
                if abs(offset) < 0.25:
                    motions.append({"action": "hover", "params": {"duration": 0.45}})
                    continue
                direction = "right" if offset > 0 else "left"
                if not outward:
                    direction = "left" if direction == "right" else "right"
                member_distance = int(clamp(distance * max(1.0, abs(offset)), 10, 90))
                motions.append({
                    "action": direction,
                    "params": {"distance_cm": member_distance, "speed": speed},
                })
            return motions

        if preset == "zigzag":
            for iteration in range(repetitions):
                steps.extend([
                    color_step(palette[(2 * iteration) % len(palette)], f"Zig color {iteration + 1}A"),
                    {"action": "forward", "params": {"distance_cm": distance, "speed": speed}, "label": "Advance"},
                    {"action": "left", "params": {"distance_cm": distance, "speed": speed}, "label": "Zig left"},
                    color_step(palette[(2 * iteration + 1) % len(palette)], f"Zig color {iteration + 1}B"),
                    {"action": "forward", "params": {"distance_cm": distance, "speed": speed}, "label": "Advance"},
                    {"action": "right", "params": {"distance_cm": distance, "speed": speed}, "label": "Zag right"},
                ])
        elif preset == "spiral":
            for iteration in range(repetitions * 2):
                segment = int(clamp(distance + iteration * 6, 10, 90))
                steps.extend([
                    led_map(iteration, f"Spiral chroma phase {iteration + 1}"),
                    {"action": "forward", "params": {"distance_cm": segment, "speed": speed}, "label": f"Spiral leg {iteration + 1}"},
                    {"action": "turn_right", "params": {"degrees": degrees}, "label": f"Spiral turn {iteration + 1}"},
                ])
        elif preset == "neon_weave":
            for iteration in range(repetitions):
                steps.extend([
                    led_map(iteration * 2, "Weave chroma A"),
                    {"action": "left", "params": {"distance_cm": distance, "speed": speed}, "label": "Weave left"},
                    {"action": "forward", "params": {"distance_cm": distance, "speed": speed}, "label": "Weave advance"},
                    led_map(iteration * 2 + 1, "Weave chroma B"),
                    {"action": "right", "params": {"distance_cm": min(90, distance * 2), "speed": speed}, "label": "Weave cross"},
                    {"action": "forward", "params": {"distance_cm": distance, "speed": speed}, "label": "Weave advance"},
                    {"action": "left", "params": {"distance_cm": distance, "speed": speed}, "label": "Weave recenter"},
                ])
        elif preset == "color_wave":
            for iteration in range(repetitions * 2):
                steps.extend([
                    {
                        "action": "color_wave",
                        "params": {
                            "palette": [hex_color(*color) for color in palette],
                            "palette_offset": iteration,
                            "stagger_ms": phase_ms,
                            "brightness": led_brightness,
                        },
                        "label": f"Fleet color wave {iteration + 1}",
                    },
                    {"action": "wait", "params": {"duration": 0.35}, "label": "Wave hold"},
                ])
        elif preset == "box":
            for side in range(4 * repetitions):
                steps.extend([
                    led_map(side, f"Corner palette {side + 1}"),
                    {"action": "forward", "params": {"distance_cm": distance, "speed": speed}, "label": f"Box side {side + 1}"},
                    {"action": "turn_right", "params": {"degrees": 90}, "label": f"Box corner {side + 1}"},
                ])
        elif preset == "split_merge":
            for iteration in range(repetitions):
                steps.extend([
                    led_map(iteration, f"Split palette {iteration + 1}"),
                    indexed_motion(lateral_split(True), "Role-indexed lateral split"),
                    {"action": "forward", "params": {"distance_cm": distance, "speed": speed}, "label": "Parallel advance"},
                    led_map(iteration + 1, "Merge color inversion", phase_ms),
                    indexed_motion(lateral_split(False), "Role-indexed merge"),
                    {"action": "hover", "params": {"duration": 0.8}, "label": "Merge stabilization"},
                ])
        elif preset == "wavefront":
            forward_motions = [
                {"action": "forward", "params": {"distance_cm": distance, "speed": speed}}
                for _ in range(count)
            ]
            backward_motions = [
                {"action": "backward", "params": {"distance_cm": distance, "speed": speed}}
                for _ in range(count)
            ]
            for iteration in range(repetitions):
                steps.extend([
                    led_map(iteration, "Wavefront illumination", phase_ms),
                    indexed_motion(forward_motions, "Forward phase propagation", phase_ms),
                    {"action": "hover", "params": {"duration": 0.6}, "label": "Wavefront crest"},
                    indexed_motion(backward_motions, "Reverse phase propagation", phase_ms, True),
                ])
        elif preset == "pinwheel":
            for iteration in range(repetitions):
                turns_out = [
                    {"action": "turn_left" if member % 2 == 0 else "turn_right", "params": {"degrees": degrees}}
                    for member in range(count)
                ]
                turns_home = [
                    {"action": "turn_right" if member % 2 == 0 else "turn_left", "params": {"degrees": degrees}}
                    for member in range(count)
                ]
                steps.extend([
                    led_map(iteration, "Pinwheel phase colors"),
                    indexed_motion(turns_out, "Counter-rotating yaw phase"),
                    {"action": "forward", "params": {"distance_cm": distance, "speed": speed}, "label": "Radial translation"},
                    indexed_motion(turns_home, "Heading restoration"),
                    {"action": "backward", "params": {"distance_cm": distance, "speed": speed}, "label": "Radial return"},
                ])
        elif preset == "helix":
            for iteration in range(repetitions * 2):
                turns = [
                    {"action": "turn_left" if member % 2 == 0 else "turn_right", "params": {"degrees": degrees}}
                    for member in range(count)
                ]
                segment = int(clamp(distance + 4 * iteration, 10, 80))
                steps.extend([
                    led_map(iteration, f"Helix phase {iteration + 1}", phase_ms // 2),
                    indexed_motion(turns, f"Alternating helix yaw {iteration + 1}"),
                    {"action": "forward", "params": {"distance_cm": segment, "speed": speed}, "label": f"Helix translation {iteration + 1}"},
                ])
        elif preset == "braid":
            for iteration in range(repetitions):
                first = [
                    {"action": "left" if member % 2 == 0 else "right", "params": {"distance_cm": distance, "speed": speed}}
                    for member in range(count)
                ]
                cross = [
                    {"action": "right" if member % 2 == 0 else "left", "params": {"distance_cm": min(90, distance * 2), "speed": speed}}
                    for member in range(count)
                ]
                restore = [
                    {"action": "left" if member % 2 == 0 else "right", "params": {"distance_cm": distance, "speed": speed}}
                    for member in range(count)
                ]
                steps.extend([
                    led_map(iteration, "Braid channel colors"),
                    indexed_motion(first, "Braid divergence"),
                    {"action": "forward", "params": {"distance_cm": distance, "speed": speed}, "label": "Braid phase advance A"},
                    indexed_motion(cross, "Braid crossover"),
                    {"action": "forward", "params": {"distance_cm": distance, "speed": speed}, "label": "Braid phase advance B"},
                    indexed_motion(restore, "Braid lane restoration"),
                ])
        elif preset == "starburst":
            center = (count - 1) / 2.0
            for iteration in range(repetitions):
                turn_out: list[dict[str, Any]] = []
                turn_home: list[dict[str, Any]] = []
                for member in range(count):
                    offset = member - center
                    member_degrees = int(clamp(abs(offset) * degrees, 15, 120))
                    if abs(offset) < 0.25:
                        turn_out.append({"action": "hover", "params": {"duration": 0.35}})
                        turn_home.append({"action": "hover", "params": {"duration": 0.35}})
                    elif offset < 0:
                        turn_out.append({"action": "turn_left", "params": {"degrees": member_degrees}})
                        turn_home.append({"action": "turn_right", "params": {"degrees": member_degrees}})
                    else:
                        turn_out.append({"action": "turn_right", "params": {"degrees": member_degrees}})
                        turn_home.append({"action": "turn_left", "params": {"degrees": member_degrees}})
                steps.extend([
                    led_map(iteration, f"Starburst role colors {iteration + 1}"),
                    indexed_motion(turn_out, "Role-indexed angular divergence"),
                    {"action": "forward", "params": {"distance_cm": distance, "speed": speed}, "label": "Radial excursion"},
                    {"action": "hover", "params": {"duration": 0.6}, "label": "Starburst hold"},
                    {"action": "backward", "params": {"distance_cm": distance, "speed": speed}, "label": "Radial return"},
                    indexed_motion(turn_home, "Heading restoration"),
                ])
        elif preset == "relay":
            forward_motions = [
                {"action": "forward", "params": {"distance_cm": distance, "speed": speed}}
                for _ in range(count)
            ]
            backward_motions = [
                {"action": "backward", "params": {"distance_cm": distance, "speed": speed}}
                for _ in range(count)
            ]
            for iteration in range(repetitions):
                steps.extend([
                    led_map(iteration, "Relay color baton", phase_ms),
                    indexed_motion(forward_motions, "Leader-to-follower forward relay", phase_ms),
                    {"action": "hover", "params": {"duration": 0.5}, "label": "Relay endpoint hold"},
                    led_map(iteration + 1, "Reverse relay colors", phase_ms),
                    indexed_motion(backward_motions, "Follower-to-leader return relay", phase_ms, True),
                ])
        elif preset == "accordion":
            for iteration in range(repetitions):
                steps.extend([
                    led_map(iteration, "Accordion expansion colors"),
                    indexed_motion(lateral_split(True), "Fleet expansion"),
                    {"action": "forward", "params": {"distance_cm": distance, "speed": speed}, "label": "Expanded translation"},
                    led_map(iteration + 1, "Accordion compression colors"),
                    indexed_motion(lateral_split(False), "Fleet compression"),
                    {"action": "backward", "params": {"distance_cm": distance, "speed": speed}, "label": "Compressed return"},
                    {"action": "hover", "params": {"duration": 0.7}, "label": "Accordion stabilization"},
                ])
        elif preset == "figure_eight":
            half_turn = int(clamp(degrees, 30, 90))
            for iteration in range(repetitions):
                steps.extend([
                    led_map(iteration * 2, "Figure-eight lobe A colors"),
                    {"action": "turn_left", "params": {"degrees": half_turn}, "label": "Lobe A entry"},
                    {"action": "forward", "params": {"distance_cm": distance, "speed": speed}, "label": "Lobe A translation"},
                    {"action": "turn_right", "params": {"degrees": min(120, half_turn * 2)}, "label": "Central crossover"},
                    {"action": "forward", "params": {"distance_cm": distance, "speed": speed}, "label": "Lobe B translation"},
                    led_map(iteration * 2 + 1, "Figure-eight lobe B colors"),
                    {"action": "turn_left", "params": {"degrees": half_turn}, "label": "Heading recovery"},
                    {"action": "backward", "params": {"distance_cm": distance, "speed": speed}, "label": "Figure-eight return"},
                ])
        else:
            raise ValueError(f"unknown preset: {preset}")

        steps.append({"action": "hover", "params": {"duration": 1.0}, "label": "Final stabilization"})
        if auto_land:
            steps.append({"action": "land", "params": {}, "label": "Controlled landing"})
        return steps

    def preview_mission(self, preset: str, params: dict[str, Any], count: int) -> dict[str, Any]:
        steps = self._preset_steps(preset, params, max(1, count))
        estimate = sum(self._step_timeout(step["action"], dict(step.get("params") or {}), max(1, count)) for step in steps)
        return {
            "preset": preset,
            "classification": "OPEN-LOOP ROLE-PHASED CHOREOGRAPHY",
            "members": max(1, count),
            "step_count": len(steps),
            "estimated_seconds": round(estimate, 1),
            "steps": [step.get("label", step["action"].upper()) for step in steps],
            "warning": "Reported local positions are not a shared global frame; maintain physical separation.",
        }

    def start_mission(
        self,
        target: str,
        name: str,
        params: dict[str, Any],
        custom_steps: list[dict[str, Any]] | None = None,
    ) -> None:
        with self.lock:
            if self.mission.get("active"):
                raise RuntimeError("a mission is already active")

        workers = self.targets(target)
        if not workers:
            raise RuntimeError("no present controllers match the target")
        disconnected = [worker.drone_id for worker in workers if not worker.state.connected]
        if disconnected:
            raise RuntimeError(f"connect these drones before running a mission: {', '.join(disconnected)}")

        minimum_battery = float(clamp(float(params.get("min_battery", 25)), 10, 80))
        low_battery = [
            f"{worker.drone_id}={worker.state.battery:.0f}%"
            for worker in workers
            if worker.state.battery > 0 and worker.state.battery < minimum_battery
        ]
        if low_battery:
            raise RuntimeError(
                f"mission blocked below {minimum_battery:.0f}% battery: {', '.join(low_battery)}"
            )

        if custom_steps is not None:
            if not 1 <= len(custom_steps) <= 60:
                raise RuntimeError("custom mission must contain 1 to 60 steps")
            steps = [self._validate_custom_step(step) for step in custom_steps]
            mission_name = name or "CUSTOM"
        else:
            steps = self._preset_steps(name, params, len(workers))
            mission_name = name.upper()

        contains_motion = any(
            step["action"] in {
                "forward", "backward", "left", "right", "turn_left", "turn_right", "indexed_motion"
            }
            for step in steps
        )
        auto_takeoff = bool(params.get("auto_takeoff", False))
        sequence_contains_takeoff = any(step["action"] == "takeoff" for step in steps)
        if contains_motion and not (auto_takeoff or sequence_contains_takeoff):
            grounded = [
                worker.drone_id for worker in workers
                if worker.state.flight_state not in {"AIRBORNE", "HOVER"}
            ]
            if grounded:
                raise RuntimeError(
                    "take off first or enable AUTO TAKEOFF for: " + ", ".join(grounded)
                )

        self.mission_abort_event.clear()
        mission_state = {
            "active": True,
            "name": mission_name,
            "target": target,
            "step_index": 0,
            "total_steps": len(steps),
            "status": "ARMED",
            "classification": "OPEN-LOOP ROLE-PHASED CHOREOGRAPHY",
            "started_at": utc_now(),
        }
        self.publish_from_thread("mission", mission_state)
        self.publish_from_thread(
            "event", {"level": "MISSION", "message": f"{mission_name} armed for {target} with {len(steps)} steps"}
        )
        self.mission_thread = threading.Thread(
            target=self._mission_loop,
            args=(mission_name, workers, steps),
            name=f"mission-{mission_name.lower()}",
            daemon=True,
        )
        self.mission_thread.start()

    def _validate_custom_step(self, step: dict[str, Any]) -> dict[str, Any]:
        action = str(step.get("action", "")).lower()
        allowed = {
            "takeoff", "hover", "land", "forward", "backward", "left", "right",
            "turn_left", "turn_right", "set_led", "set_led_mode", "led_off",
            "wait", "color_wave", "fleet_led_map", "indexed_motion",
        }
        if action not in allowed:
            raise RuntimeError(f"unsupported custom mission action: {action}")
        params = dict(step.get("params") or {})
        return {"action": action, "params": params, "label": str(step.get("label") or action.upper())}

    def _wait_for_tickets(
        self,
        tickets: list[threading.Event],
        timeout: float,
        label: str,
    ) -> None:
        deadline = time.monotonic() + timeout
        for ticket in tickets:
            while not ticket.wait(0.1):
                if self.mission_abort_event.is_set():
                    raise InterruptedError("mission aborted")
                if time.monotonic() > deadline:
                    raise TimeoutError(f"step timed out: {label}")

    def _mission_loop(self, name: str, workers: list[DroneWorker], steps: list[dict[str, Any]]) -> None:
        try:
            self.publish_from_thread("mission", {"status": "RUNNING"})
            for index, step in enumerate(steps, start=1):
                if self.mission_abort_event.is_set():
                    raise InterruptedError("mission aborted")
                action = step["action"]
                params = dict(step.get("params") or {})
                label = step.get("label", action.upper())
                self.publish_from_thread(
                    "mission", {"step_index": index, "total_steps": len(steps), "status": label}
                )
                self.publish_from_thread(
                    "event", {"level": "MISSION", "message": f"{name} {index}/{len(steps)}: {label}"}
                )

                tickets: list[threading.Event] = []
                if action == "color_wave":
                    palette = normalize_palette(params.get("palette"))
                    offset = int(params.get("palette_offset", 0))
                    stagger = clamp(float(params.get("stagger_ms", 150)), 0, 1200) / 1000.0
                    brightness = int(clamp(float(params.get("brightness", 100)), 0, 100))
                    for worker_index, worker in enumerate(workers):
                        red, green, blue = palette[(offset + worker_index) % len(palette)]
                        tickets.append(worker.enqueue(
                            "set_led", priority=20, red=red, green=green, blue=blue, brightness=brightness
                        ))
                        if stagger and self.mission_abort_event.wait(stagger):
                            raise InterruptedError("mission aborted")
                elif action == "fleet_led_map":
                    colors = params.get("colors") if isinstance(params.get("colors"), list) else []
                    stagger = clamp(float(params.get("stagger_ms", 0)), 0, 1200) / 1000.0
                    brightness = int(clamp(float(params.get("brightness", 100)), 0, 100))
                    for worker_index, worker in enumerate(workers):
                        color = colors[worker_index % len(colors)] if colors else hex_color(*PALETTE[worker_index % len(PALETTE)])
                        red, green, blue = parse_hex_rgb(color)
                        tickets.append(worker.enqueue(
                            "set_led", priority=20, red=red, green=green, blue=blue, brightness=brightness
                        ))
                        if stagger and self.mission_abort_event.wait(stagger):
                            raise InterruptedError("mission aborted")
                elif action == "indexed_motion":
                    motions = params.get("motions") if isinstance(params.get("motions"), list) else []
                    if not motions:
                        raise RuntimeError("indexed_motion requires a motion for each role")
                    order = list(range(len(workers)))
                    if bool(params.get("reverse_order", False)):
                        order.reverse()
                    stagger = clamp(float(params.get("stagger_ms", 0)), 0, 1200) / 1000.0
                    for worker_index in order:
                        worker = workers[worker_index]
                        motion = motions[worker_index % len(motions)]
                        motion_action = str(motion.get("action", "hover")).lower()
                        motion_params = dict(motion.get("params") or {})
                        if motion_action not in {
                            "hover", "forward", "backward", "left", "right", "turn_left", "turn_right"
                        }:
                            raise RuntimeError(f"unsupported indexed motion: {motion_action}")
                        tickets.append(worker.enqueue(motion_action, priority=20, **motion_params))
                        if stagger and self.mission_abort_event.wait(stagger):
                            raise InterruptedError("mission aborted")
                else:
                    tickets = [worker.enqueue(action, priority=20, **params) for worker in workers]

                timeout = self._step_timeout(action, params, len(workers))
                self._wait_for_tickets(tickets, timeout, label)

            self.publish_from_thread("mission", {"active": False, "status": "COMPLETE"})
            self.publish_from_thread("event", {"level": "PASS", "message": f"Mission {name} complete"})
        except InterruptedError:
            self.publish_from_thread("mission", {"active": False, "status": "ABORTED"})
            self.publish_from_thread("event", {"level": "ABORT", "message": f"Mission {name} aborted; hover requested"})
            for worker in workers:
                if worker.state.connected:
                    worker.enqueue("hover", priority=1, duration=1.0)
        except Exception as exc:
            self.publish_from_thread("mission", {"active": False, "status": f"FAILED: {exc}"})
            self.publish_from_thread("event", {"level": "ERROR", "message": f"Mission {name} failed: {exc}"})

    def _step_timeout(self, action: str, params: dict[str, Any], member_count: int = 1) -> float:
        if action in {"forward", "backward", "left", "right"}:
            distance_m = float(params.get("distance_cm", 30)) / 100.0
            speed_mps = clamp(float(params.get("speed", 35)) / 50.0, 0.2, 2.0)
            return max(5.0, distance_m / speed_mps + 5.0)
        if action == "indexed_motion":
            motions = params.get("motions") if isinstance(params.get("motions"), list) else []
            motion_times = [
                self._step_timeout(str(motion.get("action", "hover")), dict(motion.get("params") or {}), 1)
                for motion in motions
            ]
            stagger = clamp(float(params.get("stagger_ms", 0)), 0, 1200) / 1000.0
            return max(motion_times or [5.0]) + stagger * max(0, member_count - 1)
        if action in {"color_wave", "fleet_led_map"}:
            stagger = clamp(float(params.get("stagger_ms", 0)), 0, 1200) / 1000.0
            return 5.0 + stagger * max(0, member_count - 1)
        if action in {"hover", "wait"}:
            return float(params.get("duration", 2.0)) + 4.0
        return 12.0

    def abort_mission(self) -> None:
        if not self.mission.get("active"):
            self.publish_from_thread("event", {"level": "MISSION", "message": "No active mission to abort"})
            return
        self.mission_abort_event.set()

    def shutdown(self) -> None:
        self.stop_event.set()
        self.mission_abort_event.set()
        if self.monitor_thread:
            self.monitor_thread.join(timeout=1.5)
        for worker in self.workers.values():
            worker.stop()
        for worker in self.workers.values():
            worker.join(timeout=1.5)


def create_app(simulate: bool) -> FastAPI:
    app = FastAPI(title="RSCL CoDrone Swarm Command Center", version="0.5.1")
    controller_holder: dict[str, FleetController] = {}

    @app.on_event("startup")
    async def startup() -> None:
        controller_holder["controller"] = FleetController(simulate, asyncio.get_running_loop())

    @app.on_event("shutdown")
    async def shutdown() -> None:
        controller = controller_holder.get("controller")
        if controller:
            controller.shutdown()

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(WEB_ROOT / "index.html")

    @app.get("/api/status")
    async def status() -> JSONResponse:
        return JSONResponse(controller_holder["controller"].snapshot())

    @app.post("/api/scan")
    async def scan() -> JSONResponse:
        ports = controller_holder["controller"].scan(announce=True)
        return JSONResponse({"ok": True, "ports": ports})

    @app.post("/api/command")
    async def command(request: Request) -> JSONResponse:
        data = await request.json()
        target = str(data.get("target", "ALL")).upper()
        cmd = str(data.get("command", "")).lower()
        params = data.get("params") or {}
        allowed = {
            "connect",
            "disconnect",
            "takeoff",
            "hover",
            "land",
            "emergency_stop",
            "forward",
            "backward",
            "left",
            "right",
            "turn_left",
            "turn_right",
            "set_led",
            "set_led_mode",
            "led_off",
        }
        if cmd not in allowed:
            raise HTTPException(400, f"unsupported command: {cmd}")
        if cmd == "emergency_stop" and data.get("confirm") is not True:
            raise HTTPException(400, "emergency stop requires confirm=true")
        try:
            controller_holder["controller"].command(target, cmd, params)
        except KeyError:
            raise HTTPException(404, f"unknown target: {target}")
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))
        return JSONResponse({"ok": True, "target": target, "command": cmd})

    @app.post("/api/lighting/apply")
    async def apply_lighting(request: Request) -> JSONResponse:
        data = await request.json()
        mapping = data.get("mapping") or {}
        if not isinstance(mapping, dict):
            raise HTTPException(400, "mapping must be an object keyed by drone ID")
        try:
            controller_holder["controller"].apply_led_map(
                mapping, int(data.get("brightness", 100))
            )
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))
        return JSONResponse({"ok": True, "applied": len(mapping)})

    @app.post("/api/mission/preview")
    async def preview_mission(request: Request) -> JSONResponse:
        data = await request.json()
        target = str(data.get("target", "ALL")).upper()
        preset = str(data.get("preset", "")).lower()
        params = dict(data.get("params") or {})
        try:
            workers = controller_holder["controller"].targets(target)
            count = len(workers) or 1
            preview = controller_holder["controller"].preview_mission(preset, params, count)
        except KeyError:
            raise HTTPException(404, f"unknown target: {target}")
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(409, str(exc))
        return JSONResponse(preview)

    @app.post("/api/mission/run")
    async def run_mission(request: Request) -> JSONResponse:
        data = await request.json()
        target = str(data.get("target", "ALL")).upper()
        preset = str(data.get("preset", "")).lower()
        params = dict(data.get("params") or {})
        custom_steps = data.get("steps")
        name = str(data.get("name") or ("CUSTOM" if custom_steps is not None else preset))
        try:
            controller_holder["controller"].start_mission(
                target=target,
                name=name if custom_steps is not None else preset,
                params=params,
                custom_steps=custom_steps,
            )
        except KeyError:
            raise HTTPException(404, f"unknown target: {target}")
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(409, str(exc))
        return JSONResponse({"ok": True, "target": target, "mission": name})

    @app.post("/api/mission/abort")
    async def abort_mission() -> JSONResponse:
        controller_holder["controller"].abort_mission()
        return JSONResponse({"ok": True})

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        controller = controller_holder["controller"]
        controller.websockets.add(ws)
        await ws.send_json({"type": "snapshot", "payload": controller.snapshot()})
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            controller.websockets.discard(ws)
        except asyncio.CancelledError:
            controller.websockets.discard(ws)
            raise

    app.mount("/static", StaticFiles(directory=WEB_ROOT), name="static")
    app.mount("/assets", StaticFiles(directory=ASSETS_ROOT), name="assets")
    return app


def open_windows_browser(url: str) -> None:
    try:
        subprocess.run(["cmd.exe", "/C", "start", "", url], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="RSCL CoDrone swarm browser command center")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--simulate", action="store_true", help="Run without hardware")
    mode.add_argument("--live", action="store_true", help="Use attached CoDrone EDU controllers")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    simulate = not args.live
    if not simulate:
        get_codrone_class()
    asyncio.sleep = _STANDARD_ASYNCIO_SLEEP

    url = f"http://localhost:{args.port}"
    print("\nRSCL CoDrone Swarm Command Center v0.5.1")
    print(f"Mode: {'SIMULATION' if simulate else 'LIVE'}")
    print(f"Dashboard: {url}\n")
    if not args.no_browser:
        threading.Timer(1.2, open_windows_browser, args=(url,)).start()

    uvicorn.run(
        create_app(simulate),
        host=args.host,
        port=args.port,
        log_level="info",
        loop="asyncio",
    )


if __name__ == "__main__":
    main()
