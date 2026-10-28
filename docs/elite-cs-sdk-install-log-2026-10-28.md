# elite_cs_sdk 安装全流程记录（本机 · 2026-10-28）

日期：2026-10-28  
机器：Windows 10 x64（`win32 10.0.19045`）  
目标：让 `sensors-arm --no-dry-run` 能 `import elite_cs_sdk`，驱动 Cell B/C 的 `arm_cs_write`  
结果：**成功** — `.venv` 中 `elite_cs_sdk-1.0.0-cp312-cp312-win_amd64`

相关文档：

- [pip 装不上时的解决方案](elite-cs-sdk-no-pypi-workaround.md)
- [Windows 上编 Python 原生扩展的环境 / 技巧 / 坑](windows-python-extension-build-env.md)
- 总览：[`cs66.md`](cs66.md)、hik-sensors [`elite-cs-vs-ec.md`](../../sensors/docs/elite-cs-vs-ec.md)

---

## 1. 为何要装

`dry_run: false` 时，CS 系列走 `sensors/drivers/arm/cs_*.py`，启动会执行：

```text
elite_cs_sdk required for arm_cs_write open() when dry_run=false
```

这与 EC 系列的 PyPI 包 `elirobots`（`elite.EC`）**不是同一个包**。`elite_cs_sdk` **不在 PyPI**，官方路径是源码编译 Python 绑定再装 wheel。

---

## 2. 最终产物与校验

| 项 | 路径 / 值 |
|----|-----------|
| 工作区 venv | `C:\Users\user\Desktop\autodl-tmp\.venv` |
| Python | 3.12.15（Anaconda 打包，MSVC） |
| wheel | `vendor\Elite_Robots_CS_SDK_Python\dist\elite_cs_sdk-1.0.0-cp312-cp312-win_amd64.whl`（约 576 KB） |
| 安装位置 | `.venv\Lib\site-packages\elite_cs_sdk\` |
| 插件 | 本次 **未** 编 KIN / Pose 插件（`ELITE_COMPILE_KIN_PLUGIN=OFF` 等）；真机写关节不依赖它们 |

校验命令：

```powershell
C:\Users\user\Desktop\autodl-tmp\.venv\Scripts\python.exe -c "import elite_cs_sdk; print(elite_cs_sdk.__file__)"
```

重装同一 wheel（换机器或清 venv 后）：

```powershell
.\.venv\Scripts\python.exe -m pip install --force-reinstall `
  vendor\Elite_Robots_CS_SDK_Python\dist\elite_cs_sdk-*.whl
```

真机示例：

```powershell
sensors-arm run -c configs\default.yaml --no-dry-run --port 6018
```

---

## 3. 输入材料（本机已有 / 下载）

| 角色 | 路径 |
|------|------|
| C++ SDK 源码 | `C:\Users\user\Downloads\elite_compare\Elite_Robots_CS_SDK-main` |
| Python 绑定源码 | `vendor\Elite_Robots_CS_SDK_Python`（Elite-Robots 官方仓库 clone） |
| 预编译 win_x64 SDK（备用，本次未直接链接） | `vendor\elite-cs-sdk-win\elite-cs-sdk-v1.4.7-win_x64\` |
| Boost 1.86 源码包 | `vendor\boost_1_86_0.zip` → 解压 `vendor\boost_1_86_0\` |
| 便携 CMake 3.31.6 | `vendor\cmake\bin\cmake.exe` |
| MSVC | VS 2022 Build Tools（`vcvars64.bat`） |
| pybind11（pip） | `.venv` 内 `pybind11` 3.1.0，用其 CMake config，**不** FetchContent 拉 git |

官方说明仍以 Python SDK 的 `doc/BuildGuide/` 为准；本记录写的是**本机弱网下实际跑通**的变体。

---

## 4. 时间线（按阻塞顺序）

### 4.1 发现 pip 不可行

- `pip install elite_cs_sdk` / 搜 PyPI：无此发行包。
- 仓库内只有「从源码 `cmake` → `python_wheel` → `pip install dist/*.whl`」。

### 4.2 工具链缺口

| 缺口 | 处理 |
|------|------|
| 无 MSVC | 安装 VS 2022 Build Tools（含 C++ 工作负载）；安装器曾返回 3010（需重启类），之后 `vcvars64` + `cl` 可用 |
| 无系统 CMake | winget / 部分镜像失败；改下便携 zip → `vendor\cmake` |
| vcpkg | clone / bootstrap / 拉 boost-asio 等：GitHub SSL、代理、7zr、损坏的 cmake 工具 zip 反复失败 → **放弃 vcpkg** |
| Boost | 直接下 `boost_1_86_0.zip`（约 208 MiB）；`7zr` 打不开该 zip；`Expand-Archive` 对 ~8.5 万条目极慢；改用 **Python `zipfile.extractall`** |
| pybind11 FetchContent | 官方 CMake 会 `git clone` pybind11，弱网失败；改为 **`find_package(pybind11 CONFIG)`** 指向 pip 包的 `pybind11.get_cmake_dir()` |

### 4.3 对本仓库 CMake 的一处本地修改

文件：`vendor\Elite_Robots_CS_SDK_Python\src\cpp\CMakeLists.txt`

- 去掉 `FetchContent` 拉 pybind11 的逻辑。
- 改为：`find_package(pybind11 CONFIG REQUIRED)`。

（若上游已支持「仅用已安装 pybind11」，可对照官方更新后决定是否保留此补丁。）

### 4.4 Configure（成功参数）

在 **Developer / vcvars64** 环境下（路径按本机）：

```bat
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"

set BOOST_ROOT=C:\Users\user\Desktop\autodl-tmp\vendor\boost_1_86_0

cmake -S vendor\Elite_Robots_CS_SDK_Python -B vendor\Elite_Robots_CS_SDK_Python\build ^
  -G "Visual Studio 17 2022" -A x64 ^
  -DELITE_CS_SDK_REPO=C:/Users/user/Downloads/elite_compare/Elite_Robots_CS_SDK-main ^
  -DELITE_COMPILE_KIN_PLUGIN=OFF ^
  -DELITE_COMPILE_POSE_ALG_PLUGIN=OFF ^
  -DELITE_COMPILE_TESTS=OFF ^
  -DELITE_COMPILE_EXAMPLES=OFF ^
  -DELITE_COMPILE_DOC=OFF ^
  -DBOOST_ROOT=%BOOST_ROOT% ^
  -DBoost_INCLUDE_DIR=%BOOST_ROOT% ^
  -DBoost_NO_BOOST_CMAKE=ON ^
  -DPYBIND11_FINDPYTHON=ON ^
  -DPython_EXECUTABLE=C:/Users/user/Desktop/autodl-tmp/.venv/Scripts/python.exe ^
  -DPython3_EXECUTABLE=C:/Users/user/Desktop/autodl-tmp/.venv/Scripts/python.exe ^
  -Dpybind11_DIR=C:/Users/user/Desktop/autodl-tmp/.venv/Lib/site-packages/pybind11/share/cmake/pybind11
```

要点：

- 变量名必须是 **`BOOST_ROOT`**（不是 `Boost_ROOT`），否则 CMake 3.31 `FindBoost` 直接报错。
- 必须钉死 **venv 的 Python 3.12**；否则 pybind 会误找到本机 `miniconda` 的 3.14，编出的 `.pyd` 无法在 3.12 venv 里 import。
- `libssh` 未装：CMake 仅 WARNING，SSH 走外部命令降级；本机 RTSI/Primary 写关节仍可编过。

### 4.5 Build + 安装

```bat
cmake --build vendor\Elite_Robots_CS_SDK_Python\build --config Release --target python_wheel -j 4

.\.venv\Scripts\python.exe -m pip install --force-reinstall `
  vendor\Elite_Robots_CS_SDK_Python\dist\elite_cs_sdk-1.0.0-cp312-cp312-win_amd64.whl
```

构建大致阶段：编 `elite_cs_series_sdk` 共享库 → 编 `elite_cs_sdk_python.pyd` → 拷贝进临时 package → `pybind11_stubgen` → `pip wheel` → `dist/`。

编库时有大量 C4244/C4267 警告，可忽略；**以 `BUILD_EXIT=0` 与 wheel 生成、import 成功为准**。

---

## 5. 刻意未做 / 可后续补

- 未启用 kinematics / pose algebra 插件（省掉 Eigen、orocos-kdl、更重的 vcpkg）。
- 未把预编译 `elite-cs-sdk-v1.4.7-win_x64` DLL **直接**链进绑定；本次是 **源码同编** C++ SDK + 绑定（版本以 `Elite_Robots_CS_SDK-main` 为准）。
- 未在文档机上做真机 Primary 30001 联调记录（安装完成后由 `--no-dry-run` 现场验证）。

---

## 6. 工作区卫生提示

- `vendor/boost_*`、`vendor/cmake`、大型 zip、Build Tools 安装包：**勿提交进 git**。
- `vendor/Elite_Robots_CS_SDK_Python` 若是独立 clone，保持与上游分离；本地 CMake 补丁单独记在本页。
- 已生成的 **wheel 可拷贝到其它同 ABI 机器**（同 Win amd64 + 同 CPython 3.12），避免每台重编；换 3.11/3.13 必须重编。
