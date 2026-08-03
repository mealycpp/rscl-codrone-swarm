#!/usr/bin/env python3

import glob
import os

from codrone_edu.drone import Drone


def find_controller() -> str:
    ports = sorted(glob.glob("/dev/ttyACM*"))

    if not ports:
        raise RuntimeError("No CoDrone controller found under /dev/ttyACM*")

    return ports[0]


port = find_controller()
drone = Drone()

print(f"Connecting through {port}...", flush=True)
drone.pair(port)

battery = drone.get_battery()

if battery <= 0:
    print("FAIL: Controller opened, but drone did not respond.", flush=True)
    os._exit(1)

print("CONNECTED", flush=True)
print(f"BATTERY: {battery}%", flush=True)
print(f"FRONT RANGE: {drone.get_front_range()} cm", flush=True)
print(f"HEIGHT: {drone.get_height()} cm", flush=True)
print("ONE-DRONE WSL SMOKE TEST: PASS", flush=True)

os._exit(0)
