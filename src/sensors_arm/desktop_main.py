"""Desktop-style entry (same spirit as sensors-dcs.desktop_main)."""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser

import uvicorn

from sensors_arm.config import load_config
from sensors_arm.paths import capture_launch_cwd, resolve_config_path
from sensors_arm.runtime import Orchestrator
from sensors_arm.viz import create_app


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sensors-arm-desktop")
    p.add_argument("-c", "--config", default=os.environ.get("SENSORS_ARM_CONFIG", "configs/default.yaml"))
    p.add_argument("--ui", action="store_true", help="Open system browser")
    p.add_argument("--no-dry-run", action="store_true")
    p.add_argument("--port", type=int, default=None)
    args = p.parse_args(argv)

    capture_launch_cwd()
    cfg = load_config(resolve_config_path(args.config))
    if args.no_dry_run:
        cfg = cfg.model_copy(update={"dry_run": False})
    if args.port is not None:
        cfg = cfg.model_copy(update={"runtime": cfg.runtime.model_copy(update={"viz_port": args.port})})

    orch = Orchestrator(cfg)
    app = create_app(orch)
    host = cfg.runtime.viz_host
    port = int(cfg.runtime.viz_port)
    url = f"http://127.0.0.1:{port}/"
    print(f"[sensors-arm] headless backend at {url}", flush=True)
    orch.start()
    if args.ui or os.environ.get("SENSORS_ARM_UI") == "1" or os.environ.get("SENSORS_ARM_BROWSER") == "1":
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    finally:
        orch.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
