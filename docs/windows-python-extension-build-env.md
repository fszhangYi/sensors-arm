# Windows：为 Python 源码扩展搭建编译环境（技巧、坑、解法）

背景：本工作区为安装 **`elite_cs_sdk`**（pybind11 + CMake + MSVC）搭过一整套环境。下文按「通用技巧」写，例子取自该次实装；专项步骤见：

- [elite-cs-sdk-no-pypi-workaround.md](elite-cs-sdk-no-pypi-workaround.md)
- [elite-cs-sdk-install-log-2026-10-28.md](elite-cs-sdk-install-log-2026-10-28.md)

---

## 1. 你在编什么

典型栈：

```text
MSVC (cl) + CMake + C++ 库依赖 + pybind11 → .pyd + 附属 DLL → pip wheel → 装进指定 venv
```

和「纯 Python 包 `pip install`」的差别：

- 必须有 **与目标 Python 匹配的编译器**（Windows 上即 MSVC，版本不必等于 Python 发行说明里的旧号，但要用能编 C++17 的 VS 2019/2022）。
- wheel 标签绑定 **平台 + CPython 次版本**（如 `cp312-win_amd64`）。
- 依赖库（Boost、Eigen…）要么系统/包管理器提供，要么你自己解压并告诉 CMake。

---

## 2. 推荐工具清单（Windows）

| 组件 | 建议 | 说明 |
|------|------|------|
| VS Build Tools 2022 | 勾选「使用 C++ 的桌面开发」 | 用 `vcvars64.bat` 注入环境，再调 cmake/msbuild |
| CMake | ≥ 3.14；便携目录亦可 | 不必强依赖 winget；坏 zip 会表现为 7zr/Expand 失败 |
| Python | 专用 **venv**，次版本固定 | 编/装/跑同一解释器 |
| pip 构建链 | `setuptools wheel build pybind11 pybind11_stubgen` | 官方 `python_wheel` 常用 `--no-build-isolation` |
| Boost 等 | 源码树或 vcpkg | 弱网优先 **源码 zip + BOOST_ROOT** |
| Git | clone 上游 SDK | FetchContent 再拉依赖时网络最易炸 |

本机落盘示例（勿默认提交 git）：

- `vendor\cmake\`
- `vendor\boost_1_86_0\`
- VS：`...\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat`

---

## 3. 技巧（省时间）

### 3.1 先固定「唯一 Python」

配置阶段显式传入：

```text
-DPython3_EXECUTABLE=C:/.../.venv/Scripts/python.exe
-DPython_EXECUTABLE=...（同上）
-DPYBIND11_FINDPYTHON=ON
```

否则 CMake/pybind11 可能捡到 PATH 上的 miniconda/系统 Python，编出另一 ABI 的 `.pyd`，venv 里 `import` 莫名失败。

### 3.2 能关的插件就关

运动学 / 位姿代数插件会拉 Eigen、orocos-kdl 等。若业务只要通信与 `writeServoj`：

```text
-DELITE_COMPILE_KIN_PLUGIN=OFF
-DELITE_COMPILE_POSE_ALG_PLUGIN=OFF
```

先打通最小闭环，再按需开插件。

### 3.3 用已安装的 pybind11，别再 FetchContent 克隆

弱网下 `GIT_REPOSITORY https://github.com/pybind/pybind11.git` 经常卡死。

```powershell
python -c "import pybind11; print(pybind11.get_cmake_dir())"
```

CMake：

```text
-Dpybind11_DIR=<上面打印的目录>
find_package(pybind11 CONFIG REQUIRED)
```

### 3.4 Boost：完整源码树足够 header-only Asio

许多 SDK 只需 `find_package(Boost REQUIRED)` 找到 `boost/version.hpp`，**不必**先 `b2` 编译全套库（除非选项要求 `Boost::system` 等）。

设置（注意拼写，见坑）：

```bat
set BOOST_ROOT=C:\path\to\boost_1_86_0
cmake ... -DBOOST_ROOT=%BOOST_ROOT% -DBoost_INCLUDE_DIR=%BOOST_ROOT% -DBoost_NO_BOOST_CMAKE=ON
```

### 3.5 大 zip 用 Python 解压

`Expand-Archive` 对数万条目的 Boost zip 极慢；`7zr` 对个别 zip 会报 *Cannot open the file as archive*（即使 .NET `ZipFile` 能读）。更稳：

```python
import zipfile
zipfile.ZipFile(r"boost_1_86_0.zip").extractall(r"vendor")
```

### 3.6 多配置生成器要带 `--config Release`

`Visual Studio 17 2022` 生成器下：

```bat
cmake --build build --config Release --target python_wheel -j 4
```

只写 `cmake --build build` 可能进 Debug，或找不到你期望的输出目录。

### 3.7 编一次，拷 wheel

同 `cpXXX-win_amd64` 的机器可直接 `pip install` 现成 wheel，避免每台重装 VS/Boost。

---

## 4. 坑与解决方案（实装踩过）

| 现象 | 原因 | 解法 |
|------|------|------|
| `pip install elite_cs_sdk` 失败 / 找不到包 | 不在 PyPI | 走源码 `python_wheel` 或安装已有 `.whl` |
| CMake：`Boost_ROOT is not the correct spelling` | CMake 3.31 FindBoost 强制 `BOOST_ROOT` | 改用 **`BOOST_ROOT`** / `-DBOOST_ROOT=` |
| 警告 *Boost_ROOT is set … ignoring* | CMP0074 未开，环境变量名混用 | 统一 `BOOST_ROOT`；需要时再设 policy |
| 找到 Python 3.14，venv 却是 3.12 | PATH 上另有 conda | 强制 `-DPython3_EXECUTABLE=<venv>` |
| FetchContent / `git clone pybind11` 超时 | GitHub 网络 | pip 装 pybind11 + `find_package`；或镜像 zip |
| vcpkg：SSL、代理、工具 zip 损坏、7zr 失败 | 国内弱网 + 引导下载链脆 | **弃用 vcpkg**，本地 Boost + 便携 CMake |
| `7zr` 打不开刚下的 zip，但大小对 | 某些 zip 实现 / 未下完 / 工具限制 | 用 Python/`Expand-Archive` 校验 `ZipFile.OpenRead` |
| `Expand-Archive` 跑十几分钟无 asio.hpp | 慢而非挂 | 换 Python 解压；或等文件出现后再编 |
| `libssh was not found` WARNING | 未装 libssh | 可继续；SSH 相关能力降级，Primary/RTSI 仍可能够用 |
| 大量 C4244/C4267 | SDK 头文件转换告警 | 一般可忽略；以链接与 import 为准 |
| `import elite_cs_sdk` 仍失败 | 装错环境 / 缺 DLL / Debug-Release 混用 | 确认 `pip show` 在同一 venv；检查 site-packages 内 DLL 与 `.pyd` 同目录 |
| 安装器 exit 3010 | VS 组件要重启 | 重启后再跑 `vcvars64` 验证 `cl` |
| PowerShell `$ErrorActionPreference=Stop` + git | git 把进度打到 stderr | 克隆时用 `Continue`，或判 `Test-Path` 而非仅 exit code |

---

## 5. 最小「健康检查」脚本思路

配置成功后应看到类似日志：

```text
-- Found Boost: ... (found version "1.86.0")
-- Found pybind11: ...
-- Found Python3: .../.venv/Scripts/python.exe (found version "3.12.x")
-- Generating done
```

构建成功：

```text
Created wheel for elite-cs-sdk: filename=elite_cs_sdk-...-cp312-cp312-win_amd64.whl
```

运行时：

```powershell
python -c "import elite_cs_sdk; from elite_cs_sdk import EliteDriver; print('ok')"
```

---

## 6. Linux 对照（便于 AutoDL）

| Windows 痛点 | Linux 常见替代 |
|--------------|----------------|
| VS Build Tools | `build-essential` |
| 便携 CMake / winget | `apt install cmake` |
| Boost zip | `libboost-all-dev` |
| vcpkg 拉依赖 | apt / 源码 |
| `vcvars64` | 普通 shell 即可 |

Python 绑定流程相同：本地 `ELITE_CS_SDK_REPO` → `python_wheel` → 装进**同一个** venv。

---

## 7. 维护建议

1. 把 **打好的 wheel** 与「如何复现」文档一起留在工作区（或制品库），新人优先 pip 本地 wheel。
2. 上游 Python SDK 的 CMake 若已支持 `find_package(pybind11)`，及时丢掉临时补丁，减少分叉。
3. 升级 Python 次版本（3.12→3.13）= **必须重编** 扩展包。
