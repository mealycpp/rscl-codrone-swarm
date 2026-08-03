from __future__ import annotations

import itertools
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from codrone_edu.drone import Drone

from .telemetry import TelemetrySnapshot, empty_snapshot, parse_sensor_bundle

TelemetryCallback = Callable[[str, dict[str, Any]], None]
EventCallback = Callable[[str, str, str], None]


@dataclass(order=True)
class WorkItem:
    priority: int
    sequence: int
    name: str = field(compare=False)
    args: tuple[Any, ...] = field(compare=False, default_factory=tuple)
    done: threading.Event = field(compare=False, default_factory=threading.Event)
    error: Exception | None = field(compare=False, default=None)


class DroneAgent:
    """Own one CoDrone serial link and serialize every operation on it."""

    def __init__(
        self,
        drone_id: str,
        port: str,
        role: str,
        accent: str,
        telemetry_callback: TelemetryCallback,
        event_callback: EventCallback,
    ) -> None:
        self.drone_id = drone_id
        self.port = port
        self.role = role
        self.accent = accent
        self._telemetry_callback = telemetry_callback
        self._event_callback = event_callback

        self._queue: queue.PriorityQueue[WorkItem] = queue.PriorityQueue()
        self._sequence = itertools.count()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name=f"codrone-{drone_id}",
            daemon=True,
        )

        self._drone: Drone | None = None
        self.connected = False
        self.airborne = False
        self.last_command = "IDLE"
        self.command_state = "READY"
        self.error_state = "NONE"
        self.colors: list[Any] = ["UNKNOWN", "UNKNOWN"]
        self.snapshot: TelemetrySnapshot = empty_snapshot(drone_id, port, role, accent)
        self._next_telemetry = 0.0
        self._next_diagnostics = 0.0

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.enqueue("disconnect", priority=0)
        self._thread.join(timeout=3.0)

    def enqueue(self, name: str, *args: Any, priority: int = 10) -> WorkItem:
        item = WorkItem(priority, next(self._sequence), name, args)
        self._queue.put(item)
        return item

    def _event(self, level: str, message: str) -> None:
        self._event_callback(self.drone_id, level, message)

    def _publish(self, snapshot: TelemetrySnapshot) -> None:
        self.snapshot = snapshot
        self._telemetry_callback(self.drone_id, snapshot.to_dict())

    def _run(self) -> None:
        while not self._stop.is_set():
            now = time.monotonic()
            timeout = max(0.02, min(0.15, self._next_telemetry - now))
            try:
                item = self._queue.get(timeout=timeout)
            except queue.Empty:
                item = None

            if item is not None:
                try:
                    self._execute(item)
                except Exception as exc:  # hardware errors must not kill worker
                    item.error = exc
                    self.command_state = "ERROR"
                    self._event("ERROR", f"{item.name.upper()} failed: {exc}")
                finally:
                    item.done.set()
                    self._queue.task_done()

            now = time.monotonic()
            if self.connected and now >= self._next_telemetry and self._queue.empty():
                self._poll_telemetry()
                self._next_telemetry = now + 0.35

    def _connect(self) -> None:
        if self.connected:
            return
        self._event("INFO", f"Opening {self.port}")
        drone = Drone()
        drone.pair(self.port)
        battery = drone.get_battery()
        if battery <= 0:
            try:
                drone.close()
            except Exception:
                pass
            raise RuntimeError("controller opened, but paired drone did not respond")
        self._drone = drone
        self.connected = True
        self.command_state = "READY"
        self._next_telemetry = 0.0
        self._next_diagnostics = 0.0
        self._event("SUCCESS", f"Connected on {self.port}; battery {battery}%")
        self._set_identity_led()
        self._poll_telemetry()

    def _disconnect(self) -> None:
        if self._drone is not None:
            try:
                if self.airborne:
                    self._drone.land()
                    time.sleep(1.0)
            except Exception:
                pass
            try:
                self._drone.close()
            except Exception:
                pass
        self._drone = None
        self.connected = False
        self.airborne = False
        self.command_state = "OFFLINE"
        offline = empty_snapshot(self.drone_id, self.port, self.role, self.accent)
        offline.last_command = self.last_command
        offline.command_state = "OFFLINE"
        self._publish(offline)
        self._event("INFO", "Disconnected")

    def _set_identity_led(self) -> None:
        if self._drone is None:
            return
        rgb = {
            "#00E5FF": (0, 229, 255),
            "#FF3DF2": (255, 61, 242),
            "#69FF97": (105, 255, 151),
            "#FFB020": (255, 176, 32),
        }.get(self.accent.upper(), (0, 229, 255))
        try:
            self._drone.set_drone_LED(*rgb, 80)
        except Exception as exc:
            self._event("WARN", f"Identity LED unavailable: {exc}")

    def _execute(self, item: WorkItem) -> None:
        if item.name == "connect":
            self._connect()
            return
        if item.name == "disconnect":
            self._disconnect()
            return
        if not self.connected or self._drone is None:
            raise RuntimeError("drone is not connected")

        drone = self._drone
        self.last_command = item.name.upper()
        self.command_state = "EXECUTING"
        self._event("COMMAND", self.last_command)

        if item.name == "takeoff":
            drone.takeoff()
            self.airborne = True
        elif item.name == "hover":
            drone.hover(float(item.args[0]) if item.args else 1.0)
        elif item.name == "land":
            drone.land()
            self.airborne = False
        elif item.name == "emergency_stop":
            drone.emergency_stop()
            self.airborne = False
        elif item.name == "forward":
            drone.move_forward(float(item.args[0]), "cm", float(item.args[1]))
        elif item.name == "backward":
            drone.move_backward(float(item.args[0]), "cm", float(item.args[1]))
        elif item.name == "left":
            drone.move_left(float(item.args[0]), "cm", float(item.args[1]))
        elif item.name == "right":
            drone.move_right(float(item.args[0]), "cm", float(item.args[1]))
        elif item.name == "turn_left":
            drone.turn_left(int(item.args[0]), 3)
        elif item.name == "turn_right":
            drone.turn_right(int(item.args[0]), 3)
        elif item.name == "role_led":
            self._set_identity_led()
        elif item.name == "warning_led":
            drone.set_drone_LED(255, 176, 32, 100)
        elif item.name == "buzzer":
            drone.drone_buzzer(int(item.args[0]), int(item.args[1]))
        else:
            raise ValueError(f"Unknown command: {item.name}")

        self.command_state = "COMPLETE"
        self._event("SUCCESS", f"{self.last_command} complete")
        self._next_telemetry = 0.0

    def _poll_telemetry(self) -> None:
        if self._drone is None:
            return
        try:
            bundle = self._drone.get_sensor_data(0.03)
            now = time.monotonic()
            if now >= self._next_diagnostics:
                try:
                    self.error_state = str(self._drone.get_error_data(0.05) or "NONE")
                except Exception as exc:
                    self.error_state = f"DIAGNOSTIC_UNAVAILABLE: {exc}"
                try:
                    colors = self._drone.get_colors()
                    if colors:
                        self.colors = list(colors)
                except Exception:
                    pass
                self._next_diagnostics = now + 4.0

            snapshot = parse_sensor_bundle(
                self.drone_id,
                self.port,
                self.role,
                self.accent,
                bundle,
                connected=self.connected,
                airborne=self.airborne,
                last_command=self.last_command,
                command_state=self.command_state,
                error_state=self.error_state,
                colors=self.colors,
            )
            self._publish(snapshot)
        except Exception as exc:
            self._event("WARN", f"Telemetry poll failed: {exc}")
