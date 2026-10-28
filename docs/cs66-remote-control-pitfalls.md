# CS66 远程控制踩坑与解决方案

日期：2026-10-28  
场景：`sensors-arm` 真机遥控 Cell B/C（Elite CS66 + `elite_cs_sdk`）。  
对照控制差异：[`cs66-vs-ec616-control.md`](cs66-vs-ec616-control.md)。  
操作清单：[`cs66-live-control-checklist.md`](cs66-live-control-checklist.md)。

---

## 0. 正确心理模型

EC616 的 TT 是「往透传通道塞关节」；CS66 是：

1. Primary 让控制器跑 **ExternalControl** 脚本  
2. 脚本 **反向连 PC**（50001/50003/50004）  
3. PC 用 **`writeServoj` / `writeIdle`** 喂轨迹  
4. 真机关节反馈靠 **RTSI 30004**（本仓库默认强制）

任一环节断了，表现常常是：连得上但不动、`writeServoj false`、三口 EOF、或示教器速度报警。

---

## 1. SDK / 环境

| 坑 | 现象 | 解决 |
|----|------|------|
| 当成 `elirobots` | `elite_cs_sdk required for arm_cs_write...` | 安装 **`elite_cs_sdk` wheel**（非 PyPI）。见 [`elite-cs-sdk-no-pypi-workaround.md`](elite-cs-sdk-no-pypi-workaround.md) |
| 错 Python / 错 venv | import 成功但运行时另一解释器 | 用工作区 `.venv\Scripts\python.exe` 启动；`import elite_cs_sdk; print(__file__)` 校验 |
| Windows 源码编译 | 缺 MSVC / cmake | 优先用已构建的 `cp312-win_amd64.whl`；编译环境见 [`windows-python-extension-build-env.md`](windows-python-extension-build-env.md) |

---

## 2. 网络与外控握手

| 坑 | 现象 | 解决 |
|----|------|------|
| 防火墙挡反向口 | 偶发连上、随即 EOF；`isRobotConnected()` 假 | PC **入站放行 50001/50003/50004** |
| 多网卡 `local_ip` 错 | 脚本反连到不可达地址 | `sensors_multi.yaml` 设 `params.local_ip` 为机器人可达的本机 IP |
| 示教器未进远程/自动 | 脚本下发失败或立刻退出 | Remote + 自动；允许 Primary 下发脚本（`headless_mode: true`） |
| `script_file_path` 空 | 「script doesn't exist」 | 驱动应回落到 SDK 自带外控脚本；勿指到不存在的绝对路径 |
| Arm 前未上电/未松闸 | 外控 ready 失败 | 驱动默认 `ensure_power`：`powerOn` + `brakeRelease` |
| reverse 读超时 | 50001/3/4 **同时 EOF**，臂不动 | 拉长 `servoj_timeout_ms`（UI 稀疏点动常用 **2000**）；Armed 后靠 **keepalive `writeIdle`**；勿过早 Disarm |

**建议顺序：** 连接 → 三维关节与示教器一致（RTSI）→ **Arm** → 点动/斜坡 → Disarm。

---

## 3. RTSI 与「假关节」

| 坑 | 现象 | 解决 |
|----|------|------|
| 无 RTSI | Arm/jog 拒绝；或旧逻辑用 YAML home 冒充 live | `require_rtsi: true` + `configs/rtsi/*`；控制器开 **30004** |
| recipe 相对路径错 | open 失败 / 无 measured | 从 **`sensors-arm` 目录** 启动，路径相对该 cwd |
| input recipe 含 `speed_slider_*` | `CS RTSI connect failed`；日志 `unknow variable … IN_USE` | 本机 Cell C 用不了这些 input 字段；改用最小 input（如 `input_bit_registers0_to_31`），见 `configs/rtsi/input_recipe.txt` |
| 用 home 当实测 | 三维「有数」但与示教器不符，一点就超速 | **live 禁止 home synth**；无 measured 直接拒绝运动 |

确认 RTSI：读环 `joints_source=rtsi`、`measured=true`；关节角与示教器一致。

---

## 4. `writeServoj` 与速度

| 坑 | 现象 | 解决 |
|----|------|------|
| 单步角差过大 | 示教器 **exceed control speed** / External Control speed limit | 降 `stream_max_rad_s`（默认约 **0.5** rad/s）；示教器速度滑条 **≥50%** 再试；驱动会乘 RTSI `speed_scaling` |
| 每次从滞后 RTSI 重起点 | 点动「回抽再前进」、晃 | `cmd_continuity_rad`（默认 **0.10**）：与 RTSI 接近时从 **`last_cmd` 连续**下发；首次 Arm 后锁存伺服设定点 |
| `writeServoj` 参数个数错 | TypeError / 始终 false | 本 SDK：**3 参** `(pos, timeout_ms, cartesian)`，不要传第 4 个 |
| 未等 `isRobotConnected` | 一写就 false | `ensure_cs_motion_ready` 后再写 |
| 稀疏点动后脚本退出 | 下一次 EOF | 点与点之间靠 timeout + keepalive，不要把 timeout 当成 100 ms 级 dense-only |

脚本侧另有 `JOINT_IGNORE_SPEED`（约 30 rad/s 量级）硬顶；上位机应远低于示教器实际允许速度。

---

## 5. 绝对斜坡「规划很多点，只晃几下」

| 坑 | 现象 | 解决 |
|----|------|------|
| 每点再跑一整段 `_servoj_stream` + `writeIdle` | 422 点规划，实机只顿几下 | CS 斜坡用 **`servoj_once`**（单点 servoj，结束再 idle） |
| `max_delta` 相对 **滞后 RTSI** | 跑几步后 `\|path−RTSI\| > max_delta` 失败 | 斜坡 guard 相对 **上一指令点**；CS dense 路径已改 |
| 斜坡频率过低 + 嵌套限速 | 不丝滑 | CS 默认抬到约 **`cs_ramp_hz: 50`**；点间距已由时长/`max_delta` 约束 |

相关代码：`abs_ramp.py`（`cs_dense`）、`cs_write._servoj_once`。

> **远程连续下发（遥操作）**：曾误走 `_servoj_stream`（嵌套限速 + 每点 `writeIdle`）。**阶段 A 已改为稠密 `servoj_once`**（`timing=teleop/direct` + YAML `servoj_*`）。专题见 **[cs66-remote-teleop-smooth.md](cs66-remote-teleop-smooth.md)**。

---

## 6. TCP 拖拽 IK 慢

| 坑 | 现象 | 解决 |
|----|------|------|
| 首次冷加载 | 第一次拖琥珀球像卡住 | 启动后台 **FK/IK warm**（含一次假 LM）；等日志 `FK/IK warm done` |
| 默认软限位 **TRF + 数值雅可比** | 后续每次 IK 仍很慢 | 拖动走 **`interactive` LM**（无边界），`max_nfev≈80`，`solver_tol=1e-6` |
| 失败升级多 seed × 高 nfev | 拖一下算很久 | 升级仍限 LM + 少量种子；`/api/arm/ik` 放线程池免堵 UI |

正逆解在本地 SciPy + YAML MDH，**不**走 Elite KDL 插件。

---

## 7. Home / 配置

| 坑 | 说明 |
|----|------|
| Home 存的是什么 | UI Home = **`home_joints_rad`（关节弧度）**，不是 TCP pose |
| 配置位置 | `sensors-arm/configs/default.yaml` → 各 `arms[].home_joints_rad` |
| 改完不生效 | 需重启 `sensors-arm`；运行中也可用「设为 Home」写内存（不落盘除非改 YAML） |

---

## 8. 快速排障顺序

```text
1. import elite_cs_sdk 是否在当前 .venv？
2. dry_run=false 且 --no-dry-run？
3. 30001 / 30004 通？PC 入站 50001/3/4？
4. 连接后 joints_source=rtsi 且与示教器一致？
5. Arm 成功后再点动；看 keepalive_error / writeServoj 报错
6. 超速 → 降 stream_max、提高示教器速度比例、确认 continuity
7. 斜坡发飘 → 确认 CS dense servoj_once 代码已加载（重启）
```

---

## 9. 关键配置键（`arm_cs_write`）

| 键 | 作用（摘要） |
|----|----------------|
| `require_rtsi` | 无 RTSI 则拒绝 live 运动 |
| `rtsi_*_recipe` / `rtsi_frequency` | RTSI 配方与频率 |
| `servoj_timeout_ms` | 下一点到达前 reverse 等待（稀疏 UI 宜大） |
| `keepalive_s` / `idle_timeout_ms` | Armed 保活 |
| `stream_max_rad_s` | 稀疏流式峰值角速度 |
| `cmd_continuity_rad` | 与 RTSI 接近时用 last_cmd 防回抽 |
| `max_delta_deg` | 单次指令最大关节步长 |
| `local_ip` | 多网卡时脚本反连地址 |
| `headless_mode` | Primary 下发外控脚本 |

Cell 覆盖见 `configs/sensors_multi.yaml`。
