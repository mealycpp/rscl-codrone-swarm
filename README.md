# RSCL CoDrone Swarm Command Nexus

A scalable, two-drone-first CoDrone EDU swarm platform for the Reconfigurable
Space Computing Lab at CPP. The application combines live WSL hardware control,
full 31-field telemetry, event logging, role-aware group commands, and a sci-fi
Qt Quick/QML dashboard.

## Current proven hardware baseline

- Two CoDrone EDU controllers attached to WSL through `usbipd-win`
- `/dev/ttyACM0` and `/dev/ttyACM1`
- Independent telemetry from both drones
- Synchronized takeoff, hover, and landing

## Install in the existing repository

Extract this bundle over `~/rscl-codrone-swarm`, then run:

```bash
cd ~/rscl-codrone-swarm
source .venv/bin/activate
./scripts/setup_gui.sh
```

The setup script also copies the real RSCL logo from:

```text
/mnt/c/Users/elhad/Downloads/RSCL_emblem_outer_background_transparent.png
```

when that file is present.

## Launch safely in simulation

```bash
python main.py --simulate
```

## Launch with the two physical drones

Attach both controllers from Administrator PowerShell, confirm both devices are
`Attached`, then in Ubuntu:

```bash
ls -l /dev/ttyACM*
sudo chmod a+rw /dev/ttyACM0 /dev/ttyACM1
python main.py --live
```

## Safety

Use `LAND ALL` as the normal emergency action. `MOTOR STOP` immediately cuts
motors and can drop airborne drones; it requires a press-and-hold confirmation.
Keep drones separated and use small movement increments.
