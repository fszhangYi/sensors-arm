"""Derive FOV extrinsics + fingertip samples from Cell C EOAT STL meshes."""

from __future__ import annotations

import re
import struct
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from sensors_arm.paths import static_dir

# Tool-frame meshes (meters) used by cs66.urdf EOAT
DEFAULT_MESHES = {
    "camera": "models/cs66/meshes/D405_camera.STL",
    "tip_l": "models/cs66/meshes/EFG-C65_D405_fingertip_l.STL",
    "tip_r": "models/cs66/meshes/EFG-C65_D405_fingertip_r.STL",
}


def load_binary_stl_points(path: Path) -> np.ndarray:
    data = path.read_bytes()
    if len(data) < 84:
        raise ValueError(f"STL too small: {path}")
    n = struct.unpack_from("<I", data, 80)[0]
    need = 84 + n * 50
    if len(data) < need:
        raise ValueError(f"STL truncated: {path} (need {need} bytes, got {len(data)})")
    pts = np.empty((n * 3, 3), dtype=np.float64)
    off = 84
    for i in range(n):
        vals = struct.unpack_from("<12fH", data, off)
        pts[i * 3] = vals[3:6]
        pts[i * 3 + 1] = vals[6:9]
        pts[i * 3 + 2] = vals[9:12]
        off += 50
    return pts


def aabb(pts: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mn = pts.min(axis=0)
    mx = pts.max(axis=0)
    return mn, mx, 0.5 * (mn + mx)


def unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        raise ValueError("zero vector")
    return v / n


def mesh_paths(base: Path | None = None) -> dict[str, Path]:
    root = base or static_dir()
    out = {k: root / rel for k, rel in DEFAULT_MESHES.items()}
    missing = [str(p) for p in out.values() if not p.is_file()]
    if missing:
        raise FileNotFoundError("missing EOAT STL(s):\n  " + "\n  ".join(missing))
    return out


def extract_from_stls(
    *,
    mesh_base: Path | None = None,
    open_extra_mm: float = 32.0,
) -> dict[str, Any]:
    """Heuristic lens/look/right + fingertip samples from tool-frame STLs (output mm)."""
    paths = mesh_paths(mesh_base)
    cam = load_binary_stl_points(paths["camera"])
    tip_l = load_binary_stl_points(paths["tip_l"])
    tip_r = load_binary_stl_points(paths["tip_r"])

    c_mn, c_mx, c_c = aabb(cam)
    l_mn, l_mx, l_c = aabb(tip_l)
    r_mn, r_mx, r_c = aabb(tip_r)

    # Lens ≈ camera AABB center pushed to the +Z face (toward tip).
    lens_m = np.array([c_c[0], c_c[1], c_mx[2]], dtype=float)
    tip_mid_m = np.array(
        [0.5 * (l_c[0] + r_c[0]), 0.5 * (l_c[1] + r_c[1]), 0.5 * (l_mx[2] + r_mx[2])],
        dtype=float,
    )
    look = unit(tip_mid_m - lens_m)
    # Prefer camera right ≈ −X in tool frame; re-orthonormalize.
    up_guess = np.array([0.0, 1.0, 0.0], dtype=float)
    right = np.cross(look, up_guess)
    if float(np.linalg.norm(right)) < 1e-8:
        up_guess = np.array([0.0, 0.0, 1.0], dtype=float)
        right = np.cross(look, up_guess)
    right = unit(right)
    # Flip so right · (−X) ≥ 0
    if float(right @ np.array([-1.0, 0.0, 0.0])) < 0:
        right = -right
    up = unit(np.cross(right, look))
    right = unit(np.cross(up, look))

    def mm(v: np.ndarray) -> list[float]:
        return [round(float(x) * 1000.0, 3) for x in v]

    # Finger samples from AABB extrema (m → mm)
    z_root = min(float(l_mn[2]), float(r_mn[2]))
    z_tip = max(float(l_mx[2]), float(r_mx[2]))
    samples = [
        {"name": "root_L", "xyz": mm(np.array([l_c[0], l_c[1], z_root])), "tag": "root"},
        {"name": "root_R", "xyz": mm(np.array([r_c[0], r_c[1], z_root])), "tag": "root"},
        {"name": "tip_L", "xyz": mm(np.array([l_c[0], l_c[1], z_tip])), "tag": "blade"},
        {"name": "tip_R", "xyz": mm(np.array([r_c[0], r_c[1], z_tip])), "tag": "blade"},
        {"name": "hook_c_L", "xyz": mm(np.array([l_mn[0], l_c[1], z_tip])), "tag": "hook_c"},
        {"name": "hook_c_R", "xyz": mm(np.array([r_mx[0], r_c[1], z_tip])), "tag": "hook_c"},
        {
            "name": "hook_o_L",
            "xyz": mm(np.array([l_mn[0] - open_extra_mm / 1000.0, l_c[1], z_tip])),
            "tag": "hook_o",
        },
        {
            "name": "hook_o_R",
            "xyz": mm(np.array([r_mx[0] + open_extra_mm / 1000.0, r_c[1], z_tip])),
            "tag": "hook_o",
        },
    ]

    return {
        "units": "mm",
        "lens": mm(lens_m),
        "look": [round(float(x), 6) for x in look],
        "right": [round(float(x), 6) for x in right],
        "up": [round(float(x), 6) for x in up],
        "samples": samples,
        "source": {
            "camera_stl": str(paths["camera"]),
            "tip_l_stl": str(paths["tip_l"]),
            "tip_r_stl": str(paths["tip_r"]),
            "camera_aabb_m": {"min": c_mn.tolist(), "max": c_mx.tolist()},
            "tip_l_aabb_m": {"min": l_mn.tolist(), "max": l_mx.tolist()},
            "tip_r_aabb_m": {"min": r_mn.tolist(), "max": r_mx.tolist()},
            "method": "AABB heuristic: lens=cam +Z face center; look→tip mid; samples from tip AABB",
        },
    }


def _fmt_flow_list(vals: list[float], *, ndigits: int = 4) -> str:
    parts = []
    for x in vals:
        fx = float(x)
        s = f"{fx:.{ndigits}f}".rstrip("0").rstrip(".")
        if s == "-0":
            s = "0"
        if "." not in s:
            s = f"{fx:.{ndigits}f}"
        parts.append(s)
    return "[" + ", ".join(parts) + "]"


def _fmt_sample_line(s: dict[str, Any], indent: str = "        ") -> str:
    xyz = _fmt_flow_list([float(x) for x in s["xyz"]], ndigits=3)
    name = s.get("name", "")
    tag = s.get("tag", "")
    return f"{indent}- {{ name: {name}, xyz: {xyz}, tag: {tag} }}"


def _split_arm_camera_block(arm_body: str) -> tuple[str, str, str, str]:
    """Return (before, camera_header_line, camera_body, after)."""
    m = re.search(r"^(?P<ind>[ \t]*)camera:\s*\n", arm_body, re.M)
    if not m:
        raise KeyError("no camera: block in arm")
    ind = m.group("ind")
    ind_len = len(ind)
    start = m.end()
    lines = arm_body[start:].splitlines(keepends=True)
    body_lines: list[str] = []
    rest_i = len(lines)
    for i, line in enumerate(lines):
        if not line.strip():
            body_lines.append(line)
            continue
        # Dedent to sibling of camera (same or less indent) ends the block
        lead = len(line) - len(line.lstrip(" \t"))
        if lead <= ind_len and not line.lstrip().startswith("#"):
            rest_i = i
            break
        body_lines.append(line)
    before = arm_body[: m.start()]
    header = m.group(0)
    body = "".join(body_lines)
    after = "".join(lines[rest_i:])
    return before, header, body, after


def patch_arm_camera_yaml(text: str, arm_id: str, patch: dict[str, Any]) -> str:
    """Rewrite lens/look/right/up/samples under arms[id].camera; preserve other keys/comments."""
    arm_pat = re.compile(
        rf"(^[ \t]*- id:\s*{re.escape(arm_id)}\s*\n)(.*?)(?=^[ \t]*- id:\s|\nagents:|\Z)",
        re.M | re.S,
    )
    m = arm_pat.search(text)
    if not m:
        raise KeyError(f"arm id {arm_id!r} not found in YAML")
    arm_head, arm_body = m.group(1), m.group(2)
    before, cam_header, cam_body, after = _split_arm_camera_block(arm_body)

    def repl_vec(body: str, key: str, vals: list[float] | None) -> str:
        if vals is None:
            return body
        nd = 6 if key in ("look", "right", "up") else 3
        line = _fmt_flow_list(vals, ndigits=nd)
        new_body, n = re.subn(
            rf"(^[ \t]*{key}:\s*).*$",
            rf"\g<1>{line}",
            body,
            count=1,
            flags=re.M,
        )
        if n == 0:
            new_body = re.sub(
                rf"(^[ \t]*units:\s*.*\n)",
                rf"\1      {key}: {line}\n",
                body,
                count=1,
                flags=re.M,
            )
            if new_body == body:
                new_body = body + f"      {key}: {line}\n"
        return new_body

    cam_body = repl_vec(cam_body, "lens", patch.get("lens"))
    cam_body = repl_vec(cam_body, "look", patch.get("look"))
    cam_body = repl_vec(cam_body, "right", patch.get("right"))
    if patch.get("up") is not None:
        cam_body = repl_vec(cam_body, "up", patch.get("up"))

    samples = patch.get("samples")
    if samples is not None:
        sample_block = "      samples:\n" + "\n".join(_fmt_sample_line(s) for s in samples) + "\n"
        if re.search(r"^[ \t]*samples:\s*$", cam_body, re.M):
            cam_body, n = re.subn(
                r"(^[ \t]*samples:\s*\n)(?:^[ \t]*- .*\n)+",
                sample_block,
                cam_body,
                count=1,
                flags=re.M,
            )
            if n == 0:
                raise ValueError("failed to replace samples: list")
        else:
            cam_body = re.sub(
                r"(^[ \t]*(?:footprint_depths_mm|notes):)",
                sample_block + r"\1",
                cam_body,
                count=1,
                flags=re.M,
            )

    note = "Synced from EOAT STL AABB heuristic; UI may still override modes/optics."
    if re.search(r"^[ \t]*notes:", cam_body, re.M):
        cam_body = re.sub(
            r"(^[ \t]*notes:\s*).*$",
            rf'\1"{note}"',
            cam_body,
            count=1,
            flags=re.M,
        )

    new_arm_body = before + cam_header + cam_body + after
    return text[: m.start()] + arm_head + new_arm_body + text[m.end() :]


def write_arm_camera_to_config(
    config_path: Path,
    arm_id: str,
    patch: dict[str, Any],
) -> Path:
    """Patch YAML on disk; return path written."""
    path = Path(config_path)
    text = path.read_text(encoding="utf-8")
    new_text = patch_arm_camera_yaml(text, arm_id, patch)
    # Validate still parses
    raw = yaml.safe_load(new_text)
    if not isinstance(raw, dict):
        raise ValueError("patched YAML root is not a mapping")
    arms = raw.get("arms") or []
    hit = next((a for a in arms if isinstance(a, dict) and a.get("id") == arm_id), None)
    if not hit or not isinstance(hit.get("camera"), dict):
        raise ValueError("patched YAML missing arm camera")
    path.write_text(new_text, encoding="utf-8", newline="\n")
    return path
