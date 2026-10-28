# elite_cs_sdk：pip 装不上时的解决方案

适用：`sensors-arm` / `sensors-dcs` 真机 CS 臂（`arm_cs_write` / `arm_cs_read`），报错类似：

```text
elite_cs_sdk required for arm_cs_write open() when dry_run=false
```

或：

```text
ModuleNotFoundError: No module named 'elite_cs_sdk'
```

完整本机实装记录见 [install-log-2026-10-28](elite-cs-sdk-install-log-2026-10-28.md)；编译环境细节见 [windows-python-extension-build-env](windows-python-extension-build-env.md)。

---

## 1. 先分清两个「Elite」包

| | EC 系列（如 EC616） | CS 系列（如 CS66） |
|--|--------------------|-------------------|
| hik-sensors kind | `arm_write` / `arm_read` | **`arm_cs_write`** / `arm_cs_read` |
| Python 包 | **`elirobots`**（PyPI 有）→ `import elite` / `elite.EC` | **`elite_cs_sdk`**（**PyPI 无**） |
| 装法 | `pip install elirobots` | 源码编 wheel 再 `pip install *.whl` |

**不要**以为装了 `elirobots` 就能开 CS；也不要搜 `pip install elite_cs_sdk` 指望官方索引有包。

---

## 2. 官方意图（摘要）

上游：

- C++：[Elite_Robots_CS_SDK](https://github.com/Elite-Robots/Elite_Robots_CS_SDK)
- Python 绑定：[Elite_Robots_CS_SDK_Python](https://github.com/Elite-Robots/Elite_Robots_CS_SDK_Python)

流程固定为：

1. 本机准备 **C++ SDK 源码树**（`ELITE_CS_SDK_REPO` 必须是本地路径，不能写 git URL）。
2. `cmake` 配置 Python 绑定工程（Windows 文档常写 vcpkg + Boost/libssh/…）。
3. `cmake --build … --target python_wheel`。
4. `pip install --force-reinstall dist/elite_cs_sdk-*.whl`。

官方 BuildGuide：`Elite_Robots_CS_SDK_Python/doc/BuildGuide/`。

---

## 3. 推荐解决路径（按成本）

### A. 已有同环境 wheel（最快）

若同事 / 本机 `vendor/.../dist/` 已有匹配 wheel：

- 平台：`win_amd64`
- 标签：`cp312`（必须与目标 venv 的 Python **次版本一致**）

```powershell
.\.venv\Scripts\python.exe -m pip install --force-reinstall path\to\elite_cs_sdk-*-cp312-cp312-win_amd64.whl
.\.venv\Scripts\python.exe -c "import elite_cs_sdk; print(elite_cs_sdk.__file__)"
```

本工作区当前产物示例：

`vendor\Elite_Robots_CS_SDK_Python\dist\elite_cs_sdk-1.0.0-cp312-cp312-win_amd64.whl`

### B. 本机源码编译（无现成 wheel 时）

最低需求（真机写关节、**可关** KIN/Pose 插件）：

- Visual Studio 2022 Build Tools（C++）
- CMake ≥ 3.14（本机用过 3.31 便携版）
- Boost 头文件（Asio；可用完整 `boost_1_86_0` 源码树，不必 vcpkg）
- 工作区 Python ≥ 3.10（本机 3.12）+ `pip install setuptools wheel build pybind11 pybind11_stubgen`
- 本地 C++ SDK + Python 绑定源码

弱网时建议：

- **跳过 vcpkg**，`BOOST_ROOT` 指到解压的 Boost。
- **不要**让 CMake `FetchContent` 再 clone pybind11；用 pip 的 `pybind11.get_cmake_dir()`。
- 插件：`ELITE_COMPILE_KIN_PLUGIN=OFF`、`ELITE_COMPILE_POSE_ALG_PLUGIN=OFF`（够用 `EliteDriver.writeServoj` 等）。

可复用本机成功命令见 [install-log §4.4–4.5](elite-cs-sdk-install-log-2026-10-28.md)。

### C. Linux 工控机 / AutoDL

官方 Ubuntu 路径通常更顺：`apt` 装 `libboost-all-dev`、`cmake`、`build-essential`，再按 BuildGuide 编。仍须本地 C++ SDK 路径；编出的是 `manylinux`/`linux_x86_64` 的 wheel，**不能**与 Windows wheel 混用。

---

## 4. 常见误区

1. **`pip install elite` / `elirobots` 冒充 CS SDK** — EC only。
2. **编进了系统 Python，跑的是 venv** — `.pyd` 与解释器 ABI 不一致会 import 失败；始终 `-DPython3_EXECUTABLE=<venv>/python`。
3. **只拷 `.pyd` 不装 wheel** — wheel 还会带上同目录的 C++ SDK DLL、`external_control.script` 等；应用官方 `python_wheel` 打包结果。
4. **Python 小版本不一致** — `cp312` 的 wheel 不能给 3.11/3.13 用。
5. **dry_run 一直为 true** — 装好 SDK 后仍须 YAML `dry_run: false` 且启动加 `--no-dry-run`（见仓库根目录 `启动与密码.txt`）。

---

## 5. 装好后最小验收

```powershell
python -c "from elite_cs_sdk import EliteDriver, EliteDriverConfig; print('ok')"
```

再按 [`elite-sdk-apis-in-use.md`](elite-sdk-apis-in-use.md) 与控制器固件要求做 Primary/RTSI 联调。

---

## 6. 与 sensors 栈的关系

- 驱动与 `kind` 只在 **`sensors`（hik-sensors）**；apps 不 fork SDK。
- `sensors-arm` 只消费已安装的 `elite_cs_sdk`；本目录文档负责 **如何在 Windows 工作区弄到这个包**。
