# CS66 model assets

- Local archive: `sensors-arm/CS66urdf.rar` → extracted package `CS66urdf/`
- URDF: SolidWorks export `CS66urdf.urdf` (mesh URIs rewritten to relative `meshes/`)
- Control SDK: **Elite CS** — hik-sensors `arm_cs_write` / `arm_cs_read` + `elite_cs_sdk`
  (not EC `elirobots` / `arm_write`)
- Note: exporter wrote `<limit lower="0" upper="0"/>` on all revolute joints, which
  clamps URDFLoader `setJointValue` to zero. Limits were widened to ±2π for viz.
- EE (viz only): KWR75 + DH AG-95 copied from Cell A `ec616/meshes/` onto `link6`
  (same offsets as `ec616.urdf`: FT at flange, AG95 at z=+0.0335 on FT face).
