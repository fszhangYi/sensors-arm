# CS66 与 EC616 控制方式对比

日期：2026-10-28  
范围：本工位 `sensors-arm` + hik-sensors 驱动（Cell A = EC616，Cell B/C = CS66）。  
相关：[`elite-sdk-apis-in-use.md`](elite-sdk-apis-in-use.md)、[`cs66.md`](cs66.md)、[`cs66-remote-control-pitfalls.md`](cs66-remote-control-pitfalls.md)。

---

## 1. 一句话

| 系列 | 控制范式 | 本仓库驱动 |
|------|----------|------------|
| **EC616** | 控制器 **TT 透传**（`TT_init` + `TT_add_joint`） | `arm_write` / `arm_read`（`elirobots` → `elite.EC`） |
| **CS66** | 示教器 **ExternalControl 外控** + 反向口 **`writeServoj`** | `arm_cs_write` / `arm_cs_read`（`elite_cs_sdk` → `EliteDriver`） |

**CS66 没有 EC 的 TT 透传。** 远程跟随时，功能上最接近 TT 的是连续 `writeServoj`，但握手、超时、速度门限与反馈通道完全不同。

---

## 2. 对照表

| 项 | EC616（Cell A） | CS66（Cell B / C） |
|----|-----------------|---------------------|
| hik-sensors `kind` | `arm_write` / `arm_read` | **`arm_cs_write`** / `arm_cs_read` |
| Python SDK | PyPI **`elirobots`** | **`elite_cs_sdk`**（非 PyPI，需 wheel/源码） |
| 主连接 | TCP **54321** + monitor **8056** | Primary **30001** |
| 关节反馈 | `monitor_info.machinePos` 等 | **RTSI 30004**（真机默认 `require_rtsi: true`） |
| 流式写关节 | `TT_add_joint`（**度**） | `writeServoj(pos, timeout_ms, cartesian=False)`（**弧度**） |
| 进入运动前 | `robot_servo_on` / `set_servo_status` / **`TT_init`** | `powerOn` + `brakeRelease` + **`sendExternalControlScript`** |
| PC 入站端口 | 一般无反向监听 | **50001 / 50003 / 50004**（脚本反连 PC） |
| UI「Arm」 | 开 TT / 伺服门控 | 等 RTSI measured → 种子 `_last_cmd` → 外控就绪 + keepalive |
| 点动 / 斜坡 | 直接 TT 加点 | servoj 流式或 `servoj_once`（稠密斜坡） |
| 单位注意 | 驱动层常用度 | SDK / 本驱动统一用弧度 |
| FK/IK 包 | `sensors.kinematics`（EC616 DH） | `cs66_kinematics` / `cs66_kin_g26562`（示教 MDH） |

---

## 3. 控制链路（概念）

### EC616 · TT

```text
PC ──TCP 54321──► EC 控制器
                    │
                    ├─ TT_init / TT_add_joint  ← 透传关节流
                    └─ monitor 8056 ──► PC 读角
```

特点：通道相对「长连接推流」；点动一次 ≈ 往 TT 里塞一个目标。没有 ExternalControl 脚本反连 PC 的那套超时语义。

### CS66 · ExternalControl + servoj

```text
PC ──Primary 30001──► CS 控制器（可下发外控脚本）
PC ◄──50001/50003/50004── 脚本反向连 PC（EliteDriver reverse）
PC ──RTSI 30004──► 读 actual_joint_positions 等

运动：写侧 EliteDriver.writeServoj / writeIdle
门控：无 RTSI measured → 拒绝 Arm / jog / abs
```

特点：必须先让外控脚本跑起来并保持 reverse 不超时；稀疏点动要靠较长 `servoj_timeout_ms` + keepalive `writeIdle`；稠密斜坡应用单点 `servoj_once`，避免「每点再套一层 rate-limited stream」。

---

## 4. 配置落点（本仓库）

| | EC616 | CS66 |
|--|-------|------|
| 设备 YAML | `sensors_multi.yaml` → `kind: arm_write` | `kind: arm_cs_write` |
| 臂 UI / home | `configs/default.yaml` → `arm-a` | `arm-b` / `arm-c` |
| 运动学 | 默认 `sensors.kinematics` | `kinematics: cs66_*` + `kinematics_profile` |
| RTSI recipe | 无 | `configs/rtsi/output_recipe.txt` 等 |

---

## 5. 选型注意

- 工位标牌是 **CS / ES66** → 走 CS SDK，**不要**装错成只用 `elirobots`。  
- 工位是 **EC616 / EC66** → 走 TT，**不要**用 `arm_cs_write`。  
- 两套驱动都在 hik-sensors；上层 `sensors-arm` 用同一套 Arm / jog / 斜坡 UI，但底层命令语义不同（见踩坑文档）。
- Gello「远程连续下发」属 CS 侧遥操作：勿套 TT 思维；稠密 `servoj_once` 与抖动根因见 **[cs66-remote-teleop-smooth.md](cs66-remote-teleop-smooth.md)**。

---

## 6. 相关代码

| 角色 | 路径 |
|------|------|
| EC 写 | `sensors/src/sensors/drivers/arm/elite_write.py` |
| CS 写 | `sensors/src/sensors/drivers/arm/cs_write.py` |
| CS SDK 封装 | `sensors/src/sensors/drivers/arm/_cs_sdk.py` |
| 斜坡 | `sensors-arm/src/sensors_arm/abs_ramp.py` |
| 真机清单 | [`cs66-live-control-checklist.md`](cs66-live-control-checklist.md) |
