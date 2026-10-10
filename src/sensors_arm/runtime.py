"""Lean multi-arm orchestrator (arm read/write only)."""

from __future__ import annotations

import math
import threading
import time
from typing import Any

import uvicorn

from sensors_arm.abs_ramp import AbsRampController
from sensors_arm.agents import build_agent
from sensors_arm.agents.arm_agent import ArmAgent
from sensors_arm.agents.arm_write_agent import ArmWriteAgent
from sensors_arm.agents.base import BaseAgent
from sensors_arm.arm_pose import cartesian_payload, set_tcp_xyz, xyzrpy_to_joints_rad
from sensors_arm.config import (
    ArmConfig,
    ArmModelRef,
    config_summary,
    parse_home_joints,
    resolve_model,
)
from sensors_arm.frame import Frame
from sensors_arm.paths import ensure_sensors_import

ensure_sensors_import()
from sensors import SensorManager  # noqa: E402


class VizHub:
    """Thread-safe latest snapshot; WebSocket clients poll via ``snapshot()``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: dict[str, Any] | None = None
        self._seq = 0

    def publish(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._seq += 1
            self._latest = {**payload, "_hub_seq": self._seq}

    def snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._latest) if self._latest is not None else None


class Orchestrator:
    def __init__(self, cfg: ArmConfig) -> None:
        self.cfg = cfg
        self._tcp_xyz = list(set_tcp_xyz(getattr(cfg, "tcp_xyz", None)))
        dry = cfg.dry_run
        self.manager = SensorManager.from_yaml(cfg.sensors_config, dry_run=dry)
        self.agents: dict[str, BaseAgent] = {}
        known = self.manager.ids()
        for acfg in cfg.agents:
            try:
                sensor = self.manager.get(acfg.sensor_id)
            except KeyError as e:
                raise KeyError(
                    f"agent {acfg.id!r} sensor_id={acfg.sensor_id!r} not in "
                    f"sensors_config; known={known}"
                ) from e
            self.agents[acfg.id] = build_agent(acfg, sensor)

        self._bind_agent_kinematics()
        self.hub = VizHub()
        self._stop = threading.Event()
        self._viz_thread: threading.Thread | None = None
        self._console_thread: threading.Thread | None = None
        self._server: uvicorn.Server | None = None
        self._shutdown_requested = False
        self._home_lock = threading.Lock()
        self._homes: dict[str, list[float] | None] = {}
        for arm in cfg.arms:
            hj, _ = parse_home_joints(
                arm.home_joints_rad if arm.home_joints_rad is not None else cfg.home_joints_rad,
                n=int(arm.num_joints or 6),
            )
            self._homes[arm.id] = hj
        self._sync_homes_to_agents()
        ramp_cfg = getattr(cfg, "arm_abs_ramp", None)
        self._abs_ramp = AbsRampController(
            default_params=ramp_cfg.model_dump() if ramp_cfg is not None else None
        )
        self._abs_ramp.bind_process_stop(lambda: self._stop.is_set())
        # Per-arm session: agents are started only via connect (not all at once).
        self._connected: set[str] = set()
        self._connect_lock = threading.Lock()

    def _arm_by_id(self, arm_id: str) -> ArmModelRef:
        for a in self.cfg.arms:
            if a.id == arm_id:
                return a
        raise KeyError(f"unknown arm id: {arm_id}")

    def _kin_for_arm(self, arm: ArmModelRef) -> dict[str, Any]:
        model = resolve_model(self.cfg, arm)
        tcp = arm.tcp_xyz if arm.tcp_xyz is not None else self.cfg.tcp_xyz
        return {
            "kinematics": getattr(model, "kinematics", None) or "kinematics",
            "kinematics_profile": getattr(model, "kinematics_profile", None),
            "tcp_xyz": list(tcp) if tcp is not None else None,
        }

    def _bind_agent_kinematics(self) -> None:
        """Attach per-arm FK/IK backend (CS66 → cs66_kinematics)."""
        for arm in self.cfg.arms:
            kin = self._kin_for_arm(arm)
            for aid in (arm.read_agent, arm.write_agent):
                if not aid:
                    continue
                agent = self.agents.get(aid)
                if agent is not None and hasattr(agent, "set_kinematics"):
                    agent.set_kinematics(**kin)  # type: ignore[misc]

    def _sync_homes_to_agents(self) -> None:
        for arm in self.cfg.arms:
            hj = self._homes.get(arm.id)
            reader = self.agents.get(arm.read_agent)
            if isinstance(reader, ArmAgent):
                reader.set_home_joints_rad(hj)
            if not bool(getattr(self.manager.ctx, "dry_run", False)) or hj is None:
                continue
            writer = self.agents.get(arm.write_agent) if arm.write_agent else None
            if isinstance(writer, ArmWriteAgent):
                sens = writer.sensor
                if hasattr(sens, "_last_cmd_rad"):
                    try:
                        n = int(getattr(sens, "num_joints", 6) or 6)
                        sens._last_cmd_rad = [float(x) for x in hj[:n]]
                    except Exception:  # noqa: BLE001
                        pass

    def _arm_network(self, arm: ArmModelRef) -> dict[str, Any]:
        """Read-only TCP endpoint from hik-sensors device config (not HTTP)."""
        agent = self.agents.get(arm.write_agent or "") or self.agents.get(arm.read_agent)
        sensor = getattr(agent, "sensor", None) if agent else None
        ip = getattr(sensor, "robot_ip", None)
        port = getattr(sensor, "robot_tcp_port", None)
        if not ip:
            cfg = getattr(sensor, "config", None) or {}
            if isinstance(cfg, dict):
                ip = cfg.get("robot_ip") or cfg.get("endpoint") or cfg.get("ip")
                if port is None:
                    port = cfg.get("robot_tcp_port")
        try:
            port_i = int(port) if port is not None else 54321
        except (TypeError, ValueError):
            port_i = 54321
        ip_s = str(ip).strip() if ip else None
        endpoint = f"{ip_s}:{port_i}" if ip_s else None
        return {"robot_ip": ip_s, "robot_tcp_port": port_i, "endpoint": endpoint}

    def arms_descriptor(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for arm in self.cfg.arms:
            model = resolve_model(self.cfg, arm)
            net = self._arm_network(arm)
            out.append(
                {
                    "id": arm.id,
                    "label": arm.label or arm.id,
                    "model": arm.model,
                    "brand": model.brand,
                    "product": model.product,
                    "num_joints": model.num_joints,
                    "urdf": model.urdf,
                    "joint_names": model.joint_names,
                    "joint_offset_rad": model.joint_offset_rad,
                    "joint_signs": model.joint_signs,
                    "mirror_y": model.mirror_y,
                    "backend": model.backend,
                    "kinematics": getattr(model, "kinematics", None) or "kinematics",
                    "kinematics_profile": getattr(model, "kinematics_profile", None),
                    "read_agent": arm.read_agent,
                    "write_agent": arm.write_agent,
                    "home_joints_rad": self._homes.get(arm.id),
                    "tcp_xyz": list(arm.tcp_xyz or self.cfg.tcp_xyz or self._tcp_xyz),
                    "connected": arm.id in self._connected,
                    "robot_ip": net["robot_ip"],
                    "robot_tcp_port": net["robot_tcp_port"],
                    "endpoint": net["endpoint"],
                }
            )
        return out

    def status(self) -> dict[str, Any]:
        return {
            "app": "sensors-arm",
            "config": config_summary(self.cfg),
            "arms": self.arms_descriptor(),
            "agents": {aid: a.stats() for aid, a in self.agents.items()},
            "sensors_site": self.manager.bundle.site,
            "sensors_dry_run": self.manager.ctx.dry_run,
            "arm_abs_ramp": self._abs_ramp.status(),
            "connected_arms": sorted(self._connected),
        }

    def arm_connected(self, arm_id: str) -> bool:
        return arm_id in self._connected

    def arm_connect(self, arm_id: str) -> dict[str, Any]:
        """Open read (+ write) agents for one arm. Does not touch other arms."""
        arm = self._arm_by_id(arm_id)
        with self._connect_lock:
            if arm_id in self._connected:
                return {
                    "ok": True,
                    "arm_id": arm_id,
                    "connected": True,
                    "message": "already connected",
                }
            reader = self.agents.get(arm.read_agent)
            if not isinstance(reader, ArmAgent):
                return {"ok": False, "error": f"read agent missing for {arm_id!r}", "arm_id": arm_id}
            writer = self.agents.get(arm.write_agent) if arm.write_agent else None
            if arm.write_agent and not isinstance(writer, ArmWriteAgent):
                return {"ok": False, "error": "write agent missing", "arm_id": arm_id}
            try:
                reader.start()
                if isinstance(writer, ArmWriteAgent):
                    writer.start()
            except Exception as e:  # noqa: BLE001
                try:
                    if isinstance(writer, ArmWriteAgent):
                        writer.stop(join_timeout=0.5, close_sensor=False)
                except Exception:  # noqa: BLE001
                    pass
                try:
                    reader.stop(join_timeout=0.5, close_sensor=True)
                except Exception:  # noqa: BLE001
                    pass
                return {"ok": False, "error": str(e), "arm_id": arm_id}
            self._connected.add(arm_id)
            print(f"[sensors-arm] connected {arm_id}", flush=True)
            return {
                "ok": True,
                "arm_id": arm_id,
                "connected": True,
                "message": f"已连接 {arm.label or arm_id}",
            }

    def arm_disconnect(self, arm_id: str) -> dict[str, Any]:
        """Stop agents for one arm and close its sensor. Other arms stay up."""
        arm = self._arm_by_id(arm_id)
        with self._connect_lock:
            if arm_id not in self._connected:
                return {
                    "ok": True,
                    "arm_id": arm_id,
                    "connected": False,
                    "message": "already disconnected",
                }
            try:
                ramp_st = self._abs_ramp.status()
                if self._abs_ramp.enabled and ramp_st.get("arm_agent_id") == arm.read_agent:
                    self._abs_ramp.cancel(message=f"因断开 {arm_id} 取消绝对下发")
            except Exception:  # noqa: BLE001
                pass
            writer = self.agents.get(arm.write_agent) if arm.write_agent else None
            reader = self.agents.get(arm.read_agent)
            # Writer shares sensor with reader: disarm/stop loop, reader closes sensor.
            if isinstance(writer, ArmWriteAgent):
                try:
                    writer.stop(join_timeout=1.0, close_sensor=False)
                except Exception as e:  # noqa: BLE001
                    print(f"[sensors-arm] disconnect write {arm_id}: {e}", flush=True)
                try:
                    writer.ring.clear()
                except Exception:  # noqa: BLE001
                    pass
            if isinstance(reader, ArmAgent):
                try:
                    reader.stop(join_timeout=1.0, close_sensor=True)
                except Exception as e:  # noqa: BLE001
                    print(f"[sensors-arm] disconnect read {arm_id}: {e}", flush=True)
                try:
                    reader.ring.clear()
                except Exception:  # noqa: BLE001
                    pass
            self._connected.discard(arm_id)
            print(f"[sensors-arm] disconnected {arm_id}", flush=True)
            return {
                "ok": True,
                "arm_id": arm_id,
                "connected": False,
                "message": f"已断开 {arm.label or arm_id}",
            }

    def start(self) -> None:
        # Do not auto-start arm agents — UI/API connects per arm on demand.
        self._stop.clear()
        self._viz_thread = threading.Thread(target=self._viz_loop, name="viz-sampler", daemon=True)
        self._viz_thread.start()
        self._console_thread = threading.Thread(
            target=self._console_loop, name="console", daemon=True
        )
        self._console_thread.start()

        def _warm_fk() -> None:
            try:
                from sensors_arm.arm_pose import warm_kinematics

                backends: list[tuple[str, str | None]] = []
                seen: set[str] = set()
                for arm in self.cfg.arms:
                    kin = self._kin_for_arm(arm)
                    pkg = str(kin["kinematics"])
                    prof = kin.get("kinematics_profile")
                    key = f"{pkg}:{prof or ''}"
                    if key not in seen:
                        seen.add(key)
                        backends.append((pkg, prof if isinstance(prof, str) else None))
                if not backends:
                    backends = [("kinematics", None)]
                warm_kinematics(backends)
            except Exception as e:  # noqa: BLE001
                print(f"[sensors-arm] FK warm skipped: {e}", flush=True)

        threading.Thread(target=_warm_fk, name="warm-fk", daemon=True).start()

    def stop(self, *, for_shutdown: bool = False) -> None:
        self._stop.set()
        try:
            self._abs_ramp.cancel(message="shutdown")
        except Exception:  # noqa: BLE001
            pass
        join_t = 0.25 if for_shutdown else 2.0
        if self._viz_thread and self._viz_thread.is_alive():
            self._viz_thread.join(timeout=join_t)
        if self._console_thread and self._console_thread.is_alive():
            self._console_thread.join(timeout=join_t)
        with self._connect_lock:
            connected = list(self._connected)
        for arm_id in connected:
            try:
                self.arm_disconnect(arm_id)
            except Exception:  # noqa: BLE001
                pass
        # Belts-and-suspenders: stop any leftover agents.
        writers = [a for a in self.agents.values() if isinstance(a, ArmWriteAgent)]
        readers = [a for a in self.agents.values() if a not in writers]
        for agent in writers + readers:
            try:
                if agent.running:
                    agent.stop(join_timeout=join_t, close_sensor=not for_shutdown)
            except Exception:  # noqa: BLE001
                pass
        self._connected.clear()
        if not for_shutdown:
            try:
                self.manager.close_all()
            except Exception:  # noqa: BLE001
                pass

    def request_shutdown(self) -> dict[str, Any]:
        import os

        if self._shutdown_requested:
            return {"ok": True, "message": "shutdown already requested"}
        self._shutdown_requested = True
        self._stop.set()
        print("[sensors-arm] shutdown requested", flush=True)

        def _force() -> None:
            time.sleep(1.0)
            os._exit(0)

        def _cleanup() -> None:
            try:
                self.stop(for_shutdown=True)
            except Exception as e:  # noqa: BLE001
                print(f"[sensors-arm] cleanup error: {e}", flush=True)
            os._exit(0)

        threading.Thread(target=_force, daemon=True).start()
        threading.Thread(target=_cleanup, daemon=True).start()
        return {"ok": True, "message": "shutdown requested"}

    def _frame_for_viz(self, fr: Frame) -> dict[str, Any]:
        return fr.to_dict()

    def _viz_payload(self) -> dict[str, Any]:
        frames = []
        rates: dict[str, Any] = {}
        live_agents: set[str] = set()
        for arm in self.cfg.arms:
            if arm.id not in self._connected:
                continue
            live_agents.add(arm.read_agent)
            if arm.write_agent:
                live_agents.add(arm.write_agent)
        for aid, agent in self.agents.items():
            if aid not in live_agents:
                continue
            fr = agent.ring.latest.get()
            if fr is not None:
                frames.append(self._frame_for_viz(fr))
            st = agent.stats()
            rates[aid] = {
                "hz_target": agent.hz,
                "hz_meas": st.get("hz_meas"),
                "seq": fr.seq if fr is not None else None,
            }
        return {
            "schema": "sensors_arm.viz.v1",
            "site": self.cfg.site,
            "t_wall": time.time(),
            "arms": self.arms_descriptor(),
            "rates": {"viz_hz_target": self.cfg.runtime.viz_hz, "agents": rates},
            "frames": frames,
            "dry_run": bool(self.manager.ctx.dry_run),
            "arm_abs_ramp": self._abs_ramp.status(),
            "connected_arms": sorted(self._connected),
        }

    def _viz_loop(self) -> None:
        period = 1.0 / max(1.0, float(self.cfg.runtime.viz_hz))
        next_t = time.perf_counter()
        while not self._stop.is_set():
            now = time.perf_counter()
            if now < next_t:
                time.sleep(min(0.005, next_t - now))
                continue
            next_t = max(next_t + period, time.perf_counter())
            try:
                self.hub.publish(self._viz_payload())
            except Exception:  # noqa: BLE001
                pass

    def _console_loop(self) -> None:
        period = 1.0 / max(0.5, float(self.cfg.runtime.console_hz))
        while not self._stop.wait(period):
            parts = []
            for arm in self.cfg.arms:
                if arm.id not in self._connected:
                    parts.append(f"{arm.id}:off")
                    continue
                reader = self.agents.get(arm.read_agent)
                fr = reader.ring.latest.get() if reader else None
                j = None
                if fr and isinstance(fr.payload, dict):
                    j = fr.payload.get("joints_rad")
                deg = ""
                if isinstance(j, list) and j:
                    deg = "[" + ", ".join(f"{math.degrees(float(x)):.1f}" for x in j[:6]) + "]"
                parts.append(f"{arm.id}{deg or '…'}")
            print("[sensors-arm] " + " | ".join(parts), flush=True)

    def latest_joints(self, arm_id: str) -> list[float] | None:
        arm = self._arm_by_id(arm_id)
        reader = self.agents.get(arm.read_agent)
        if not isinstance(reader, ArmAgent):
            return None
        fr = reader.ring.latest.get()
        if not fr or not isinstance(fr.payload, dict):
            return None
        j = fr.payload.get("joints_rad")
        if not isinstance(j, list):
            return None
        try:
            return [float(x) for x in j]
        except (TypeError, ValueError):
            return None

    def _resolve_rw(self, arm_id: str) -> tuple[ArmAgent, ArmWriteAgent] | dict[str, Any]:
        meta = self._arm_by_id(arm_id)
        if not meta.write_agent:
            return {"ok": False, "error": f"arm {arm_id!r} has no write_agent"}
        writer = self.agents.get(meta.write_agent)
        reader = self.agents.get(meta.read_agent)
        if not isinstance(writer, ArmWriteAgent):
            return {"ok": False, "error": "write agent missing"}
        if not isinstance(reader, ArmAgent):
            return {"ok": False, "error": "read agent missing; refuse motion without live joints"}
        return reader, writer

    def arm_command(
        self,
        arm_id: str,
        *,
        arm: bool = False,
        disarm: bool = False,
        stop: bool = False,
        joints_rad: list[float] | None = None,
        jog_joint: int | None = None,
        delta_deg: float | None = None,
        delta_rad: float | None = None,
        cancel_abs_ramp: bool = False,
        timing: str | None = None,
        duration_s: float | None = None,
        t_min_s: float | None = None,
        t_max_s: float | None = None,
        v_norm_rad_s: float | None = None,
        jerk_seg_frac: float | None = None,
        accel_seg_frac: float | None = None,
    ) -> dict[str, Any]:
        """Arm/disarm/jog; absolute ``joints_rad`` uses timed abs-ramp (DCS semantics)."""
        resolved = self._resolve_rw(arm_id)
        if isinstance(resolved, dict):
            return resolved
        reader, writer = resolved

        if cancel_abs_ramp:
            return self._abs_ramp.cancel()

        if arm_id not in self._connected:
            return {
                "ok": False,
                "error": f"arm {arm_id!r} 未连接 — 请先点「连接」",
                "connected": False,
            }

        if arm:
            if self.latest_joints(arm_id) is None:
                return {
                    "ok": False,
                    "error": "no live arm read joints yet; wait for Read before Arm",
                }
            return writer.command(arm=True)

        if disarm or stop:
            self._abs_ramp.cancel(message="因 Disarm/Estop 取消绝对下发")
            return writer.command(disarm=True, stop=True)

        if joints_rad is not None:
            mode = str(timing or "scale_by_d").strip().lower()
            # TCP-drag: one-shot write, no jerk / abs-ramp interpolation.
            if mode in ("direct", "immediate", "step"):
                if self._abs_ramp.enabled:
                    self._abs_ramp.cancel(message="因直接下发取消斜坡")
                armed = bool(getattr(writer.sensor, "armed", False))
                if not armed:
                    fr = writer.ring.latest.get()
                    if fr is not None:
                        armed = bool(fr.payload.get("armed"))
                if not armed:
                    return {
                        "ok": False,
                        "error": "arm_write not armed; click Arm before direct write",
                    }
                try:
                    q_star = [float(x) for x in joints_rad]
                except (TypeError, ValueError):
                    return {"ok": False, "error": "joints_rad must be 6 floats"}
                if len(q_star) != 6 or any(not math.isfinite(x) for x in q_star):
                    return {"ok": False, "error": "joints_rad must be exactly 6 finite values"}
                base = self.latest_joints(arm_id)
                if base is None:
                    return {
                        "ok": False,
                        "error": "no live arm read joints; refuse direct write without current pose",
                    }
                wr = writer.command(
                    joints_rad=q_star,
                    reference_joints_rad=list(base),
                )
                out = dict(wr) if isinstance(wr, dict) else {"ok": bool(wr)}
                out["timing"] = "direct"
                return out
            # New abs-send replaces any in-flight ramp (same as DCS).
            return self._abs_ramp.start(
                reader=reader,
                writer=writer,
                joints_rad=list(joints_rad),
                timing=mode if mode in ("scale_by_d", "fixed") else "scale_by_d",
                duration_s=duration_s,
                t_min_s=t_min_s,
                t_max_s=t_max_s,
                v_norm_rad_s=v_norm_rad_s,
                jerk_seg_frac=jerk_seg_frac,
                accel_seg_frac=accel_seg_frac,
            )

        if self._abs_ramp.enabled:
            return {
                "ok": False,
                "error": "absolute ramp active; cancel or wait before jog",
                **self._abs_ramp.status(),
            }

        if jog_joint is not None:
            cur = self.latest_joints(arm_id)
            if cur is None:
                return {"ok": False, "error": "no live joints for jog"}
            d = float(delta_rad) if delta_rad is not None else math.radians(float(delta_deg or 0))
            tgt = list(cur)
            ji = int(jog_joint)
            if ji < 0 or ji >= len(tgt):
                return {"ok": False, "error": "jog_joint out of range"}
            tgt[ji] = float(tgt[ji]) + d
            return writer.command(joints_rad=tgt, reference_joints_rad=cur)

        return {"ok": False, "error": "arm, disarm/stop, joints_rad, or jog_joint required"}

    def arm_home_get(self, arm_id: str) -> dict[str, Any]:
        arm = self._arm_by_id(arm_id)
        hj = self._homes.get(arm.id)
        return {
            "ok": True,
            "arm_id": arm_id,
            "configured": hj is not None,
            "home_joints_rad": hj,
            "write_agent": arm.write_agent,
        }

    def arm_home_set(self, arm_id: str, joints: list[float] | None = None) -> dict[str, Any]:
        arm = self._arm_by_id(arm_id)
        n = int(arm.num_joints or resolve_model(self.cfg, arm).num_joints)
        if joints is None:
            joints = self.latest_joints(arm_id)
        parsed, err = parse_home_joints(joints, n=n)
        if parsed is None:
            return {"ok": False, "error": err}
        with self._home_lock:
            self._homes[arm_id] = parsed
        self._sync_homes_to_agents()
        return {"ok": True, "arm_id": arm_id, "home_joints_rad": parsed}

    def arm_home_go(
        self,
        arm_id: str,
        *,
        t_min_s: float | None = None,
        t_max_s: float | None = None,
        v_norm_rad_s: float | None = None,
        jerk_seg_frac: float | None = None,
        accel_seg_frac: float | None = None,
    ) -> dict[str, Any]:
        """Home = abs-send sugar to configured home (DCS go_arm_home)."""
        st = self.arm_home_get(arm_id)
        if not st.get("configured") or not st.get("home_joints_rad"):
            return {
                "ok": False,
                "error": st.get("error") or "home_joints_rad 未配置或格式错误",
                **st,
            }
        out = self.arm_command(
            arm_id,
            joints_rad=list(st["home_joints_rad"]),
            timing="scale_by_d",
            t_min_s=t_min_s,
            t_max_s=t_max_s,
            v_norm_rad_s=v_norm_rad_s,
            jerk_seg_frac=jerk_seg_frac,
            accel_seg_frac=accel_seg_frac,
        )
        out = dict(out)
        out["home"] = self.arm_home_get(arm_id)
        return out

    def arm_ik(self, arm_id: str, xyzrpy: list[float], seed: list[float] | None = None) -> dict[str, Any]:
        arm = self._arm_by_id(arm_id)
        kin = self._kin_for_arm(arm)
        if seed is None:
            seed = self.latest_joints(arm_id)
        if seed is None:
            seed = [0.0] * int(arm.num_joints or 6)
        try:
            tcp = kin.get("tcp_xyz")
            if tcp is not None:
                set_tcp_xyz(tcp)
            result = xyzrpy_to_joints_rad(
                xyzrpy,
                q_seed_rad=seed,
                tcp_xyz=tcp,
                kinematics=kin["kinematics"],
                kinematics_profile=kin.get("kinematics_profile"),
                # Drag-friendly: multi-seed + slightly looser accept (CS66 provisional DH).
                max_nfev=800,
                accept_residual=2.0e-2,
                position_tolerance_m=5e-3,
                orientation_tolerance_rad=5e-2,
                ori_weight=0.2,
                multi_seed=True,
            )
            if not isinstance(result, dict):
                return {"ok": False, "error": "unexpected IK result"}
            if not result.get("ok", True) and result.get("joints_rad") is None:
                return {"ok": False, "error": result.get("error") or "ik failed", **result}
            joints = result.get("joints_rad")
            out = {"ok": True, **result}
            if isinstance(joints, list):
                out["cartesian"] = cartesian_payload(
                    joints,
                    tcp_xyz=tcp,
                    kinematics=kin["kinematics"],
                    kinematics_profile=kin.get("kinematics_profile"),
                )
            return out
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}
