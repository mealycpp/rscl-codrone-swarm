from codrone_edu.drone import Drone

PORT = "/dev/ttyS3"

drone = Drone()

try:
    print(f"Connecting through {PORT}...")
    drone.pair(PORT)

    print("CONNECTED")
    print(f"BATTERY: {drone.get_battery()} %")
    print(f"FRONT RANGE: {drone.get_front_range()} cm")
    print(f"HEIGHT: {drone.get_height()} cm")
    print("WSL TEST: PASS")

finally:
    drone.close()
    print("CLOSED CLEANLY")
