# StarArm102 → Lumos：LeRobot 接入版

**第一次使用、每天开机启动、开始遥操作与采集数据，请直接按 [完整启动教程](docs/STARTUP_zh-CN.md) 操作。**

新仓库：https://github.com/VincentHSS/stararm102-lumos-lerobot

这是基于原遥操作仓库整理的完整接入版。安装后，LeRobot 自动识别：

- `--robot.type=lumos`：Lumos 从臂，CAN / SingleArm SDK。
- `--teleop.type=stararm102`：StarArm102 主臂，UART / FashionStar SDK，保留 HD 按钮和原校准映射。

提供统一入口 `lumos-lerobot`，实际控制和数据采集仍调用 LeRobot 原生程序。模型输出直接使用 Lumos 的六关节绝对位置（rad）和夹爪开度（0～1），不需要再次经过主臂映射。

## 安装

在 Ubuntu 机器人主机上解压本目录，并在目录内运行。不要覆盖已有的校准文件。

```bash
conda create -n lumos-lerobot python=3.12 -y
conda activate lumos-lerobot
bash scripts/install_lerobot_ubuntu.sh
```

安装器会安装系统构建依赖、固定版本的 Lumos SDK、固定版本的 `lerobot[core_scripts]`、本插件，并修正该版本 LeRobot 的录制动作保存逻辑。系统软件包安装需要 `sudo`，整个过程需要网络；安装过程不打开机械臂连接。

固定基线：

| 项目 | 版本 |
|---|---|
| Python | 3.12 |
| LeRobot | `3991580a5673f5f0219a4e8835a5f973eeccf9a7`（版本字段 0.6.2） |
| Lumos SDK | `040412542c0b6b6fd2bb6dd652c0de6c666631be` |
| 原遥操作代码 | `c9922364c22156bba277ff1ba904f5d0ac696079` |

已存在的 `.dependencies` 仓库如果版本不同，安装器会停止并说明原因，不会自动重置你的工作。

## 配置与校准

安装器会创建 `configs/local.json`。修改实际设备端口：

```text
robot.can_interface       Lumos 的 CAN 接口，默认 can0
teleop.port              StarArm 的串口，默认 /dev/ttyUSB0
robot/teleop.gripper     两边保持一致，默认 true
teleop.button_enabled   有 HD 按钮板为 true，没有则 false
teleop.signs             六个主从关节方向，默认 [-1,1,1,1,-1,-1]
teleop.joint_map         Lumos 六关节对应的主臂舵机 ID
```

JSON 中相对路径以配置文件目录为基准，`~` 会展开为用户目录。`configs/example.json` 保留模板；真实配置放在 `configs/local.json`。

检查 CAN 状态；尚未配置时按硬件要求启用 1 Mbps：

```bash
ip -details link show can0
# 只在接口尚未启用、且设备使用此参数时执行：
sudo ip link set can0 up type can bitrate 1000000
```

已有原校准文件时，直接把两端 `mapping_file` 指向同一文件。首次校准使用原向导：

```bash
lumos-lerobot calibrate --config configs/local.json
```

校准会读取配对主从臂的参考姿态和主臂活动范围，默认保存到 `~/.config/stararm102_lumos/calibration.json`。初始化 Lumos SDK 会使能电机，HD 按钮也会控制主臂保持状态；这同样适用于下面的预览。

## 检查与预览

```bash
# 只检查依赖、配置、校准、插件注册和工厂；不连接机械臂。
lumos-lerobot doctor --config configs/local.json

# 调用 LeRobot 原生遥操作循环，读取真实设备，但不下发运动目标。
lumos-lerobot preview --config configs/local.json
```

没有生成 Lumos 限位文件时，仍可以预览；无法进入执行或采集模式。

## 设置从臂限位，再执行

本代码不把主臂校准范围视为 Lumos 的机械限位。执行前需要 `lumos_joint_limits.json`，内容为按 SDK 关节 1～6 顺序的 `lower_rad` 和 `upper_rad` 两个数组。

如果确认实际安装型号使用 SDK 的 `FastTouchV2.SLDASM.urdf`，且六关节顺序是 `joint1` 到 `joint6`，可导出：

```bash
python tools/export_joint_limits.py \
  --urdf .dependencies/startouch_sdk/src/config/FastTouchV2.SLDASM.urdf \
  --output lumos_joint_limits.json
```

使用其他型号时，指定对应 URDF，必要时用 `--joint-names` 指定实际六关节名。导出不证明型号、关节顺序或 SDK 坐标正确，必须核对后使用。

确认主从关节映射、方向、参考姿态和从臂限位正确后：

```bash
lumos-lerobot teleop --config configs/local.json
```

这会下发运动目标。默认最大速度 50°/s，每帧目标最多变化 2°，按实际 dt 限速；连接时要求 Lumos 距离校准参考姿态不超过 0.15 rad。夹爪反向可在配置中加入 `teleop.invert_gripper: true`。

`Ctrl+C` 停止并释放资源。发生卡滞或持续力矩报警时使用硬件急停，不要通过增大限速或修改 SDK 保护阈值掩盖问题。

## 加相机并采集

默认配置没有相机，先验证机械臂链路。需要视觉数据时，把 `configs/local.json` 中 `robot.cameras` 改为以下 JSON 对象（按实际设备号替换 0）：

```json
{
  "front": {
    "type": "opencv",
    "index_or_path": 0,
    "width": 640,
    "height": 480,
    "fps": 30
  }
}
```

设置 `dataset.single_task`、`dataset.repo_id`、保存目录及 episode 数量，然后：

```bash
lumos-lerobot record --config configs/local.json
```

该命令会驱动机械臂，保存标准 LeRobotDataset。默认只保存在本地（`push_to_hub=false`），不上传数据。相同数据目录不会被自动覆盖；新一轮采集使用新目录或自行使用 LeRobot 的 resume 选项。

本基线的上游录制循环未使用 `send_action()` 返回值。安装器调用 `tools/patch_record.py`，仅对 `robot.name == 'lumos'` 保存最终限幅/限速后发送的目标，并拒绝预览模式下录制训练数据。原文件备份为 `lerobot_record.py.before_lumos.bak`。缺少该修正时，统一采集入口会在连接前拒绝运行。

数据中：

- `observation.state`：Lumos 六关节和可选夹爪的实测状态。
- `observation.images.front` 等：相机 RGB 图像。
- `action`：最终发送给 SDK 的六关节目标和可选夹爪目标，不代表机械臂已经实际到达。

先录一小段检查关节顺序、单位、夹爪方向、图像和频率，再批量采集。

## 原生 LeRobot 命令

插件本身也可以直接用于 `lerobot-teleoperate` / `lerobot-record`。可让入口打印实际参数，不连接设备：

```bash
lumos-lerobot preview --config configs/local.json --print-command
lumos-lerobot record --config configs/local.json --print-command
```

输出为 argv JSON 数组，方便检查参数和路径，不要将整个 JSON 当成 shell 命令粘贴。

## 修改代码的位置

| 文件 | 主要职责 |
|---|---|
| `src/lerobot_robot_lumos_stararm102/config.py` | 设备注册及可调整配置 |
| `stararm102.py` | `connect()` 打开 UART；`get_action()` 读主臂、滤波、转换为 Lumos 坐标 |
| `lumos.py` | `connect()` 初始化 SDK/相机；`get_observation()` 读真实状态；`send_action()` 限位限速并控制 |
| `common.py` | 校准格式、动作字段、目标限速与关节限位读取 |
| `cli.py` | 统一配置文件、环境检查、原向导调用和 LeRobot 原生命令启动 |
| `_legacy.py` | 原脚本原样副本，复用底层读取/滤波/按钮/SDK 路径逻辑 |

训练 ACT 等策略通常不需要因硬件接入修改模型。策略部署时直接使用 `Lumos.send_action()`，不用连接主臂；仍需设置 Lumos 配置中的启动参考姿态文件。

## 测试与限制

安装完成后可运行无实机测试：

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

测试使用真实 LeRobot 配置、设备工厂、处理器、控制循环和数据集；串口、CAN SDK、相机与键盘监听使用测试替身，不会连接硬件或上传数据。具体执行结果见 `VALIDATION.md`。

这份交付不包含已完成的实机验收、额外硬件通信看门狗、高频独立伺服线程或完整策略部署程序。数值有限性检查不能证明 UART 反馈是最新帧。Ubuntu 上的 SDK 构建和设备通信仍需在你的机器验证。

## 原仓库来源

原脚本、原安装脚本和原单元测试来自 `VincentHSS/stararm102-lumos-teleop`；原说明保存在 `README_STANDALONE.md`。原仓库未声明开源许可证，本仓库不替原作者授予额外的复制、修改或分发许可。

- https://github.com/VincentHSS/stararm102-lumos-teleop
- https://github.com/huggingface/lerobot
- https://github.com/lumos-open/startouch_sdk
