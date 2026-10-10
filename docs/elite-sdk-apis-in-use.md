# Elite SDK：当前实际用到的接口

日期：2026-10-10  
说明：FK/IK（`sensors.kinematics` / `cs66_kinematics` + YAML）**不调用** Elite SDK。SDK 只挂在 hik-sensors 的读写驱动上，做连机、读角、流式下发。

---

## 1. EC 系列 · `elirobots` → `elite.EC`

路径：`sensors/drivers/arm/elite_{read,write}.py`、`_elite_monitor.py`  
配置：Cell A · `arm_write` / `arm_read` · 端口 54321 + monitor 8056

| 用途 | API |
|------|-----|
| 连接 | `EC(ip=..., auto_connect=True)` |
| 监视线程 | `monitor_thread_run()` / 停监视（`monitor_run_state=False` 等） |
| 读关节 | `monitor_info.machinePos` |
| Arm | `robot_servo_on()`、`set_servo_status(1)`、`TT_init(...)`；必要时 `stop()` |
| 流式写关节 | `TT_add_joint(deg)` |
| Disarm | `stop()` |

---

## 2. CS 系列 · `elite_cs_sdk`

路径：`sensors/drivers/arm/cs_{read,write}.py`、`_cs_sdk.py`  
配置：Cell B · `arm_cs_write` / `arm_cs_read` · Primary 30001 / RTSI 30004

| 用途 | API |
|------|-----|
| 配置/建连 | `EliteDriverConfig`、`EliteDriver(cfg)` |
| 外控脚本 | `sendExternalControlScript()` |
| 连通检查 | `isRobotConnected()` |
| 流式写关节 | `writeServoj(joints_rad, timeout_ms, cartesian=False, queue=False)` |
| 空闲/停止 | `writeIdle(...)`、`stopControl(...)` |
| RTSI 读角 | `RtsiIOInterface(...)`、`connect` / `disconnect`、`getActualJointPositions()` |

---

## 3. 明确未用（运动学侧）

- 无 `KdlKinematicsPlugin` / SDK 内置 FK·IK  
- `cs66_kinematics` 里的 `elite_mdh` 只是自研 MDH 公式命名，不 import SDK  

**边界**：SDK = 关节 IO；正逆解 = 本地 SciPy + YAML DH。
