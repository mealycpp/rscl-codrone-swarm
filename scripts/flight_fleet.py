#!/usr/bin/env python3

from __future__ import annotations

import glob
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from codrone_edu.drone import Drone


@dataclass
class Agent:
    drone_id: str
    port: str
    drone: Drone
    battery: int = 0
    airborne: bool = False


def discover_ports() -> list[str]:
    return sorted(glob.glob("/dev/ttyACM*"))


def run_parallel(
    agents: list[Agent],
    command: str,
    *args: object,
) -> None:
    print(f"\nSWARM COMMAND: {command.upper()}", flush=True)

    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=len(agents)) as executor:
        futures = {
            executor.submit(getattr(agent.drone, command), *args): agent
            for agent in agents
        }

        for future in as_completed(futures):
            agent = futures[future]

            try:
                future.result()

                if command == "takeoff":
                    agent.airborne = True
                elif command == "land":
                    agent.airborne = False

                print(
                    f"[{agent.drone_id}] {command.upper()} COMPLETE",
                    flush=True,
                )

            except Exception as exc:
                errors.append(f"{agent.drone_id}: {exc}")

    if errors:
        raise RuntimeError(
            f"{command} failed — " + "; ".join(errors)
        )


def land_airborne_agents(agents: list[Agent]) -> None:
    airborne = [agent for agent in agents if agent.airborne]

    if not airborne:
        return

    print("\nSAFETY LANDING ACTIVE DRONES", flush=True)

    try:
        run_parallel(airborne, "land")
    except Exception as exc:
        print(f"Safety landing warning: {exc}", file=sys.stderr)


def close_agents(agents: list[Agent]) -> None:
    for agent in agents:
        try:
            agent.drone.close()
        except Exception:
            pass


def main() -> int:
    ports = discover_ports()

    if len(ports) < 2:
        print(
            f"Expected at least two controllers; found {ports}",
            file=sys.stderr,
        )
        return 1

    # Use every detected controller, so this scales beyond two later.
    agents = [
        Agent(
            drone_id=f"D{index}",
            port=port,
            drone=Drone(),
        )
        for index, port in enumerate(ports)
    ]

    try:
        for agent in agents:
            print(
                f"[{agent.drone_id}] Connecting through {agent.port}...",
                flush=True,
            )

            agent.drone.pair(agent.port)
            agent.battery = agent.drone.get_battery()

            if agent.battery < 40:
                raise RuntimeError(
                    f"{agent.drone_id} battery invalid or too low: "
                    f"{agent.battery}%"
                )

            print(
                f"[{agent.drone_id}] READY — "
                f"BATTERY {agent.battery}%",
                flush=True,
            )

        print(
            "\nPlace drones at least 1 meter apart, "
            "facing the same direction.",
            flush=True,
        )

        confirmation = input(
            "Type TAKEOFF to begin the synchronized test: "
        ).strip()

        if confirmation != "TAKEOFF":
            print("Flight cancelled.")
            return 0

        run_parallel(agents, "takeoff")
        run_parallel(agents, "hover", 3)
        run_parallel(agents, "land")

        time.sleep(2)

        print("\nTWO-DRONE SYNCHRONIZED FLIGHT: PASS", flush=True)
        return 0

    except KeyboardInterrupt:
        print("\nOperator interruption received.", file=sys.stderr)
        return 130

    except Exception as exc:
        print(f"\nFLIGHT TEST FAILED: {exc}", file=sys.stderr)
        return 1

    finally:
        land_airborne_agents(agents)
        close_agents(agents)


if __name__ == "__main__":
    raise SystemExit(main())
