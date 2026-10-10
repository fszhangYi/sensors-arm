# 从 sensors-dcs 拆分说明

`sensors-arm` 只承接机械臂可视化与 gated 控制，便于多品牌/多工位配置，而不拖入采集全栈。

## 迁入

| 来源 (sensors-dcs) | 目标 (sensors-arm) |
|--------------------|--------------------|
| `agents/arm_agent.py` | 同名（包名改为 `sensors_arm`） |
| `agents/arm_write_agent.py` | 同名 |
| `agents/base.py` | 精简保留 |
| `arm_pose.py` | 同名（FK 后台 warm，避免卡 agent） |
| `frame.py` / `buffer.py` | 同名 |
| `static/models/ec616` | 软链接（省磁盘） |
| `static/vendor/three*` / URDFLoader | 拷贝 |
| `static/appearance.css` | 拷贝 |

驱动仍走 `./sensors` → hik-sensors 的 `arm_read` / `arm_write`（Elite）。

## 未迁入

Gello、RealSense、夹爪、录制/episode、export-timeline、pi05、Gello↔Arm sync/teleop、完整鉴权壳、Wine 桌面打包。

## 多臂扩展点

1. `configs/models_catalog.yaml` — 型号 / URDF / 关节映射  
2. `configs/sensors_*.yaml` — 设备与 IP（新品牌需在 hik-sensors 注册 kind）  
3. 启动 YAML `arms:` — UI 卡片与 read/write agent 绑定  
