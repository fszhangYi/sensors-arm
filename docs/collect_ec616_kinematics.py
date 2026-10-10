#!/usr/bin/env python3
"""Collect EC616 FK/IK modeling data via the official Elite EC Python SDK.

Package
    PyPI ``elirobots`` → ``from elite import EC``
    (EC series JSON-RPC on TCP 8055; optional read-only monitor on 8056)

Default robot IP
    192.168.1.200

Safety (hard rule)
    This script **must not** command any robot motion, servo, trajectory, drag,
    IO, TCP write, or parameter write. It only:

    * connects to the SDK command port
    * **gets** identity / DH / frames / current pose
    * optionally starts the **8056 monitor** (state stream, no commands)
    * calls controller **positiveKinematic / inverseKinematic** on the
      **already held** pose (pure computation on the controller, not a move)

    Forbidden (non-exhaustive): ``movj`` / ``movl`` / ``moveByJoint``,
    ``TT_init`` / ``TT_add_joint``, ``robot_servo_on``, ``set_servo_status``,
    ``stop``, ``wait_stop``, ``switch_drag_teach``, ``cmd_set_tcp``,
    ``setUserFrame``, ``set_payload``, ``run_speed`` setter, ``setCollision*``.

Usage
    pip install elirobots
    python docs/collect_ec616_kinematics.py
    python docs/collect_ec616_kinematics.py --ip 192.168.1.200 -o /tmp/ec616_kin.json

The dump is meant to fill ``cs66_kinematics/profiles/elite_ec616.yaml`` fields
(link lengths from ``getDH``, one teach pair from the current pose, TCP from
flange vs TCP difference). Soft joint limits are **not** exposed by this SDK.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

DEFAULT_IP = "192.168.1.200"
# Official socket manual: getDH index in [0, 11] → d1 … d12.
DH_INDEX_COUNT = 12
TOOL_COUNT = 8
USER_FRAME_COUNT = 8
UNIT_DEG = 0
UNIT_RAD = 1


# ---------------------------------------------------------------------------
# Motion-related method names: refuse if someone later wires them in by mistake.
# ---------------------------------------------------------------------------
# JSON-RPC method names this script is allowed to send (gets + kinematics math).
_ALLOWED_RPC = frozenset(
    {
        "getSoftVersion",
        "getJointVersion",
        "getRobotType",
        "getRobotSubtype",
        "getSpeed",
        "getCurrentCoord",
        "getCycleMode",
        "getToolNumber",
        "getAutoRunToolNumber",
        "getUserNumber",
        "getRobotSafetyParamsEnabled",
        "getRobotSafeyPower",
        "getRobotSafetyPower",
        "getRobotSafetyMomentum",
        "getRobotSafetyToolForce",
        "getRobotSafetyElbowForce",
        "getRobotSpeedPercentage",
        "get_servo_precise_position_status",
        "getDH",
        "getTcpPos",
        "get_tool_payload",
        "getUserFrame",
        "get_joint_pos",
        "get_motor_pos",
        "get_actual_joint",
        "get_base_flange_pose",
        "get_tcp_pose",
        "get_actual_tcp",
        "positiveKinematic",
        "inverseKinematic",
        "inverseKinematicAll",
        "poseInv",
        "poseMul",
    }
)


def _rpc(ec: Any, method: str, params: dict[str, Any] | None = None) -> Any:
    if method not in _ALLOWED_RPC:
        raise RuntimeError(f"blocked RPC {method!r}: not in read-only allow-list")
    return ec.send_CMD(method, params)


def _jsonable(obj: Any) -> Any:
    if obj is None or isinstance(obj, (bool, int, float, str)):
        if isinstance(obj, float) and not math.isfinite(obj):
            return None
        return obj
    if isinstance(obj, Enum):
        return {"name": obj.name, "value": obj.value}
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(x) for x in obj]
    if hasattr(obj, "__dict__") and not callable(obj):
        try:
            return _jsonable(vars(obj))
        except Exception:
            return repr(obj)
    return repr(obj)


def _is_sdk_error(raw: Any) -> bool:
    return isinstance(raw, tuple) and len(raw) >= 2 and raw[0] is False


def _safe(label: str, fn: Callable[[], Any], errors: list[dict[str, Any]]) -> Any:
    try:
        raw = fn()
    except Exception as exc:  # noqa: BLE001
        errors.append({"label": label, "error": f"{type(exc).__name__}: {exc}"})
        return None
    if _is_sdk_error(raw):
        errors.append({"label": label, "error": _jsonable(raw)})
        return None
    return _jsonable(raw)


def _as_float_list(raw: Any, n: int | None = None) -> Optional[list[float]]:
    if not isinstance(raw, (list, tuple)):
        return None
    out: list[float] = []
    for x in raw:
        try:
            out.append(float(x))
        except (TypeError, ValueError):
            return None
    if n is not None and len(out) < n:
        return None
    return out[:n] if n is not None else out


def _pose_mm_rxyz_deg(pose: Any) -> Optional[dict[str, list[float]]]:
    v = _as_float_list(pose, 6)
    if v is None:
        return None
    return {"position_mm": v[:3], "orientation_rxyz_deg": v[3:]}


def _tcp_from_flange_and_tcp(
    flange_mm_deg: Optional[list[float]],
    tcp_mm_deg: Optional[list[float]],
) -> Optional[dict[str, Any]]:
    """Approximate flange→TCP translation (mm) assuming same orientation.

    Controller TCP is flange ⊕ tool; if R is the same, Δp = p_tcp − p_flange
    in base frame. Also report |ΔR| via Euler difference.
    """
    f = _as_float_list(flange_mm_deg, 6)
    t = _as_float_list(tcp_mm_deg, 6)
    if f is None or t is None:
        return None
    dp = [t[i] - f[i] for i in range(3)]
    dr = [t[i] - f[i] for i in range(3, 6)]
    return {
        "delta_xyz_mm_base": dp,
        "delta_rxyz_deg": dr,
        "delta_xyz_norm_mm": math.sqrt(sum(x * x for x in dp)),
        "note": (
            "delta_xyz_mm_base is TCP origin minus flange origin in the base "
            "frame (not necessarily the tool-frame [0,0,L] offset). Use "
            "controller poseMul/poseInv for a proper T_flange_tool."
        ),
    }


def collect(ec: Any, *, with_monitor: bool, monitor_wait_s: float) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    dump: dict[str, Any] = {
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "sdk": "elirobots / elite.EC",
        "robot_ip": getattr(ec, "robot_ip", None),
        "motion_commanded": False,
        "identity": {},
        "dh": {},
        "frames": {},
        "current_snapshot": {},
        "controller_fk_ik": {},
        "monitor_8056": None,
        "profile_hints": {},
        "errors": errors,
    }

    ident = dump["identity"]
    ident["soft_version"] = _safe("soft_version", lambda: ec.soft_version, errors)
    ident["robot_series"] = _safe("robot_series", lambda: ec.robot_series, errors)
    ident["robot_type"] = _safe("robot_type", lambda: ec.robot_type, errors)
    ident["servo_version"] = _safe("servo_version", lambda: ec.servo_version, errors)
    ident["run_speed_percent"] = _safe("run_speed", lambda: ec.run_speed, errors)
    ident["current_frame"] = _safe("current_frame", lambda: ec.current_frame, errors)
    ident["cycle_mode"] = _safe("cycle_mode", lambda: ec.cycle_mode, errors)
    ident["tool_num_teach"] = _safe(
        "tool_frame_num_in_teach_mode", lambda: ec.tool_frame_num_in_teach_mode, errors
    )
    ident["tool_num_run"] = _safe(
        "tool_frame_num_in_run_mode", lambda: ec.tool_frame_num_in_run_mode, errors
    )
    ident["user_frame_num"] = _safe("user_frame_num", lambda: ec.user_frame_num, errors)
    ident["safety_parameters"] = _safe(
        "get_safety_parameters", lambda: ec.get_safety_parameters(), errors
    )
    ident["encoder_precise"] = _safe(
        "get_servo_precise_position_status",
        lambda: ec.get_servo_precise_position_status(is_block=False),
        errors,
    )

    dh_named: dict[str, Any] = {}
    dh_list: list[Any] = []
    for i in range(DH_INDEX_COUNT):
        val = _safe(f"getDH[{i}]", lambda i=i: _rpc(ec, "getDH", {"index": i}), errors)
        key = f"d{i + 1}"
        dh_named[key] = val
        dh_list.append(val)
    dump["dh"] = {
        "source": "JSON-RPC getDH; index 0..11 → d1..d12 (Elite EC socket manual)",
        "unit_note": "controller millimetres (same as teach-pendant 连杆参数)",
        "d1_to_d12": dh_named,
        "values_in_index_order": dh_list,
        "elite_ec616_yaml_mapping_note": (
            "profiles/elite_ec616.yaml link_length_mm is the 6-scalar DH map "
            "[d1, a2, a3, d4, d5, d6] ≈ XML LinkLength_1..6, not a raw copy of "
            "all eight pendant d's. Typical: a2←d3, a3←d5, d5←d7, d6←d8; "
            "wrist d4 combines lateral offsets (d2/d4/d6). Compare this dump "
            "to the existing YAML instead of overwriting blindly."
        ),
    }

    frames = dump["frames"]
    tools: dict[str, Any] = {}
    for n in range(TOOL_COUNT):
        tools[str(n)] = {
            "tcp_pose_deprecated_getTcpPos_deg": _safe(
                f"getTcpPos[{n}]",
                lambda n=n: _rpc(ec, "getTcpPos", {"tool_num": n, "unit_type": UNIT_DEG}),
                errors,
            ),
            "payload": _safe(f"get_payload[{n}]", lambda n=n: ec.get_payload(n), errors),
        }
    frames["tools_0_7"] = tools
    users: dict[str, Any] = {}
    for n in range(USER_FRAME_COUNT):
        users[str(n)] = _safe(
            f"getUserFrame[{n}]",
            lambda n=n: ec.get_user_frame_data(n, unit_type=UNIT_DEG),
            errors,
        )
    frames["user_0_7_deg"] = users

    snap = dump["current_snapshot"]
    snap["joint_deg"] = _safe("get_joint", lambda: ec.get_joint(), errors)
    snap["motor_pos"] = _safe("get_motor_pos", lambda: ec.get_motor_pos(), errors)
    snap["actual_joint"] = _safe(
        "get_actual_joint", lambda: _rpc(ec, "get_actual_joint"), errors
    )
    snap["flange_base_deg"] = _safe(
        "get_flange_pose_deg", lambda: ec.get_flange_pose(unit_type=UNIT_DEG), errors
    )
    snap["flange_base_rad"] = _safe(
        "get_flange_pose_rad", lambda: ec.get_flange_pose(unit_type=UNIT_RAD), errors
    )
    snap["tcp_base_current_tool_deg"] = _safe(
        "get_tcp_pose_deg",
        lambda: ec.get_tcp_pose(frame_num=-1, tool_num=-1, unit_type=UNIT_DEG),
        errors,
    )
    snap["tcp_base_current_tool_rad"] = _safe(
        "get_tcp_pose_rad",
        lambda: ec.get_tcp_pose(frame_num=-1, tool_num=-1, unit_type=UNIT_RAD),
        errors,
    )
    snap["tcp_base_tool0_deg"] = _safe(
        "get_tcp_pose_tool0_deg",
        lambda: ec.get_tcp_pose(frame_num=-1, tool_num=0, unit_type=UNIT_DEG),
        errors,
    )
    snap["actual_tcp"] = _safe(
        "get_actual_tcp", lambda: _rpc(ec, "get_actual_tcp"), errors
    )
    snap["flange_minus_tcp"] = _tcp_from_flange_and_tcp(
        snap.get("flange_base_deg"), snap.get("tcp_base_current_tool_deg")
    )

    jdeg = _as_float_list(snap.get("joint_deg"), 6)
    flange_deg = _as_float_list(snap.get("flange_base_deg"), 6)
    tcp_deg = _as_float_list(snap.get("tcp_base_current_tool_deg"), 6)

    kin = dump["controller_fk_ik"]
    kin["note"] = (
        "positiveKinematic / inverseKinematic / inverseKinematicAll are "
        "controller math on the current numbers only — they do not move the arm."
    )
    if jdeg is not None:
        kin["fk_from_current_joints_deg"] = _safe(
            "positiveKinematic",
            lambda: ec.get_forward_kinematic(jdeg, unit_type=UNIT_DEG),
            errors,
        )
        fk = _as_float_list(kin.get("fk_from_current_joints_deg"), 6)
        if fk is not None and flange_deg is not None:
            kin["fk_vs_flange_abs_err"] = [abs(fk[i] - flange_deg[i]) for i in range(6)]
        if fk is not None and tcp_deg is not None:
            kin["fk_vs_tcp_abs_err"] = [abs(fk[i] - tcp_deg[i]) for i in range(6)]
            kin["fk_matches_hint"] = (
                "If FK error vs flange is tiny and vs TCP is large, controller "
                "positiveKinematic is flange-referenced (typical)."
            )
    if flange_deg is not None:
        kin["ik_flange_seed_current_joints"] = _safe(
            "inverseKinematic_flange",
            lambda: ec.get_inverse_kinematic(
                flange_deg, ref_joint=jdeg, unit_type=UNIT_DEG
            ),
            errors,
        )
        kin["ik_all_flange"] = _safe(
            "inverseKinematicAll_flange",
            lambda: _rpc(ec, "inverseKinematicAll", {"targetPose": flange_deg}),
            errors,
        )
    if tcp_deg is not None:
        kin["ik_tcp_seed_current_joints"] = _safe(
            "inverseKinematic_tcp",
            lambda: ec.get_inverse_kinematic(tcp_deg, ref_joint=jdeg, unit_type=UNIT_DEG),
            errors,
        )
    if flange_deg is not None and tcp_deg is not None:
        inv_flange = _safe(
            "poseInv_flange",
            lambda: ec.pose_inv(flange_deg, unit_type=UNIT_DEG),
            errors,
        )
        if isinstance(inv_flange, list):
            kin["T_flange_tool_via_poseMul_deg"] = _safe(
                "poseMul(inv_flange, tcp)",
                lambda: ec.pose_mul(inv_flange, tcp_deg, unit_type=UNIT_DEG),
                errors,
            )

    if with_monitor:
        mon: dict[str, Any] | None = None
        try:
            if not hasattr(ec, "monitor_thread_run"):
                raise RuntimeError("elite.EC missing monitor_thread_run")
            ec.monitor_thread_run()
            deadline = time.perf_counter() + max(0.5, float(monitor_wait_s))
            ready = False
            while time.perf_counter() < deadline:
                info = getattr(ec, "monitor_info", None)
                pos = getattr(info, "machinePos", None)
                if pos is not None and len(pos) >= 6 and pos[0] is not None:
                    ready = True
                    break
                time.sleep(0.05)
            info = getattr(ec, "monitor_info", None)
            mon = {
                "ready": ready,
                "machinePos": _jsonable(getattr(info, "machinePos", None)),
                "machinePose": _jsonable(getattr(info, "machinePose", None)),
                "machineFlangePose": _jsonable(getattr(info, "machineFlangePose", None)),
                "machineUserPose": _jsonable(getattr(info, "machineUserPose", None)),
                "machineUserFlangePose": _jsonable(
                    getattr(info, "machineUserFlangePose", None)
                ),
                "robotState": _jsonable(getattr(info, "robotState", None)),
                "robotMode": _jsonable(getattr(info, "robotMode", None)),
            }
        except Exception as exc:  # noqa: BLE001
            errors.append({"label": "monitor_8056", "error": str(exc)})
            mon = {"ready": False, "error": str(exc)}
        dump["monitor_8056"] = mon

    teach = None
    if jdeg is not None and flange_deg is not None:
        teach = {
            "index": 1,
            "joint_deg": jdeg,
            "position_mm": flange_deg[:3],
            "orientation_rxyz_deg": flange_deg[3:],
            "source": "current pose at collection time (flange, unit_type=deg)",
        }
    t_tool = kin.get("T_flange_tool_via_poseMul_deg")
    tcp_xyz_m = None
    t_list = _as_float_list(t_tool, 6)
    if t_list is not None:
        tcp_xyz_m = [t_list[0] / 1000.0, t_list[1] / 1000.0, t_list[2] / 1000.0]

    dump["profile_hints"] = {
        "id": "elite_ec616",
        "link_length_mm_from_getDH_not_1to1": dh_list,
        "one_teach_pose_candidate": teach,
        "default_tcp_xyz_m_from_poseMul": tcp_xyz_m,
        "soft_limits_deg": None,
        "soft_limits_note": (
            "elirobots / EC JSON-RPC has no get-soft-limit API; keep pendant "
            "values (J3 ±156°, others ±360° on the hik EC616 cell)."
        ),
        "joint_offset_deg_note": (
            "SDK does not expose URDF-style joint_offset. Keep YAML "
            "[0, -90, 0, -90, 180, 0] unless a new teach calibration says otherwise."
        ),
    }
    return dump


def _close(ec: Any) -> None:
    try:
        if getattr(ec, "monitor_run_state", False):
            ec.monitor_run_state = False
            th = getattr(ec, "monitor_thread", None)
            if th is not None and getattr(th, "is_alive", lambda: False)():
                th.join(timeout=2.0)
    except Exception:
        pass
    try:
        ec.disconnect_ETController()
    except Exception:
        pass


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Read-only EC616 FK/IK data collection via elite.EC (no motion)."
    )
    p.add_argument("--ip", default=DEFAULT_IP, help=f"controller IP (default {DEFAULT_IP})")
    p.add_argument(
        "-o",
        "--out",
        default="",
        help="JSON output path (default: alongside this script)",
    )
    p.add_argument(
        "--skip-monitor",
        action="store_true",
        help="do not open TCP 8056 (JSON-RPC 8055 only)",
    )
    p.add_argument("--monitor-wait", type=float, default=8.0, help="seconds to wait for 8056")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    ip = str(args.ip).strip() or DEFAULT_IP

    try:
        from elite import EC  # type: ignore
    except ImportError:
        print(
            "Missing official EC SDK. Install:  pip install elirobots",
            file=sys.stderr,
        )
        return 2

    print(f"[collect-ec616] connecting elite.EC ip={ip} (command port 8055, no motion)")
    ec = EC(ip=ip, auto_connect=True)
    try:
        dump = collect(
            ec,
            with_monitor=not args.skip_monitor,
            monitor_wait_s=float(args.monitor_wait),
        )
    finally:
        _close(ec)

    out = Path(args.out) if args.out else Path(__file__).resolve().parent / "ec616-kinematics-dump.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dump, indent=2, ensure_ascii=False)
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"[collect-ec616] wrote {out}", file=sys.stderr)
    nerr = len(dump.get("errors") or [])
    if nerr:
        print(f"[collect-ec616] {nerr} field(s) failed (see errors[] in JSON)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
