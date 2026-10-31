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
        # UI-applied max_delta_deg overrides (survive driver config re-reads; not YAML).
        self._max_delta_deg_override: dict[str, float] = {}
        # Remote continuous teleop: browser pushes latest joints; backend writes @ fixed Hz.
        self._teleop_lock = threading.Lock()
        self._teleop_streams: dict[str, dict[str, Any]] = {}

    def _arm_by_id(self, arm_id: str) -> ArmModelRef:
        for a in self.cfg.arms:
            if a.id == arm_id:
                return a
        raise KeyError(f"unknown arm id: {arm_id}")

    def _kin_for_arm(self, arm: ArmModelRef) -> dict[str, Any]:
        model = resolve_model(self.cfg, arm)
        tcp = arm.tcp_xyz if arm.tcp_xyz is not None else self.cfg.tcp_xyz
        pkg = getattr(model, "kinematics", None) or "kinematics"
        prof = getattr(model, "kinematics_profile", None)
        supported: bool | None = None
        pkg_s = str(pkg)
        # YAML-backed CS66 packs (Cell B / Cell C)
        _cs66_mod = {
            "cs66_kinematics": "sensors.cs66_kinematics",
            "cs66": "sensors.cs66_kinematics",
            "sensors.cs66_kinematics": "sensors.cs66_kinematics",
            "cs66_kin_g26562": "sensors.cs66_kin_g26562",
            "cs66_g26562": "sensors.cs66_kin_g26562",
            "sensors.cs66_kin_g26562": "sensors.cs66_kin_g26562",
        }.get(pkg_s)
        if _cs66_mod and prof:
            try:
                import importlib

                get_profile = importlib.import_module(_cs66_mod).get_profile
                supported = bool(get_profile(str(prof)).supported)
            except Exception:  # noqa: BLE001
                supported = False
        return {
            "kinematics": pkg,
            "kinematics_profile": prof,
            "kinematics_supported": supported,
            "tcp_xyz": list(tcp) if tcp is not None else None,
        }

    def _bind_agent_kinematics(self) -> None:
        """Attach per-arm FK/IK backend (CS66 YAML packs / legacy)."""
        for arm in self.cfg.arms:
            kin = self._kin_for_arm(arm)
            bind = {
                "kinematics": kin["kinematics"],
                "kinematics_profile": kin.get("kinematics_profile"),
                "tcp_xyz": kin.get("tcp_xyz"),
            }
            for aid in (arm.read_agent, arm.write_agent):
                if not aid:
                    continue
                agent = self.agents.get(aid)
                if agent is not None and hasattr(agent, "set_kinematics"):
                    agent.set_kinematics(**bind)  # type: ignore[misc]

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
            kin = self._kin_for_arm(arm)
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
                    "gripper_rpy": list(model.gripper_rpy) if model.gripper_rpy else None,
                    "backend": model.backend,
                    "kinematics": kin["kinematics"],
                    "kinematics_profile": kin.get("kinematics_profile"),
                    "kinematics_supported": kin.get("kinematics_supported"),
                    "read_agent": arm.read_agent,
                    "write_agent": arm.write_agent,
                    "home_joints_rad": self._homes.get(arm.id),
                    "tcp_xyz": list(arm.tcp_xyz or self.cfg.tcp_xyz or self._tcp_xyz),
                    "connected": arm.id in self._connected,
                    "robot_ip": net["robot_ip"],
                    "robot_tcp_port": net["robot_tcp_port"],
                    "endpoint": net["endpoint"],
                    "max_delta_deg": self.arm_max_delta_get(arm.id).get("max_delta_deg"),
                }
            )
        return out

    def _write_sensor_for_arm(self, arm_id: str) -> Any:
        arm = self._arm_by_id(arm_id)
        writer = self.agents.get(arm.write_agent or "") if arm.write_agent else None
        if writer is None:
            raise KeyError(f"arm {arm_id} has no write_agent")
        sens = getattr(writer, "sensor", None)
        if sens is None:
            raise RuntimeError(f"arm {arm_id} write agent has no sensor")
        return sens

    def _apply_max_delta_to_sensor(self, sens: Any, deg: float) -> None:
        """Push degrees into driver attribute + mutable config dict."""
        rad = abs(math.radians(float(deg)))
        if hasattr(sens, "max_delta_rad"):
            sens.max_delta_rad = rad
        cfg = getattr(sens, "config", None)
        if isinstance(cfg, dict):
            cfg["max_delta_deg"] = float(deg)

    def arm_max_delta_get(self, arm_id: str) -> dict[str, Any]:
        """Per-arm joint command guard: max |Δq| in degrees (driver max_delta_deg)."""
        arm = self._arm_by_id(arm_id)
        try:
            sens = self._write_sensor_for_arm(arm_id)
        except (KeyError, RuntimeError) as e:
            return {"ok": False, "arm_id": arm_id, "error": str(e), "max_delta_deg": None}
        # Prefer UI override, then keep sensor attribute in sync with it.
        if arm_id in self._max_delta_deg_override:
            deg = float(self._max_delta_deg_override[arm_id])
            try:
                self._apply_max_delta_to_sensor(sens, deg)
            except Exception:  # noqa: BLE001
                pass
        else:
            rad = getattr(sens, "max_delta_rad", None)
            if rad is None:
                cfg = getattr(sens, "config", None) or {}
                try:
                    deg = float(cfg.get("max_delta_deg")) if isinstance(cfg, dict) else None
                except (TypeError, ValueError):
                    deg = None
            else:
                deg = float(math.degrees(float(rad)))
        if deg is not None and math.isfinite(deg):
            deg = round(float(deg), 4)
        return {
            "ok": True,
            "arm_id": arm_id,
            "label": arm.label or arm_id,
            "max_delta_deg": deg,
        }

    def arm_max_delta_set(self, arm_id: str, max_delta_deg: float) -> dict[str, Any]:
        """Update runtime max_delta on the write driver (does not rewrite YAML)."""
        try:
            deg = float(max_delta_deg)
        except (TypeError, ValueError):
            return {"ok": False, "arm_id": arm_id, "error": "max_delta_deg must be a number"}
        if not math.isfinite(deg) or deg <= 0:
            return {"ok": False, "arm_id": arm_id, "error": "max_delta_deg must be > 0"}
        if deg > 180.0:
            return {"ok": False, "arm_id": arm_id, "error": "max_delta_deg must be ≤ 180°"}
        try:
            sens = self._write_sensor_for_arm(arm_id)
        except (KeyError, RuntimeError) as e:
            return {"ok": False, "arm_id": arm_id, "error": str(e)}
        if not hasattr(sens, "max_delta_rad"):
            return {
                "ok": False,
                "arm_id": arm_id,
                "error": "write sensor does not support max_delta_rad",
            }
        deg = round(abs(deg), 4)
        self._max_delta_deg_override[arm_id] = deg
        self._apply_max_delta_to_sensor(sens, deg)
        return self.arm_max_delta_get(arm_id)

    def status(self) -> dict[str, Any]:
        return {
            "app": "sensors-arm",
            "config": config_summary(self.cfg),
            "arms": self.arms_descriptor(),
            "agents": {aid: a.stats() for aid, a in self.agents.items()},
            "sensors_site": self.manager.bundle.site,
            "sensors_dry_run": self.manager.ctx.dry_run,
            "arm_abs_ramp": self._abs_ramp.status(),
            "teleop_stream": self.teleop_stream_status(),
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
            # Re-apply UI maxΔ after open() — drivers may rebuild from YAML 15°.
            if arm_id in self._max_delta_deg_override and isinstance(writer, ArmWriteAgent):
                try:
                    self._apply_max_delta_to_sensor(
                        writer.sensor, self._max_delta_deg_override[arm_id]
                    )
                except Exception:  # noqa: BLE001
                    pass
            self._connected.add(arm_id)
            print(f"[sensors-arm] connected {arm_id}", flush=True)
            return {
                "ok": True,
                "arm_id": arm_id,
                "connected": True,
                "message": f"已连接 {arm.label or arm_id}",
                "max_delta_deg": self.arm_max_delta_get(arm_id).get("max_delta_deg"),
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
            try:
                self.teleop_stream_stop(arm_id, message=f"因断开 {arm_id} 停止连续下发")
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
                print(
                    f"[sensors-arm] FK/IK warm done ({len(backends)} backend(s))",
                    flush=True,
                )
            except Exception as e:  # noqa: BLE001
                print(f"[sensors-arm] FK/IK warm skipped: {e}", flush=True)

        threading.Thread(target=_warm_fk, name="warm-fk-ik", daemon=True).start()

    def stop(self, *, for_shutdown: bool = False) -> None:
        self._stop.set()
        try:
            self._abs_ramp.cancel(message="shutdown")
        except Exception:  # noqa: BLE001
            pass
        try:
            self.teleop_stream_stop_all(message="shutdown")
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
            "teleop_stream": self.teleop_stream_status(),
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

    def latest_joints(
        self, arm_id: str, *, require_measured: bool | None = None
    ) -> list[float] | None:
        """Return latest reader joints.

        When ``require_measured`` is True (default on live / non-dry_run), reject
        synth / command-only poses so Arm/jog cannot seed from YAML home.
        """
        arm = self._arm_by_id(arm_id)
        reader = self.agents.get(arm.read_agent)
        if not isinstance(reader, ArmAgent):
            return None
        fr = reader.ring.latest.get()
        if not fr or not isinstance(fr.payload, dict):
            return None
        need_measured = (
            bool(require_measured)
            if require_measured is not None
            else (not bool(getattr(self.manager.ctx, "dry_run", False)))
        )
        if need_measured:
            if fr.payload.get("synth"):
                return None
            if fr.payload.get("measured") is False:
                return None
            source = str(fr.payload.get("joints_source") or "")
            if source in ("synth", "command", "none"):
                return None
            # source ""/"unknown": allow only when explicitly measured (EC monitor).
            if source in ("", "unknown") and not fr.payload.get("measured"):
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

    @staticmethod
    def _is_cs_arm_write(sensor: Any) -> bool:
        kind_v = getattr(getattr(sensor, "kind", None), "value", None)
        kind_s = str(
            kind_v if kind_v is not None else getattr(sensor, "kind", "") or ""
        )
        return kind_s == "arm_cs_write"

    def _writer_armed(self, writer: ArmWriteAgent) -> bool:
        armed = bool(getattr(writer.sensor, "armed", False))
        if not armed:
            fr = writer.ring.latest.get()
            if fr is not None:
                armed = bool(fr.payload.get("armed"))
        return armed

    def teleop_stream_status(self, arm_id: str | None = None) -> dict[str, Any]:
        """Snapshot of backend fixed-Hz teleop write stream(s)."""
        with self._teleop_lock:
            if arm_id is not None:
                st = self._teleop_streams.get(arm_id)
                if st is None:
                    return {
                        "arm_id": arm_id,
                        "enabled": False,
                        "hz": 100.0,
                        "write_path": None,
                    }
                return {
                    "arm_id": arm_id,
                    "enabled": bool(st.get("enabled")),
                    "hz": float(st.get("hz") or 100.0),
                    "write_path": st.get("write_path"),
                    "write_count": int(st.get("write_count") or 0),
                    "last_ok": st.get("last_ok"),
                    "last_error": st.get("last_error"),
                    "message": st.get("message"),
                    "last_t_wall": st.get("last_t_wall"),
                    "has_setpoint": st.get("setpoint") is not None,
                }
            return {
                aid: {
                    "enabled": bool(st.get("enabled")),
                    "hz": float(st.get("hz") or 100.0),
                    "write_path": st.get("write_path"),
                    "write_count": int(st.get("write_count") or 0),
                    "last_ok": st.get("last_ok"),
                    "last_error": st.get("last_error"),
                    "message": st.get("message"),
                    "last_t_wall": st.get("last_t_wall"),
                    "has_setpoint": st.get("setpoint") is not None,
                }
                for aid, st in self._teleop_streams.items()
            }

    def teleop_stream_stop(
        self, arm_id: str, *, message: str | None = None
    ) -> dict[str, Any]:
        """Stop the fixed-Hz write thread for one arm (keeps ExternalControl armed)."""
        with self._teleop_lock:
            st = self._teleop_streams.get(arm_id)
            th = st.get("thread") if isinstance(st, dict) else None
            stop_ev = st.get("stop") if isinstance(st, dict) else None
            if isinstance(stop_ev, threading.Event):
                stop_ev.set()
            if isinstance(st, dict):
                st["enabled"] = False
                if message:
                    st["message"] = message
                st["last_t_wall"] = time.time()
        if th is not None and th.is_alive() and th is not threading.current_thread():
            th.join(timeout=2.0)
        with self._teleop_lock:
            st = self._teleop_streams.get(arm_id)
            if isinstance(st, dict):
                st["thread"] = None
                st["enabled"] = False
                if message and not st.get("message"):
                    st["message"] = message
        return {"ok": True, **self.teleop_stream_status(arm_id)}

    def teleop_stream_stop_all(self, *, message: str | None = None) -> None:
        with self._teleop_lock:
            ids = list(self._teleop_streams.keys())
        for aid in ids:
            self.teleop_stream_stop(aid, message=message)

    def teleop_stream_setpoint(
        self, arm_id: str, joints_rad: list[float]
    ) -> dict[str, Any]:
        """Latest-wins setpoint for the backend write thread (does not write itself)."""
        try:
            q = [float(x) for x in joints_rad]
        except (TypeError, ValueError):
            return {"ok": False, "error": "joints_rad must be 6 floats"}
        if len(q) != 6 or any(not math.isfinite(x) for x in q):
            return {"ok": False, "error": "joints_rad must be exactly 6 finite values"}
        with self._teleop_lock:
            st = self._teleop_streams.get(arm_id)
            if not st or not st.get("enabled"):
                enabled = False
                last_err = (st or {}).get("last_error") if isinstance(st, dict) else None
            else:
                st["setpoint"] = q
                st["last_t_wall"] = time.time()
                enabled = True
                last_err = st.get("last_error")
        snap = self.teleop_stream_status(arm_id)
        if not enabled:
            return {
                "ok": False,
                "error": last_err or "teleop stream not enabled; start continuous send first",
                **snap,
            }
        return {"ok": True, "arm_id": arm_id, **snap}

    def teleop_stream_set(
        self,
        arm_id: str,
        *,
        enabled: bool,
        joints_rad: list[float] | None = None,
        hz: float | None = None,
    ) -> dict[str, Any]:
        """Start/stop backend fixed-Hz latest-wins teleop write (remote continuous)."""
        if not enabled:
            return self.teleop_stream_stop(
                arm_id, message="已停止远程连续下发；ExternalControl 由 keepalive idle 保活"
            )

        resolved = self._resolve_rw(arm_id)
        if isinstance(resolved, dict):
            return resolved
        _reader, writer = resolved

        if arm_id not in self._connected:
            return {
                "ok": False,
                "error": f"arm {arm_id!r} 未连接 — 请先点「连接」",
                "connected": False,
            }
        if not self._writer_armed(writer):
            return {
                "ok": False,
                "error": "arm_write not armed; click Arm before continuous teleop",
            }

        # Teleop stream wins over abs-ramp.
        if self._abs_ramp.enabled:
            self._abs_ramp.cancel(message="因远程连续下发取消斜坡")

        write_hz = max(1.0, min(125.0, float(hz if hz is not None else 100.0)))
        cs_dense = self._is_cs_arm_write(writer.sensor)
        write_path = "cs_servoj_once" if cs_dense else "ec_tt"

        seed: list[float] | None = None
        if joints_rad is not None:
            try:
                seed = [float(x) for x in joints_rad]
            except (TypeError, ValueError):
                return {"ok": False, "error": "joints_rad must be 6 floats"}
            if len(seed) != 6 or any(not math.isfinite(x) for x in seed):
                return {"ok": False, "error": "joints_rad must be exactly 6 finite values"}

        # Restart cleanly if already running.
        self.teleop_stream_stop(arm_id)

        stop_ev = threading.Event()
        st: dict[str, Any] = {
            "enabled": True,
            "stop": stop_ev,
            "thread": None,
            "setpoint": seed,
            "hz": write_hz,
            "write_path": write_path,
            "write_count": 0,
            "last_ok": None,
            "last_error": None,
            "message": f"远程连续下发中 · {write_hz:g} Hz · {write_path}",
            "last_t_wall": time.time(),
            "fail_streak": 0,
        }
        with self._teleop_lock:
            self._teleop_streams[arm_id] = st

        th = threading.Thread(
            target=self._teleop_stream_loop,
            name=f"teleop-stream-{arm_id}",
            daemon=True,
            args=(arm_id,),
        )
        with self._teleop_lock:
            st["thread"] = th
        th.start()
        return {"ok": True, **self.teleop_stream_status(arm_id)}

    def _teleop_stream_loop(self, arm_id: str) -> None:
        """Fixed-Hz write of latest setpoint; decoupled from browser HTTP RTT."""
        fail_max = 5
        final_error: str | None = None
        final_message: str | None = None
        try:
            while not self._stop.is_set():
                with self._teleop_lock:
                    st = self._teleop_streams.get(arm_id)
                    if not st or not st.get("enabled"):
                        break
                    stop_ev: threading.Event = st["stop"]
                    hz = float(st.get("hz") or 100.0)
                    q = st.get("setpoint")
                    write_path = st.get("write_path")
                if stop_ev.is_set():
                    break

                period = 1.0 / max(1.0, hz)
                if q is None:
                    stop_ev.wait(period)
                    continue

                resolved = self._resolve_rw(arm_id)
                if isinstance(resolved, dict):
                    final_error = str(resolved.get("error") or "teleop agents missing")
                    break
                _reader, writer = resolved
                if arm_id not in self._connected or not self._writer_armed(writer):
                    final_error = "连接/Arm 已断开，已停止远程连续下发"
                    break

                if write_path == "cs_servoj_once" or self._is_cs_arm_write(writer.sensor):
                    result = writer.command(
                        joints_rad=list(q),
                        servoj_once=True,
                        relative_to_last=True,
                        idle_after=False,
                    )
                else:
                    base = self.latest_joints(arm_id, require_measured=True)
                    ref = list(base) if base is not None else list(q)
                    result = writer.command(
                        joints_rad=list(q),
                        reference_joints_rad=ref,
                    )
                ok = bool(result.get("ok")) if isinstance(result, dict) else bool(result)
                with self._teleop_lock:
                    st = self._teleop_streams.get(arm_id)
                    if not st:
                        break
                    st["last_ok"] = ok
                    st["last_t_wall"] = time.time()
                    if ok:
                        st["fail_streak"] = 0
                        st["write_count"] = int(st.get("write_count") or 0) + 1
                        st["last_error"] = None
                        st["message"] = (
                            f"远程连续下发中 · {hz:g} Hz · 已写 {st['write_count']}"
                        )
                    else:
                        st["fail_streak"] = int(st.get("fail_streak") or 0) + 1
                        st["last_error"] = (
                            result.get("error")
                            if isinstance(result, dict)
                            else "write rejected"
                        )
                        if st["fail_streak"] >= fail_max:
                            final_error = (
                                "远程连续下发写臂连续失败："
                                + str(st["last_error"])
                                + "；已停止"
                            )
                            st["enabled"] = False
                            stop_ev.set()
                            break

                stop_ev.wait(period)

            if final_error is None and (
                self._stop.is_set()
                or (
                    arm_id in self._teleop_streams
                    and self._teleop_streams[arm_id].get("stop")
                    and self._teleop_streams[arm_id]["stop"].is_set()
                )
            ):
                final_message = "已停止远程连续下发；ExternalControl 由 keepalive idle 保活"
        finally:
            with self._teleop_lock:
                st = self._teleop_streams.get(arm_id)
                if st is not None:
                    st["enabled"] = False
                    st["thread"] = None
                    if final_error:
                        st["last_ok"] = False
                        st["last_error"] = final_error
                        st["message"] = final_error
                    elif final_message:
                        st["last_ok"] = True
                        st["last_error"] = None
                        st["message"] = final_message
                    st["last_t_wall"] = time.time()

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
            live = self.latest_joints(arm_id, require_measured=True)
            if live is None:
                return {
                    "ok": False,
                    "error": (
                        "no measured arm joints yet — refuse Arm. "
                        "For CS66: ensure RTSI (configs/rtsi/*) is up; "
                        "YAML home synth is disabled on live."
                    ),
                }
            return writer.command(arm=True)

        if disarm or stop:
            self._abs_ramp.cancel(message="因 Disarm/Estop 取消绝对下发")
            self.teleop_stream_stop(arm_id, message="因 Disarm/Estop 停止连续下发")
            return writer.command(disarm=True, stop=True)

        if joints_rad is not None:
            mode = str(timing or "scale_by_d").strip().lower()
            # TCP-drag / remote teleop: one setpoint per call, no abs-ramp.
            # CS66: dense writeServoj (servoj_once) so controller servoj_* smooths;
            # never per-point writeIdle (that path is _servoj_stream — jerky for teleop).
            if mode in ("direct", "immediate", "step", "teleop"):
                if self._abs_ramp.enabled:
                    self._abs_ramp.cancel(message="因直接下发取消斜坡")
                if not self._writer_armed(writer):
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
                base = self.latest_joints(arm_id, require_measured=True)
                if base is None:
                    return {
                        "ok": False,
                        "error": (
                            "no measured joints; refuse direct write "
                            "(CS66 needs RTSI)"
                        ),
                    }
                cs_dense = self._is_cs_arm_write(writer.sensor)
                if cs_dense:
                    # Guard vs last command (continuity); single writeServoj per frame.
                    wr = writer.command(
                        joints_rad=q_star,
                        servoj_once=True,
                        relative_to_last=True,
                        idle_after=False,
                    )
                else:
                    # EC TT: one TT_add_joint; reference = measured for max_delta.
                    wr = writer.command(
                        joints_rad=q_star,
                        reference_joints_rad=list(base),
                    )
                out = dict(wr) if isinstance(wr, dict) else {"ok": bool(wr)}
                out["timing"] = mode if mode != "teleop" else "teleop"
                if cs_dense:
                    out["servoj_once"] = True
                    out["write_path"] = "cs_servoj_once"
                else:
                    out["write_path"] = "ec_tt"
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
            # CS: pass jog to driver so it can stream from continuous last_cmd
            # (pre-building from lagged RTSI caused rewind shake).
            # EC: still expand to absolute joints from measured read.
            cur = self.latest_joints(arm_id, require_measured=True)
            if cur is None:
                return {
                    "ok": False,
                    "error": (
                        "no measured joints for jog "
                        "(CS66 needs RTSI actual_joint_positions)"
                    ),
                }
            d = float(delta_rad) if delta_rad is not None else math.radians(float(delta_deg or 0))
            ji = int(jog_joint)
            if ji < 0 or ji >= len(cur):
                return {"ok": False, "error": "jog_joint out of range"}
            kind_v = getattr(getattr(writer.sensor, "kind", None), "value", None)
            kind_s = str(kind_v if kind_v is not None else getattr(writer.sensor, "kind", "") or "")
            if kind_s == "arm_cs_write":
                return writer.command(jog_joint=ji, delta_rad=d)
            tgt = list(cur)
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
            joints = self.latest_joints(arm_id, require_measured=True)
            if joints is None and bool(getattr(self.manager.ctx, "dry_run", False)):
                joints = self.latest_joints(arm_id, require_measured=False)
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

    def arm_ik(
        self,
        arm_id: str,
        xyzrpy: list[float],
        seed: list[float] | None = None,
        *,
        ori_weight: float | None = None,
        orientation_tolerance_rad: float | None = None,
        accept_residual: float | None = None,
    ) -> dict[str, Any]:
        arm = self._arm_by_id(arm_id)
        kin = self._kin_for_arm(arm)
        if seed is None:
            seed = self.latest_joints(arm_id, require_measured=True)
            if seed is None:
                seed = self.latest_joints(arm_id, require_measured=False)
        if seed is None:
            seed = [0.0] * int(arm.num_joints or 6)
        try:
            tcp = kin.get("tcp_xyz")
            if tcp is not None:
                set_tcp_xyz(tcp)
            # TCP-drag path: interactive LM (no soft-limit TRF). Soft TRF +
            # 2-point jac was the main reason amber-ball IK felt slow.
            ik_kwargs: dict[str, Any] = {
                "q_seed_rad": seed,
                "tcp_xyz": tcp,
                "kinematics": kin["kinematics"],
                "kinematics_profile": kin.get("kinematics_profile"),
                "interactive": True,
                "max_nfev": 80,
                "multi_seed": False,
                "soft_limit_retry": False,
                "enforce_teach_soft_limits": False,
                "solver_tol": 1e-6,
            }
            if ori_weight is not None:
                ik_kwargs["ori_weight"] = float(ori_weight)
            if orientation_tolerance_rad is not None:
                ik_kwargs["orientation_tolerance_rad"] = float(orientation_tolerance_rad)
            if accept_residual is not None:
                ik_kwargs["accept_residual"] = float(accept_residual)
            result = xyzrpy_to_joints_rad(xyzrpy, **ik_kwargs)
            if (
                isinstance(result, dict)
                and (
                    not result.get("ok", True)
                    or result.get("joints_rad") is None
                )
            ):
                # Limited escalate: still LM, slightly more budget + ±0.25 rad seeds.
                slow = dict(ik_kwargs)
                slow["max_nfev"] = 160
                slow["multi_seed"] = True
                result = xyzrpy_to_joints_rad(xyzrpy, **slow)
                if isinstance(result, dict):
                    result = dict(result)
                    result["ik_escalated"] = True
            if not isinstance(result, dict):
                return {"ok": False, "error": "unexpected IK result"}
            if not result.get("ok", True) and result.get("joints_rad") is None:
                return {"ok": False, "error": result.get("error") or "ik failed", **result}
            joints = result.get("joints_rad")
            out = {"ok": True, **result}
            if isinstance(joints, list):
                # Reuse achieved TCP from IK when present; still need flange for blue ball.
                cart = cartesian_payload(
                    joints,
                    tcp_xyz=tcp,
                    kinematics=kin["kinematics"],
                    kinematics_profile=kin.get("kinematics_profile"),
                )
                achieved = result.get("achieved_xyzrpy")
                if isinstance(achieved, list) and len(achieved) >= 6:
                    cart["cartesian_xyzrpy"] = list(achieved)
                out["cartesian"] = cart
            return out
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}
