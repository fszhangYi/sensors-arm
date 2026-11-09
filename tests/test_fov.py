"""FOV geometry + per-arm camera enable gate."""

from __future__ import annotations

import io
import zipfile

import pytest

from sensors_arm.config import ArmCameraConfig, load_config
from sensors_arm.fov import analyze, build_export_zip, fov_from_intrinsics, resolve_mode_fov
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


def test_export_zip_contains_report_and_figures():
    pytest.importorskip("matplotlib")
    cfg = load_config(project_root() / "configs" / "default.yaml")
    arm_c = next(a for a in cfg.arms if a.id == "arm-c")
    cam = arm_c.camera.model_dump()
    result = analyze(cam)
    blob = build_export_zip(result, cam, arm_id="arm-c", label="Cell C")
    assert blob[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = zf.namelist()
        assert any(n.endswith("report.md") for n in names)
        assert any(n.endswith("fov_summary.json") for n in names)
        assert any(n.endswith("figures/fov_angular_compare.png") for n in names)
        assert any(n.endswith("figures/fov_side_wedge.png") for n in names)
        assert any(n.endswith("figures/fov_coverage_bars.png") for n in names)
        md = next(n for n in names if n.endswith("report.md"))
        text = zf.read(md).decode("utf-8")
        assert "视场校验" in text


def test_extract_and_patch_yaml_from_stl(tmp_path):
    from sensors_arm.fov_stl import extract_from_stls, patch_arm_camera_yaml

    extracted = extract_from_stls()
    assert len(extracted["lens"]) == 3
    assert len(extracted["samples"]) >= 4
    src = (project_root() / "configs" / "default.yaml").read_text(encoding="utf-8")
    patched = patch_arm_camera_yaml(
        src,
        "arm-c",
        {
            "lens": extracted["lens"],
            "look": extracted["look"],
            "right": extracted["right"],
            "samples": extracted["samples"],
        },
    )
    assert "lens:" in patched
    # Write to temp and reload
    p = tmp_path / "default.yaml"
    p.write_text(patched, encoding="utf-8")
    cfg = load_config(p)
    arm_c = next(a for a in cfg.arms if a.id == "arm-c")
    assert arm_c.camera and arm_c.camera.enabled
    assert arm_c.camera.lens == pytest.approx(extracted["lens"], abs=1e-3)
    assert len(arm_c.camera.samples) == len(extracted["samples"])
