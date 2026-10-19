# 如何搭建 StarArm102 + Lumos 的 LeRobot 遥操作系统

本教程依次完成：**环境搭建 → 接线与端口设置 → 配对校准 → 预览 → 遥操作 → 关节数据采集 → 动作回放**。

本篇暂不配置摄像头，采集命令只保存关节和夹爪数据。

项目地址：[VincentHSS/stararm102-lumos-lerobot](https://github.com/VincentHSS/stararm102-lumos-lerobot)。

## 产品与系统组成

| 设备 | 作用 | 与电脑的连接方式 |
|---|---|---|
| StarArm102 主臂（Leader） | 人手拖动，提供六关节与可选夹爪输入 | USB / UART |
| Lumos 单臂（Follower） | 执行主臂映射得到的动作 | CAN，使用 Lumos SingleArm SDK |
| Ubuntu 主机 | 运行 LeRobot、控制机械臂、保存数据 | 同时连接主从臂 |

```text
StarArm102 主臂 ── USB/UART ── Ubuntu / LeRobot ── CAN ── Lumos 从臂
```

本仓库的 LeRobot 设备类型分别是 `stararm102` 和 `lumos`。安装后自动发现，不需要将文件手动复制进 LeRobot 源码目录。

## 初始环境搭建

使用 Ubuntu 22.04 / 24.04 x86_64、Python 3.12。遥操作和关节数据采集可以使用 CPU，不要求先搭建 CUDA 训练环境。Jetson/ARM 的 Lumos 原生 SDK 构建尚未验证。

| 软件 | 本项目使用的版本 |
|---|---|
| Python | 3.12 |
| LeRobot | 固定 commit `3991580a5673f5f0219a4e8835a5f973eeccf9a7`，版本字段 0.6.2 |
| Lumos SDK | 固定 commit `040412542c0b6b6fd2bb6dd652c0de6c666631be` |

### 1. 安装基础工具

```bash
sudo apt-get update
sudo apt-get install -y git curl can-utils
```

### 2. 安装 Conda

已经能运行 `conda --version` 时跳过本步。以下使用 Miniforge 官方 Linux x86_64 安装包；`~/miniforge3` 已存在时不要重复安装到该目录。

```bash
mkdir -p ~/Downloads
cd ~/Downloads
curl -L https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh \
  -o Miniforge3-Linux-x86_64.sh
bash Miniforge3-Linux-x86_64.sh -b -p "$HOME/miniforge3"
source "$HOME/miniforge3/etc/profile.d/conda.sh"
```

来源：[Miniforge 官方说明](https://github.com/conda-forge/miniforge)。已有 Miniconda / Anaconda 也可以直接使用。

### 3. 创建并激活环境

```bash
conda create -n lumos-lerobot python=3.12 -y
conda activate lumos-lerobot
python --version
```

应输出 `Python 3.12.x`。

## 安装与调试

### 1. 克隆本仓库

```bash
cd ~
git clone https://github.com/VincentHSS/stararm102-lumos-lerobot.git
cd ~/stararm102-lumos-lerobot
```

### 2. 安装 LeRobot、硬件 SDK 和适配器

保持 `lumos-lerobot` 环境已激活：

```bash
bash scripts/install_lerobot_ubuntu.sh
```

脚本安装系统构建依赖、固定版本的 Lumos SDK、LeRobot 及本仓库适配器，并修正该版本的采集逻辑，让保存的 action 对应限速后实际发送的目标。需要网络和 `sudo` 权限。

安装正常结束后再继续。安装失败时先处理错误，不要跳过失败步骤启动机器人。

### 3. 检查安装结果

```bash
python -c "import serial, fashionstar_uart_sdk; from startouchclass import SingleArm; print('SDK OK')"
python -c "from lerobot_robot_lumos_stararm102 import LumosConfig, StarArm102Config; print(LumosConfig().type, StarArm102Config().type)"
python -m pip check
```

应看到 `SDK OK`、`lumos stararm102`，且没有依赖冲突。

## 接线与端口设置

### 1. 接线

1. 按厂商说明连接机械臂、电源和急停，确认工作区域畅通。
2. StarArm102 的 USB/UART 接到 Ubuntu 主机。
3. Lumos 通过 CAN 适配器接到同一台主机，按硬件说明完成总线接线与终端电阻配置。
4. 按厂商要求上电，保持急停可及。

**初始化 Lumos SDK 时可能使能电机，校准和预览也会初始化 SDK。** 预览只是“不发送运动目标”，不能当作断电状态。不要同时运行多个控制程序。

### 2. 找到 StarArm102 串口

```bash
ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
ls -l /dev/serial/by-id/ 2>/dev/null
```

也可以使用 LeRobot 的端口识别工具，按终端提示插拔主臂的 USB：

```bash
lerobot-find-port
```

以下假设主臂为 `/dev/ttyUSB0`。Lumos 从臂使用 CAN，不需要填写第二个 UART 串口。

串口报 `Permission denied` 时：

```bash
sudo usermod -aG dialout "$USER"
```

注销 Ubuntu 登录并重新登录，使组权限生效，再重新激活环境。不要用 `sudo lerobot-teleoperate ...` 绕过权限，避免进入另一套 Python 环境。

### 3. 设置 Lumos CAN 接口

```bash
ip -details link show can0
```

应看到接口为 `UP`、`bitrate 1000000`。接口存在但尚未启用时：

```bash
sudo ip link set can0 up type can bitrate 1000000
```

已经 UP 且速率正确时直接继续。提示 `Device or resource busy` 时先检查接口状态。

确实要重新设置速率时，先停止控制进程，再运行：

```bash
sudo ip link set can0 down
sudo ip link set can0 up type can bitrate 1000000
```

找不到 `can0` 时，检查适配器驱动和实际接口名。

### 4. 设置后续命令使用的端口与路径

回到仓库根目录，再设置以下变量。端口不是默认值时在这里替换：

```bash
cd ~/stararm102-lumos-lerobot

export STARARM_PORT=/dev/ttyUSB0
export LUMOS_CAN=can0
export LUMOS_SDK_ROOT="$PWD/.dependencies/startouch_sdk"
export LUMOS_MAPPING_FILE="$HOME/.config/stararm102_lumos/calibration.json"
export LUMOS_LIMITS_FILE="$PWD/lumos_joint_limits.json"
```

变量只对当前终端生效，新开终端或重新登录后需要再次设置。

## 校准

### 1. 配对校准主从臂

本项目同时记录主从臂参考姿态，使用下面的配对向导：

```bash
python stararm102_lumos_teleop.py \
  --calibrate \
  --leader-port "$STARARM_PORT" \
  --can "$LUMOS_CAN" \
  --sdk-root "$LUMOS_SDK_ROOT" \
  --calibration-file "$LUMOS_MAPPING_FILE" \
  --gripper
```

按终端提示操作：

1. 将主从臂放到相互对应的参考姿态，按 Enter 记录。
2. 缓慢移动主臂六个关节，覆盖计划使用的遥操作范围；完成后按 Enter。
3. 记录主臂夹爪完全闭合与完全打开的位置。
4. 等待提示校准文件保存成功。

不要为了扩大范围强行碰撞机械限位。没有 HD 按钮板时增加 `--button-disable`；不用夹爪时删除 `--gripper`，后续主从臂命令中的 `gripper` 也都改为 `false`。

默认校准文件为 `~/.config/stararm102_lumos/calibration.json`。已有原项目的有效校准，且端口、关节顺序、夹爪设置和参考姿态一致时可以复用。

适配器的 `calibrate()` 负责读取这份文件，分别调用 `lerobot-calibrate` 不能代替首次配对向导；遥操作启动时也不会自动完成配对参考姿态采集。

### 2. 准备 Lumos 真实关节限位

执行和采集模式必须有从臂限位文件，不能用主臂扫描范围代替。

只有确认实际型号使用 SDK 的 `FastTouchV2.SLDASM.urdf`，且 `joint1` 到 `joint6` 与 SDK 关节顺序和方向一致时，才使用：

```bash
python tools/export_joint_limits.py \
  --urdf "$LUMOS_SDK_ROOT/src/config/FastTouchV2.SLDASM.urdf" \
  --output "$LUMOS_LIMITS_FILE"
```

其他型号改用对应 URDF 与实际关节名。核对文件中的 `lower_rad`、`upper_rad`，它们应各有六个 SDK 坐标下的 rad 数值。核实后保留，以后启动不用反复导出。文件已存在时工具会拒绝覆盖。

## 遥操作

### 1. 先预览

保持当前终端的环境变量有效，运行 LeRobot 原生命令：

```bash
lerobot-teleoperate \
  --robot.type=lumos \
  --robot.id=lumos01 \
  --robot.can_interface="$LUMOS_CAN" \
  --robot.sdk_root="$LUMOS_SDK_ROOT" \
  --robot.mapping_file="$LUMOS_MAPPING_FILE" \
  --robot.gripper=true \
  --robot.execute=false \
  --robot.cameras='{}' \
  --teleop.type=stararm102 \
  --teleop.id=stararm01 \
  --teleop.port="$STARARM_PORT" \
  --teleop.mapping_file="$LUMOS_MAPPING_FILE" \
  --teleop.gripper=true \
  --teleop.button_enabled=true \
  --fps=30
```

缓慢移动主臂，一次先检查一个关节，观察打印的目标。确认顺序、方向和夹爪开合方向后，按 `Ctrl+C` 停止。

没有 HD 按钮板时，将 `--teleop.button_enabled=true` 改为 `false`。夹爪反向时增加 `--teleop.invert_gripper=true`。需要改变关节方向时，可使用 `--teleop.signs='[-1,1,1,1,-1,-1]'` 并调整对应项；改变 `joint_map` 后需重新配对校准。

### 2. 启动主从跟随

将 Lumos 恢复到校准参考姿态附近，确认急停、方向和限位，再运行：

```bash
lerobot-teleoperate \
  --robot.type=lumos \
  --robot.id=lumos01 \
  --robot.can_interface="$LUMOS_CAN" \
  --robot.sdk_root="$LUMOS_SDK_ROOT" \
  --robot.mapping_file="$LUMOS_MAPPING_FILE" \
  --robot.joint_limits_file="$LUMOS_LIMITS_FILE" \
  --robot.gripper=true \
  --robot.execute=true \
  --robot.cameras='{}' \
  --teleop.type=stararm102 \
  --teleop.id=stararm01 \
  --teleop.port="$STARARM_PORT" \
  --teleop.mapping_file="$LUMOS_MAPPING_FILE" \
  --teleop.gripper=true \
  --teleop.button_enabled=true \
  --fps=30
```

移动主臂，Lumos 会按映射跟随。首次先做小幅单关节动作，逐项确认六关节与夹爪。

- 启动时要求 Lumos 距离参考姿态的最大关节误差不超过 0.15 rad。
- 默认最大目标变化速度 50°/s，单帧最多变化 2°。
- HD 按钮仍用于主臂保持，按钮板不参与六关节和夹爪映射。
- `Ctrl+C` 正常退出；卡滞、碰撞或持续力矩报警时立即停止并使用硬件急停。

## 数据集制作与采集

熟悉遥操作后再采集。采集程序本身会控制 Lumos，不要同时运行另一个遥操作进程。

### 1. 记录 10 个回合

示例每段 30 秒，段间留 15 秒重置场景，只保存在本地：

```bash
lerobot-record \
  --robot.type=lumos \
  --robot.id=lumos01 \
  --robot.can_interface="$LUMOS_CAN" \
  --robot.sdk_root="$LUMOS_SDK_ROOT" \
  --robot.mapping_file="$LUMOS_MAPPING_FILE" \
  --robot.joint_limits_file="$LUMOS_LIMITS_FILE" \
  --robot.gripper=true \
  --robot.execute=true \
  --robot.cameras='{}' \
  --teleop.type=stararm102 \
  --teleop.id=stararm01 \
  --teleop.port="$STARARM_PORT" \
  --teleop.mapping_file="$LUMOS_MAPPING_FILE" \
  --teleop.gripper=true \
  --teleop.button_enabled=true \
  --dataset.repo_id=VincentHSS/lumos_joint_demo_001 \
  --dataset.root="$PWD/datasets/lumos_joint_demo_001" \
  --dataset.single_task="Move the arm through the demonstrated joint trajectory" \
  --dataset.fps=30 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=15 \
  --dataset.num_episodes=10 \
  --dataset.video=false \
  --dataset.no_stamp=true \
  --dataset.push_to_hub=false \
  --display_data=false \
  --play_sounds=false
```

第一次可以先把 `num_episodes` 改为 `3`、`episode_time_s` 改为 `15`，确认链路正常再扩大数量。重置阶段程序仍可能处理遥操作输入。

下一批数据同时修改名称与目录，例如将两处 `lumos_joint_demo_001` 改成 `lumos_joint_demo_002`，避免覆盖已有数据。

### 2. 记录参数

| 参数 | 含义 |
|---|---|
| `dataset.repo_id` | 数据集名称，本例不会触发上传 |
| `dataset.root` | 本地保存目录 |
| `dataset.single_task` | 本批数据的任务描述 |
| `dataset.fps` | 数据采集频率 |
| `dataset.episode_time_s` | 单回合时长 |
| `dataset.reset_time_s` | 段间重置时长 |
| `dataset.num_episodes` | 本次采集回合数 |
| `dataset.video=false` | 不保存视频 |
| `dataset.no_stamp=true` | 名称不自动附加时间戳 |
| `dataset.push_to_hub=false` | 只保存在本地 |

### 3. 键盘控制

监听可用时：右方向键提前结束当前阶段，左方向键请求重录当前 episode，Esc 结束采集。图形桌面、SSH 和终端权限会影响监听，按终端提示确认是否可用。

没有键盘监听时，按设置的回合数量和时长完成。紧急停止使用硬件急停，不依赖键盘监听。

### 4. 检查数据

等待正常结束并完成写盘，再查看：

```bash
find datasets/lumos_joint_demo_001 -maxdepth 3 -type f | head -30
```

使用 LeRobot 读取数据：

```bash
python - <<'PY'
from pathlib import Path
from lerobot.datasets import LeRobotDataset

dataset = LeRobotDataset(
    "VincentHSS/lumos_joint_demo_001",
    root=Path("datasets/lumos_joint_demo_001").resolve(),
    video_backend="pyav",
)
print("回合数:", dataset.num_episodes)
print("总帧数:", dataset.num_frames)
print("状态维度:", dataset[0]["observation.state"].shape)
print("动作维度:", dataset[0]["action"].shape)
PY
```

启用夹爪时状态和动作都是 7 维（六关节 + 夹爪），不用夹爪时为 6 维。`observation.state` 是 Lumos 实测状态，`action` 是限速后最终发送的目标。这里没有图像或视频字段。

安装器已对固定版本的 LeRobot 应用录制修正。如果你另行重装了 LeRobot，应在采集前重新运行安装器，或用 `tools/patch_record.py` 修正实际运行环境中的录制文件。

## 重播一个回合

回放会真实驱动 Lumos。先确认数据内容、工作区和急停，并将 Lumos 恢复到校准参考姿态附近。回放不读取 StarArm102。

`episode` 从 `0` 开始，下面回放第一个回合：

```bash
lerobot-replay \
  --robot.type=lumos \
  --robot.id=lumos01 \
  --robot.can_interface="$LUMOS_CAN" \
  --robot.sdk_root="$LUMOS_SDK_ROOT" \
  --robot.mapping_file="$LUMOS_MAPPING_FILE" \
  --robot.joint_limits_file="$LUMOS_LIMITS_FILE" \
  --robot.gripper=true \
  --robot.execute=true \
  --robot.cameras='{}' \
  --dataset.repo_id=VincentHSS/lumos_joint_demo_001 \
  --dataset.root="$PWD/datasets/lumos_joint_demo_001" \
  --dataset.episode=0 \
  --play_sounds=false
```

## 以后每天如何启动

首次安装、校准和限位核对完成后，不用每天重新安装或重新校准。

1. 按厂商要求接线、上电，检查急停与工作区。
2. 打开终端，激活环境并设置本终端变量：

```bash
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate lumos-lerobot
cd ~/stararm102-lumos-lerobot

export STARARM_PORT=/dev/ttyUSB0
export LUMOS_CAN=can0
export LUMOS_SDK_ROOT="$PWD/.dependencies/startouch_sdk"
export LUMOS_MAPPING_FILE="$HOME/.config/stararm102_lumos/calibration.json"
export LUMOS_LIMITS_FILE="$PWD/lumos_joint_limits.json"

ip -details link show "$LUMOS_CAN"
```

其他 Conda 安装位置使用你自己的激活方式；端口不是默认值时修改对应变量。CAN 重启后处于 DOWN 时按前文启用。

3. 确认 Lumos 在参考姿态附近，运行“先预览”的完整命令。
4. 预览正常后按 `Ctrl+C` 退出，运行“启动主从跟随”的完整命令。
5. 要采集时先退出遥操作，再运行“记录 10 个回合”的命令。

## 训练与推理

本篇先完成无摄像头的硬件接入、关节数据采集与回放，暂不提供视觉策略训练和部署命令。

当前固定版本的 ACT 要求至少有图像输入或 `observation.environment_state`；本篇只有机械臂自身的 `observation.state`，直接套用视觉 ACT 训练命令会报错。不要通过伪造环境状态来绕过输入要求。

## FAQ

| 问题 | 处理方法 |
|---|---|
| 找不到 `conda` | source 你自己的 Conda 安装目录下的 `etc/profile.d/conda.sh` |
| 找不到 `lerobot-teleoperate` | 激活 `lumos-lerobot` 环境，确认安装成功 |
| 串口 `Permission denied` | 加入 `dialout` 组后注销 Ubuntu 登录并重新登录 |
| 找不到 `/dev/ttyUSB0` | 查看实际串口和 `/dev/serial/by-id/`，修改 `STARARM_PORT` |
| 找不到 `can0` | 检查适配器驱动和实际接口名 |
| CAN 提示 busy | 查看是否已 UP、速率是否正确；重配前先停止控制程序 |
| 没有校准文件 | 核对 `LUMOS_MAPPING_FILE`，完成配对向导 |
| 端口或关节顺序与校准不符 | 使用原校准设置，或重新配对校准 |
| HD 按钮 ID 7 不响应 | 有按钮时检查接线与 ID；没有按钮板才禁用 |
| 缺少从臂限位 | 核对 `LUMOS_LIMITS_FILE`，生成并核实限位 |
| `Lumos is away from calibrated home` | 按厂商操作恢复参考姿态，或重新校准，不放大容差跳过检查 |
| SDK 找不到配置 | 检查 `LUMOS_SDK_ROOT/src/config/robot_kinematics.yaml` |
| 数据目录已存在 | 为新采集换一个新名称和新目录 |
| 方向不正确 | 先停在预览模式，逐关节核对 `joint_map` 与 `signs` |
| 卡滞、碰撞、力矩报警 | 停止并使用硬件急停，检查机械状态和映射，不提高保护阈值掩盖问题 |

## 验证与参考

软件已通过 20 项测试，覆盖真实 LeRobot 工厂、命令行、控制循环、数据集读写与回放函数。物理串口、CAN SDK 和其他硬件输入使用测试替身；你的 Ubuntu SDK 构建、实际通信与运动仍需首次调试。环境见 [验证记录](../VALIDATION.md)。

本文参考 [Cello / Violin 教程](https://github.com/servodevelop/lerobot/blob/docs/docs/cello-violin.md) 的实操章节组织，设备类型、端口、校准方式和命令都按本项目调整。

- [原独立遥操作脚本](https://github.com/VincentHSS/stararm102-lumos-teleop)
- [LeRobot 官方硬件接入说明](https://huggingface.co/docs/lerobot/integrate_hardware)
- [Lumos SDK](https://github.com/lumos-open/startouch_sdk)
