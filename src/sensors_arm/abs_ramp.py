"""Joint-space absolute send with timed interpolation (ported from sensors-dcs).

Timing: ``T = clamp(d / v_norm, t_min, t_max)`` then α(u) along path
(default jerk-limited seven-segment). See sensors-dcs docs/jerk-seven-segment.md.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any, Callable

from sensors_arm.agents.arm_agent import ArmAgent
from sensors_arm.agents.arm_write_agent import ArmWriteAgent
from sensors_arm.agents.base import BaseAgent


def joints6_from_ring(agent: BaseAgent, *, prefer_key: str = "joints_rad") -> list[float] | None:
    fr = agent.ring.latest.get()
    if fr is None:
        return None
    raw = fr.payload.get(prefer_key)
    if not isinstance(raw, (list, tuple)) or len(raw) < 6:
        raw = fr.payload.get("feedback_joints_rad") or fr.payload.get("joints_rad")
    if not isinstance(raw, (list, tuple)) or len(raw) < 6:
        return None
    try:
        out = [float(raw[i]) for i in range(6)]
    except (TypeError, ValueError):
        return None
    if any(not math.isfinite(x) for x in out):
        return None
    return out


def delta_max_joint(qa: list[float], qg: list[float]) -> tuple[float, int]:
    best_i = 0
    best_d = 0.0
    for i in range(6):
        d = abs(float(qg[i]) - float(qa[i]))
        if d > best_d:
            best_d = d
            best_i = i
    return best_d, best_i


def s_curve_alpha(u: float) -> float:
    u = max(0.0, min(1.0, float(u)))
    return 0.5 * (1.0 - math.cos(math.pi * u))


def clamp_seven_segment_fracs(
    jerk_seg_frac: float,
    accel_seg_frac: float,
) -> tuple[float, float, float]:
    tj = max(0.02, min(0.22, float(jerk_seg_frac)))
    ta = max(0.0, min(0.30, float(accel_seg_frac)))
    need = 4.0 * tj + 2.0 * ta
    if need > 1.0 - 1e-9:
        scale = (1.0 - 1e-6) / need
        tj *= scale
        ta *= scale
    tv = max(0.0, 1.0 - 4.0 * tj - 2.0 * ta)
    return tj, ta, tv


def seven_segment_alpha(
    u: float,
    *,
    jerk_seg_frac: float = 0.10,
    accel_seg_frac: float = 0.15,
) -> float:
    u = max(0.0, min(1.0, float(u)))
    if u <= 0.0:
        return 0.0
    if u >= 1.0:
        return 1.0
    tj, ta, tv = clamp_seven_segment_fracs(jerk_seg_frac, accel_seg_frac)
    segs: list[tuple[float, float]] = [
        (tj, 1.0),
        (ta, 0.0),
        (tj, -1.0),
        (tv, 0.0),
        (tj, -1.0),
        (ta, 0.0),
        (tj, 1.0),
    ]

    def _integrate(t_query: float) -> float:
        a = 0.0
        v = 0.0
        p = 0.0
        t_left = float(t_query)
        for dur, j in segs:
            if dur <= 0.0:
                continue
            if t_left <= 0.0:
                break
            dt = dur if t_left >= dur else t_left
            p = p + v * dt + 0.5 * a * dt * dt + (1.0 / 6.0) * j * dt * dt * dt
            v = v + a * dt + 0.5 * j * dt * dt
            a = a + j * dt
            t_left -= dt
        return p

    p_end = _integrate(1.0)
    if abs(p_end) < 1e-18:
        return u
    return max(0.0, min(1.0, _integrate(u) / p_end))


def path_alpha(
    u: float,
    *,
    profile: str = "linear",
    jerk_seg_frac: float = 0.10,
    accel_seg_frac: float = 0.15,
) -> float:
    u = max(0.0, min(1.0, float(u)))
    prof = str(profile or "linear").strip().lower()
    if prof == "seven_segment":
        return seven_segment_alpha(
            u, jerk_seg_frac=jerk_seg_frac, accel_seg_frac=accel_seg_frac
        )
    if prof == "cosine":
        return s_curve_alpha(u)
    return u


def interp_path(
    qa: list[float],
    qg: list[float],
    n: int,
    *,
    profile: str = "linear",
    jerk_seg_frac: float = 0.10,
    accel_seg_frac: float = 0.15,
) -> list[list[float]]:
    n = max(1, int(n))
    out: list[list[float]] = []
    for k in range(1, n + 1):
        a = path_alpha(
            k / n,
            profile=profile,
            jerk_seg_frac=jerk_seg_frac,
            accel_seg_frac=accel_seg_frac,
        )
        out.append([float(qa[i]) + a * (float(qg[i]) - float(qa[i])) for i in range(6)])
    return out


def path_peak_step(qa: list[float], path: list[list[float]]) -> float:
    prev = qa
    peak = 0.0
    for qk in path:
        step = max(abs(float(qk[i]) - float(prev[i])) for i in range(6))
        if step > peak:
            peak = step
        prev = qk
    return peak


def abs_move_duration_s(
    *,
    d_rad: float,
    v_norm_rad_s: float,
    t_min_s: float,
    t_max_s: float,
) -> float:
    t_min = max(0.1, min(30.0, float(t_min_s)))
    t_max = max(0.1, min(30.0, float(t_max_s)))
    if t_min > t_max:
        t_min, t_max = t_max, t_min
    v = float(v_norm_rad_s)
    if not math.isfinite(v) or v <= 0:
        v = 0.02
    d = max(0.0, float(d_rad))
    if d < 1e-9:
        return t_min
    return max(t_min, min(t_max, d / v))


class AbsRampController:
    """Owns one absolute joint ramp thread (DCS arm_abs_ramp, no gripper/gello)."""

    def __init__(self, *, default_params: dict[str, Any] | None = None) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._process_stop: Callable[[], bool] | None = None
        self._defaults = {
            "t_min_s": 0.1,
            "t_max_s": 30.0,
            "v_norm_rad_s": 0.02,
            "profile": "seven_segment",
            "jerk_seg_frac": 0.10,
            "accel_seg_frac": 0.15,
            "ramp_hz": 20.0,
        }
        if default_params:
            self._defaults.update(default_params)
        self._enabled = False
        self._phase = "idle"
        self._index = 0
        self._n = 0
        self._duration_s = 0.0
        self._hz = 20.0
        self._arm_id: str | None = None
        self._writer_id: str | None = None
        self._last_ok: bool | None = None
        self._last_error: str | None = None
        self._message: str | None = None
        self._write_count = 0
        self._last_t_wall: float | None = None
        self._target: list[float] | None = None
        self._timing: str | None = None
        self._delta_max: float | None = None

    def bind_process_stop(self, fn: Callable[[], bool]) -> None:
        self._process_stop = fn

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self._enabled,
                "phase": self._phase,
                "ramp_index": self._index,
                "ramp_n": self._n,
                "duration_s": self._duration_s,
                "hz": self._hz,
                "arm_agent_id": self._arm_id,
                "arm_write_agent_id": self._writer_id,
                "last_ok": self._last_ok,
                "last_error": self._last_error,
                "message": self._message,
                "write_count": self._write_count,
                "last_t_wall": self._last_t_wall,
                "target_joints": list(self._target) if self._target is not None else None,
                "timing": self._timing,
                "delta_max": self._delta_max,
                "params": dict(self._defaults),
            }

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def cancel(self, *, message: str | None = None) -> dict[str, Any]:
        self._stop.set()
        th = self._thread
        if th is not None and th.is_alive() and th is not threading.current_thread():
            th.join(timeout=2.0)
        with self._lock:
            was = self._enabled or self._phase == "ramping"
            self._enabled = False
            self._thread = None
            if was or self._phase == "ramping":
                self._phase = "idle"
                self._last_ok = True
                self._last_error = None
                self._message = message or "绝对下发已取消"
                self._last_t_wall = time.time()
        return {"ok": True, **self.status()}

    def start(
        self,
        *,
        reader: ArmAgent,
        writer: ArmWriteAgent,
        joints_rad: list[float],
        timing: str = "scale_by_d",
        duration_s: float | None = None,
        t_min_s: float | None = None,
        t_max_s: float | None = None,
        v_norm_rad_s: float | None = None,
        jerk_seg_frac: float | None = None,
        accel_seg_frac: float | None = None,
    ) -> dict[str, Any]:
        armed = bool(getattr(writer.sensor, "armed", False))
        if not armed:
            fr = writer.ring.latest.get()
            if fr is not None:
                armed = bool(fr.payload.get("armed"))
        if not armed:
            return {"ok": False, "error": "arm_write not armed; click Arm before absolute ramp"}

        try:
            q_star = [float(x) for x in joints_rad]
        except (TypeError, ValueError):
            return {"ok": False, "error": "joints_rad must be 6 floats"}
        if len(q_star) != 6 or any(not math.isfinite(x) for x in q_star):
            return {"ok": False, "error": "joints_rad must be exactly 6 finite values"}

        qa0 = joints6_from_ring(reader)
        if qa0 is None:
            return {
                "ok": False,
                "error": "no live arm read joints; refuse absolute ramp without current pose",
            }

        t_min = float(t_min_s if t_min_s is not None else self._defaults["t_min_s"])
        t_max = float(t_max_s if t_max_s is not None else self._defaults["t_max_s"])
        v_norm = float(
            v_norm_rad_s if v_norm_rad_s is not None else self._defaults["v_norm_rad_s"]
        )
        profile = str(self._defaults.get("profile") or "seven_segment")
        tj_in = (
            jerk_seg_frac
            if jerk_seg_frac is not None
            else self._defaults["jerk_seg_frac"]
        )
        ta_in = (
            accel_seg_frac
            if accel_seg_frac is not None
            else self._defaults["accel_seg_frac"]
        )
        jerk_frac, accel_frac, _tv = clamp_seven_segment_fracs(tj_in, ta_in)
        mode = str(timing or "scale_by_d").strip().lower()
        if mode not in ("scale_by_d", "fixed"):
            mode = "scale_by_d"

        dmax, ji = delta_max_joint(qa0, q_star)
        if mode == "fixed":
            dur = 10.0 if duration_s is None else float(duration_s)
            if not math.isfinite(dur):
                dur = 10.0
            dur = max(0.1, min(30.0, dur))
        else:
            dur = abs_move_duration_s(
                d_rad=dmax, v_norm_rad_s=v_norm, t_min_s=t_min, t_max_s=t_max
            )

        hz = float(self._defaults.get("ramp_hz") or 20.0)
        hz = max(0.1, hz)
        n = max(1, int(round(dur * hz)))
        path = interp_path(
            qa0,
            q_star,
            n,
            profile=profile,
            jerk_seg_frac=jerk_frac,
            accel_seg_frac=accel_frac,
        )
        peak = path_peak_step(qa0, path)
        max_delta = float(getattr(writer.sensor, "max_delta_rad", 0.0) or 0.0)
        if max_delta > 0 and peak > max_delta + 1e-12:
            need_n = max(1, int((dmax / max_delta) + 0.999999))
            scale = peak / max(dmax / n, 1e-12)
            need_n_s = max(need_n, int((scale * dmax / max_delta) + 0.999999))
            need_s = need_n_s / hz
            return {
                "ok": False,
                "error": (
                    f"ramp peak step ≈{peak:.4f} rad (joint {ji}) exceeds driver max_delta="
                    f"{max_delta:.4f} rad at {dur:g}s×{hz:g}Hz ({profile}); "
                    f"increase t_max / lower v_norm or use duration ≥{need_s:.1f}s (max 30)"
                ),
                "delta_max": dmax,
                "peak_step": peak,
                "worst_joint": ji,
                "ramp_n": n,
                "duration_s": dur,
            }

        self._stop.set()
        th_old = self._thread
        if th_old is not None and th_old.is_alive():
            th_old.join(timeout=2.0)

        with self._lock:
            self._enabled = True
            self._phase = "ramping"
            self._index = 0
            self._n = n
            self._duration_s = dur
            self._hz = hz
            self._arm_id = reader.agent_id
            self._writer_id = writer.agent_id
            self._last_ok = None
            self._last_error = None
            self._message = f"关节斜坡开始：{dur:g}s @ {hz:g}Hz × {n} 点 ({mode}, {profile})"
            self._write_count = 0
            self._last_t_wall = time.time()
            self._target = list(q_star)
            self._timing = mode
            self._delta_max = dmax

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="arm-abs-ramp",
            args=(
                reader,
                writer,
                list(qa0),
                list(q_star),
                n,
                hz,
                profile,
                jerk_frac,
                accel_frac,
            ),
            daemon=True,
        )
        self._thread.start()
        return {
            "ok": True,
            "t_min_s": t_min,
            "t_max_s": t_max,
            "v_norm_rad_s": v_norm,
            "jerk_seg_frac": jerk_frac,
            "accel_seg_frac": accel_frac,
            "timing": mode,
            "delta_max": dmax,
            "peak_step": peak,
            **self.status(),
        }

    def _loop(
        self,
        reader: ArmAgent,
        writer: ArmWriteAgent,
        qa0: list[float],
        q_star: list[float],
        n: int,
        hz: float,
        profile: str,
        jerk_seg_frac: float,
        accel_seg_frac: float,
    ) -> None:
        period = 1.0 / max(0.1, float(hz))
        path = interp_path(
            qa0,
            q_star,
            n,
            profile=profile,
            jerk_seg_frac=jerk_seg_frac,
            accel_seg_frac=accel_seg_frac,
        )
        final_error: str | None = None
        final_message: str | None = None
        completed = False
        try:
            next_t = time.perf_counter()
            for k, qk in enumerate(path, start=1):
                if self._stop.is_set() or (self._process_stop and self._process_stop()):
                    final_message = "绝对下发已取消"
                    break
                ref = joints6_from_ring(reader) or (path[k - 2] if k >= 2 else qa0)
                result = writer.command(joints_rad=list(qk), reference_joints_rad=list(ref))
                with self._lock:
                    self._index = k
                    self._write_count += 1
                    self._last_ok = bool(result.get("ok"))
                    self._last_error = result.get("error")
                    self._last_t_wall = time.time()
                    if not result.get("ok"):
                        self._message = f"ramp write failed at {k}/{n}: {result.get('error')}"
                    else:
                        self._message = f"关节斜坡 {k}/{n}"
                if not result.get("ok"):
                    final_error = str(result.get("error") or "ramp write failed")
                    break
                next_t += period
                delay = next_t - time.perf_counter()
                if delay > 0:
                    self._stop.wait(delay)
                else:
                    next_t = time.perf_counter()
            else:
                completed = True
                final_message = f"绝对下发完成：{n} 点已写入（关节空间/{profile}）"
        except Exception as e:  # noqa: BLE001
            final_error = f"abs ramp exception: {e}"

        with self._lock:
            self._enabled = False
            self._thread = None
            if completed:
                self._phase = "completed"
                self._last_ok = True
                self._last_error = None
                self._message = final_message
            elif final_error:
                self._phase = "error"
                self._last_ok = False
                self._last_error = final_error
                self._message = final_error
            else:
                self._phase = "idle"
                self._last_ok = True
                self._last_error = None
                self._message = final_message or "绝对下发已取消"
            self._last_t_wall = time.time()
