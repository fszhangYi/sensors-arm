# 琥珀色 TCP 球拖拽 + IK 预览

日期：2026-10-10  
状态：**已实现**  
范围：sensors-arm 3D 画布；仿 sensors-dcs `docs/tcp-drag-ik.md`，用于现场核对 FK/IK。

---

## 产品结论

| # | 行为 |
|---|------|
| 1 | 琥珀色球优先跟随 `cartesian_xyzrpy`（FK）；无 FK 时落在 URDF tip + `tcp_xyz` |
| 1b | 浮动窗 **「自动下发」** 默认勾选：IK 成功后 `POST /api/arm/command` 且 **`timing=direct`（无斜坡插值）**；取消勾选则仅预览 |
| 2 | LMB 点中球 → 重质量阻尼拖拽（只改 xyz，rpy 冻结） |
| 3 | 节流 `POST /api/arm/ik`（带 `arm_id` + seed） |
| 4 | 浮动窗显示 IK joints；成功时写入「绝对下发」输入框并刷新 URDF |
| 5 | **不下发** `arm_command`；关窗后球与 URDF 恢复 live 读数 |
| 6 | 未点中球时 OrbitControls 照常旋转 / 缩放 / 平移 |

---

## API

已有：`POST /api/arm/ik`

```json
{ "arm_id": "cell_a", "xyzrpy": [x,y,z,rx,ry,rz], "seed_joints_rad": [...] }
```

---

## 验收

1. 连接臂后琥珀球出现在 TCP；空白处 LMB 仍 orbit。
2. 拖球缓动、不贴鼠标；浮动窗 joints 更新；URDF 随 IK 预览。
3. 关窗后球回到 live FK；点「下发」仍走原 abs ramp（需手动）。
4. Cell A（`sensors.kinematics`）与 Cell B（`cs66_kinematics`）均走各自后端。
