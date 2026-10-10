# 绝对点位下发（从 sensors-dcs 迁入）

与 DCS `arm_abs_ramp` / Infer「下发」同语义：

1. 须先 **Arm**
2. 读当前关节 `q_a`，目标 `q★`
3. `d = max_i |q★_i − q_a_i|`
4. `T = clamp(d / v_norm, t_min, t_max)`（`timing=scale_by_d`）
5. `N = round(T × ramp_hz)`，按 profile（默认 **seven_segment**）生成 α(u)，关节空间插值
6. 每点 `writer.command(joints_rad=…, reference_joints_rad=…)`

实现：[`abs_ramp.py`](../src/sensors_arm/abs_ramp.py)。配置：`arm_abs_ramp:`（见 `configs/default.yaml`）。

UI：右侧「绝对下发」；双击 `joints` 填当前角；下发中按钮变为「取消」。Home 走同一斜坡。

未迁入：夹爪联写、Gello bias、Gello sync/teleop 闸。
