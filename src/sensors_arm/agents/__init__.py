from __future__ import annotations

from typing import TYPE_CHECKING

from sensors_arm.agents.arm_agent import ArmAgent
from sensors_arm.agents.arm_write_agent import ArmWriteAgent
from sensors_arm.agents.base import BaseAgent
from sensors_arm.config import AgentConfig

if TYPE_CHECKING:
    from sensors.core.base import Sensor


def build_agent(cfg: AgentConfig, sensor: Sensor) -> BaseAgent:
    if cfg.type == "arm":
        return ArmAgent(
            agent_id=cfg.id,
            sensor=sensor,
            hz=cfg.hz,
            buffer_frames=cfg.buffer_frames,
        )
    if cfg.type == "arm_write":
        return ArmWriteAgent(
            agent_id=cfg.id,
            sensor=sensor,
            hz=cfg.hz,
            buffer_frames=cfg.buffer_frames,
        )
    raise ValueError(f"unsupported agent type: {cfg.type}")
