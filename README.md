# StarArm102 → Lumos：LeRobot 接入版

[**从安装到遥操作的完整实操教程**](docs/stararm102-lumos.md)

教程按 **环境搭建 → 接线与端口 → 校准 → 遥操作 → 关节数据采集 → 回放** 编写，暂不配置摄像头。

## 设备接入

- `--robot.type=lumos`：Lumos 单臂，CAN / SingleArm SDK。
- `--teleop.type=stararm102`：StarArm102 主臂，UART / FashionStar SDK，保留 HD 按钮和配对校准映射。
- 关节使用绝对位置，单位 rad；夹爪使用 0～1 开度。
- LeRobot 原生命令自动发现本插件，支持遥操作、关节数据采集与回放。

## 安装

在 Ubuntu 22.04 / 24.04 x86_64 的 Python 3.12 环境中：

```bash
git clone https://github.com/VincentHSS/stararm102-lumos-lerobot.git
cd stararm102-lumos-lerobot
bash scripts/install_lerobot_ubuntu.sh
```

首次使用按 [完整教程](docs/stararm102-lumos.md) 完成环境、硬件、校准和限位检查，再启动执行模式。SDK 初始化可能使能电机，预览也会连接 SDK。

## 配置文件入口

除教程中的 LeRobot 原生命令，也保留 `lumos-lerobot` 统一入口：

```bash
lumos-lerobot doctor --config configs/local.json
lumos-lerobot preview --config configs/local.json
```

配置模板见 [configs/example.json](configs/example.json)。该入口从配置文件读取端口和路径，不读取教程中的 `STARARM_PORT` 等环境变量；使用时须保持配置与校准文件一致。`teleop`、`record` 模式会真实发送动作。

## 代码位置

| 文件 | 职责 |
|---|---|
| `src/lerobot_robot_lumos_stararm102/config.py` | 主从臂注册和参数 |
| `stararm102.py` | UART 读取、HD 按钮、滤波、主从映射 |
| `lumos.py` | CAN SDK、实测状态、目标限位限速与发送 |
| `common.py` | 校准文件、字段与公共数学处理 |
| `cli.py` | 配置文件启动入口 |
| `tools/patch_record.py` | 让固定版本录制限速后的实际下发目标 |

## 验证与来源

软件测试与硬件验证范围见 [VALIDATION.md](VALIDATION.md)。完整测试：

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

原脚本、原安装脚本和原单元测试来自 [VincentHSS/stararm102-lumos-teleop](https://github.com/VincentHSS/stararm102-lumos-teleop)，原说明保存在 [README_STANDALONE.md](README_STANDALONE.md)。原仓库未声明开源许可证，本仓库不替原作者授予额外的复制、修改或分发许可。
