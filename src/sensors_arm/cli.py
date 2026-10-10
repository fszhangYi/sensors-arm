from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

from sensors_arm.config import load_config
from sensors_arm.paths import capture_launch_cwd, resolve_config_path
from sensors_arm.runtime import Orchestrator
from sensors_arm.viz import create_app


def _cmd_run(args: argparse.Namespace) -> int:
    capture_launch_cwd()
    cfg_path = resolve_config_path(args.config)
    cfg = load_config(cfg_path)
    if args.dry_run is True:
        cfg = cfg.model_copy(update={"dry_run": True})
    elif args.no_dry_run:
        cfg = cfg.model_copy(update={"dry_run": False})
    if args.port is not None:
        rt = cfg.runtime.model_copy(update={"viz_port": int(args.port)})
        cfg = cfg.model_copy(update={"runtime": rt})

    orch = Orchestrator(cfg)
    app = create_app(orch)
    host = cfg.runtime.viz_host
    port = cfg.runtime.viz_port
    print(f"[sensors-arm] config={cfg_path}", flush=True)
    print(f"[sensors-arm] open http://127.0.0.1:{port}/", flush=True)
    orch.start()
    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
    finally:
        orch.stop()
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    capture_launch_cwd()
    cfg = load_config(resolve_config_path(args.config))
    import json

    from sensors_arm.config import config_summary

    print(json.dumps(config_summary(cfg), indent=2, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sensors-arm", description="Multi-arm viz & control")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Start orchestrator + viz")
    run.add_argument("-c", "--config", default="configs/default.yaml")
    run.add_argument("--dry-run", action="store_true", default=None)
    run.add_argument("--no-dry-run", action="store_true")
    run.add_argument("--port", type=int, default=None)
    run.set_defaults(func=_cmd_run)

    show = sub.add_parser("show-config", help="Print resolved config summary")
    show.add_argument("-c", "--config", default="configs/default.yaml")
    show.set_defaults(func=_cmd_show)

    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
