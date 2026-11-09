"""Geometric wrist-camera FOV coverage (camera-fov-analysis skill).

Needle-hole angular test only — not intrinsics calibration / PnP.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np


def unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        raise ValueError("zero vector")
    return v / n


def fov_from_intrinsics(width: float, height: float, fx: float, fy: float) -> tuple[float, float]:
    """HFOV/VFOV in degrees from pinhole fx,fy (pixels) and image size."""
    if width <= 0 or height <= 0 or fx <= 0 or fy <= 0:
        raise ValueError("width/height/fx/fy must be > 0")
    h = math.degrees(2.0 * math.atan(float(width) / (2.0 * float(fx))))
    v = math.degrees(2.0 * math.atan(float(height) / (2.0 * float(fy))))
    return h, v


def resolve_mode_fov(mode: dict[str, Any]) -> tuple[float, float]:
    """Prefer explicit H/V degrees; else derive from W,H,fx,fy."""
    if mode.get("H_deg") is not None and mode.get("V_deg") is not None:
        return float(mode["H_deg"]), float(mode["V_deg"])
    w = mode.get("width")
    h = mode.get("height")
    fx = mode.get("fx")
    fy = mode.get("fy")
    if None in (w, h, fx, fy):
        raise ValueError(
            f"mode {mode.get('id')!r} needs H_deg+V_deg or width+height+fx+fy"
        )
    return fov_from_intrinsics(float(w), float(h), float(fx), float(fy))


def axes(cfg: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    lens = np.asarray(cfg["lens"], dtype=float)
    look = unit(np.asarray(cfg["look"], dtype=float))
    right = unit(np.asarray(cfg["right"], dtype=float))
    if "up" in cfg and cfg["up"] is not None:
        up = unit(np.asarray(cfg["up"], dtype=float))
    else:
        up = unit(np.cross(look, right))
    right = unit(np.cross(up, look))
    return lens, look, right, up


def project(
    p: np.ndarray, lens: np.ndarray, look: np.ndarray, right: np.ndarray, up: np.ndarray
) -> tuple[float, float, float]:
    rel = p - lens
    d = float(rel @ look)
    az = float(np.degrees(np.arctan2(rel @ right, d)))
    el = float(np.degrees(np.arctan2(rel @ up, d)))
    return d, az, el


def in_fov(d: float, az: float, el: float, H: float, V: float, *, min_depth: float = 1.0) -> bool:
    return d > min_depth and abs(az) <= H / 2.0 and abs(el) <= V / 2.0


def analyze(cfg: dict[str, Any]) -> dict[str, Any]:
    """Run coverage for ``cfg`` (lens/look/right/modes/samples in mm)."""
    for key in ("lens", "look", "right", "modes", "samples"):
        if key not in cfg:
            raise ValueError(f"fov config missing required key: {key}")
    lens, look, right, up = axes(cfg)
    points: list[dict[str, Any]] = []
    for s in cfg["samples"]:
        xyz = np.asarray(s["xyz"], dtype=float)
        d, az, el = project(xyz, lens, look, right, up)
        points.append(
            {
                "name": s.get("name", ""),
                "tag": s.get("tag", ""),
                "xyz": xyz.tolist(),
                "d_mm": d,
                "az_deg": az,
                "el_deg": el,
                "in_fov": {},
                "margin_h_deg": {},
                "margin_v_deg": {},
            }
        )

    mode_rows: list[dict[str, Any]] = []
    for m in cfg["modes"]:
        H, V = resolve_mode_fov(m)
        flags: list[bool] = []
        for pt in points:
            ok = in_fov(pt["d_mm"], pt["az_deg"], pt["el_deg"], H, V)
            flags.append(ok)
            pt["in_fov"][m["id"]] = ok
            pt["margin_h_deg"][m["id"]] = H / 2.0 - abs(pt["az_deg"])
            pt["margin_v_deg"][m["id"]] = V / 2.0 - abs(pt["el_deg"])
        n_ok = sum(flags)
        tagged: dict[str, Any] = {}
        for tag in sorted({p["tag"] for p in points if p["tag"]}):
            subset = [p for p in points if p["tag"] == tag]
            tagged[tag] = {
                "in": sum(1 for p in subset if p["in_fov"][m["id"]]),
                "n": len(subset),
            }
        hooks_o = [p for p in points if p["tag"] == "hook_o"]
        margin_h = None
        if hooks_o:
            margin_h = H / 2.0 - max(abs(p["az_deg"]) for p in hooks_o)
        mode_rows.append(
            {
                "id": m["id"],
                "label": m.get("label", m["id"]),
                "width": m.get("width"),
                "height": m.get("height"),
                "fx": m.get("fx"),
                "fy": m.get("fy"),
                "H_deg": H,
                "V_deg": V,
                "half_H": H / 2.0,
                "half_V": V / 2.0,
                "in_count": n_ok,
                "n": len(points),
                "by_tag": tagged,
                "open_hook_h_margin_deg": margin_h,
                "all_in": n_ok == len(points) and len(points) > 0,
            }
        )

    depths = cfg.get("footprint_depths_mm") or [90, 118, 120]
    footprints: list[dict[str, Any]] = []
    for m in mode_rows:
        H, V = m["H_deg"], m["V_deg"]
        for d in depths:
            footprints.append(
                {
                    "mode": m["id"],
                    "d_mm": float(d),
                    "width_mm": 2 * float(d) * math.tan(math.radians(H / 2)),
                    "height_mm": 2 * float(d) * math.tan(math.radians(V / 2)),
                }
            )

    # Prefer the widest FOV that still covers all points; else most in_count.
    recommend = None
    full = [m for m in mode_rows if m["all_in"]]
    if full:
        recommend = max(full, key=lambda m: m["H_deg"] * m["V_deg"])["id"]
    elif mode_rows:
        recommend = max(mode_rows, key=lambda m: (m["in_count"], m["H_deg"]))["id"]
    for m in mode_rows:
        m["recommend"] = m["id"] == recommend

    return {
        "lens": lens.tolist(),
        "look": look.tolist(),
        "right": right.tolist(),
        "up": up.tolist(),
        "points": points,
        "modes": mode_rows,
        "footprints": footprints,
        "recommend_mode": recommend,
        "frame": cfg.get("frame", ""),
        "units": cfg.get("units", "mm"),
        "camera_model": cfg.get("camera_model") or cfg.get("model", ""),
        "notes": cfg.get("notes", ""),
    }


def merge_camera_override(base: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    """Shallow+list merge for analyze request body over YAML defaults."""
    out = dict(base)
    if not override:
        return out
    for k, v in override.items():
        if v is None:
            continue
        if k == "enabled":
            continue
        out[k] = v
    return out
