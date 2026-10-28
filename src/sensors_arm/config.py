from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from sensors_arm.paths import project_root, resolve_config_path


class AgentConfig(BaseModel):
    id: str
    type: Literal["arm", "arm_write"] = "arm"
    sensor_id: str
    hz: float = 50.0
    buffer_frames: int = 64

    @field_validator("hz")
    @classmethod
    def _hz_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("hz must be > 0")
        return v


class RuntimeConfig(BaseModel):
    control_host: str = "0.0.0.0"
    control_port: int = 7020
    viz_host: str = "0.0.0.0"
    viz_port: int = 6008
    viz_hz: float = 15.0
    console_hz: float = 5.0


class ArmAbsRampConfig(BaseModel):
    """Joint-space abs send (same semantics as sensors-dcs arm_abs_ramp)."""

    t_min_s: float = 0.1
    t_max_s: float = 30.0
    v_norm_rad_s: float = 0.02
    profile: str = "seven_segment"
    jerk_seg_frac: float = 0.10
    accel_seg_frac: float = 0.15
    ramp_hz: float = 20.0

    @field_validator("profile", mode="before")
    @classmethod
    def _profile(cls, v: Any) -> str:
        s = str(v or "seven_segment").strip().lower()
        if s in ("seven", "jerk", "7seg", "7-segment"):
            s = "seven_segment"
        if s not in ("seven_segment", "cosine", "linear"):
            raise ValueError("arm_abs_ramp.profile must be seven_segment, cosine, or linear")
        return s


class ArmModelRef(BaseModel):
    """Visualization / kinematics profile for one physical arm."""

    id: str
    label: str | None = None
    # Key in models catalog (e.g. elite_ec616, stub_6dof)
    model: str = "elite_ec616"
    brand: str | None = None
    product: str | None = None
    read_agent: str
    write_agent: str | None = None
    home_joints_rad: list[float] | None = None
    tcp_xyz: list[float] | None = None
    num_joints: int | None = None

    @field_validator("home_joints_rad", mode="before")
    @classmethod
    def _home(cls, v: Any) -> list[float] | None:
        if v is None or v == "":
            return None
        if not isinstance(v, (list, tuple)):
            raise ValueError("home_joints_rad must be a list of floats (rad)")
        out = [float(x) for x in v]
        if any(x != x or x in (float("inf"), float("-inf")) for x in out):
            raise ValueError("home_joints_rad values must be finite")
        return out


class ModelCatalogEntry(BaseModel):
    brand: str = "Generic"
    product: str = "6DoF"
    num_joints: int = 6
    backend: str = "elite"  # elite | stub
    # FK/IK package: legacy hik-sensors kinematics vs YAML-backed CS66 packs
    kinematics: str = "kinematics"  # kinematics | cs66_kinematics | cs66_kin_g26562
    kinematics_profile: str | None = None  # e.g. elite_cs66 (YAML packs only)
    urdf: str | None = "/assets/models/ec616/ec616.urdf"
    joint_names: list[str] = Field(
        default_factory=lambda: ["Joint1", "Joint2", "Joint3", "Joint4", "Joint5", "Joint6"]
    )
    joint_offset_rad: list[float] = Field(
        default_factory=lambda: [0.0, -1.57079632679, 0.0, -1.57079632679, 3.14159265359, 0.0]
    )
    joint_signs: list[float] = Field(default_factory=lambda: [1.0, 1.0, 1.0, 1.0, 1.0, 1.0])
    mirror_y: bool = True
    # Extra EOAT assembly RPY (rad, URDF XYZ) applied in viz after URDF load.
    # e.g. Cell C gripper flipped 180° about tool Z → [0, 0, π]
    gripper_rpy: list[float] | None = None
    notes: str | None = None


class ArmConfig(BaseModel):
    version: int = 1
    site: str = "arm-lab"
    sensors_config: str
    dry_run: bool | None = True
    # Global defaults (overridden per-arm when set)
    home_joints_rad: list[float] | None = None
    tcp_xyz: list[float] | None = None
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    arm_abs_ramp: ArmAbsRampConfig = Field(default_factory=ArmAbsRampConfig)
    # Multi-arm view: one entry per robot shown in UI
    arms: list[ArmModelRef] = Field(default_factory=list)
    agents: list[AgentConfig] = Field(default_factory=list)
    # Optional inline catalog overrides; merged over built-in + models_catalog file
    models: dict[str, ModelCatalogEntry] = Field(default_factory=dict)
    models_catalog: str | None = "models_catalog.yaml"

    @model_validator(mode="after")
    def _require_agents_or_arms(self) -> ArmConfig:
        if not self.agents and not self.arms:
            raise ValueError("config needs agents: and/or arms:")
        return self


BUILTIN_MODELS: dict[str, ModelCatalogEntry] = {
    "elite_ec616": ModelCatalogEntry(
        brand="Elite",
        product="EC616",
        num_joints=6,
        backend="elite",
        urdf="/assets/models/ec616/ec616.urdf?v=ee-full-1",
        notes="URDF from sensors-dcs static/models/ec616",
    ),
    "elite_ec66": ModelCatalogEntry(
        brand="Elite",
        product="EC66",
        num_joints=6,
        backend="elite",
        urdf="/assets/models/ec66/ec66.urdf?v=elite-ros-1",
        joint_names=["joint1", "joint2", "joint3", "joint4", "joint5", "joint6"],
        joint_offset_rad=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        joint_signs=[1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        mirror_y=False,
        notes="URDF/STL from Elite-Robots/ROS elite_description; SDK=elirobots (shared)",
    ),
    "elite_cs66": ModelCatalogEntry(
        brand="Elite",
        product="CS66",
        num_joints=6,
        backend="elite",
        kinematics="cs66_kinematics",
        kinematics_profile="elite_cs66",
        urdf="/assets/models/cs66/cs66.urdf?v=cs66-efg-c65-3",
        joint_names=["joint1", "joint2", "joint3", "joint4", "joint5", "joint6"],
        joint_offset_rad=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        joint_signs=[1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        mirror_y=False,
        notes=(
            "URDF joints from teach MDH; meshes CS66urdf.rar; SDK=elite_cs_sdk via arm_cs_write. "
            "FK/IK=sensors.cs66_kinematics/elite_cs66 (not sensors.kinematics)"
        ),
    ),
    "elite_cs66_g26562": ModelCatalogEntry(
        brand="Elite",
        product="CS66",
        num_joints=6,
        backend="elite",
        kinematics="cs66_kin_g26562",
        kinematics_profile="elite_cs66",
        urdf="/assets/models/cs66/cs66.urdf?v=cs66-efg-c65-3",
        joint_names=["joint1", "joint2", "joint3", "joint4", "joint5", "joint6"],
        joint_offset_rad=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        joint_signs=[1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        mirror_y=False,
        gripper_rpy=[0.0, 0.0, 3.141592653589793],
        notes=(
            "Cell C copy of CS66 visuals/SDK path; FK/IK=sensors.cs66_kin_g26562/elite_cs66 "
            "(G26562 teach pairs 2026-10-27). Viz EOAT: gripper +180° about tool Z."
        ),
    ),
    "stub_6dof": ModelCatalogEntry(
        brand="Stub",
        product="Sim6",
        num_joints=6,
        backend="stub",
        urdf=None,
        notes="No mesh — joint bars only (placeholder for future brands)",
    ),
}


def load_yaml(path: str | Path) -> dict[str, Any]:
    p = resolve_config_path(path)
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"config root must be a mapping: {p}")
    return data


def load_models_catalog(path: str | Path | None) -> dict[str, ModelCatalogEntry]:
    out = {k: v.model_copy(deep=True) for k, v in BUILTIN_MODELS.items()}
    if not path:
        return out
    p = resolve_config_path(path)
    if not p.is_file():
        # allow missing relative catalog when using builtins only
        if Path(str(path)).name == Path(str(path)).name and not Path(path).is_absolute():
            alt = project_root() / "configs" / Path(str(path)).name
            if alt.is_file():
                p = alt
            else:
                return out
        else:
            return out
    raw = load_yaml(p)
    models = raw.get("models") if isinstance(raw.get("models"), dict) else raw
    if not isinstance(models, dict):
        return out
    for key, val in models.items():
        if isinstance(val, dict):
            out[str(key)] = ModelCatalogEntry.model_validate(val)
    return out


def _expand_arms_to_agents(cfg: ArmConfig) -> ArmConfig:
    """If arms: present but agents: empty, synthesize arm + arm_write agents.

    Convention: ``ArmModelRef.id`` is the hik-sensors device id (shared by
    read + write agents, same as sensors-dcs robot_write).
    """
    if cfg.agents:
        return cfg
    agents: list[AgentConfig] = []
    for arm in cfg.arms:
        agents.append(
            AgentConfig(id=arm.read_agent, type="arm", sensor_id=arm.id, hz=50.0, buffer_frames=64)
        )
        if arm.write_agent:
            agents.append(
                AgentConfig(
                    id=arm.write_agent,
                    type="arm_write",
                    sensor_id=arm.id,
                    hz=5.0,
                    buffer_frames=8,
                )
            )
    return cfg.model_copy(update={"agents": agents})


def load_config(path: str | Path) -> ArmConfig:
    raw = load_yaml(path)
    cfg_path = resolve_config_path(path)
    # Resolve sensors_config relative to the YAML file directory
    sc = raw.get("sensors_config")
    if isinstance(sc, str) and sc and not Path(sc).is_absolute():
        raw["sensors_config"] = str((cfg_path.parent / sc).resolve())
    mc = raw.get("models_catalog")
    if isinstance(mc, str) and mc and not Path(mc).is_absolute():
        cand = cfg_path.parent / mc
        if cand.is_file():
            raw["models_catalog"] = str(cand.resolve())
    cfg = ArmConfig.model_validate(raw)
    cfg = _expand_arms_to_agents(cfg)
    if not cfg.arms:
        # Synthesize a single arm view from agents for UI
        readers = [a for a in cfg.agents if a.type == "arm"]
        writers = {a.sensor_id: a for a in cfg.agents if a.type == "arm_write"}
        arms: list[ArmModelRef] = []
        for r in readers:
            w = writers.get(r.sensor_id)
            arms.append(
                ArmModelRef(
                    id=r.sensor_id,
                    label=r.sensor_id,
                    model="elite_ec616",
                    read_agent=r.id,
                    write_agent=w.id if w else None,
                    home_joints_rad=cfg.home_joints_rad,
                    tcp_xyz=cfg.tcp_xyz,
                )
            )
        cfg = cfg.model_copy(update={"arms": arms})
    return cfg


def resolve_model(
    cfg: ArmConfig, arm: ArmModelRef
) -> ModelCatalogEntry:
    catalog = load_models_catalog(cfg.models_catalog)
    catalog.update(cfg.models)
    entry = catalog.get(arm.model) or BUILTIN_MODELS.get("stub_6dof")
    assert entry is not None
    # Per-arm brand/product overrides
    data = entry.model_dump()
    if arm.brand:
        data["brand"] = arm.brand
    if arm.product:
        data["product"] = arm.product
    if arm.num_joints:
        data["num_joints"] = arm.num_joints
    return ModelCatalogEntry.model_validate(data)


def config_summary(cfg: ArmConfig) -> dict[str, Any]:
    return {
        "site": cfg.site,
        "dry_run": cfg.dry_run,
        "sensors_config": cfg.sensors_config,
        "arms": [
            {
                "id": a.id,
                "label": a.label or a.id,
                "model": a.model,
                "read_agent": a.read_agent,
                "write_agent": a.write_agent,
            }
            for a in cfg.arms
        ],
        "agents": [{"id": a.id, "type": a.type, "sensor_id": a.sensor_id} for a in cfg.agents],
        "runtime": cfg.runtime.model_dump(),
    }


def parse_home_joints(raw: Any, n: int = 6) -> tuple[list[float] | None, str | None]:
    if raw is None or raw == "":
        return None, "home_joints_rad 未配置"
    if not isinstance(raw, (list, tuple)):
        return None, "home_joints_rad 格式错误：需要浮点列表"
    try:
        vals = [float(x) for x in raw]
    except (TypeError, ValueError):
        return None, "home_joints_rad 含非数字"
    if len(vals) < n:
        return None, f"home_joints_rad 需要至少 {n} 个数"
    if any(x != x or x in (float("inf"), float("-inf")) for x in vals):
        return None, "home_joints_rad 含非有限数"
    return vals[:n], None
