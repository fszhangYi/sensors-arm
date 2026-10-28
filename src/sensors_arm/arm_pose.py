"""Live arm Cartesian pose from joints (FK) for viz — same path as hik_dataset.

Joints (rad) → flange FK → TCP offset → xyz + XYZ euler.
Inverse: TCP xyzrpy → flange target → ``ik_flange`` → joints (rad).

Backend selection (per arm model):
- ``kinematics`` → ``sensors.kinematics`` (EC616 / default)
- ``cs66_kinematics`` → ``sensors.cs66_kinematics`` (Cell B CS66)
- ``cs66_kin_g26562`` → ``sensors.cs66_kin_g26562`` (Cell C CS66 / G26562)
"""

from __future__ import annotations

import importlib
import math
import threading
from typing import Any, Callable, Sequence

import numpy as np

from sensors_arm.paths import ensure_sensors_import

ensure_sensors_import()

# Match hik_dataset / data_postprocess default tool offset (meters).
DEFAULT_TCP_XYZ: tuple[float, float, float] = (0.0, 0.0, 0.18)

PKG_LEGACY = "kinematics"
PKG_CS66 = "cs66_kinematics"
PKG_CS66_G26562 = "cs66_kin_g26562"

# Normalized package id → import path for YAML-backed CS66 FK/IK.
_CS66_YAML_MODULES: dict[str, str] = {
    PKG_CS66: "sensors.cs66_kinematics",
    PKG_CS66_G26562: "sensors.cs66_kin_g26562",
}

# Process-wide active offset (set from DCS YAML ``tcp_xyz`` at Orchestrator boot).
_active_tcp_xyz: tuple[float, float, float] = DEFAULT_TCP_XYZ


def normalize_tcp_xyz(raw: Any | None) -> tuple[float, float, float]:
    """Parse ``[x,y,z]`` meters; ``None``/empty → ``DEFAULT_TCP_XYZ``."""
    if raw is None or raw == "":
        return DEFAULT_TCP_XYZ
    if isinstance(raw, (list, tuple)):
        if len(raw) != 3:
            raise ValueError("tcp_xyz must have exactly 3 floats (meters)")
        out: list[float] = []
        for i, x in enumerate(raw):
            try:
                f = float(x)
            except (TypeError, ValueError) as e:
                raise ValueError(f"tcp_xyz[{i}] must be a finite float") from e
            if not math.isfinite(f):
                raise ValueError(f"tcp_xyz[{i}] must be a finite float")
            out.append(f)
        return (out[0], out[1], out[2])
    raise ValueError("tcp_xyz must be a list of 3 floats (meters)")


def get_tcp_xyz() -> tuple[float, float, float]:
    """Current flange→TCP translation used by online FK/IK."""
    return _active_tcp_xyz


def set_tcp_xyz(raw: Any | None) -> tuple[float, float, float]:
    """Install process-wide TCP offset (call once at Orchestrator boot)."""
    global _active_tcp_xyz
    _active_tcp_xyz = normalize_tcp_xyz(raw)
    return _active_tcp_xyz


def resolve_tcp_xyz(
    tcp_xyz: tuple[float, float, float] | Sequence[float] | None = None,
) -> tuple[float, float, float]:
    """Explicit override, else active configured offset."""
    if tcp_xyz is None:
        return get_tcp_xyz()
    return normalize_tcp_xyz(tcp_xyz)


_fk_by_key: dict[str, Callable[[list[float]], np.ndarray] | bool] = {}
# Cached IK backend: {IkResult, ik_flange, kin_cfg|None}
_ik_backend_by_key: dict[str, dict[str, Any] | bool] = {}
_scipy_rotation = None
_fk_warm_done = False
_fk_warm_lock = threading.Lock()


def _kin_key(package: str, profile_id: str | None) -> str:
    pkg = (package or PKG_LEGACY).strip() or PKG_LEGACY
    if pkg in _CS66_YAML_MODULES:
        return f"{pkg}:{(profile_id or 'elite_cs66').strip()}"
    return f"{PKG_LEGACY}:"


def normalize_kinematics(
    package: str | None = None,
    profile_id: str | None = None,
) -> tuple[str, str | None]:
    """Normalize catalog fields → ``(package, profile_id)``."""
    pkg = (package or PKG_LEGACY).strip() or PKG_LEGACY
    if pkg in ("cs66", "cs66_kinematics", "sensors.cs66_kinematics"):
        return PKG_CS66, (profile_id or "elite_cs66").strip()
    if pkg in ("cs66_kin_g26562", "sensors.cs66_kin_g26562", "cs66_g26562"):
        return PKG_CS66_G26562, (profile_id or "elite_cs66").strip()
    return PKG_LEGACY, None


def _import_cs66_yaml(package: str):
    """Import ``sensors.cs66_*`` module for a normalized CS YAML package id."""
    mod_name = _CS66_YAML_MODULES.get(package)
    if not mod_name:
        raise ImportError(f"not a CS66 YAML kinematics package: {package}")
    return importlib.import_module(mod_name)


def kinematics_ready(
    package: str | None = None,
    profile_id: str | None = None,
) -> bool:
    """True after warm (no args), or after a specific backend has been attempted."""
    if package is None:
        return _fk_warm_done
    key = _kin_key(*normalize_kinematics(package, profile_id))
    return key in _fk_by_key


def _ensure_scipy() -> None:
    global _scipy_rotation
    if _scipy_rotation is not None:
        return
    try:
        from scipy.spatial.transform import Rotation as R  # type: ignore

        _scipy_rotation = R
    except Exception:  # noqa: BLE001
        _scipy_rotation = False  # type: ignore[assignment]


def _load_fk_unlocked(pkg: str, prof: str | None):
    """Create FK for ``pkg``/``prof``; caller must hold ``_fk_warm_lock`` or accept race."""
    key = _kin_key(pkg, prof)
    cached = _fk_by_key.get(key)
    if cached is not None:
        return cached
    _ensure_scipy()
    try:
        if pkg in _CS66_YAML_MODULES:
            mod = _import_cs66_yaml(pkg)
            fn = mod.make_hik_fk_fn(prof)
        else:
            from sensors.kinematics import make_hik_fk_fn

            fn = make_hik_fk_fn()
        _fk_by_key[key] = fn
        return fn
    except Exception:  # noqa: BLE001
        # e.g. profile supported:false or import failure
        _fk_by_key[key] = False
        return False


def _get_fk(
    package: str | None = None,
    profile_id: str | None = None,
):
    """Return FK callable, ``False`` if backend unavailable."""
    pkg, prof = normalize_kinematics(package, profile_id)
    key = _kin_key(pkg, prof)
    cached = _fk_by_key.get(key)
    if cached is not None:
        return cached
    with _fk_warm_lock:
        return _load_fk_unlocked(pkg, prof)


def _load_ik_backend_unlocked(pkg: str, prof: str | None) -> dict[str, Any] | bool:
    """Import + cache ``ik_flange`` / config for ``pkg``; caller holds ``_fk_warm_lock``."""
    key = _kin_key(pkg, prof)
    cached = _ik_backend_by_key.get(key)
    if cached is not None:
        return cached
    try:
        if pkg in _CS66_YAML_MODULES:
            mod = _import_cs66_yaml(pkg)
            model_mod = importlib.import_module(f"{_CS66_YAML_MODULES[pkg]}.model")
            backend: dict[str, Any] = {
                "IkResult": model_mod.IkResult,
                "ik_flange": mod.ik_flange,
                "kin_cfg": mod.get_kinematic_config(prof),
            }
        else:
            from sensors.kinematics import ik_flange
            from sensors.kinematics.model import IkResult

            backend = {
                "IkResult": IkResult,
                "ik_flange": ik_flange,
                "kin_cfg": None,
            }
        _ik_backend_by_key[key] = backend
        return backend
    except Exception:  # noqa: BLE001
        _ik_backend_by_key[key] = False
        return False


def _get_ik_backend(
    package: str | None = None,
    profile_id: str | None = None,
) -> dict[str, Any] | bool:
    pkg, prof = normalize_kinematics(package, profile_id)
    key = _kin_key(pkg, prof)
    cached = _ik_backend_by_key.get(key)
    if cached is not None:
        return cached
    with _fk_warm_lock:
        return _load_ik_backend_unlocked(pkg, prof)


def warm_kinematics(
    backends: Sequence[tuple[str, str | None]] | None = None,
) -> None:
    """Preload FK + IK + scipy (avoids first-drag cold start).

    ``backends``: list of ``(package, profile_id)``; default warms legacy + both CS66 YAML packs.
    """
    global _fk_warm_done
    specs = list(backends) if backends else [
        (PKG_LEGACY, None),
        (PKG_CS66, "elite_cs66"),
        (PKG_CS66_G26562, "elite_cs66"),
    ]
    with _fk_warm_lock:
        _ensure_scipy()
        for package, profile_id in specs:
            pkg, prof = normalize_kinematics(package, profile_id)
            _load_fk_unlocked(pkg, prof)
            _load_ik_backend_unlocked(pkg, prof)
        _fk_warm_done = True
    # Dummy LM IK outside lock so first amber-ball drag is warm.
    for package, profile_id in specs:
        pkg, prof = normalize_kinematics(package, profile_id)
        try:
            backend = _get_ik_backend(pkg, prof)
            if backend is False or not isinstance(backend, dict):
                continue
            seed = [0.0, -0.5, 1.0, -0.5, 1.2, 0.0]
            pose = joints_rad_to_xyzrpy(
                seed,
                kinematics=pkg,
                kinematics_profile=prof,
            )
            if pose is None:
                continue
            xyzrpy_to_joints_rad(
                pose,
                q_seed_rad=seed,
                kinematics=pkg,
                kinematics_profile=prof,
                interactive=True,
                max_nfev=40,
                multi_seed=False,
                soft_limit_retry=False,
                enforce_teach_soft_limits=False,
            )
        except Exception:  # noqa: BLE001
            continue


def _tcp_matrix(tcp_xyz: tuple[float, float, float]) -> np.ndarray:
    tcp = np.eye(4, dtype=np.float64)
    tcp[:3, 3] = np.asarray(tcp_xyz, dtype=np.float64)
    return tcp


def _mat_to_euler_xyz(rot: np.ndarray) -> list[float]:
    """XYZ extrinsic euler (matches scipy Rotation.as_euler('xyz'))."""
    R = _scipy_rotation
    if R not in (None, False):
        try:
            return R.from_matrix(rot).as_euler("xyz").tolist()
        except Exception:  # noqa: BLE001
            pass
    r = np.asarray(rot, dtype=np.float64)
    sy = math.sqrt(float(r[0, 0]) ** 2 + float(r[1, 0]) ** 2)
    if sy > 1e-8:
        x = math.atan2(float(r[2, 1]), float(r[2, 2]))
        y = math.atan2(-float(r[2, 0]), sy)
        z = math.atan2(float(r[1, 0]), float(r[0, 0]))
    else:
        x = math.atan2(-float(r[1, 2]), float(r[1, 1]))
        y = math.atan2(-float(r[2, 0]), sy)
        z = 0.0
    return [x, y, z]


def _pose_to_xyzrpy(pose: np.ndarray) -> list[float]:
    return pose[:3, 3].tolist() + _mat_to_euler_xyz(pose[:3, :3])


def _xyzrpy_to_matrix(xyzrpy: Sequence[float]) -> np.ndarray:
    """Build 4×4 TCP pose from ``[x,y,z,rx,ry,rz]`` (m / XYZ euler rad)."""
    vals = [float(x) for x in list(xyzrpy)[:6]]
    if len(vals) < 6 or any(not math.isfinite(v) for v in vals):
        raise ValueError("xyzrpy must be 6 finite floats")
    x, y, z, rx, ry, rz = vals
    try:
        from scipy.spatial.transform import Rotation as R  # type: ignore

        rot = R.from_euler("xyz", [rx, ry, rz]).as_matrix()
    except Exception:  # noqa: BLE001
        # Fallback XYZ extrinsic: Rz @ Ry @ Rx
        cx, sx = math.cos(rx), math.sin(rx)
        cy, sy = math.cos(ry), math.sin(ry)
        cz, sz = math.cos(rz), math.sin(rz)
        rot = np.array(
            [
                [cy * cz, sx * sy * cz - cx * sz, cx * sy * cz + sx * sz],
                [cy * sz, sx * sy * sz + cx * cz, cx * sy * sz - sx * cz],
                [-sy, sx * cy, cx * cy],
            ],
            dtype=np.float64,
        )
    T = np.eye(4, dtype=np.float64)
    T[:3, :3] = rot
    T[:3, 3] = (x, y, z)
    return T


def compose_delta_xyzrpy(
    current_xyzrpy: Sequence[float],
    delta_xyzrpy: Sequence[float],
) -> list[float]:
    """Absolute TCP pose: ``T_next = T_current @ T_delta`` (SE(3) left-compose)."""
    T_cur = _xyzrpy_to_matrix(current_xyzrpy)
    T_delta = _xyzrpy_to_matrix(delta_xyzrpy)
    return _pose_to_xyzrpy(T_cur @ T_delta)


def relative_xyzrpy(
    from_xyzrpy: Sequence[float],
    to_xyzrpy: Sequence[float],
) -> list[float]:
    """Relative TCP delta: ``T_delta = inv(T_from) @ T_to`` → xyzrpy."""
    T_from = _xyzrpy_to_matrix(from_xyzrpy)
    T_to = _xyzrpy_to_matrix(to_xyzrpy)
    return _pose_to_xyzrpy(np.linalg.inv(T_from) @ T_to)


# Wire formats for serve robot_state / next_state (7-d: 6 + grip).
SEND_STATE_FORMATS = ("joints", "pose")  # option A: no delta on send
RECV_STATE_FORMATS = ("joints", "pose", "delta_pose")
DEFAULT_SEND_STATE_FORMAT = "pose"
DEFAULT_RECV_STATE_FORMAT = "pose"


def normalize_send_state_format(fmt: str | None) -> str:
    v = (fmt or DEFAULT_SEND_STATE_FORMAT).strip().lower()
    if v == "delta_pose":
        raise ValueError(
            "robot_state format delta_pose is disabled (option A); use joints or pose"
        )
    if v not in SEND_STATE_FORMATS:
        raise ValueError(
            f"robot_state format must be one of {SEND_STATE_FORMATS}, got {fmt!r}"
        )
    return v


def normalize_recv_state_format(fmt: str | None) -> str:
    v = (fmt or DEFAULT_RECV_STATE_FORMAT).strip().lower()
    if v not in RECV_STATE_FORMATS:
        raise ValueError(
            f"next_state format must be one of {RECV_STATE_FORMATS}, got {fmt!r}"
        )
    return v


# TCP workspace box: -1 on a bound = that side unrestricted.
TCP_CLIP_KEYS = ("x_min", "x_max", "y_min", "y_max", "z_min", "z_max")
TCP_CLIP_FREE = -1.0


def tcp_clip_bound_is_free(v: float) -> bool:
    """True when bound is the sentinel ``-1`` (no limit on that side)."""
    return float(v) == TCP_CLIP_FREE


def default_tcp_clip() -> dict[str, float]:
    return {k: TCP_CLIP_FREE for k in TCP_CLIP_KEYS}


def normalize_tcp_clip(bounds: Any | None) -> dict[str, float]:
    """Parse ``tcp_clip`` dict; missing/None → all ``-1``. Raises on bad values / lo>hi."""
    out = default_tcp_clip()
    if bounds is None:
        return out
    if not isinstance(bounds, dict):
        raise ValueError("tcp_clip must be an object with x_min…z_max")
    for k in TCP_CLIP_KEYS:
        if k not in bounds or bounds[k] is None:
            continue
        try:
            v = float(bounds[k])
        except (TypeError, ValueError) as e:
            raise ValueError(f"tcp_clip.{k} must be a finite float") from e
        if not math.isfinite(v):
            raise ValueError(f"tcp_clip.{k} must be a finite float")
        out[k] = v
    for axis, lo_k, hi_k in (
        ("x", "x_min", "x_max"),
        ("y", "y_min", "y_max"),
        ("z", "z_min", "z_max"),
    ):
        lo, hi = out[lo_k], out[hi_k]
        if not tcp_clip_bound_is_free(lo) and not tcp_clip_bound_is_free(hi) and lo > hi:
            raise ValueError(f"tcp_clip.{axis}_min ({lo}) > {axis}_max ({hi})")
    return out


def tcp_clip_is_active(bounds: dict[str, float] | None) -> bool:
    """True if any bound is not the ``-1`` sentinel."""
    if not bounds:
        return False
    return any(not tcp_clip_bound_is_free(float(bounds.get(k, TCP_CLIP_FREE))) for k in TCP_CLIP_KEYS)


def clip_tcp_xyzrpy(
    xyzrpy: Sequence[float],
    bounds: dict[str, float] | None,
) -> dict[str, Any]:
    """Clip TCP ``x,y,z`` to box; leave rpy unchanged.

    Returns ``{ok, goal_xyzrpy, goal_xyzrpy_raw, applied, error?}``.
    ``bounds`` should already be normalized (or None → no-op).
    """
    try:
        raw = [float(x) for x in list(xyzrpy)[:6]]
    except (TypeError, ValueError):
        return {
            "ok": False,
            "error": "xyzrpy must be 6 finite floats",
            "goal_xyzrpy": None,
            "goal_xyzrpy_raw": None,
            "applied": False,
        }
    if len(raw) < 6 or any(not math.isfinite(v) for v in raw):
        return {
            "ok": False,
            "error": "xyzrpy must be 6 finite floats",
            "goal_xyzrpy": None,
            "goal_xyzrpy_raw": None,
            "applied": False,
        }
    b = bounds if isinstance(bounds, dict) else default_tcp_clip()
    clipped = list(raw)
    applied = False
    for i, (lo_k, hi_k) in enumerate(
        (("x_min", "x_max"), ("y_min", "y_max"), ("z_min", "z_max"))
    ):
        lo = float(b.get(lo_k, TCP_CLIP_FREE))
        hi = float(b.get(hi_k, TCP_CLIP_FREE))
        v = clipped[i]
        if not tcp_clip_bound_is_free(lo) and v < lo:
            clipped[i] = lo
            applied = True
        if not tcp_clip_bound_is_free(hi) and clipped[i] > hi:
            clipped[i] = hi
            applied = True
    return {
        "ok": True,
        "error": None,
        "goal_xyzrpy": clipped,
        "goal_xyzrpy_raw": raw,
        "applied": applied,
    }


def joints_rad_to_xyzrpy(
    joints_rad: Sequence[float] | None,
    *,
    tcp_xyz: tuple[float, float, float] | Sequence[float] | None = None,
    kinematics: str | None = None,
    kinematics_profile: str | None = None,
) -> list[float] | None:
    """Return ``[x,y,z,rx,ry,rz]`` (m / rad) or ``None`` if joints unusable."""
    offset = resolve_tcp_xyz(tcp_xyz)
    if joints_rad is None:
        return None
    try:
        j = [float(x) for x in list(joints_rad)[:6]]
    except (TypeError, ValueError):
        return None
    if len(j) < 6 or any(not math.isfinite(x) for x in j):
        return None
    fk = _get_fk(kinematics, kinematics_profile)
    if fk is False or not callable(fk):
        return None
    try:
        T = np.asarray(fk(j), dtype=np.float64) @ _tcp_matrix(offset)
        out = _pose_to_xyzrpy(T)
    except Exception:  # noqa: BLE001
        return None
    if len(out) != 6 or any(not math.isfinite(float(x)) for x in out):
        return None
    return [float(x) for x in out]


def xyzrpy_to_joints_rad(
    xyzrpy: Sequence[float] | None,
    *,
    q_seed_rad: Sequence[float],
    tcp_xyz: tuple[float, float, float] | Sequence[float] | None = None,
    kinematics: str | None = None,
    kinematics_profile: str | None = None,
    enforce_teach_soft_limits: bool = True,
    # Infer control tolerances (default ik_flange 1e-5m / 5e-4rad is far too tight).
    position_tolerance_m: float = 2e-3,
    orientation_tolerance_rad: float = 2e-2,
    accept_residual: float = 1.5e-2,
    max_nfev: int = 600,
    soft_limit_retry: bool = True,
    ori_weight: float = 0.25,
    multi_seed: bool = True,
    interactive: bool = False,
    solver_tol: float | None = None,
) -> dict[str, Any]:
    """IK: TCP ``xyzrpy`` → ``joints_rad`` (seeded by current arm joints).

    ``interactive=True`` (TCP drag): prefer fast unbounded LM, skip soft-limit TRF
    and multi-seed by default — soft TRF + 2-point jac was the main drag lag source.
    """
    pkg, prof = normalize_kinematics(kinematics, kinematics_profile)
    offset = resolve_tcp_xyz(tcp_xyz)
    if xyzrpy is None:
        return {"ok": False, "error": "xyzrpy is None", "joints_rad": None}
    try:
        seed = [float(x) for x in list(q_seed_rad)[:6]]
    except (TypeError, ValueError):
        return {"ok": False, "error": "q_seed_rad must be 6 floats", "joints_rad": None}
    if len(seed) < 6 or any(not math.isfinite(x) for x in seed):
        return {"ok": False, "error": "q_seed_rad must be 6 finite floats", "joints_rad": None}
    try:
        T_tcp = _xyzrpy_to_matrix(xyzrpy)
        T_flange = T_tcp @ np.linalg.inv(_tcp_matrix(offset))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"invalid xyzrpy: {e}", "joints_rad": None}

    backend = _get_ik_backend(pkg, prof)
    if backend is False or not isinstance(backend, dict):
        return {"ok": False, "error": f"IK unavailable ({pkg})", "joints_rad": None}
    IkResult = backend["IkResult"]
    ik_flange = backend["ik_flange"]
    kin_cfg = backend.get("kin_cfg")

    # Interactive defaults: LM (no bounds), modest nfev, looser solver tol.
    # Caller (runtime) sets multi_seed / max_nfev explicitly for escalate.
    use_interactive = bool(interactive)
    if use_interactive:
        enforce_teach_soft_limits = False
        soft_limit_retry = False
        if max_nfev >= 600:
            max_nfev = 80
        if solver_tol is None:
            solver_tol = 1e-6
        if accept_residual < 2e-2:
            accept_residual = 2e-2
        if position_tolerance_m < 3e-3:
            position_tolerance_m = 3e-3

    nfev_cap = max(20, int(max_nfev))
    seed_list: list[list[float]] = [list(seed)]
    if multi_seed:
        # Keep escalate seeds small — full 6×4 grid made drag unusable.
        for axis in range(6):
            for delta in (0.25, -0.25):
                s2 = list(seed)
                s2[axis] = float(s2[axis]) + delta
                seed_list.append(s2)

    def _run(*, soft_limits: bool, seed_rad: list[float]) -> Any:
        seed_deg = np.rad2deg(np.asarray(seed_rad, dtype=np.float64))
        kwargs: dict[str, Any] = {
            "return_details": True,
            "enforce_teach_soft_limits": bool(soft_limits),
            "max_nfev": nfev_cap,
            "position_tolerance_m": float(position_tolerance_m),
            "orientation_tolerance_rad": float(orientation_tolerance_rad),
            "ori_weight": float(ori_weight),
            "lm_method": "lm",
        }
        if kin_cfg is not None:
            kwargs["kin_cfg"] = kin_cfg
        if solver_tol is not None:
            kwargs["solver_tol"] = float(solver_tol)
        return ik_flange(T_flange, seed_deg, **kwargs)

    result = None
    last_err: str | None = None
    best_effort: Any = None
    # Soft-limit TRF is slow (numerical jac). Interactive: LM only.
    soft_attempts = [False] if use_interactive else [bool(enforce_teach_soft_limits)]
    if (not use_interactive) and soft_limit_retry and enforce_teach_soft_limits:
        soft_attempts.append(False)
    for soft in soft_attempts:
        for seed_rad in seed_list:
            try:
                cand = _run(soft_limits=soft, seed_rad=seed_rad)
            except Exception as e:  # noqa: BLE001
                last_err = str(e)
                continue
            if not isinstance(cand, IkResult):
                last_err = "IK returned unexpected type"
                continue
            if best_effort is None or float(cand.residual_norm) < float(
                best_effort.residual_norm
            ):
                best_effort = cand
            if cand.success or float(cand.residual_norm) <= float(accept_residual):
                result = cand
                break
            last_err = (
                f"IK did not converge ({cand.message}); "
                f"residual={cand.residual_norm:.3e}"
            )
        if result is not None:
            break

    if result is None and best_effort is not None:
        result = best_effort

    if result is None:
        return {
            "ok": False,
            "error": last_err or "IK failed",
            "joints_rad": None,
        }

    joints = [
        float(x)
        for x in np.deg2rad(np.asarray(result.joint_deg, dtype=np.float64).reshape(6))
    ]
    if any(not math.isfinite(x) for x in joints):
        return {"ok": False, "error": "IK returned non-finite joints", "joints_rad": None}

    achieved = joints_rad_to_xyzrpy(
        joints,
        tcp_xyz=offset,
        kinematics=pkg,
        kinematics_profile=prof,
    )
    pos_err = None
    if achieved is not None:
        tgt = [float(x) for x in list(xyzrpy)[:6]]
        pos_err = math.sqrt(sum((achieved[i] - tgt[i]) ** 2 for i in range(3)))
        if pos_err > max(float(position_tolerance_m) * 5.0, 2.5e-2):
            return {
                "ok": False,
                "error": (
                    f"IK pose check failed: pos_err={pos_err:.3e}m "
                    f"(residual={result.residual_norm:.3e})"
                ),
                "joints_rad": None,
                "residual_norm": float(result.residual_norm),
                "pos_err_m": pos_err,
            }

    ok_flag = bool(result.success) or (
        pos_err is not None and pos_err <= max(float(position_tolerance_m) * 5.0, 2.5e-2)
    ) or float(result.residual_norm) <= float(accept_residual)
    if not ok_flag:
        return {
            "ok": False,
            "error": (
                f"IK did not converge ({result.message}); "
                f"residual={result.residual_norm:.3e}"
            ),
            "joints_rad": None,
            "residual_norm": float(result.residual_norm),
            "pos_err_m": pos_err,
        }

    return {
        "ok": True,
        "joints_rad": joints,
        "residual_norm": float(result.residual_norm),
        "nfev": int(result.nfev),
        "ik_success_flag": bool(result.success),
        "pos_err_m": pos_err,
        "kinematics": pkg,
        "kinematics_profile": prof,
        "interactive": use_interactive,
        "achieved_xyzrpy": achieved,
    }


def cartesian_payload(
    joints_rad: Sequence[float] | None,
    *,
    tcp_xyz: tuple[float, float, float] | Sequence[float] | None = None,
    kinematics: str | None = None,
    kinematics_profile: str | None = None,
) -> dict[str, Any]:
    """Compact fields for arm agent / viz payloads."""
    pkg, prof = normalize_kinematics(kinematics, kinematics_profile)
    offset = resolve_tcp_xyz(tcp_xyz) if tcp_xyz is not None else get_tcp_xyz()
    xyzrpy = joints_rad_to_xyzrpy(
        joints_rad,
        tcp_xyz=offset,
        kinematics=pkg,
        kinematics_profile=prof,
    )
    # Flange = tool offset zero (same joints / kinematics backend).
    flange = joints_rad_to_xyzrpy(
        joints_rad,
        tcp_xyz=(0.0, 0.0, 0.0),
        kinematics=pkg,
        kinematics_profile=prof,
    )
    return {
        "cartesian_xyzrpy": xyzrpy,
        "cartesian_tcp_xyz": list(offset),
        "cartesian_frame": "base_tcp" if xyzrpy is not None else None,
        "cartesian_kinematics": pkg,
        "cartesian_kinematics_profile": prof,
        "flange_xyzrpy": flange,
    }


def _lerp_xyzrpy(pose_a: Sequence[float], pose_b: Sequence[float], alpha: float) -> list[float]:
    """Linear xyz + SLERP orientation (XYZ euler); alpha in (0, 1]."""
    a = max(0.0, min(1.0, float(alpha)))
    pa = [float(x) for x in list(pose_a)[:6]]
    pb = [float(x) for x in list(pose_b)[:6]]
    xyz = [pa[i] + a * (pb[i] - pa[i]) for i in range(3)]
    try:
        from scipy.spatial.transform import Rotation as R  # type: ignore
        from scipy.spatial.transform import Slerp  # type: ignore

        ra = R.from_euler("xyz", pa[3:6])
        rb = R.from_euler("xyz", pb[3:6])
        slerp = Slerp([0.0, 1.0], R.concatenate([ra, rb]))
        rpy = slerp([a]).as_euler("xyz")[0].tolist()
    except Exception:  # noqa: BLE001
        rpy = [pa[i] + a * (pb[i] - pa[i]) for i in range(3, 6)]
    return xyz + [float(x) for x in rpy]


def cartesian_linear_joint_path(
    qa: Sequence[float],
    qg: Sequence[float],
    n: int,
    *,
    tcp_xyz: tuple[float, float, float] | Sequence[float] | None = None,
    kinematics: str | None = None,
    kinematics_profile: str | None = None,
) -> dict[str, Any]:
    """Build a joint path whose TCP xyz moves in a straight line (FK → lerp → IK).

    - Endpoints from FK(``qa``) / FK(``qg``).
    - Intermediate TCP: linear xyz + SLERP orientation.
    - Each waypoint IK-seeded by the previous joints; last point is exactly ``qg``.
    """
    pkg, prof = normalize_kinematics(kinematics, kinematics_profile)
    offset = resolve_tcp_xyz(tcp_xyz)
    n = max(1, int(n))
    try:
        q_start = [float(x) for x in list(qa)[:6]]
        q_goal = [float(x) for x in list(qg)[:6]]
    except (TypeError, ValueError):
        return {"ok": False, "error": "qa/qg must be 6 floats", "joints_path": None}
    if len(q_start) < 6 or len(q_goal) < 6:
        return {"ok": False, "error": "qa/qg must be length 6", "joints_path": None}
    if any(not math.isfinite(x) for x in q_start + q_goal):
        return {"ok": False, "error": "qa/qg must be finite", "joints_path": None}

    pose_a = joints_rad_to_xyzrpy(
        q_start, tcp_xyz=offset, kinematics=pkg, kinematics_profile=prof
    )
    pose_g = joints_rad_to_xyzrpy(
        q_goal, tcp_xyz=offset, kinematics=pkg, kinematics_profile=prof
    )
    if pose_a is None or pose_g is None:
        return {
            "ok": False,
            "error": "FK failed for start/goal joints; cannot build Cartesian ramp",
            "joints_path": None,
        }

    if n == 1:
        return {
            "ok": True,
            "joints_path": [list(q_goal)],
            "pose_start": pose_a,
            "pose_goal": pose_g,
        }

    path: list[list[float]] = []
    seed = list(q_start)
    for k in range(1, n):
        alpha = k / float(n)
        xyzrpy = _lerp_xyzrpy(pose_a, pose_g, alpha)
        ik = xyzrpy_to_joints_rad(
            xyzrpy,
            q_seed_rad=seed,
            tcp_xyz=offset,
            kinematics=pkg,
            kinematics_profile=prof,
            enforce_teach_soft_limits=False,
            soft_limit_retry=False,
            max_nfev=120,
            accept_residual=1e-2,
        )
        if not ik.get("ok") or not ik.get("joints_rad"):
            return {
                "ok": False,
                "error": (
                    f"IK failed at Cartesian ramp {k}/{n}: "
                    f"{ik.get('error') or 'unknown'}"
                ),
                "joints_path": None,
                "fail_index": k,
                "fail_xyzrpy": xyzrpy,
            }
        qk = [float(x) for x in ik["joints_rad"][:6]]
        path.append(qk)
        seed = qk
    path.append(list(q_goal))
    return {
        "ok": True,
        "joints_path": path,
        "pose_start": pose_a,
        "pose_goal": pose_g,
    }
