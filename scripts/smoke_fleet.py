#!/usr/bin/env python3

from __future__ import annotations

import glob
import os
import sys
from dataclasses import dataclass

from codrone_edu.drone import Drone


@dataclass
class Agent:
    drone_id: str
    port: str
    drone: Drone
    battery: int
    front_range: float
    height: float


def discover_ports() -> list[str]:
    return sorted(glob.glob("/dev/ttyACM*"))


def close_connected(agents: list[Agent]) -> None:
    for agent in reversed(agents):
        try:
            agent.drone.close()
        except Exception as exc:
            print(
                f"Warning closing {agent.drone_id}: {exc}",
                file=sys.stderr,
                flush=True,
            )


def fail(message: str, connected: list[Agent]) -> None:
    print(f"\nFLEET TEST: FAIL — {message}", flush=True)
    close_connected(connected)

    # Robolink 2.8 may leave a receiver thread active after failed pairing.
    os._exit(1)


def main() -> int:
    expected_size = int(os.environ.get("FLEET_SIZE", "2"))
    ports = discover_ports()

    print(f"Detected Linux controller ports: {ports}", flush=True)

    if len(ports) != expected_size:
        print(
            f"Expected {expected_size} controllers, found {len(ports)}.",
            flush=True,
        )
        return 1

    connected: list[Agent] = []

    for index, port in enumerate(ports):
        drone_id = f"D{index}"
        drone = Drone()

        print(f"\n[{drone_id}] Connecting through {port}...", flush=True)

        try:
            drone.pair(port)
            battery = drone.get_battery()

            if battery <= 0:
                fail(
                    f"{drone_id} controller opened, but its drone did not respond.",
                    connected,
                )

            agent = Agent(
                drone_id=drone_id,
                port=port,
                drone=drone,
                battery=battery,
                front_range=drone.get_front_range(),
                height=drone.get_height(),
            )

            connected.append(agent)
            print(f"[{drone_id}] Connected — battery {battery}%", flush=True)

        except Exception as exc:
            fail(f"{drone_id} raised: {exc}", connected)

    print("\nTWO-DRONE FLEET SUMMARY")
    print("-" * 67)
    print(
        f"{'ID':<5} {'PORT':<15} {'BATTERY':<10} "
        f"{'FRONT RANGE':<15} {'HEIGHT':<10}"
    )
    print("-" * 67)

    for agent in connected:
        print(
            f"{agent.drone_id:<5} "
            f"{agent.port:<15} "
            f"{str(agent.battery) + '%':<10} "
            f"{str(agent.front_range) + ' cm':<15} "
            f"{str(agent.height) + ' cm':<10}"
        )

    print("-" * 67)
    print("TWO-DRONE WSL FLEET TEST: PASS", flush=True)

    close_connected(connected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
