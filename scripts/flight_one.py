#!/usr/bin/env python3

import glob
import sys
import time

from codrone_edu.drone import Drone


def find_controller() -> str:
    ports = sorted(glob.glob("/dev/ttyACM*"))

    if len(ports) != 1:
        raise RuntimeError(
            f"Expected exactly one controller, found: {ports}"
        )

    return ports[0]


def main() -> int:
    port = find_controller()
    drone = Drone()
    airborne = False
    connected = False

    print(f"Connecting through {port}...")

    try:
        drone.pair(port)

        battery = drone.get_battery()
        if battery <= 0:
            raise RuntimeError("Drone did not respond to the controller.")

        connected = True
        print(f"CONNECTED — BATTERY {battery}%")

        if battery < 40:
            raise RuntimeError("Battery below 40%; flight rejected.")

        input(
            "Clear the flight area, place the drone flat, "
            "then press Enter to take off..."
        )

        print("TAKEOFF")
        drone.takeoff()
        airborne = True

        print("HOVER — 3 SECONDS")
        drone.hover(3)

        print("LAND")
        drone.land()
        airborne = False

        time.sleep(2)
        print("ONE-DRONE WSL FLIGHT TEST: PASS")
        return 0

    except KeyboardInterrupt:
        print("\nInterrupted by operator.")
        return 130

    except Exception as exc:
        print(f"FLIGHT TEST FAILED: {exc}", file=sys.stderr)
        return 1

    finally:
        if airborne:
            print("Attempting controlled landing...")
            try:
                drone.land()
                time.sleep(2)
            except Exception as exc:
                print(f"Landing failed: {exc}", file=sys.stderr)

        if connected:
            try:
                drone.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
