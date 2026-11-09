# sensors-arm：相机视场校验（Cell C）— 功能计划

日期：2026-11-09  
状态：P0 已落地（按 cell `camera.enabled` 区分；前端可改 W/H/fx/fy/HFOV/VFOV）  
相关：Cell C EOAT（`EFG-C65` + 指尖 + D405 支架/相机网格）· office_skills [`camera-fov-analysis`](../../office_skills/camera-fov-analysis/SKILL.md)

### 实现摘要（2026-11-09）

| 项 | 位置 |
|----|------|
| 每臂开关 | `configs/default.yaml` → `arms[].camera.enabled`（仅 `arm-c` 为 true） |
| 模型 | `ArmCameraConfig` in `src/sensors_arm/config.py` |
| 算法 | `src/sensors_arm/fov.py` |
| API | `GET/POST /api/fov/camera` · `POST /api/fov/analyze` |
| UI | 左侧「视场校验」面板（无相机 cell 隐藏） |

---

## 1. 目标

在 **sensors-arm** 中提供「腕部 D405 相对指尖/工件特征是否入画」的**几何视场校验**：

- 输入：装配外参（来自 URDF/网格或配置）+ 流分辨率档位（HFOV×VFOV）+ 采样点  
- 输出：各点是否 `in_fov`、角域裕量、可选遮挡、分档对比与建议默认分辨率  
- 首发场景：**Cell C（`elite_cs66_g26562`）**，相机已挂在慧灵 EFG-C65 工装上  

**一句话：** 改支架/指尖/开合后，不靠猜，直接在臂可视化旁得到「这一档流能不能看见指尖」。

---

## 2. 非目标（本期不做）

| 不做 | 原因 |
|------|------|
| 内参标定 / PnP / 畸变估计 | 属标定管线；本功能用手册或本机枚举的 FOV |
| 深度精度、曝光、IR 质量 | 光学/成像质量另案 |
| 实时视频上画框跟拍 | 可二期；一期以几何角域 + 3D 示意为准 |
| 替代 RealSense 官方标定工具 | 只做装配覆盖决策 |

方法对齐 skill：针孔角域  
`d = (P−L)·look`，`az/el = atan2(·)`，`in_fov ⇔ d>ε ∧ |az|≤H/2 ∧ |el|≤V/2`。

---

## 3. 与现有资产的关系

| 已有 | 用法 |
|------|------|
| URDF `wrist_cam_d405_link` + `D405_camera.STL` | 估计镜头中心 `LENS`、粗光轴（外壳几何或配置覆盖） |
| `gripper_fingertip_{l,r}_link` STL | 采样指尖根/刃/钩点（闭合态；张开用参数化偏移） |
| `gripper_rpy` Cell C +180° about tool Z | 校验时与可视化同一 EOAT 姿态 |
| `office_skills/camera-fov-analysis` | 算法与报告格式直接复用；sensors-arm 负责**位姿自动填充 + 产品入口** |

装配坐标系以 **夹爪工具系（米）** 为准（与 `EFG-C65.v3` / 导入脚本一致）；内部计算可转 mm 以匹配 skill 脚本。

---

## 4. 功能形态（建议分两期交付）

### P0 — 离线/API 校验（MVP）

1. **配置包** `configs/fov/cell_c_d405.json`（可手改）：  
   - `model_id: elite_cs66_g26562`  
   - FOV `modes[]`（默认 HD87 / HD84 / VGA 参考表；可填本机 `rs-enumerate-devices -c`）  
   - 可选覆盖：`lens` / `look` / `right`（若网格推不准）  
   - `samples` 或「从指尖网格自动采样」开关  
2. **Python 模块** `sensors_arm/fov_analyze.py`：  
   - 读 URDF/网格或 JSON → 相机轴系 + 采样点  
   - 调用与 skill 相同的投影逻辑（可 vendoring `analyze_fov.py` 核心函数）  
   - 写出 `export/fov/<stamp>/report.md` + PNG（侧视楔、角域、足迹）  
3. **HTTP API**（挂在 sensors-arm FastAPI）：  
   - `POST /api/fov/analyze` `{ model_id, mode_ids?, jaw_open_mm? }`  
   - 返回 JSON：每点 `d,az,el,in_fov` + 汇总 + 报告相对 URL  
4. **CLI**：`python -m sensors_arm.fov_analyze -c configs/fov/cell_c_d405.json`

**验收：** Cell C 默认配置下，对至少 2 个 FOV 档给出指尖入画表；改 `lens` 俯角后结果随之变。

### P1 — 可视化叠加（产品化）

1. 3D 场景中：镜头点、光轴、H/V 视锥半透明楔；采样点绿/红（入画/出画）。  
2. 侧栏「视场校验」：选 FOV 档、开合、一键分析、显示裕量与推荐档。  
3. （可选）射线 vs 支架/夹爪 STL 遮挡（trimesh），点状态多一列 `blocked`。

**验收：** 不离开臂页面即可完成一次 Cell C 校验并看懂结论。

### P2 — 扩展（有需求再开）

- 多相机（胸部位姿另配置）  
- 与 DCS episode 对齐：导出「本站默认 FOV 档」写入 manifest  
- 关节角相关：校验「当前 FK 姿态下」世界系工件点（需工件坐标输入）

---

## 5. 数据流

```text
Cell C URDF + EOAT meshes
        │
        ▼
  位姿解析（工具系）
   · LENS / look / right / up   ← D405 网格或 JSON 覆盖
   · samples[]                 ← 指尖网格极值 / 参数化开合
        │
        ▼
  FOV modes（H×V °）
        │
        ▼
  角域投影 → in_fov / 裕量 /（可选）遮挡
        │
        ├──► JSON API（UI）
        └──► report.md + PNG（存档）
```

**开合：** 一期用「闭合采样 + 开口半宽参数」两套点；不做夹爪关节动画驱动指尖网格（静态 URDF 限制）。

---

## 6. 相机外参如何得到（需拍板）

优先级从稳到省：

| 方案 | 做法 | 精度 |
|------|------|------|
| **A. 配置手填（推荐起步）** | 从 CAD/装配量 `LENS,look,right` 写入 JSON；与 skill 一致 | 高（以 CAD 为准） |
| **B. 网格启发式** | 用 `D405_camera.STL` AABB/主方向估镜头与光轴，再允许 JSON 微调 | 中，需目视核对 |
| **C. 标定回流** | 以后用棋盘格外参写回同一 JSON | 高，本期不依赖 |

计划默认：**A 为主、B 作辅助初值**。Cell C 的 `gripper_rpy=[0,0,π]` 必须乘进外参，与画面 EOAT 一致。

---

## 7. UI / API 草图

**侧栏（P1）**

- 模型：只在 CS66 Cell C（或配置声明 `supports_fov: true`）启用入口  
- 下拉：FOV 档（可多选对比）  
- 滑条/数字：开口 mm（0 = 闭合）  
- 按钮：分析 · 打开报告  
- 结果表：点名 | az | el | 裕量 | 入画 | 遮挡  

**API 响应摘要**

```json
{
  "model_id": "elite_cs66_g26562",
  "modes": [{ "id": "HD87", "in_fov": 8, "total": 10, "recommend": true }],
  "points": [{ "name": "tip_L", "mode": "HD87", "az_deg": 12.1, "el_deg": -3.2, "in_fov": true }],
  "report_url": "/export/fov/.../report.md"
}
```

---

## 8. 目录与归属

| 路径 | 内容 |
|------|------|
| `sensors_arm/fov_*.py` | 解析、投影、报告 |
| `configs/fov/cell_c_d405.json` | Cell C 默认输入 |
| `docs/camera-fov-validation-plan.md` | 本文 |
| `docs/camera-fov.md` | 实现后用户文档 |
| 可选 vendoring | `office_skills/camera-fov-analysis/scripts/analyze_fov.py` 核心 |

不把驱动/相机采集放进 sensors-arm；真机图仅作对照，不进 MVP。

---

## 9. 风险与对策

| 风险 | 对策 |
|------|------|
| STL 推光轴不准 | JSON 强制可覆盖；报告注明「外参来源」 |
| 只校验闭合指尖 | 明确开口参数；文档写清 |
| 与实拍不一致 | 清单：先对一档实拍指尖入画做一次人工对照，再信任几何 |
| 缓存旧 URDF | 已有 `?v=cs66-efg-c65-d405-1`；FOV 配置改版同样 bump |

---

## 10. 建议排期

| 周 | 交付 |
|----|------|
| 1 | 冻结 Cell C `LENS/look/right`（你确认 CAD 或我出网格初值你改）+ `cell_c_d405.json` |
| 1–2 | `fov_analyze` 模块 + CLI + `POST /api/fov/analyze` + MD/PNG |
| 2–3 | 3D 视锥/点着色 + 侧栏（P1） |
| 按需 | 遮挡、多相机、写入 DCS manifest |

---

## 11. 需要你确认的问题

1. **外参**：你能否提供 CAD 里镜头中心与光轴（或接受先用网格启发式 + 你微调 JSON）？  
2. **默认流档**：产线 D405 常用 1280×720 还是 848×480 / 640×480？  
3. **开口**：指尖最大开合行程（mm）要按慧灵 C65 额定哪一档？  
4. **入口**：MVP 是否只需 API/CLI，UI 放到第二期？  
5. **遮挡**：第一期要不要上支架 STL 射线遮挡？

确认后按 §10 开工；算法不另起炉灶，复用 `camera-fov-analysis`。
