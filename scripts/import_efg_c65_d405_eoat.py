"""Import Cell C EFG-C65 + D405 EOAT accessory STLs into cs66 tool frame.

Source: SolidWorks assembly export ``OUT - *.STL`` (mm, assembly coords).
Target: same meter tool frame as ``meshes/EFG-C65.v3.STL`` (mount z=0, tip ≈ z=0.117).

 empirically (AABB match OUT gripper ↔ v3):
   x_t = x_mm/1000 - 0.05864894152
   y_t = z_mm/1000 - 0.12178901672
   z_t = y_mm/1000 - 0.00058486998
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MESH_DIR = ROOT / "src/sensors_arm/static/models/cs66/meshes"
# Optional mirror used by sensors-dcs desktop/viz
DCS_MESH = (
    ROOT.parent / "sensors-dcs/src/sensors_dcs/static/models/cs66/meshes"
)

# Fitted so OUT gripper AABB → EFG-C65.v3 AABB
TX = -0.05864894152
TY = -0.12178901672
TZ = -0.00058486998

PARTS = {
    "EFG-C65_D405_fingertip_l.STL": "OUT - EFG-C65_D405_fingertip_1out-2.STL",  # −X after map
    "EFG-C65_D405_fingertip_r.STL": "OUT - EFG-C65_D405_fingertip_1out-1.STL",  # +X after map
    "EFG-C65_D405_bracket.STL": "OUT - EFG-C65_D405_bracketout-1.STL",
    "EFG-C65_D405_l_clamp.STL": "OUT - EFG-C65_D405_l_clampout-1.STL",
    "D405_camera.STL": "OUT - D405_camera_officialout-1.STL",
}


def load_binary_stl(path: Path) -> tuple[np.ndarray, np.ndarray]:
    data = path.read_bytes()
    n = struct.unpack_from("<I", data, 80)[0]
    normals = np.empty((n, 3), dtype=np.float32)
    tris = np.empty((n, 3, 3), dtype=np.float32)
    off = 84
    for i in range(n):
        vals = struct.unpack_from("<12fH", data, off)
        normals[i] = vals[0:3]
        tris[i, 0] = vals[3:6]
        tris[i, 1] = vals[6:9]
        tris[i, 2] = vals[9:12]
        off += 50
    return normals, tris


def transform_assembly_mm_to_tool_m(tris: np.ndarray, normals: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """OUT mm → tool m; axes: (x,y,z)_out → (x,z,y)_tool with translation."""
    out = np.empty_like(tris, dtype=np.float32)
    # x_t = x/1000 + TX; y_t = z/1000 + TY; z_t = y/1000 + TZ
    out[:, :, 0] = tris[:, :, 0] / 1000.0 + TX
    out[:, :, 1] = tris[:, :, 2] / 1000.0 + TY
    out[:, :, 2] = tris[:, :, 1] / 1000.0 + TZ
    # normals: same linear map without translation (permutation + scale sign +1)
    nrm = np.empty_like(normals, dtype=np.float32)
    nrm[:, 0] = normals[:, 0]
    nrm[:, 1] = normals[:, 2]
    nrm[:, 2] = normals[:, 1]
    # re-normalize
    lens = np.linalg.norm(nrm, axis=1, keepdims=True)
    lens = np.maximum(lens, 1e-12)
    nrm = nrm / lens
    return nrm.astype(np.float32), out


def write_binary_stl(path: Path, normals: np.ndarray, tris: np.ndarray) -> None:
    n = len(tris)
    header = b"EFG-C65 D405 EOAT tool-frame (m)" + b"\0" * 80
    header = header[:80]
    buf = bytearray(header)
    buf += struct.pack("<I", n)
    for i in range(n):
        nx, ny, nz = map(float, normals[i])
        buf += struct.pack("<3f", nx, ny, nz)
        for v in range(3):
            buf += struct.pack("<3f", float(tris[i, v, 0]), float(tris[i, v, 1]), float(tris[i, v, 2]))
        buf += struct.pack("<H", 0)
    path.write_bytes(buf)


def convert_one(src: Path, dest: Path) -> None:
    normals, tris = load_binary_stl(src)
    normals, tris = transform_assembly_mm_to_tool_m(tris, normals)
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_binary_stl(dest, normals, tris)
    mn, mx = tris.reshape(-1, 3).min(0), tris.reshape(-1, 3).max(0)
    print(f"wrote {dest.name}  aabb={mn} .. {mx}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--src",
        type=Path,
        default=Path(
            r"C:\Users\user\xwechat_files\wxid_ljtvhkq00jn722_4ced\msg\file\2026-09\20260929_2\20260929_2"
        ),
    )
    ap.add_argument("--also-dcs", action="store_true", default=True)
    args = ap.parse_args()
    if not args.src.is_dir():
        print(f"missing src dir: {args.src}", file=sys.stderr)
        return 1
    for dest_name, src_name in PARTS.items():
        src = args.src / src_name
        if not src.is_file():
            print(f"missing {src}", file=sys.stderr)
            return 1
        convert_one(src, MESH_DIR / dest_name)
        if args.also_dcs and DCS_MESH.is_dir():
            convert_one(src, DCS_MESH / dest_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
