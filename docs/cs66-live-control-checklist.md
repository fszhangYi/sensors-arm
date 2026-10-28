# CS66 真机控制检查清单（sensors-arm）

配合 [`cs66.md`](cs66.md)、[`elite-sdk-apis-in-use.md`](elite-sdk-apis-in-use.md)。

## 必须满足

1. **`elite_cs_sdk` 已装进工作区 `.venv`**（非 PyPI `elirobots`）
2. **`dry_run: false`** + 启动 `--no-dry-run`
3. **RTSI 配方**：`configs/rtsi/output_recipe.txt` + `input_recipe.txt`  
   - `sensors_multi.yaml` 里 Cell B/C 的 `require_rtsi: true`  
   - 控制器开放 **30004**，PC 与机器人互通
4. **外控回连**：PC 入站 **50001 / 50003 / 50004**（Windows 防火墙）  
   - 多网卡时设 `params.local_ip` 为机器人能访问的本机地址
5. **示教器**：Remote / 自动；允许 Primary 下发脚本（`headless_mode: true`）

## 安全门（2026-10-28 起）

| 规则 | 行为 |
|------|------|
| live 下禁止 home synth | `ArmAgent` 仅在 `ctx.dry_run` 时合成姿态 |
| 无 measured 关节 | `Arm` / jog / abs / direct write **拒绝** |
| `require_rtsi` | `arm_cs_write.open()` 无 recipe 直接失败 |
| Arm 种子 | 必须读到 `joints_source=rtsi`，写入 `_last_cmd_rad` |
| keepalive 失败 | 自动 Disarm（不再静默 Armed） |

## 操作顺序

```text
连接 → 等三维关节与示教器一致（RTSI）→ Arm → 手动调节 / 绝对下发 → Disarm
```

若 Arm 报 *no measured arm joints*：先查 RTSI 30004 与 recipe 路径（从 `sensors-arm` 目录启动，相对路径 `configs/rtsi/...`）。

若三口同时 EOF：外控脚本因 reverse 超时退出；确认 keepalive 在跑，且未过早 Disarm。

## 示教器 “exceed control speed” / External Control speed limit

原因：相邻两次 `writeServoj` 目标差 ÷ `servoj_time` 超过外控/关节限速（示教器速度比例较低时更易触发）。

处理：
1. 把示教器速度滑条调到合理值（建议先 ≥50% 试）
2. 配置已默认 `stream_max_rad_s: 0.5`（约 29°/s），并会乘 RTSI `speed_scaling`；仍报警可再降到 `0.2`
3. 点动平滑：驱动在 `|last_cmd−RTSI| < cmd_continuity_rad`（默认 0.10 rad）时从指令连续流式下发，避免每次从滞后 RTSI 回抽再前进
4. 绝对斜坡（CS）：每点 `servoj_once`（不再套一层 rate-limited stream + writeIdle）；`max_delta` 相对上一指令点而非滞后 RTSI；默认约 50 Hz。否则会出现「规划几百点却只晃几下」
5. 重启 sensors-arm 使配置生效；点动前先 Arm，等 RTSI 角与示教器一致
