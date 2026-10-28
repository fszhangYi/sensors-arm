# CS66 远程连续下发（遥操作）抖动问题 — 调研与处理记录

日期：2026-10-28  
状态：**阶段 A 已落地；lookahead=0.25 仍不够丝滑；阶段 B / 其它杠杆待选**  
范围：`sensors-arm` UI「远程连续下发」→ CS66（`arm_cs_write` / `writeServoj`）  
相关：

- [CS66 vs EC616 控制方式](cs66-vs-ec616-control.md)（TT vs ExternalControl）
- [CS66 远程控制踩坑](cs66-remote-control-pitfalls.md)（`servoj_once` / `writeIdle` / continuity）
- [真机控制检查清单](cs66-live-control-checklist.md)
- Gello 源：`gello` 上位机 `GET /joints`（标定角）
- 外部参考：UR `servoj` 手册 / [Trajectory improvements for servoj()](https://www.universal-robots.com/articles/ur/programming/trajectory-improvements-for-servoj/)（CS ExternalControl 语义近 UR）

---

## 1. 问题陈述

### 1.1 现象

在 Cell C（CS66）上：

1. 拉取 Gello 远程 `joints`（如 `http://127.0.0.1:7020/joints`）
2. 预下发通过后，点击 **「远程连续下发」**
3. 臂能跟着动，但 **明显抖动 / 顿挫**，不像 EC616 上 TT 遥操作那样丝滑

用户判断：当前实现像是把远程点位 **一帧一帧生硬塞给机械臂**；EC616 则靠 **TT + 缓存池** 吃流，手感平滑。

### 1.2 目标

在 CS66 上实现与「密集跟点遥操作」同等级的丝滑度：

- 源：远程实时 joints（Gello 等）
- 汇：CS66 ExternalControl + `writeServoj`
- 约束：不虚构 EC 的 TT API；在 CS SDK 能力内找对等范式

---

## 2. 背景：远程连续下发是怎么来的

| 时间线 | 内容 |
|--------|------|
| 此前 | UI「远程下发」= 预检锁存一帧 → `POST /api/arm/command` + `timing=scale_by_d` → **abs-ramp 多点斜坡**（一次性到位，不是遥操作） |
| 2026-10-28 需求变更 | 改名为 **「远程连续下发」**：点击后把 **实时** 远程 joints 连续写臂；再点停止 |
| 前端实现 | `viz.py`：`remoteStreaming`；每帧 `applyRemoteFrame` → HTTP 写臂；latest-wins 排队 |
| 初版写路径 | `timing: 'direct'` → **误走** `_servoj_stream`（嵌套限速 + 每点 `writeIdle`）→ 抖 |

即：产品语义已是 **遥操作**；抖的是 **写路径选型错误**。

---

## 3. EC616 为何丝滑（对照）

```text
Arm → TT_init(t≈2, …)     # 控制器侧轨迹/缓冲（口语「缓存池」）
循环 → TT_add_joint(deg)   # 上位机只往池里推目标
```

要点：控制器消化缓冲并插补；上位机不必为每一跳再套一层限速小斜坡。详见 [cs66-vs-ec616-control.md](cs66-vs-ec616-control.md)。

---

## 4. CS66 对等能力

**CS66 没有 TT。** 功能上最接近「连续透传」的是：

```text
ExternalControl 常驻
循环 → writeServoj(q, timeout_ms)   # 稠密单点 = _servoj_once
空闲 → writeIdle（keepalive）；运动中勿每点 idle
平滑 → servoj_time / servoj_lookahead_time / servoj_gain
连续 → _last_cmd + cmd_continuity_rad
```

**错误路径** `_servoj_stream`：按 `stream_max_rad_s` 拆多步 + `sleep` + **结束 `writeIdle`** → 遥操作每帧走这条就会顿挫。

---

## 5. 根因定位

```text
浏览器 remoteStreaming
  → POST /api/arm/command { joints_rad, timing: "direct"|"teleop" }
  → runtime.arm_command
  【修复前】writer.command(joints_rad) 无 servoj_once
           → cs_write → _servoj_stream → 抖
  【修复后】CS: writer.command(servoj_once=True, relative_to_last=True, idle_after=False)
           → _servoj_once → 稠密 writeServoj；平滑交给脚本 servoj_* 参数
```

---

## 6. 处理方案

### 阶段 A — 稠密 writeServoj（**已落地 2026-10-28**）

| 改动 | 说明 |
|------|------|
| `runtime.py` | `timing in (direct, immediate, step, teleop)` 且 `kind=arm_cs_write` → `servoj_once=True`、`relative_to_last=True`、`idle_after=False`；EC 仍走 TT 单点 |
| `viz.py` | 远程连续下发 body 使用 `timing: 'teleop'`；提示文案标明 servoj_once |
| `sensors_multi.yaml` | `defaults.arm_cs_write` 与 arm-b/c 显式写出 `servoj_time` / `servoj_lookahead_time` / `servoj_gain` |

响应字段：成功时 CS 路径带 `"write_path": "cs_servoj_once"`、`"servoj_once": true`。

验收建议：

1. 重启 sensors-arm，重新连接 Cell C → Arm → 拉取 → 预下发 → 远程连续下发  
2. 网络面板或日志确认命令返回 `servoj_once: true` / `write_path: cs_servoj_once`  
3. 示教器侧应无「每点顿一下再 idle」的手感  
4. Lookahead：工位 YAML 现为 **`servoj_lookahead_time: 0.25`**（曾试 0.1 偏顿、0.4 偏钝；定 0.25）。仍卡可做阶段 B 或微调 0.2–0.3  



### 阶段 B — 丝滑增强（**未做**）

1. 后端定点频写线程（50–125 Hz）latest-wins，与浏览器 RTT 解耦  
2. 相对 `_last_cmd` 速率裁剪，减少 `max_delta` 硬拒断流  
3.（可选）WS 上行专用 teleop 通道  

### 阶段 C — 非目标

- 不在 CS 上模拟 `TT_init`  
- 不把遥操作改回 abs-ramp  
- 不把 DH 夹爪混进 Gello `/gripper`  

---

## 6.1 2026-10-28 续：lookahead=0.25 仍不够时的其它杠杆（调研）

> 结论先行：**继续拧 lookahead 边际收益有限**（UR 官方常用区间约 **0.03–0.2 s**，0.25 已略超）。下一批应优先动 **设定点节奏 / 架构**，其次才是 `gain` / `servoj_time` / 源滤波。

### 当前链路（卡顿来源）

```text
Gello /joints (≈20–50 Hz, 有噪声)
  → 浏览器 SSE/poll
  → 每帧 POST /api/arm/command  (串行等 RTT；in-flight 时 latest-wins)
  → runtime teleop → writeServoj(servoj_once)
  → 控制器 servoj(t=0.008, lookahead=0.25, gain=300)
并行：Armed keepalive 仍可能偶尔抢到 _io_lock 插入 writeIdle
```

UR 明确警告：**设定点更新频率低或噪声大时，高 gain / 短 lookahead 会振**；  
更新过慢时机器人会在目标附近减速再等下一点 → **顿挫**（与「一帧一帧塞」体感一致）。  
EC 丝滑靠 TT **控制器侧缓冲吃流**；CS 没有对等池，**PC 侧设定点必须密且稳**。

### 杠杆优先级（建议）

| 优先级 | 杠杆 | 作用 | 代价 / 注意 |
|--------|------|------|-------------|
| **P0** | **后端定点频写线程**（阶段 B.1） | 浏览器只更新「最新目标」；Python 以固定 50–125 Hz `writeServoj`，与 HTTP RTT 解耦 → 最接近 EC「池」 | 开发量中；需与 keepalive / Arm 门控协调 |
| **P0** | **遥操作期抑制 keepalive `writeIdle`** | 稠密 servoj 时若插入 idle，等于打断连续设定点（文档早已写「运动中勿每点 idle」） | 改小：`stream_latched` 或「最近 N ms 有过 servoj」则跳过 idle；超时仍要 idle 保外控 |
| **P1** | **对齐 `servoj_time` 与真实写频** | 现 `t=0.008`（125 Hz 语义）；若实际只有 ~15–30 Hz HTTP，则 t 与到达率不匹配 → 易顿。后端写线程后：`t ≈ 1/write_hz`（可试 **0.008→0.01/0.016** 或升到 **0.002** 若能稳住 100 Hz+） | 须与写线程一起改，单改 t 收益不定 |
| **P1** | **微调 `servoj_gain`** | 低更新率：试 **200–250** 减振；高密稳流后可回到 **300–500** 跟手 | 过高 + 噪声源 = 抖 |
| **P2** | lookahead 微调 | 官方上限常写 **0.2**；可试 **0.20**；再往上（>0.3）多半更钝而非更丝滑 | 已试 0.1/0.4/0.25，别再当主手段 |
| **P2** | **源侧滤波**（Gello joints EMA / 1€ filter） | 降设定点噪声，减轻 servoj P 项追噪 | 增加跟踪滞后 |
| **P2** | **相对 `_last_cmd` 速率软裁剪**（阶段 B.2） | 大跳变时插值/限速而非 `max_delta` 硬拒断流 | 急停语义要保留 |
| **P3** | WebSocket teleop 上行 | 降浏览器→后端延迟抖动 | 在有写线程后收益变小 |
| **P3** | 控制器脚本侧 waypoint buffer | UR 文章对**有界轨迹**推荐；**无界遥操作**要闭环控缓冲深度，且 Elite `writeServoj` 更偏「最新设定点」 | 复杂；非首选 |

### 不建议再做的

- 把遥操作改回 `_servoj_stream` / abs-ramp（已证更抖）  
- 在 CS 上假扮 `TT_init`  
- 只靠把 lookahead 拧到 0.4+「更平滑」（体感钝、跟手差）

### 建议落地顺序

1. **先验证**：连续下发时 DevTools 看 `/api/arm/command` 实际 Hz 与 RTT；日志/`write_ms`；是否偶发 `writeIdle`（keepalive）。  
2. **小改**：遥操作 / `stream_latched` 期间跳过 keepalive idle。  
3. **主改**：后端 50–125 Hz latest-wins 写线程 + 匹配 `servoj_time`。  
4. **精调**：`gain`、源滤波、软限速。

---

## 7. 过程与结果日志

| 日期 | 动作 | 结果 |
|------|------|------|
| 2026-10-28 | 「远程下发」→「远程连续下发」+ `timing=direct` | 成为遥操作；实机 **抖动明显** |
| 2026-10-28 | 对照 EC TT vs CS servoj；追踪调用链 | **根因**：direct 未走 `servoj_once`，每帧 `_servoj_stream` + `writeIdle` |
| 2026-10-28 | 建立本文档；方案拆 A/B | 文档就绪，代码未改 |
| 2026-10-28 | **阶段 A 落地**：runtime CS direct/teleop → `servoj_once`；YAML 显式 servoj_*；更新本文 | **代码已合入本仓** |
| 2026-10-28 | 实机反馈：比 `_servoj_stream` **好太多**，仍略卡；回忆 EC lookahead ≈ **400 ms** | 曾设 `servoj_lookahead_time` **0.1 → 0.4** |
| 2026-10-28 | 用户指定 lookahead | 改为 **`0.25`**（defaults + arm-b/c） |
| 2026-10-28 | 实机：0.25 好一些仍不达标；调研其它杠杆 | 写入 §6.1；主因指向 **设定点节奏/架构**，非再拧 lookahead |

### 结果摘要

| 项 | 状态 |
|----|------|
| 问题可复现路径 | 已记录 |
| 根因（阶段 A） | 已确认：曾误走 `_servoj_stream` |
| 阶段 A（稠密 servoj_once + servoj_* 参数） | **已实现** |
| Lookahead | **0.25 s**；再调 **非主路径** |
| 阶段 B（后端写线程） | 未做 → **下一优先** |
| Keepalive 与稠密 servoj 争用 | **已标为 P0 嫌疑**（§6.1） |
| 实机丝滑验收 | 阶段 A+0.25 改善但 **未达标** |

---

## 8. 涉及文件索引

| 文件 | 角色 |
|------|------|
| `sensors-arm/src/sensors_arm/viz.py` | 远程连续下发 UI；`timing: teleop` |
| `sensors-arm/src/sensors_arm/runtime.py` | direct/teleop → CS `servoj_once` |
| `sensors-arm/src/sensors_arm/agents/arm_write_agent.py` | `servoj_once` 透传 |
| `sensors-arm/configs/sensors_multi.yaml` | `servoj_time` / `lookahead` / `gain` |
| `sensors/src/sensors/drivers/arm/cs_write.py` | `_servoj_once` / `_servoj_stream` |
| `sensors/src/sensors/drivers/arm/_cs_sdk.py` | 将 servoj_* 写入 EliteDriver cfg |
| `sensors/src/sensors/drivers/arm/elite_write.py` | EC TT（对照） |
| `sensors-arm/src/sensors_arm/abs_ramp.py` | CS dense 斜坡同样用 `servoj_once` |

---

## 9. 一句话

**EC 遥操作 = TT 池吃点；CS 遥操作 = 稠密 `servoj_once` 流吃点 + 控制器 `servoj_*` 平滑。**  
阶段 A 已把连续下发从 `_servoj_stream` 改到 `_servoj_once`；若仍不够丝滑，再做阶段 B 后端定点频缓存池。
