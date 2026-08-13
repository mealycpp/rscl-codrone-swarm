# _hu_silence: mute codrone-edu library-internal prints (health spam)
import codrone_edu.drone as _ced_drone  # triggers the one-time version banner
# codrone-edu 2.8 monkey-patches sleep with interruptible_sleep(), which calls
# checkInterrupt() — defined only when a Drone initializes. Define it so the
# hijacked sleep is harmless in sim mode (no Drone ever created).
if not hasattr(_ced_drone, "checkInterrupt"):
    _ced_drone.checkInterrupt = lambda: None
import sys as _sys
_noop = lambda *a, **k: None
for _n, _m in list(_sys.modules.items()):
    if _n.startswith("codrone_edu"):
        try: _m.print = _noop
        except Exception: pass

from rscl_codrone_swarm.web_app import main


if __name__ == "__main__":
    main()
