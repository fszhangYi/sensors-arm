# sensors-arm

从 **sensors-dcs** 拆出的**机械臂可视化与控制**子系统：只保留 `arm` / `arm_write`，风格对齐 DCS（teal lab UI、YAML 配置、hik-sensors 驱动）。

## 依赖布局

```text
sensors-arm/
  sensors -> ../sensors          # hik-sensors 软链接（Elite arm_read / arm_write）
  configs/
    default.yaml                 # 多臂示例
    models_catalog.yaml          # 型号目录（品牌 / URDF / 关节映射）
    sensors_multi.yaml
  src/sensors_arm/
```

运行时把 `./sensors/src` 插到 `sys.path` 最前（与 DCS 相同）。

## 安装

```bash
cd /path/to/workspace
git clone <sensors> && git clone <sensors-arm>   # 或拷贝本目录
cd sensors-arm
ln -sfn ../sensors ./sensors

python3 -m venv .venv && source .venv/bin/activate
pip install -U pip
pip install -e ../sensors
pip install -e .
# 真机 Elite：
pip install -e ".[elite]"
# FK/IK：
pip install -e ".[kinematics]"
```

## 快速开始（dry-run 双臂）

```bash
sensors-arm run -c configs/default.yaml
# → http://127.0.0.1:6008/
```

左侧切换 **Cell A · EC616**（`arm_write` / elirobots）与 **Cell B · CS66**（`arm_cs_write` / elite_cs_sdk）。  
切换型号只换展示；**「连接 / 断开」按臂手动开会话**，启动时不会自动连所有臂。  
读侧可 **复制 joints / pose**，或「填入下发」/双击 joints 标签；IP 只读显示（EC:54321 / CS:30001）。  
写通道：连接 → `Arm` → 点动 / **绝对下发（插值斜坡）** / `Home`。  
绝对下发语义同 sensors-dcs（`T=clamp(d/v_norm,…)` + 七段 jerk），见 [docs/arm-abs-ramp.md](docs/arm-abs-ramp.md)。  
型号说明：[docs/cs66.md](docs/cs66.md)、[docs/ec66.md](docs/ec66.md)。

单臂：

```bash
sensors-arm run -c configs/single_elite.yaml
```

## 多款机械臂配置

1. 在 `configs/models_catalog.yaml` 增加型号（`brand` / `product` / `urdf` / 关节 offset·signs）。  
2. 在 `sensors_*.yaml` 增加设备（当前后端主要为 Elite `arm_write` / `arm_read`；新品牌需在 hik-sensors 注册 kind）。  
3. 在启动 YAML 的 `arms:` 列表里挂 `model` + `read_agent` / `write_agent`。

```yaml
arms:
  - id: arm-a
    label: "Cell A · EC616"
    model: elite_ec616
    read_agent: arm-a-read
    write_agent: arm-a-write
  - id: arm-b
    label: "Cell B · CS66"
    model: elite_cs66
    read_agent: arm-b-read
    write_agent: arm-b-write
```

URDF 放在 `src/sensors_arm/static/models/<name>/`，`urdf` 填 `/assets/models/...`。

## API（摘要）

| 路径 | 说明 |
|------|------|
| `GET /api/status` | 配置 + arms 描述 + agent 统计 |
| `GET /api/arms` | 多臂型号 / URDF 元数据 |
| `POST /api/arm/command` | Arm / Disarm / joints / jog |
| `POST /api/arm/home/set\|go` | Home |
| `POST /api/arm/ik` | TCP xyzrpy → joints |
| `WS /ws` | 实时 frames |

## 与 sensors-dcs 的边界

| 保留 | 未纳入（仍在 DCS） |
|------|-------------------|
| ArmAgent / ArmWriteAgent | Gello、相机、夹爪、录制、后处理 |
| Elite 驱动（经 sensors） | Gello→Arm sync/teleop、pi05 |
| FK/IK（arm_pose） | 完整采集 Tab / 鉴权壳（可后续再接） |
| EC616 / CS66 / EC66 URDF 展示 | 桌面 Wine 打包 |

## License

Apache-2.0
