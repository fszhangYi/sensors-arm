# CS66 model assets

- Local archive: `sensors-arm/CS66urdf.rar` → extracted package `CS66urdf/`
- **Meshes (arm)**: SolidWorks export (unchanged)
- **Joint origins**: Cell B = `cs66_kinematics` teach MDH; Cell C =
  Elite ROS2 `config/cs66/default_kinematics.yaml` (catalog). Cell C FK/IK
  runtime still uses `cs66_kin_g26562` unit teach MDH.
- Control SDK: **Elite CS** — hik-sensors `arm_cs_write` / `arm_cs_read` + `elite_cs_sdk`
  (not EC `elirobots` / `arm_write`)
- Revolute `<limit>`: position/vel from teach soft_limits_deg (±363°) /
  `joint_vel_max_deg_s`. Effort 150/150/150/28/28/28 Nm from Elite ROS2
  `joint_limits.yaml` (also in profile `joint_effort_max_nm`). Gripper (Cell C):
  force max 300 N (range 60–300), velocity 32.5 mm / 0.7 s.
  Exporter used to write `lower=upper=0`; viz falls back to ±363° if that happens.
- **EE (viz)**:
  - KWR75 FT on `link6` (same as Cell A)
  - **EFG-C65** gripper (replaces AG-95): source STEP `cad/EFG-C65.STEP`
    (from `EFG-C65（外发）.STEP`); runtime mesh `meshes/EFG-C65.v3.STL`
    (Rx+90° so CAD −Y mount → tool −Z; mm→m; mount bore axis@XY=0, z=0; tip ≈ z=0.117)
  - Mount joint: gripper at z=+0.0335 on KWR75 tool face
  - Cell B `tcp_xyz` default `[0,0,0.1505]` ≈ flange→EFG tip (via KWR75)
  - **Cell C** uses `cs66_cell_c.urdf` (**no KWR75**; EFG on `link6`, `tcp_xyz≈[0,0,0.117]`)
    tooling on `gripper_centor_link`:
    dual fingertips (`gripper_opening` prismatic ±X, 0…0.033 m/side, R mimics L),
    `EFG-C65_D405_bracket.STL`, `EFG-C65_D405_l_clamp.STL`, `D405_camera.STL`
    — imported from SolidWorks `OUT - *.STL` via
    `scripts/import_efg_c65_d405_eoat.py` (assembly mm → tool m)
