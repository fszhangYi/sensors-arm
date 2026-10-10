from __future__ import annotations

import math
import time
from typing import Any

from sensors_arm.paths import ensure_sensors_import

ensure_sensors_import()
from sensors.core.base import Sensor  # noqa: E402

from sensors_arm.agents.base import BaseAgent
from sensors_arm.frame import Frame


class ArmAgent(BaseAgent):
    """Read-only Elite arm agent (``kind=arm_read``) — never commands the robot.

    Joints come from Elite EC ``monitor_info.machinePos`` (degrees → radians),
    matching ``elite_robot.get_joint_state`` / demo_test kinematics units.
    """

    kind = "arm_read"

    def __init__(
        self,
        *,
        agent_id: str,
        sensor: Sensor,
        hz: float = 50.0,
        buffer_frames: int = 64,
        dry_run_synth: bool = True,
        home_joints_rad: list[float] | None = None,
    ) -> None:
        super().__init__(
            agent_id=agent_id,
            sensor=sensor,
            hz=hz,
            buffer_frames=buffer_frames,
        )
        self.dry_run_synth = dry_run_synth
        self._n_joints = int(getattr(sensor, "num_joints", None) or 6)
        self._home_joints_rad: list[float] | None = None
        self._kinematics = "kinematics"
        self._kinematics_profile: str | None = None
        self._tcp_xyz: list[float] | None = None
        self.set_home_joints_rad(home_joints_rad)

    def set_kinematics(
        self,
        *,
        kinematics: str = "kinematics",
        kinematics_profile: str | None = None,
        tcp_xyz: list[float] | None = None,
    ) -> None:
        """Bind FK/IK backend for this arm (from models catalog)."""
        self._kinematics = str(kinematics or "kinematics")
        self._kinematics_profile = kinematics_profile
        self._tcp_xyz = list(tcp_xyz) if tcp_xyz is not None else None

    def set_home_joints_rad(self, joints: list[float] | None) -> None:
        """Configure dry-run fallback pose (DCS ``home_joints_rad``)."""
        if joints is None:
            self._home_joints_rad = None
            return
        try:
            vals = [float(x) for x in list(joints)[: self._n_joints]]
        except (TypeError, ValueError):
            self._home_joints_rad = None
            return
        if len(vals) < self._n_joints or any(not math.isfinite(x) for x in vals):
            self._home_joints_rad = None
            return
        self._home_joints_rad = vals

    def read_frame(self) -> Frame:
        sample = dict(self.sensor.read())
        t_wall = float(sample.get("ts") or time.time())
        t_mono = time.perf_counter()
        self._seq += 1

        joints = sample.get("joints_rad")
        dry = bool(sample.get("dry_run")) or joints is None
        # Only synth when the sensor has no joints yet — if sharing arm_write in
        # dry_run, keep the driver's reported pose so jog stays relative to it.
        if dry and self.dry_run_synth and joints is None:
            joints = self._synth_joints(t_wall)
            sample = {
                **sample,
                "joints_rad": joints,
                "joints_deg": [math.degrees(x) for x in joints],
                "dry_run": True,
                "synth": True,
            }

        # Normalize to plain list[float] so ring consumers (IK seed) never see ndarray/tuple quirks.
        if joints is not None:
            try:
                joints = [float(x) for x in list(joints)[: self._n_joints]]
                if len(joints) < self._n_joints or any(not math.isfinite(x) for x in joints):
                    joints = None
            except (TypeError, ValueError):
                joints = None

        payload: dict[str, Any] = {
            "joints_rad": joints,
            "joints_deg": sample.get("joints_deg"),
            "num_joints": sample.get("num_joints") or self._n_joints,
            "robot_ip": sample.get("robot_ip") or getattr(self.sensor, "robot_ip", None),
            "endpoint": sample.get("endpoint"),
            "backend": sample.get("backend") or "elite_ec",
            "mode": sample.get("mode") or "read_only",
            "dry_run": dry,
            "synth": bool(sample.get("synth")),
        }
        # Skip FK until warmed (avoids dual-thread scipy import deadlock).
        try:
            from sensors_arm.arm_pose import cartesian_payload, kinematics_ready

            if kinematics_ready():
                payload.update(
                    cartesian_payload(
                        joints,
                        tcp_xyz=self._tcp_xyz,
                        kinematics=self._kinematics,
                        kinematics_profile=self._kinematics_profile,
                    )
                )
            else:
                payload["cartesian_xyzrpy"] = None
        except Exception:  # noqa: BLE001
            payload["cartesian_xyzrpy"] = None
        return Frame(
            sensor_id=self.sensor_id,
            agent_id=self.agent_id,
            kind=self.kind,
            t_wall=t_wall,
            t_mono=t_mono,
            payload=payload,
            seq=self._seq,
        )

    def _synth_joints(self, t_wall: float) -> list[float]:
        """Dry-run pose when the driver has no joints yet.

        Prefer configured ``home_joints_rad`` (static). If unset, hold zeros —
        not a sine demo — so Read matches Home semantics offline.
        """
        del t_wall  # home/zeros are static; keep signature for call sites
        if self._home_joints_rad is not None and len(self._home_joints_rad) >= self._n_joints:
            return list(self._home_joints_rad[: self._n_joints])
        return [0.0] * self._n_joints
