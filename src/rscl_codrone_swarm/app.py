from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from .backend import FleetBackend


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RSCL CoDrone Swarm Command Nexus")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--simulate", action="store_true", help="Run without hardware")
    mode.add_argument("--live", action="store_true", help="Use /dev/ttyACM* hardware")
    parser.add_argument("--fullscreen", action="store_true", help="Start full screen")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    project_root = Path(__file__).resolve().parents[2]

    QCoreApplication.setOrganizationName("RSCL")
    QCoreApplication.setApplicationName("CoDrone Swarm Command Nexus")
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

    app = QGuiApplication(sys.argv[:1])
    engine = QQmlApplicationEngine()
    backend = FleetBackend(project_root=project_root, simulate=args.simulate or not args.live)
    engine.rootContext().setContextProperty("backend", backend)
    engine.rootContext().setContextProperty("projectRoot", QUrl.fromLocalFile(str(project_root) + "/"))
    engine.rootContext().setContextProperty("startFullscreen", args.fullscreen)

    qml_file = project_root / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_file)))
    if not engine.rootObjects():
        return 2
    return app.exec()
