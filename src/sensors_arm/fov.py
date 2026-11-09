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


def normalize_camera_units_mm(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with lens/samples in mm (direction vectors unchanged)."""
    work = dict(cfg)
    if str(work.get("units") or "mm").lower() != "m":
        work["units"] = work.get("units") or "mm"
        return work
    work["lens"] = [float(x) * 1000.0 for x in work["lens"]]
    work["samples"] = [
        {**s, "xyz": [float(x) * 1000.0 for x in s["xyz"]]}
        for s in work["samples"]
    ]
    work["units"] = "mm"
    return work


def write_report_md(
    result: dict[str, Any],
    *,
    arm_id: str = "",
    label: str = "",
    cfg: dict[str, Any] | None = None,
) -> str:
    """Markdown evaluation report (Chinese headings for operators)."""
    cfg = cfg or {}
    lines = [
        "# 腕部相机视场校验报告",
        "",
        f"- 工位: `{label or arm_id or '—'}`",
        f"- 相机: `{result.get('camera_model') or cfg.get('camera_model') or '—'}`",
        f"- 坐标系: {result.get('frame') or cfg.get('frame') or '—'}",
        f"- 单位: {result.get('units') or 'mm'}",
        f"- 推荐档: **{result.get('recommend_mode') or '—'}**",
        f"- LENS: `{np.round(result['lens'], 3).tolist()}`",
        f"- look: `{np.round(result['look'], 4).tolist()}`",
        f"- right: `{np.round(result['right'], 4).tolist()}`",
        "",
        "## 结论摘要",
        "",
    ]
    modes = result.get("modes") or []
    if modes:
        best = next((m for m in modes if m.get("recommend")), modes[0])
        lines.append(
            f"推荐使用档位 `{best['id']}`"
            f"（H×V = {best['H_deg']:.1f}°×{best['V_deg']:.1f}°，"
            f"入画 {best['in_count']}/{best['n']}）。"
        )
        outs = [
            p["name"]
            for p in result.get("points") or []
            if not (p.get("in_fov") or {}).get(best["id"], False)
        ]
        if outs:
            lines.append(f"出画点: {', '.join(outs)}。")
        else:
            lines.append("全部采样点均在推荐档视场内。")
    lines += [
        "",
        "## 档位对比",
        "",
        "| id | 分辨率 | H×V (°) | 入画 | 开口钩 H 裕量 | 推荐 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for m in modes:
        res = ""
        if m.get("width") and m.get("height"):
            res = f"{m['width']}×{m['height']}"
        marg = m.get("open_hook_h_margin_deg")
        marg_s = f"{marg:.1f}°" if marg is not None else "—"
        lines.append(
            f"| {m['id']} | {res or '—'} | {m['H_deg']:.1f}×{m['V_deg']:.1f} | "
            f"{m['in_count']}/{m['n']} | {marg_s} | "
            f"{'★' if m.get('recommend') else ''} |"
        )
    lines += [
        "",
        "## 采样点",
        "",
        "| name | tag | d (mm) | az (°) | el (°) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for p in result.get("points") or []:
        lines.append(
            f"| {p.get('name','')} | {p.get('tag','')} | {p['d_mm']:.1f} | "
            f"{p['az_deg']:.2f} | {p['el_deg']:.2f} |"
        )
    lines += [
        "",
        "## 示意图",
        "",
        "- `figures/fov_angular_compare.png` — 各档 FOV 角域框 vs 特征点 (az/el)",
        "- `figures/fov_side_wedge.png` — 推荐档侧视楔形与深度",
        "- `figures/fov_coverage_bars.png` — 各档入画数量条形图",
        "",
        "## 备注",
        "",
        result.get("notes") or cfg.get("notes") or "（无）",
        "",
        "> 本报告为针孔几何角域评估，不含内参标定 / 畸变 / 深度精度。",
        "",
    ]
    return "\n".join(lines)


def _mpl():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon, Rectangle

    return plt, Rectangle, Polygon


def plot_angular_compare(result: dict[str, Any], path: Any) -> None:
    plt, Rectangle, _Polygon = _mpl()
    fig, ax = plt.subplots(figsize=(8.5, 5.5), dpi=140)
    colors = ["#0d6e75", "#1a7a4c", "#c45c26", "#6b4c9a", "#333"]
    for i, m in enumerate(result["modes"]):
        H, V = m["H_deg"], m["V_deg"]
        ax.add_patch(
            Rectangle(
                (-H / 2, -V / 2),
                H,
                V,
                fill=False,
                edgecolor=colors[i % len(colors)],
                lw=1.8 if m.get("recommend") else 1.2,
                linestyle="-" if m.get("recommend") else "--",
                label=f"{m['id']} {H:.0f}×{V:.0f}" + (" ★" if m.get("recommend") else ""),
            )
        )
    tag_style = {
        "blade": ("o", "#d97816", 36),
        "hook_c": ("o", "#0d6e75", 48),
        "hook_o": ("^", "#6b4c9a", 55),
        "root": ("x", "#c0392b", 60),
    }
    for p in result["points"]:
        mk, c, s = tag_style.get(p.get("tag") or "", ("o", "#666", 28))
        ax.scatter([p["az_deg"]], [p["el_deg"]], marker=mk, c=c, s=s, zorder=3)
        ax.annotate(
            p.get("name") or "",
            (p["az_deg"], p["el_deg"]),
            textcoords="offset points",
            xytext=(4, 4),
            fontsize=7,
            color="#444",
        )
    ax.axhline(0, color="#bbb", lw=0.8)
    ax.axvline(0, color="#bbb", lw=0.8)
    ax.set_aspect("equal")
    ax.set_xlabel("azimuth / °")
    ax.set_ylabel("elevation / °")
    ax.set_title("Feature points vs FOV crop boxes")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def plot_side_wedge(result: dict[str, Any], path: Any) -> None:
    """Side view in (look, up) plane: FOV elevation wedge + point depths."""
    plt, _Rectangle, Polygon = _mpl()
    modes = result.get("modes") or []
    mode = next((m for m in modes if m.get("recommend")), modes[0] if modes else None)
    if mode is None:
        return
    half_v = float(mode["half_V"])
    fig, ax = plt.subplots(figsize=(8.0, 5.2), dpi=140)
    d_max = max((p["d_mm"] for p in result["points"]), default=120.0) * 1.15
    d_max = max(d_max, 80.0)
    # wedge polygon in (depth along look, elevation offset ≈ d*tan(el))
    top = math.tan(math.radians(half_v)) * d_max
    bot = -top
    wedge = Polygon(
        [(0, 0), (d_max, bot), (d_max, top)],
        closed=True,
        facecolor=(0.05, 0.45, 0.48, 0.18),
        edgecolor="#0d6e75",
        lw=1.6,
        label=f"{mode['id']} ±{half_v:.1f}° elev",
    )
    ax.add_patch(wedge)
    for p in result["points"]:
        d = float(p["d_mm"])
        # lateral in up direction ≈ d * tan(el)
        y = d * math.tan(math.radians(float(p["el_deg"])))
        in_rec = (p.get("in_fov") or {}).get(mode["id"], False)
        ax.scatter(
            [d],
            [y],
            c=("#1a7a4c" if in_rec else "#c0392b"),
            s=42,
            zorder=3,
            marker="o" if in_rec else "x",
        )
        ax.annotate(p.get("name") or "", (d, y), textcoords="offset points", xytext=(4, 3), fontsize=7)
    ax.set_xlim(0, d_max)
    ax.set_xlabel("depth along look / mm")
    ax.set_ylabel("up-plane offset / mm")
    ax.set_title(f"Side wedge · recommended `{mode['id']}`")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(True, alpha=0.3)
    ax.set_aspect("equal", adjustable="datalim")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def plot_coverage_bars(result: dict[str, Any], path: Any) -> None:
    plt, _Rectangle, _Polygon = _mpl()
    modes = result.get("modes") or []
    if not modes:
        return
    ids = [m["id"] for m in modes]
    vals = [m["in_count"] for m in modes]
    totals = [m["n"] for m in modes]
    colors = ["#f0b429" if m.get("recommend") else "#3dd6c6" for m in modes]
    fig, ax = plt.subplots(figsize=(7.5, 4.2), dpi=140)
    bars = ax.bar(ids, vals, color=colors, edgecolor="#1a2433", width=0.55)
    for bar, v, n in zip(bars, vals, totals):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            v + 0.08,
            f"{v}/{n}",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    ax.set_ylim(0, max(totals + [1]) + 1.2)
    ax.set_ylabel("points in FOV")
    ax.set_title("Coverage by stream mode (★ = recommend)")
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def build_export_zip(
    result: dict[str, Any],
    cfg: dict[str, Any],
    *,
    arm_id: str = "",
    label: str = "",
) -> bytes:
    """Pack Markdown report + JSON + schematic PNGs into a zip (in-memory)."""
    import io
    import json
    import zipfile
    from datetime import datetime, timezone

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = f"fov_{arm_id or 'arm'}_{stamp}"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        md = write_report_md(result, arm_id=arm_id, label=label, cfg=cfg)
        zf.writestr(f"{root}/report.md", md)
        zf.writestr(
            f"{root}/fov_summary.json",
            json.dumps(result, indent=2, ensure_ascii=False),
        )
        zf.writestr(
            f"{root}/camera_input.json",
            json.dumps(cfg, indent=2, ensure_ascii=False),
        )
        # figures
        for name, plot_fn in (
            ("fov_angular_compare.png", plot_angular_compare),
            ("fov_side_wedge.png", plot_side_wedge),
            ("fov_coverage_bars.png", plot_coverage_bars),
        ):
            img = io.BytesIO()
            plot_fn(result, img)
            img.seek(0)
            zf.writestr(f"{root}/figures/{name}", img.read())
        readme = (
            "sensors-arm FOV export\n"
            f"arm={arm_id} label={label}\n"
            "Open report.md; figures/ holds schematics.\n"
        )
        zf.writestr(f"{root}/README.txt", readme)
    return buf.getvalue()
