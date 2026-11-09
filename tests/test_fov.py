"""FOV geometry + per-arm camera enable gate."""

from __future__ import annotations

from sensors_arm.config import ArmCameraConfig, ArmConfig, load_config
from sensors_arm.fov import analyze, fov_from_intrinsics, resolve_mode_fov
from sensors_arm.paths import project_root


def test_fov_from_intrinsics_hd():
    h, v = fov_from_intrinsics(1280, 720, 650.0, 650.0)
    assert 85.0 < h < 95.0
    assert 55.0 < v < 65.0


def test_resolve_mode_prefers_degrees():
    H, V = resolve_mode_fov({"id": "x", "H_deg": 87, "V_deg": 58, "fx": 1, "fy": 1, "width": 10, "height": 10})
    assert H == 87 and V == 58


def test_analyze_cell_c_defaults():
    cfg = load_config(project_root() / "configs" / "default.yaml")
    arm_c = next(a for a in cfg.arms if a.id == "arm-c")
    assert arm_c.camera and arm_c.camera.enabled
    result = analyze(arm_c.camera.model_dump())
    assert result["modes"]
    assert result["points"]
    assert result["recommend_mode"]


def test_cells_without_camera_disabled():
    cfg = load_config(project_root() / "configs" / "default.yaml")
    by_id = {a.id: a for a in cfg.arms}
    assert by_id["arm-a"].camera is None or not by_id["arm-a"].camera.enabled
    assert by_id["arm-b"].camera is None or not by_id["arm-b"].camera.enabled
    assert by_id["arm-c"].camera and by_id["arm-c"].camera.enabled


def test_camera_config_roundtrip():
    cam = ArmCameraConfig.model_validate(
        {
            "enabled": True,
            "lens": [0.0, 0.0, 0.0],
            "look": [0.0, 0.0, 1.0],
            "right": [-1.0, 0.0, 0.0],
            "modes": [{"id": "m", "width": 640, "height": 480, "fx": 400, "fy": 400}],
            "samples": [{"name": "p", "xyz": [0.0, 0.0, 100.0], "tag": "blade"}],
        }
    )
    assert cam.enabled
    H, V = resolve_mode_fov(cam.modes[0].model_dump())
    assert H > 0 and V > 0
