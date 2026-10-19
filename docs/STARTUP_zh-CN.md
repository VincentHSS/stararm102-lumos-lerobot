# StarArm102 控制 Lumos：从零到启动

仓库：<https://github.com/VincentHSS/stararm102-lumos-lerobot>

这份教程按 **Ubuntu 22.04 / 24.04 的 x86_64 主机、StarArm102 主臂、Lumos 单臂、UART、1 Mbps CAN** 编写。软件环境统一使用 **Python 3.12**。如果你用的是 Jetson/ARM，先确认 Lumos 原生 SDK 的架构支持，再安装；本项目没有验证 ARM 构建。

最终日常使用的三个命令：

| 目的 | 命令 |
|---|---|
| 预览目标 | `lumos-lerobot preview --config configs/local.json` |
| 主臂控制从臂 | `lumos-lerobot teleop --config configs/local.json` |
| 遥操作并采集数据 | `lumos-lerobot record --config configs/local.json` |

**先预览，再执行。** `preview` 不发送运动目标，但构造 Lumos SDK 仍可能使能电机，HD 按钮也可能改变主臂保持状态。`teleop`、`record` 会强制进入执行模式，即使配置文件中 `robot.execute` 写的是 `false`。不要同时运行多个控制进程。

## 一、第一次准备：只做一次

### 1. 连接硬件

1. 按设备厂商要求接好机械臂、电源与急停，确认工作区域畅通。
2. 将 StarArm102 主臂的 USB/UART 接到 Ubuntu 主机。
3. 将 Lumos 的 CAN 设备接到同一台主机，按硬件说明完成总线接线与终端电阻配置。
4. 需要录制视觉数据时，连接相机。
5. 机械臂上电、急停和使能的具体顺序以厂商说明为准。启动下面的校准、预览或执行程序前，保持急停可及。

### 2. 安装系统工具

打开 Ubuntu 终端：

```bash
sudo apt-get update
sudo apt-get install -y git curl can-utils
```

### 3. 准备 Conda 和 Python 3.12

如果 `conda --version` 已能运行，直接创建环境，不要重复安装 Conda。

没有 Conda 时，以下命令安装官方 Miniforge 的 Linux x86_64 版本。`~/miniforge3` 已存在时不要再次执行安装命令；已有其他 Conda 发行版也可以直接使用。

```bash
mkdir -p ~/Downloads
cd ~/Downloads
curl -L https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh \
  -o Miniforge3-Linux-x86_64.sh
bash Miniforge3-Linux-x86_64.sh -b -p "$HOME/miniforge3"
source "$HOME/miniforge3/etc/profile.d/conda.sh"
```

安装方式来源：[Miniforge 官方说明](https://github.com/conda-forge/miniforge)。

创建环境：

```bash
conda create -n lumos-lerobot python=3.12 -y
conda activate lumos-lerobot
python --version
```

应输出 `Python 3.12.x`。后面所有 Python、安装和启动命令，都在这个环境中运行。

### 4. 下载新仓库并安装

```bash
cd ~
git clone https://github.com/VincentHSS/stararm102-lumos-lerobot.git
cd ~/stararm102-lumos-lerobot
bash scripts/install_lerobot_ubuntu.sh
```

安装脚本会：

- 安装 SDK 构建所需的系统包。
- 下载固定版本的 Lumos SDK，并在当前 Python 环境中构建安装。
- 下载固定版本的 LeRobot，安装硬件、数据集和视频等依赖。
- 安装本仓库的两个硬件适配器。
- 修正该 LeRobot 版本的采集逻辑，让数据保存最终限速后发送的动作。
- 创建你的本地配置文件 `configs/local.json`。

安装中可能需要输入 `sudo` 密码。必须看到脚本正常结束后再启动机器人；如果安装失败，先处理错误，不要继续往下运行。

安装结束时应看到：

```text
Installed. Edit configs/local.json, then run: lumos-lerobot calibrate --config configs/local.json
```

不需要再手动把代码复制到 LeRobot 的 `robots` 或 `teleoperators` 目录。

### 5. 确认串口和权限

查看串口：

```bash
ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
ls -l /dev/serial/by-id/ 2>/dev/null
```

找到 StarArm102 对应的端口。默认配置使用 `/dev/ttyUSB0`，不是这个端口就改成实际值。有稳定的 `/dev/serial/by-id/...` 路径时，可以在首次校准前选用该路径，之后一直保持一致。

如果串口提示 `Permission denied`：

```bash
sudo usermod -aG dialout "$USER"
```

**注销 Ubuntu 登录并重新登录**，使组权限生效。重新打开终端、激活环境、回到仓库后再继续。不要靠 `sudo lumos-lerobot ...` 绕过权限，否则可能进入另一套 Python 环境。

### 6. 配置 CAN

```bash
ip -details link show can0
```

你要确认接口存在，并看到 `UP`、`bitrate 1000000`。如果实际接口名不是 `can0`，下面的命令和配置都换成实际名称。

接口存在但尚未启用时：

```bash
sudo ip link set can0 up type can bitrate 1000000
ip -details link show can0
```

如果已经是 `UP` 且速率正确，直接继续。如果报 `Device or resource busy`，先重新查看状态，不要反复执行同一配置命令。

如果确实需要改速率，先停止所有控制程序，再重新配置：

```bash
sudo ip link set can0 down
sudo ip link set can0 up type can bitrate 1000000
```

如果提示 `Cannot find device "can0"`，先检查 CAN 适配器、驱动和实际接口名；本程序无法凭空创建硬件 CAN 接口。

### 7. 编辑本地配置

确认当前目录：

```bash
cd ~/stararm102-lumos-lerobot
nano configs/local.json
```

第一次主要检查以下项目：

| 配置项 | 你要填写的内容 |
|---|---|
| `robot.can_interface` | Lumos 的 CAN 接口，例如 `can0` |
| `teleop.port` | StarArm102 的串口，例如 `/dev/ttyUSB0` |
| `robot.gripper` 和 `teleop.gripper` | 有夹爪时两边都是 `true`；不使用夹爪时两边都设为 `false` |
| `teleop.button_enabled` | 有 HD 按钮板时为 `true`；没有时设为 `false` |
| `teleop.button_id` | 默认 `7`，按实际按钮板 ID 修改 |
| `robot.mapping_file` 和 `teleop.mapping_file` | 两边必须指向同一份配对校准文件 |

`sdk_root` 和 `joint_limits_file` 等默认路径可以先保留。相对路径从配置文件所在的 `configs` 目录计算，所以 `../.dependencies/startouch_sdk` 指向仓库根目录下的 SDK。

`nano` 保存：按 `Ctrl+O`，按 Enter，按 `Ctrl+X` 退出。检查 JSON 语法：

```bash
python -m json.tool configs/local.json > /dev/null
```

正常情况没有输出。不要在 JSON 中添加 `//` 注释、中文说明或末尾多余逗号。

### 8. 第一次配对校准

校准会连接真实主从臂，Lumos SDK 初始化时可能使能电机；校准流程不下发关节运动目标。

```bash
lumos-lerobot calibrate --config configs/local.json
```

按终端提示完成：

1. 将两台机械臂放到相互对应的参考姿态，按 Enter 记录参考姿态。
2. 按提示缓慢移动主臂六个关节，覆盖计划使用的遥操作范围；完成后按 Enter 停止范围记录。
3. 启用了夹爪时，分别记录主臂夹爪的闭合与打开位置。
4. 看到校准保存成功后退出。

默认校准文件：

```text
~/.config/stararm102_lumos/calibration.json
```

已有原仓库生成的有效校准文件，并且端口、关节顺序、夹爪配置和参考姿态都一致时，可以直接复用，不必重新校准。

校准文件保存后，在启动执行模式前，Lumos 应处于记录的参考姿态附近。若物理映射、端口路径或夹爪配置改变，重新校准。

### 9. 准备 Lumos 真实关节限位

执行和采集模式必须有从臂限位文件。主臂扫描到的活动范围不代表 Lumos 的机械限位。

**只有确认实际 Lumos 型号与 SDK 的 `FastTouchV2.SLDASM.urdf` 对应，且 `joint1` 到 `joint6` 与 SDK 关节顺序和方向一致时**，才使用下面的导出命令：

```bash
python tools/export_joint_limits.py \
  --urdf .dependencies/startouch_sdk/src/config/FastTouchV2.SLDASM.urdf \
  --output lumos_joint_limits.json
```

如果型号或关节名称不同，改用对应 URDF 和实际关节名；也可以根据厂商核实的 SDK 坐标填写限位文件。输出中的 `lower_rad`、`upper_rad` 都必须是六个 rad 数值。

核对限位后保留该文件，以后启动不用反复导出。文件已经存在时，导出工具会拒绝覆盖；不要为了消除报错随意删掉已经核实的限位文件。

### 10. 环境检查

```bash
lumos-lerobot doctor --config configs/local.json
```

这一步不构造 `SingleArm`，不打开串口或 CAN，只检查依赖、配对校准、配置和插件工厂。正常输出应包含：

```json
{
  "robot_factory": "Lumos",
  "teleop_factory": "StarArm102",
  "recording_patch": true,
  "hardware_connected": false
}
```

实际输出还包含版本、动作字段和限位状态。`hardware_connected: false` 是这一步的正常结果，不是故障；doctor 通过也不代表硬件通信已经验证。

### 11. 首次预览

```bash
lumos-lerobot preview --config configs/local.json
```

缓慢移动主臂，每次先验证一个关节，查看终端中的目标变化是否符合预期。确认关节顺序、方向和夹爪方向后，按 `Ctrl+C` 停止预览。

方向调整位置：

- `teleop.signs`：六个关节分别填写 `1` 或 `-1`。
- `teleop.joint_map`：主臂舵机对应顺序；改变它后需要重新校准。
- `teleop.invert_gripper`：夹爪方向反了时，在 `teleop` 配置中添加 `"invert_gripper": true`。

预览不发关节和夹爪目标，但仍会连接 SDK、使能电机并处理 HD 按钮，不能把它视为断电操作。

### 12. 启动真实遥操作

把 Lumos 恢复到已记录的参考姿态附近，确认前面的方向、限位和预览检查完成，然后运行：

```bash
lumos-lerobot teleop --config configs/local.json
```

现在移动 StarArm102，Lumos 会按映射跟随。第一次先做小幅单关节动作，逐项确认六个关节和夹爪。

程序默认按实际时间限制目标变化速度，最大 50°/s，单帧最多 2°。按 `Ctrl+C` 正常退出；出现卡滞、碰撞或持续力矩报警时立即停止并使用硬件急停。

## 二、以后每天开机：按这个顺序启动

首次安装、校准和限位核对完成后，每天不需要重新安装依赖或重新导出限位。

### 1. 接线、上电、检查急停与工作区

按第一部分的硬件要求接好设备。Lumos 应回到配对校准使用的参考姿态附近。

### 2. 打开终端，进入软件环境

如果按本教程安装了 Miniforge：

```bash
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate lumos-lerobot
cd ~/stararm102-lumos-lerobot
```

使用其他 Conda 安装位置时，先按你自己的方式激活 `lumos-lerobot` 环境，再进入仓库。

### 3. 检查串口和 CAN

```bash
ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
ip -details link show can0
```

CAN 是 `UP` 且速率为 `1000000` 就继续。重启后 CAN 处于 DOWN 时，执行第一部分的 CAN 启用命令。串口路径变化时要处理配置和校准的一致性。

### 4. 运行检查和预览

```bash
lumos-lerobot doctor --config configs/local.json
lumos-lerobot preview --config configs/local.json
```

检查目标变化正常后，按 `Ctrl+C` 退出预览。

### 5. 开始遥操作

```bash
lumos-lerobot teleop --config configs/local.json
```

这是每天真正启动主从跟随的命令。结束时按 `Ctrl+C`，等待程序退出后，按厂商要求进行机械臂断电操作。

## 三、启动数据采集

先完成真实遥操作验证，再采集数据。采集模式本身会控制机器人，不要在另一个终端同时开 `teleop`。

### 1. 找到相机

在已激活的环境和仓库目录中运行：

```bash
lerobot-find-cameras opencv
```

按输出确认设备编号，探测结束后退出该程序，释放相机。不要一边探测、一边启动采集。

### 2. 填写相机配置

把 `configs/local.json` 中的 `robot.cameras` 从 `{}` 改为下面这个对象。`index_or_path` 换成实际相机编号：

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

保持相机支持的分辨率和帧率。没有配置相机也能采集关节数据，但不会产生视觉图像。

### 3. 设置这一批数据的名称和任务

在同一个文件的 `dataset` 部分，修改：

| 配置项 | 示例 |
|---|---|
| `repo_id` | `VincentHSS/lumos_pick_place_001` |
| `root` | `../datasets/lumos_pick_place_001` |
| `single_task` | `Pick up the object and place it in the box` |
| `num_episodes` | `3` |
| `episode_time_s` | `15` |
| `reset_time_s` | `10` |
| `push_to_hub` | `false` |

第一次先采 3 段，每段 15 秒，中间留 10 秒重置场景。`push_to_hub=false` 时只保存在本地；`repo_id` 的命名不会触发上传。

第二批数据换一个新名称和目录，例如把 `_001` 改为 `_002`。本入口不会自动覆盖已有数据目录，也没有启用 resume。

### 4. 开始采集

```bash
lumos-lerobot record --config configs/local.json
```

采集开始后，用主臂完成任务。重置阶段用预留时间恢复物体与场景，注意程序仍可能处理遥操作输入。每个 episode 开头尽量保持一致的任务起始状态。

有键盘监听支持时，LeRobot 使用：

- 右方向键：提前结束当前阶段。
- 左方向键：请求重录当前 episode。
- Esc：结束采集。

图形桌面、SSH、终端焦点和键盘权限会影响按键监听；看终端提示确认监听是否可用。未启用监听时，按配置的 episode 数量和时长完成；紧急情况使用硬件急停。

### 5. 检查保存结果

正常结束并完成写盘后，查看配置的保存目录，例如：

```bash
find datasets/lumos_pick_place_001 -maxdepth 3 -type f | head -30
```

应能找到元数据和 Parquet 文件；启用了相机视频时还有 MP4 文件。数据中：

- `observation.state` 是从臂实测状态。
- `action` 是限位限速后最终发送的目标。
- `observation.images.front` 是相机画面。

第一次务必检查数据与真实动作、图像是否对应，再扩大采集数量。已完成实机数据采集之后，才进入模型训练工作。

## 四、常见启动问题

| 现象 | 处理方法 |
|---|---|
| `conda: command not found` | 执行本教程对应 Conda 安装目录的 `source .../etc/profile.d/conda.sh` |
| `lumos-lerobot: command not found` | 激活 `lumos-lerobot` 环境，并确认安装脚本成功结束；可用 `python -m lerobot_robot_lumos_stararm102.cli preview --config configs/local.json` 排查入口 |
| Python 是 3.10 或其他版本 | 重新激活 Python 3.12 的 `lumos-lerobot` 环境 |
| 串口 `Permission denied` | 加入 `dialout` 组后注销并重新登录，不要用 sudo 启动控制程序 |
| 找不到 `/dev/ttyUSB0` | 查看实际串口名和 `/dev/serial/by-id/`，核对主臂 USB 连接 |
| CAN 提示找不到设备 | 检查适配器驱动和实际 CAN 接口名 |
| CAN 提示 busy | 查看是否已 UP、速率是否正确；需要改配置时先停止控制程序 |
| 没有校准文件 | 核对配置中的路径，首次运行 `calibrate` |
| 端口或 `joint_map` 与校准不一致 | 使用原先校准的配置，或重新完成配对校准；不要随意改 JSON 内的参考角度 |
| HD 按钮 ID 7 不响应 | 有按钮时检查接线和 ID；确实没有按钮板才将 `button_enabled` 改为 `false` |
| `Lumos is away from calibrated home` | 按厂商操作恢复原参考姿态，或重新配对校准；不要直接放大容差跳过检查 |
| 缺少 `joint_limits_file` | 按第一部分第 9 步准备并核实真实从臂限位 |
| SDK 找不到 `robot_kinematics.yaml` | 检查 `.dependencies/startouch_sdk/src/config/robot_kinematics.yaml` 是否存在，核对 `robot.sdk_root` |
| 相机打不开 | 核对设备号、权限、分辨率，关闭占用相机的其他程序 |
| 数据目录已经存在 | 换一个新的数据名称和目录，不要覆盖已有采集结果 |
| 力矩报警、卡滞、异常运动 | 立即停止并使用硬件急停，检查机械状态和映射；不要提高保护阈值掩盖问题 |

## 五、当前验证范围

软件已通过 20 项测试，覆盖真实 LeRobot 工厂、命令行、遥操作循环、数据集写入/读取、H.264 MP4 和回放函数。测试中的串口、CAN SDK、相机与键盘使用替身。

本仓库尚未在你的实际 Ubuntu 机器人主机上完成 SDK 编译、通信和运动验收。第一次启动仍需按上面的预览、方向、限位和小幅动作顺序调试。详细测试环境见 [验证记录](../VALIDATION.md)。
