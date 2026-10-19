# 接入验证记录

验证日期：2026-10-20。

## 实际使用的环境

- Windows，独立 Python 3.12 虚拟环境。
- 真实 LeRobot commit `3991580a5673f5f0219a4e8835a5f973eeccf9a7`，版本 0.6.2。
- 安装 `lerobot[core_scripts]`，不是用测试替身代替 LeRobot 框架。
- torch 2.11.0+cpu、torchvision 0.26.0+cpu、datasets 4.8.5、pyarrow 26.0.0、draccus 0.11.6、PyAV 15.1.0、fashionstar-uart-sdk 1.3.12、pyserial 3.5。
- 本插件 editable 安装成功；标准 wheel 构建成功；`pip check` 无依赖冲突。

## 检查结果

20 个单元/集成测试全部通过，包括原仓库的 9 个测试。新增集成测试只替换物理 SDK、UART、相机和键盘监听，使用真实的：

- LeRobot 插件发现、配置注册、Robot/Teleoperator 工厂。
- `lerobot-teleoperate` 的命令行解析、处理器和控制循环。
- `lerobot-record` 的命令行解析、录制循环和数据集写入。
- H.264 MP4 编码，以及 PyAV 视频解码。
- LeRobotDataset 重新加载，确认 action 为 7 维、图像为 CHW 格式。
- `lerobot-replay` 的回放函数和数据读取。

测试逐帧比较 Parquet 中保存的六关节动作和 SDK 测试替身接收到的目标，确认保存的是最终限速后的目标，而不是未限速的主臂映射值。

还覆盖了：无夹爪六维接口、HD 按钮只锁定六个主臂关节、doctor 不实例化 SingleArm、不打开设备、预览不发送运动目标、启动参考姿态不符时中止并清理、非有限输入不发送、按真实 dt 限速及单帧限幅。

Ruff 检查通过；新代码已格式化。原脚本和 `_legacy.py` 保持原逻辑，Ubuntu shell 脚本保存为 LF 换行。录制修正脚本在基线源文件上验证通过并保留备份。

## 未验证的部分

没有连接实际 StarArm102、Lumos、USB 摄像头或 CAN 接口。没有在 Ubuntu 上执行 apt/SDK 编译和整套安装脚本，也没有完成真实运动、实际采集频率、碰撞/力矩保护、模型训练或策略部署验收。

本机 torchcodec 的 DLL 依赖无法加载，上游会回退到 PyAV；视频集成测试使用 PyAV 验证成功。这不影响该次 H.264 录制/读取验证，但不代表已验证 torchcodec 后端。

交付物可以作为指定版本 LeRobot 的硬件适配代码安装使用；真实机器人是否完整可用，仍需在 Ubuntu 主机按 README 完成构建、方向和限位检查以及实机调试。

## 无摄像头教程命令验证

2026-10-20 对 `docs/stararm102-lumos.md` 中的四条 LeRobot 原生命令进行了验证：从 Markdown 直接提取参数，由真实 draccus/LeRobot 配置解析，使用物理设备测试替身执行短流程。测试仅缩短运行时间、采集回合数，并将端口和路径替换为临时测试设备路径。

- 预览命令：成功执行，不向设备发送目标。
- 遥操作命令：成功通过主从臂接口发送限速目标。
- 无摄像头采集命令：成功保存并重新读取纯关节数据集，状态/动作均为 7 维，且没有图像字段。
- 回放命令：成功读取并回放第 0 个回合。

这些验证不替代 Ubuntu 安装和真实机械臂验收。
