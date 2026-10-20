# Star Arm 102 → Lumos Python 遥操作

使用 Star Arm 102 主臂实时控制 Lumos 单臂

程序通过 Star Arm UART 和 Lumos CAN 通信，不依赖 LeRobot。客户操作步骤见 [操作指南](docs/StarArm102_Lumos_Python_Teleoperation_Guide.md)。

## 硬件与环境

- Ubuntu 20.04 / 22.04 / 24.04 主机
- Python 3.10（推荐版本）
- Star Arm 102 主臂及 UART/USB 连接
- Lumos 单臂及已配置为 1 Mbps 的 CAN 接口（默认 `can0`）
- `git` 和 `sudo` 权限，以及可访问 GitHub 和 PyPI 的网络

## 安装

先准备并激活 Python 3.10 环境。若使用 Conda：

```bash
conda create -n stararm102-lumos python=3.10 -y
conda activate stararm102-lumos
```

下载本项目并运行一键安装脚本：

```bash
git clone https://github.com/VincentHSS/stararm102-lumos-teleop.git
cd stararm102-lumos-teleop
bash scripts/install_ubuntu.sh
```

脚本会安装 Lumos SDK 所需的系统构建依赖、StarArm Python 包和 Lumos Python 依赖；然后自动从 Lumos 官方仓库下载 StarTouch SDK 到项目目录 `.dependencies/startouch_sdk` 并完成安装。客户不必手动打开 Lumos 安装文档或进入 SDK 源码目录。脚本使用当前激活的 Python 环境；首次运行需要联网及 `sudo` 权限。

### 手动安装（用于排错）

在项目根目录、已激活的 Python 3.10 环境中依次执行。以下命令和一键脚本执行相同的依赖安装：

```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake pkg-config libeigen3-dev libyaml-cpp-dev liborocos-kdl-dev libtinyxml2-dev pybind11-dev

python -m pip install --upgrade pip setuptools wheel
python -m pip install pyserial fashionstar-uart-sdk

mkdir -p .dependencies
if [ ! -d .dependencies/startouch_sdk ]; then
  git clone --depth 1 https://github.com/lumos-open/startouch_sdk.git .dependencies/startouch_sdk
fi
python -m pip install -r .dependencies/startouch_sdk/requirements.txt
python -m pip install .dependencies/startouch_sdk
```

安装完成后验证接口：

```bash
python -c "import serial, fashionstar_uart_sdk; from startouchclass import SingleArm; print('SDK OK')"
```

> 安装脚本会自动从 [Lumos 官方 StarTouch SDK 仓库](https://github.com/lumos-open/startouch_sdk) 获取并安装 SDK。

## CAN 接口

检查接口：

```bash
ip -details link show can0
```

如果接口尚未启用，再配置为 1 Mbps：

```bash
sudo ip link set can0 up type can bitrate 1000000
```

若提示 `Device or resource busy`，先再次查看接口状态；如果 `can0` 已经是 `UP`，不需要重复设置。串口名称不确定时运行 `ls -l /dev/ttyUSB*`，并在后续命令中替换默认的 `/dev/ttyUSB0`。

## 首次校准

确认急停可用、工作区域畅通，并让两台机械臂处于安全且相互对应的参考姿态。校准会连接 Lumos SDK（SDK 连接会使能电机），采集 StarArm 关节范围并保存参考位置；不会下发运动目标。

```bash
python stararm102_lumos_teleop.py --calibrate --can can0 --leader-port /dev/ttyUSB0 --gripper
```

校准文件默认保存在 `~/.config/stararm102_lumos/calibration.json`。若不使用夹爪，从校准和后续命令中一并删除 `--gripper`。

### SDK 配置文件找不到

Lumos SDK 初始化需要源码目录内的 `src/config/robot_kinematics.yaml`。安装后请保留 `.dependencies/startouch_sdk` 目录；脚本会自动定位这份配置，并在 SDK 目录中完成初始化，再恢复启动目录。不要把 YAML 单独复制到项目根目录或 `site-packages`。

SDK 位于其他位置时，在运行命令中指定源码根目录：

```bash
python stararm102_lumos_teleop.py --calibrate --can can0 --leader-port /dev/ttyUSB0 --gripper --sdk-root /实际路径/startouch_sdk
```

若仍使用旧脚本，可以先从 SDK 目录启动，脚本路径填写为绝对路径：

```bash
PROJECT_DIR="$PWD"
test -f "$PROJECT_DIR/.dependencies/startouch_sdk/src/config/robot_kinematics.yaml"
cd "$PROJECT_DIR/.dependencies/startouch_sdk"
python "$PROJECT_DIR/stararm102_lumos_teleop.py" --calibrate --can can0 --leader-port /dev/ttyUSB0 --gripper
```

## 先预览，再执行

不带 `--execute` 时程序只显示输入，不向 Lumos 下发运动目标；默认开启的 HD 按钮仍会控制 StarArm 主臂悬停/释放：

```bash
python stararm102_lumos_teleop.py --can can0 --leader-port /dev/ttyUSB0 --gripper
```

确认关节映射和方向正确后才运行执行模式：

```bash
python stararm102_lumos_teleop.py --can can0 --leader-port /dev/ttyUSB0 --gripper --execute
```

如果串口不是 `/dev/ttyUSB0`，替换为实际设备名。夹爪方向相反时，在预览和执行命令中都增加 `--invert-gripper`。使用 `Ctrl+C` 正常停止；发生卡滞、碰撞或持续力矩报警时，立即停止并使用硬件急停。

## 命令行参数说明

这些参数写在 `python stararm102_lumos_teleop.py` 后面。不填写时使用默认设置，可用 `python stararm102_lumos_teleop.py --help` 查看当前脚本支持的参数。

| 参数 | 默认设置 | 意思与用途 |
| --- | --- | --- |
| `--leader-port /dev/ttyUSB0` | `/dev/ttyUSB0` | Star Arm 主臂连接的串口。电脑上的串口名称不同时，用这个参数指定实际设备。 |
| `--can can0` | `can0` | Lumos 使用的 CAN 接口名称。它只选择接口，不负责配置 CAN 波特率或启用接口。 |
| `--sdk-root /路径/startouch_sdk` | 自动查找 | 指定 Lumos SDK 源码根目录。目录下必须有 `src/config/robot_kinematics.yaml`；遇到配置文件找不到时使用。不能填写 YAML 文件本身或 `src/config` 目录。 |
| `--calibrate` | 不进行校准 | 记录两臂参考姿态、主臂关节范围及可选夹爪范围，保存后退出。首次使用或更换映射时使用；不会下发运动目标，但连接 Lumos SDK 会使能电机。 |
| `--calibration-file /路径/calibration.json` | `~/.config/stararm102_lumos/calibration.json` | 指定校准文件。不同设备或不同校准可各存一份；校准与遥操作应使用同一文件。校准模式会覆盖该文件。 |
| `--joint-map 0,1,2,3,4,5` | `0,1,2,3,4,5` | 从左到右指定 Lumos 关节 1～6 对应的 StarArm 舵机 ID。必须是 0～5 的不重复排列；改变的是关节顺序，不是运动方向，修改后需要重新校准。 |
| `--gripper` | 不控制夹爪 | 启用 StarArm 舵机 6 到 Lumos 夹爪的映射。启用后校准会记录开合范围；校准、预览和执行时须使用相同设置。 |
| `--invert-gripper` | 不反转 | 反转夹爪开合方向。主臂闭合而从臂张开时使用；只有启用 `--gripper` 才有作用，不改变六个关节的方向。 |
| `--execute` | 预览模式 | 向 Lumos 下发关节和可选夹爪目标。不带此参数只显示目标；预览仍会连接 SDK，默认开启的 HD 按钮也仍控制主臂锁定/释放。 |
| `--diagnostics-file outputs/teleop-diagnostics.csv` | 不保存日志 | 将循环耗时、输入角度和目标写入 CSV，用于排查延迟与抖动。可在预览和执行时使用；校准模式不生成此日志。每次运行覆盖指定文件。 |
| `--button-enable` | 已开启 | 显式启用 HD 主臂按钮控制。也支持 `--button_enable`。 |
| `--button-disable` | 不关闭按钮 | 无按钮板的主臂使用此参数；它与 `--button-enable` 不能同时使用。也支持 `--button_disable`。 |
| `--button-id 7` | `7` | 按钮板设备 ID，允许 7～253；0～6 保留给关节和夹爪。仅在按钮功能开启时起作用，也支持 `--button_id`。 |

例如，SDK 在项目的 `.dependencies` 目录内，需要夹爪并保存运行诊断时：

```bash
python stararm102_lumos_teleop.py --can can0 --leader-port /dev/ttyUSB0 --gripper --sdk-root "$PWD/.dependencies/startouch_sdk" --diagnostics-file outputs/teleop-diagnostics.csv
```

这条命令为预览模式，确认后增加 `--execute`。若提示 `unrecognized arguments: --sdk-root` 或 `--diagnostics-file`，说明当前运行的脚本不包含这些参数，需要更新到当前 main 版本。

## HD 按钮悬停

HD 实体按钮功能默认开启，按钮板 ID 默认是 `7`。按钮反馈为 `180°` 时锁定主臂六个关节，其他状态释放，夹爪不参与锁定。程序在按钮状态变化时发送锁定/释放指令，并显示 `HD=悬停` 或 `HD=释放`。校准采集和遥操作循环均会读取按钮。

按钮功能在预览模式也生效；`--execute` 仅控制是否向 Lumos 下发跟随目标。按钮板未响应时程序会报错退出。

如果使用无 HD 按钮的主臂，在校准、预览和执行命令中都增加 `--button-disable`：

```bash
python stararm102_lumos_teleop.py --can can0 --leader-port /dev/ttyUSB0 --gripper --button-disable
```

按钮板使用其他 ID 时，增加 `--button-id ID`（允许范围 `7..253`）。也可在脚本顶部修改 `HD_BUTTON_ENABLED` 和 `HD_BUTTON_ID` 默认值；`--button-enable` 可显式开启按钮功能。

## 调整关节映射与速度

这些参数在脚本顶部修改，不是命令行参数。重启脚本后生效；速度和滤波参数不需要重新校准，它们直接使用代码中的当前值。

| 参数 | 默认值 | 作用 | 调整后的影响与用途 |
| --- | --- | --- | --- |
| `JOINT_SIGNS` | `(-1, 1, 1, 1, -1, -1)` | 六个 Lumos 关节的跟随方向，`1` 同向、`-1` 反向。 | 某个关节方向相反时，修改对应位置的符号。它不改变关节顺序；参考姿态和映射需要与实际机械臂对应。 |
| `FOLLOW_GAIN` | `1.0` | 主臂相对参考姿态的角度变化比例，允许 `(0, 1]`。 | `1.0` 表示主臂变化 10°，映射目标变化 10°；`0.5` 表示目标变化 5°。调小减少动作幅度，适合更精细的操作；它不是速度参数。 |
| `MAX_SPEED_DEG_PER_SEC` | `50.0`，单位 °/秒 | 限制每个关节目标的变化速度，按实际采样间隔计算。 | 调大允许目标更快追赶，调小让目标变化更慢。输入快于上限时会出现追赶延迟；这是下发目标的限速，不保证从臂实际运动达到该速度。 |
| `MAX_TARGET_STEP_DEG` | `2.0`，单位 ° | 限制每次循环的最大目标变化。 | 防止通信停顿后一次追赶过大。调小会让低频循环更慢，调大会允许更大的单帧变化；它与速度上限同时生效。 |
| `FILTER_MIN_CUTOFF_HZ` | `5.0`，单位 Hz | 自适应角度滤波的最低截止频率，用于静止或慢速时抑制输入噪声。 | 调小通常更平滑，但增加滤波延迟；调大响应更快，但会放过更多噪声。只滤六个关节，不滤夹爪。 |
| `FILTER_BETA` | `0.15` | 随主臂运动速度提高滤波截止频率的系数。 | 调大让快速动作更快通过，但运动中的噪声抑制会减弱；调小让快速动作也更平滑，但可能更滞后。设为 `0` 时使用固定截止频率。 |
| `CONTROL_RATE_HZ` | `50.0`，单位 Hz | 期望的主臂读取和目标更新频率，允许 `(0, 100]`。 | 50 Hz 对应约每 20 ms 一帧。调高缩短计划周期，但串口读取或 SDK 调用耗时过长时，实际频率仍达不到设定值。实际值看终端 `rate`。 |
| `STATUS_RATE_HZ` | `5.0`，单位 Hz | 终端状态输出的最高频率。 | 调小减少打印开销，调大让终端更新更频繁；不直接改变控制频率，诊断 CSV 仍每个控制循环记录一行。 |
| `HD_BUTTON_ENABLED` | `True` | HD 按钮功能的默认开关。 | `False` 表示默认不读取按钮；命令行 `--button-enable` / `--button-disable` 可覆盖它。 |
| `HD_BUTTON_ID` | `7` | HD 按钮板的默认 ID。 | 按钮板 ID 改过时相应修改；也可直接使用 `--button-id` 覆盖。 |

每帧目标步长上限为 `min(MAX_SPEED_DEG_PER_SEC × 实际采样间隔, MAX_TARGET_STEP_DEG)`。默认 50 Hz 时约为 `min(50 × 0.02, 2) = 1°`；如果实际只有 10 Hz，则每帧仍最多 2°，连续更新下的目标速度最多约 20°/秒。持续低频应先排查通信耗时，而不是只增大步长。

滤波截止频率按 `FILTER_MIN_CUTOFF_HZ + FILTER_BETA × 主臂估计角速度的绝对值` 计算，每个关节独立更新。这里的截止频率决定平滑强度，不是控制循环频率。

修改后先使用预览模式确认，再谨慎执行。不要通过增大参数或修改 SDK 保护阈值来掩盖力矩报警。

## 延迟与抖动诊断

程序显示实际循环频率 `rate`、本轮主臂读取耗时 `read`、映射目标与已发送目标之间的最大关节差值 `target_gap`，以及读写工作超过设定周期的累计次数 `overruns`。`target_gap` 不代表从臂实际位置误差；`overruns` 不包含终端打印和日志写入耗时，实际采样间隔会包含这些开销。

| 显示项 | 单位 | 怎么看、能排查什么 |
| --- | --- | --- |
| `rate` | Hz | 最近统计窗口中的实际循环频率。持续明显低于 `CONTROL_RATE_HZ`，说明循环未达到预期速度；它不是 CAN 波特率。 |
| `read` | ms | 本轮主臂读取总耗时，包含启用按钮时的按钮读取/状态处理。50 Hz 的计划周期是 20 ms，读取本身持续超过 20 ms 时就无法达到 50 Hz。 |
| `target_gap` | ° | 滤波并映射后的目标与当前下发目标之间，六个关节中最大的差值。持续增大通常表示目标追赶受限；它不包含滤波造成的输入滞后，也不是 Lumos 实际位置反馈误差。 |
| `overruns` | 次 | 主臂读取、目标计算与下发等工作超过计划周期的累计次数。快速增长提示耗时问题；这是累计计数，不是丢包数。 |

CSV 的 `sample_interval_ms` 用来检查采样间隔是否忽长忽短，`read_ms` 定位主臂读取耗时，`send_ms` 定位目标下发区间耗时，`work_ms` 是上述读写工作总耗时，`overrun` 为该帧是否超时（`1` 是、`0` 否）。`elapsed_s` 为本次运行的采样时间；`leader_j1_deg`～`leader_j6_deg` 为按关节映射排列的原始主臂角度，`target_j1_rad`～`target_j6_rad` 为输出的 Lumos 关节目标，单位分别是度和弧度。在预览模式中这些是拟下发目标。

记录诊断文件时，在原有命令中增加 `--diagnostics-file`，例如：

```bash
python stararm102_lumos_teleop.py --can can0 --leader-port /dev/ttyUSB0 --gripper --execute --diagnostics-file outputs/teleop-diagnostics.csv
```

CSV 包含采样间隔、主臂读取与目标下发耗时、目标差值、六个主臂角度和六个下发目标。每次运行会覆盖指定文件，请为不同测试使用不同文件名。读取耗时偏高时先检查串口、SDK 与设备反馈；频率正常但 `target_gap` 持续增大，表示输入运动超过了跟随限速。默认速度上限保持原有 `50 Hz × 1°` 的水平，不会自动提高。

改动已经过模拟验证，实际机械臂上的延迟与抖动改善需要现场复测。原有校准文件可继续使用。

## 仓库内容

```text
.
├── stararm102_lumos_teleop.py
├── scripts/
│   └── install_ubuntu.sh
├── README.md
└── docs/
    └── StarArm102_Lumos_Python_Teleoperation_Guide.md
```

## License

本仓库当前未授予开源许可证；公开可见不代表获得复制、修改或再分发许可。若需为客户授予使用权，请在发布前添加经权利人确认的许可证或授权条款。

## 本版本与上一版本的区别

本节对比本仓库当前 `main` 版本与更新前的 Lumos Python 遥操作脚本。

| 项目 | 上一版本 | 当前版本 | 对使用的影响 |
| --- | --- | --- | --- |
| HD 按钮悬停 | 未集成 HD 按钮。 | 默认启用按钮板 ID 7 控制主臂锁定/释放，提供关闭和修改 ID 的参数。 | 无按钮板时加 `--button-disable`；预览模式也会控制主臂锁定/释放。 |
| 关节输入平滑 | 主臂角度直接用于目标计算，没有滤波。 | 加入自适应角度滤波，慢速时抑制噪声，快速时提高响应速度。 | 减少输入噪声传到从臂；滤波仍会引入一定滞后，实际改善需要实机复测。夹爪不参与此滤波。 |
| 跟随限速 | 用 `MAX_STEP_DEG=1.0` 限制每周期步长；循环变慢时，目标变化速度也随之下降。 | 用 `MAX_SPEED_DEG_PER_SEC=50.0` 按实际采样间隔限速，同时以 `MAX_TARGET_STEP_DEG=2.0` 限制单帧变化。 | 在正常频率波动时减少额外追赶延迟，长时间卡顿后不下发大步跳变。默认 50 Hz 时的速度上限保持不变；持续低频时仍受单帧上限限制。 |
| 终端输出 | 每个控制循环打印一次状态。 | 默认每秒最多打印 5 次，并显示实际频率、读取耗时、目标差值和超时次数。 | 降低打印开销，也更容易判断延迟来自通信耗时还是目标限速。 |
| 诊断日志 | 没有循环诊断 CSV。 | 新增 `--diagnostics-file`，逐帧记录耗时、主臂输入和输出目标。 | 可将现场数据用于排查延迟与抖动；不填写该参数时不保存日志。 |
| SDK 配置定位 | 直接从启动目录初始化 Lumos，部分 SDK 版本会找不到 `robot_kinematics.yaml`。 | 自动查找 SDK 源码目录，在该目录内完成初始化；新增 `--sdk-root` 指定位置。安装脚本也检查配置文件是否存在。 | 减少配置路径错误；仍须保留 SDK 源码目录及其 `src/config`，无需复制 YAML 到 Python 安装目录。 |
| 参数说明 | 主要提供基本运行步骤。 | 补充命令行参数、调速与滤波参数、诊断字段的中文说明。 | 可按用途选择参数，并了解调大、调小的影响。 |

原有校准文件、关节映射、关节方向和夹爪开合映射可继续使用；HD 按钮功能在本次更新中加入并默认开启，无按钮板时需要加 `--button-disable`。仍需 `--execute` 才会向 Lumos 下发跟随目标。

升级时替换为本仓库最新版 `stararm102_lumos_teleop.py`；有 HD 按钮的配置可继续使用原有命令，无按钮板时增加 `--button-disable`。SDK 无法自动定位时增加 `--sdk-root`；需要记录现场数据时增加 `--diagnostics-file`。旧版中的 `MAX_STEP_DEG` 已替换为速度上限与单帧步长上限，之前自行调整过该常量的用户需要在新版顶部重新核对设置。

本版本已通过模拟测试，尚不能据此保证实机延迟或抖动完全消失，也不会自动提高默认跟随速度。
