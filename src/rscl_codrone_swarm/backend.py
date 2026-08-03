from __future__ import annotations

import csv
import glob
import math
import os
import random
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from .agent import DroneAgent, WorkItem
from .telemetry import empty_snapshot


class FleetBackend(QObject):
    dronesChanged = Signal()
    eventsChanged = Signal()
    systemStateChanged = Signal()
    selectedTargetChanged = Signal()
    simulationModeChanged = Signal()
    telemetryArrived = Signal(str, object)
    eventArrived = Signal(str, str, str)

    def __init__(self, project_root: Path, simulate: bool = False) -> None:
        super().__init__()
        self.project_root = project_root
        self._simulate = simulate
        self._selected_target = "ALL"
        self._system_state = "SIMULATION" if simulate else "OFFLINE"
        self._drones: list[dict[str, Any]] = []
        self._events: list[dict[str, Any]] = []
        self._agents: dict[str, DroneAgent] = {}
        self._mission_lock = threading.Lock()
        self._log_file: Path | None = None
        self._log_header_written = False

        self.telemetryArrived.connect(self._apply_telemetry)
        self.eventArrived.connect(self._append_event)

        self._clock = QTimer(self)
        self._clock.setInterval(500)
        self._clock.timeout.connect(self._refresh_ages)
        self._clock.start()

        self._sim_timer = QTimer(self)
        self._sim_timer.setInterval(250)
        self._sim_timer.timeout.connect(self._simulate_tick)

        if simulate:
            self._create_simulation()
            self._sim_timer.start()
        else:
            self.scanControllers()

    @Property("QVariantList", notify=dronesChanged)
    def drones(self) -> list[dict[str, Any]]:
        return list(self._drones)

    @Property("QVariantList", notify=eventsChanged)
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    @Property(str, notify=systemStateChanged)
    def systemState(self) -> str:
        return self._system_state

    @Property(str, notify=selectedTargetChanged)
    def selectedTarget(self) -> str:
        return self._selected_target

    @Property(bool, notify=simulationModeChanged)
    def simulationMode(self) -> bool:
        return self._simulate

    @Property(int, notify=dronesChanged)
    def connectedCount(self) -> int:
        return sum(1 for drone in self._drones if drone.get("connected"))

    @Property(int, notify=dronesChanged)
    def fleetSize(self) -> int:
        return len(self._drones)

    def _set_system_state(self, state: str) -> None:
        if state != self._system_state:
            self._system_state = state
            self.systemStateChanged.emit()

    def _roles(self, count: int) -> list[tuple[str, str]]:
        defaults = [
            ("LEADER", "#FF3DF2"),
            ("FOLLOWER", "#00E5FF"),
            ("SUPPORT", "#69FF97"),
            ("RESERVE", "#FFB020"),
        ]
        return [defaults[i] if i < len(defaults) else (f"AGENT-{i}", "#8E7CFF") for i in range(count)]

    @Slot()
    def scanControllers(self) -> None:
        if self._simulate:
            return
        ports = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
        roles = self._roles(len(ports))
        self._drones = [
            empty_snapshot(f"D{i}", port, roles[i][0], roles[i][1]).to_dict()
            for i, port in enumerate(ports)
        ]
        self.dronesChanged.emit()
        self._append_event("FLEET", "INFO", f"Discovered {len(ports)} controller port(s)")
        self._set_system_state("DISCOVERED" if ports else "NO CONTROLLERS")

    @Slot()
    def connectFleet(self) -> None:
        if self._simulate:
            self._set_system_state("READY")
            self._append_event("FLEET", "SUCCESS", "Simulation fleet connected")
            for drone in self._drones:
                drone["connected"] = True
                drone["command_state"] = "READY"
            self.dronesChanged.emit()
            return

        if not self._drones:
            self.scanControllers()
        if not self._drones:
            self._append_event("FLEET", "ERROR", "No Linux serial controllers found")
            return

        self._set_system_state("CONNECTING")
        for drone in self._drones:
            drone_id = drone["drone_id"]
            if drone_id in self._agents:
                continue
            agent = DroneAgent(
                drone_id=drone_id,
                port=drone["port"],
                role=drone["role"],
                accent=drone["accent"],
                telemetry_callback=lambda did, data: self.telemetryArrived.emit(did, data),
                event_callback=lambda did, level, msg: self.eventArrived.emit(did, level, msg),
            )
            self._agents[drone_id] = agent
            agent.start()
            agent.enqueue("connect", priority=2)
        self._append_event("FLEET", "COMMAND", "Connect fleet dispatched")

    @Slot()
    def disconnectFleet(self) -> None:
        if self._simulate:
            for drone in self._drones:
                drone["connected"] = False
                drone["airborne"] = False
                drone["command_state"] = "OFFLINE"
            self.dronesChanged.emit()
            self._set_system_state("SIMULATION")
            return
        for agent in list(self._agents.values()):
            agent.enqueue("disconnect", priority=1)
        self._agents.clear()
        self._set_system_state("OFFLINE")

    @Slot(str)
    def setSelectedTarget(self, target: str) -> None:
        target = target.upper()
        if target == "ALL" or any(d["drone_id"] == target for d in self._drones):
            self._selected_target = target
            self.selectedTargetChanged.emit()

    def _target_ids(self) -> list[str]:
        if self._selected_target == "ALL":
            return [d["drone_id"] for d in self._drones if d.get("connected")]
        return [self._selected_target]

    @Slot(str)
    def command(self, command: str) -> None:
        command = command.lower().strip()
        args: tuple[Any, ...] = ()
        priority = 10
        if command == "hover":
            args = (1.0,)
            priority = 3
        elif command == "land":
            priority = 1
        elif command == "emergency_stop":
            priority = 0
        elif command in {"forward", "backward", "left", "right"}:
            args = (20.0, 0.4)
        elif command in {"turn_left", "turn_right"}:
            args = (30,)

        targets = self._target_ids()
        if not targets:
            self._append_event("FLEET", "WARN", "No connected target selected")
            return

        if self._simulate:
            self._simulate_command(targets, command)
            return

        tickets: list[tuple[str, WorkItem]] = []
        for drone_id in targets:
            agent = self._agents.get(drone_id)
            if agent is not None:
                tickets.append((drone_id, agent.enqueue(command, *args, priority=priority)))
        self._set_system_state(command.upper())
        self._append_event("FLEET", "COMMAND", f"{command.upper()} → {', '.join(targets)}")
        threading.Thread(
            target=self._watch_command_group,
            args=(command, tickets),
            daemon=True,
        ).start()

    def _watch_command_group(self, command: str, tickets: list[tuple[str, WorkItem]]) -> None:
        errors: list[str] = []
        for drone_id, ticket in tickets:
            ticket.done.wait(timeout=12.0)
            if ticket.error:
                errors.append(f"{drone_id}: {ticket.error}")
        if errors:
            self.eventArrived.emit("FLEET", "ERROR", "; ".join(errors))
            self.eventArrived.emit("FLEET", "WARN", f"{command.upper()} incomplete")
        else:
            self.eventArrived.emit("FLEET", "SUCCESS", f"{command.upper()} completed by {len(tickets)} agent(s)")
        self.eventArrived.emit("FLEET", "STATE", "READY")

    @Slot()
    def startMirrorDemo(self) -> None:
        if not self._mission_lock.acquire(blocking=False):
            self._append_event("MISSION", "WARN", "Another mission is already active")
            return
        threading.Thread(target=self._mirror_mission, daemon=True).start()

    def _mirror_mission(self) -> None:
        try:
            self.eventArrived.emit("MISSION", "COMMAND", "Mirrored expansion initiated")
            old_target = self._selected_target
            if self._simulate:
                self._simulate_command(["D0"], "left")
                self._simulate_command(["D1"], "right")
                time.sleep(1.0)
                self._simulate_command(["D0"], "turn_left")
                self._simulate_command(["D1"], "turn_right")
            else:
                pairs = [("D0", "left"), ("D1", "right")]
                tickets = []
                for drone_id, cmd in pairs:
                    agent = self._agents.get(drone_id)
                    if agent:
                        tickets.append(agent.enqueue(cmd, 20.0, 0.4))
                for ticket in tickets:
                    ticket.done.wait(8.0)
                turns = [("D0", "turn_left"), ("D1", "turn_right")]
                tickets = []
                for drone_id, cmd in turns:
                    agent = self._agents.get(drone_id)
                    if agent:
                        tickets.append(agent.enqueue(cmd, 30))
                for ticket in tickets:
                    ticket.done.wait(8.0)
            self.eventArrived.emit("MISSION", "SUCCESS", "Mirrored expansion complete")
            self._selected_target = old_target
        finally:
            self._mission_lock.release()

    @Slot()
    def startObstacleMission(self) -> None:
        if not self._mission_lock.acquire(blocking=False):
            self._append_event("MISSION", "WARN", "Another mission is already active")
            return
        threading.Thread(target=self._obstacle_mission, daemon=True).start()

    def _obstacle_mission(self) -> None:
        try:
            self.eventArrived.emit("MISSION", "COMMAND", "Collective obstacle monitor armed on D0")
            deadline = time.monotonic() + 25.0
            confirmations = 0
            while time.monotonic() < deadline:
                snapshot = next((d for d in self._drones if d["drone_id"] == "D0"), None)
                if snapshot and snapshot.get("front_range_valid") and 10 <= snapshot.get("front_range_cm", 999) <= 65:
                    confirmations += 1
                    self.eventArrived.emit("D0", "WARN", f"Obstacle candidate {confirmations}/3")
                else:
                    confirmations = 0
                if confirmations >= 3:
                    self.eventArrived.emit("MISSION", "ALERT", "Obstacle confirmed by D0 — collective hold")
                    old = self._selected_target
                    self._selected_target = "ALL"
                    self.command("hover")
                    time.sleep(1.4)
                    self.command("backward")
                    time.sleep(2.0)
                    self._selected_target = old
                    self.eventArrived.emit("MISSION", "SUCCESS", "Collective retreat complete")
                    return
                time.sleep(0.25)
            self.eventArrived.emit("MISSION", "WARN", "Obstacle mission timed out without confirmation")
        finally:
            self._mission_lock.release()

    @Slot(str)
    def removeMember(self, drone_id: str) -> None:
        drone_id = drone_id.upper()
        old = self._selected_target
        self._selected_target = drone_id
        self.command("land")
        self._selected_target = old
        self._append_event("FLEET", "ALERT", f"Controlled member removal: {drone_id}")

    def _apply_telemetry(self, drone_id: str, data: object) -> None:
        incoming = dict(data) if isinstance(data, dict) else {}
        for index, drone in enumerate(self._drones):
            if drone.get("drone_id") == drone_id:
                self._drones[index] = incoming
                break
        else:
            self._drones.append(incoming)
        self._write_telemetry(incoming)
        self.dronesChanged.emit()
        connected = self.connectedCount
        if connected == len(self._drones) and connected > 0:
            self._set_system_state("READY")

    def _append_event(self, source: str, level: str, message: str) -> None:
        event = {
            "time": datetime.now().strftime("%H:%M:%S.%f")[:-3],
            "source": source,
            "level": level.upper(),
            "message": message,
        }
        self._events.insert(0, event)
        del self._events[60:]
        self.eventsChanged.emit()
        if level.upper() == "STATE" and message == "READY":
            self._set_system_state("READY")

    def _refresh_ages(self) -> None:
        # The Qt property notification also drives the animated status pulse.
        if self._drones:
            self.dronesChanged.emit()

    def _write_telemetry(self, snapshot: dict[str, Any]) -> None:
        if not snapshot:
            return
        logs = self.project_root / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        if self._log_file is None:
            self._log_file = logs / f"telemetry-{datetime.now():%Y%m%d-%H%M%S}.csv"
        fields = [key for key in snapshot.keys() if key != "raw"]
        write_header = not self._log_file.exists() or self._log_file.stat().st_size == 0
        with self._log_file.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            writer.writerow({key: snapshot.get(key) for key in fields})

    def _create_simulation(self) -> None:
        roles = self._roles(2)
        self._drones = []
        for i in range(2):
            item = empty_snapshot(f"D{i}", f"SIM://D{i}", roles[i][0], roles[i][1]).to_dict()
            item.update(
                connected=True,
                battery=96 - i * 3,
                temperature_c=31.2 + i,
                pressure_pa=101325.0,
                sensor_status="LIVE",
                movement_state="READY",
                flight_mode="READY",
                command_state="READY",
                front_range_valid=True,
                bottom_range_valid=True,
                front_range_cm=120.0,
                bottom_range_cm=0.0,
            )
            self._drones.append(item)
        self.dronesChanged.emit()
        self._append_event("SYSTEM", "SUCCESS", "Simulation mode initialized")

    def _simulate_tick(self) -> None:
        t = time.monotonic()
        for i, drone in enumerate(self._drones):
            airborne = bool(drone.get("airborne"))
            drone["temperature_c"] = 31.0 + i + 0.5 * math.sin(t / 5 + i)
            drone["pressure_pa"] = 101325 + 22 * math.sin(t / 8 + i)
            drone["height_cm"] = (80 + 3 * math.sin(t * 1.3 + i)) if airborne else 0.0
            drone["bottom_range_cm"] = drone["height_cm"]
            drone["roll"] = 2.5 * math.sin(t * 1.7 + i)
            drone["pitch"] = 2.0 * math.cos(t * 1.4 + i)
            drone["yaw"] = (t * 7 + i * 18) % 360
            drone["accel_x"] = 0.3 * math.sin(t + i)
            drone["accel_y"] = 0.3 * math.cos(t + i)
            drone["accel_z"] = 9.81 + 0.1 * math.sin(t * 2)
            drone["gyro_roll"] = 4 * math.sin(t + i)
            drone["gyro_pitch"] = 3 * math.cos(t + i)
            drone["gyro_yaw"] = 5 * math.sin(t / 2 + i)
            drone["pos_x_m"] = 0.08 * math.sin(t / 3 + i)
            drone["pos_y_m"] = 0.05 * math.cos(t / 3 + i)
            drone["pos_z_m"] = drone["height_cm"] / 100.0
            drone["front_range_cm"] = 42.0 if (i == 0 and int(t) % 24 in {18, 19}) else 120.0 + random.uniform(-3, 3)
            drone["front_range_valid"] = True
            drone["movement_state"] = "HOVERING" if airborne else "READY"
            drone["flight_mode"] = "FLIGHT" if airborne else "READY"
            drone["updated_iso"] = datetime.now().isoformat()
            drone["sensor_status"] = "LIVE"
        self.dronesChanged.emit()

    def _simulate_command(self, targets: list[str], command: str) -> None:
        for drone in self._drones:
            if drone["drone_id"] not in targets:
                continue
            drone["last_command"] = command.upper()
            drone["command_state"] = "COMPLETE"
            if command == "takeoff":
                drone["airborne"] = True
            elif command in {"land", "emergency_stop"}:
                drone["airborne"] = False
            elif command == "forward":
                drone["pos_x_m"] += 0.2
            elif command == "backward":
                drone["pos_x_m"] -= 0.2
            elif command == "left":
                drone["pos_y_m"] += 0.2
            elif command == "right":
                drone["pos_y_m"] -= 0.2
            elif command == "turn_left":
                drone["yaw"] += 30
            elif command == "turn_right":
                drone["yaw"] -= 30
        self._append_event("FLEET", "SUCCESS", f"SIM {command.upper()} → {', '.join(targets)}")
        self._set_system_state(command.upper())
        self.dronesChanged.emit()
