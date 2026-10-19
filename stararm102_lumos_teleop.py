#!/usr/bin/env python3
"""Star Arm 102 leader -> Lumos StarTouch single-arm Python teleoperation.

Run --calibrate first. Calibration records a neutral pose and the leader's
intended joint ranges. It never commands robot motion. Teleoperation is
read-only for Lumos unless --execute is supplied. The HD leader button is
enabled by default and controls leader holding torque even in preview mode.
Use --button-disable for a leader without the HD button board.

IMPORTANT: This is a starting bridge, not a verified joint mapping. Confirm
joint order and direction with the arms clear and hardware E-stop reachable.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import threading
import time
from pathlib import Path
from contextlib import contextmanager
from typing import Sequence

LEADER_JOINT_IDS = (0, 1, 2, 3, 4, 5)
CALIBRATION_VERSION = 1

# ===================== 用户可调整的遥操作参数 =====================
# 顺序对应 Lumos 关节 1..6；1=同向，-1=反向。
JOINT_SIGNS = (-1.0, 1.0, 1.0, 1.0, -1.0, -1.0)
FOLLOW_GAIN = 1.0          # 主臂角度变化映射比例，范围 (0, 1]
MAX_SPEED_DEG_PER_SEC = 50.0  # 按实际时间限速；保持原 50 Hz 时的速度上限
MAX_TARGET_STEP_DEG = 2.0  # 单帧最大目标变化；通信卡顿后也不追赶大步
FILTER_MIN_CUTOFF_HZ = 5.0  # 静止/慢速时抑制角度噪声
FILTER_BETA = 0.15        # 快速运动时提高截止频率，减少滤波延迟
STATUS_RATE_HZ = 5.0      # 状态打印频率，避免每帧刷新终端
CONTROL_RATE_HZ = 50.0     # 读主臂/更新 Lumos 目标的循环频率
HD_BUTTON_ENABLED = True  # 默认开启 HD 实体按钮悬停功能
HD_BUTTON_ID = 7          # HD 按钮板 ID；不参与关节/夹爪映射
# ================================================================


class JointFilter:
    """Adaptive low-pass filter in degrees; fast motion receives less smoothing."""

    def __init__(self):
        self.raw: list[float] | None = None
        self.filtered: list[float] = []
        self.speed: list[float] = []

    def update(self, values: Sequence[float], dt: float) -> list[float]:
        if not all(math.isfinite(value) for value in values):
            raise RuntimeError("主臂返回无效角度，停止遥操作")
        if self.raw is None:
            self.raw = list(values)
            self.filtered = list(values)
            self.speed = [0.0] * len(values)
            return self.filtered.copy()
        dt = max(dt, 1e-6)
        speed_alpha = dt / (dt + 1.0 / (2.0 * math.pi * 5.0))
        for i, value in enumerate(values):
            self.speed[i] += speed_alpha * ((value - self.raw[i]) / dt - self.speed[i])
            cutoff = FILTER_MIN_CUTOFF_HZ + FILTER_BETA * abs(self.speed[i])
            alpha = dt / (dt + 1.0 / (2.0 * math.pi * cutoff))
            self.filtered[i] += alpha * (value - self.filtered[i])
        self.raw = list(values)
        return self.filtered.copy()


def limit_target(previous: Sequence[float], desired: Sequence[float], dt: float) -> list[float]:
    # Bound long gaps rather than converting a communication stall into a jump.
    step = math.radians(min(MAX_TARGET_STEP_DEG, MAX_SPEED_DEG_PER_SEC * max(0.0, dt)))
    return [old + max(-step, min(step, new - old)) for old, new in zip(previous, desired)]


def parse_joint_map(value: str) -> tuple[int, ...]:
    try:
        ids = tuple(int(part.strip()) for part in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected six StarArm servo IDs, e.g. 0,1,2,3,4,5") from exc
    if len(ids) != 6 or len(set(ids)) != 6 or any(item not in LEADER_JOINT_IDS for item in ids):
        raise argparse.ArgumentTypeError("joint map must be six distinct IDs from 0 through 5")
    return ids


class HDButton:
    """Match python-sdk/stararm102_ro.py: 180 degrees locks joints 0..5."""

    def __init__(self, leader, button_id: int):
        self.leader = leader
        self.id = button_id
        self.locked: bool | None = None
        if not leader.ping(button_id):
            raise RuntimeError(
                f"HD 按钮板 ID {button_id} 未响应。请检查连接/ID；无按钮时加 --button-disable。"
            )

    def update(self) -> None:
        angle = float(self.leader.servos[self.id].angle_monitor)
        if not math.isfinite(angle):
            raise RuntimeError(f"HD 按钮板 ID {self.id} 返回了无效状态")
        locked = angle == 180.0
        if locked == self.locked:
            return
        # Only affect the six arm joints; never lock the gripper or button board.
        for servo_id in LEADER_JOINT_IDS:
            self.leader.stop_on_control_mode(servo_id, 0x11 if locked else 0x10, 0x00)
        self.locked = locked
        print("\nHD 主臂：悬停锁定" if locked else "\nHD 主臂：释放，可拖动")


def read_leader(leader, joint_map: Sequence[int], include_gripper: bool = False,
                hd_button: HDButton | None = None) -> list[float]:
    ids = list(joint_map)
    if include_gripper:
        ids.append(6)
    monitor_ids = ids + ([hd_button.id] if hd_button is not None else [])
    leader.send_sync_servo_monitor(monitor_ids)
    if hd_button is not None:
        hd_button.update()
    return [float(leader.servos[servo_id].angle_monitor) for servo_id in ids]


def load_sdk():
    try:
        import serial
        import fashionstar_uart_sdk as uservo
        from startouchclass import SingleArm
    except ImportError as exc:
        raise RuntimeError(
            f"缺少 Python SDK：{exc}。请在同一个 Python 环境安装 pyserial、fashionstar-uart-sdk 和 Lumos startouch_sdk。"
        ) from exc
    return serial, uservo, SingleArm


def find_sdk_root(explicit: Path | None = None) -> Path | None:
    script_dir = Path(__file__).resolve().parent
    candidates = ([explicit] if explicit is not None else [
        script_dir / ".dependencies" / "startouch_sdk",
        script_dir / "startouch_sdk", Path.cwd(), Path.cwd() / "startouch_sdk",
    ])
    for candidate in candidates:
        root = candidate.expanduser().resolve()
        if (root / "src" / "config" / "robot_kinematics.yaml").is_file():
            return root
    if explicit is not None:
        raise RuntimeError(f"SDK 配置不存在：{explicit}/src/config/robot_kinematics.yaml")
    return None


@contextmanager
def sdk_initialization_directory(root: Path | None):
    original = Path.cwd()
    try:
        if root is not None:
            os.chdir(root)
        yield
    finally:
        os.chdir(original)


def print_joint_ranges(range_min: Sequence[float], range_max: Sequence[float]) -> None:
    print("\n┌────────┬────────────┬────────────┬────────────┐")
    print("│ 关节   │ 最小角度° │ 最大角度° │ 范围°     │")
    print("├────────┼────────────┼────────────┼────────────┤")
    for index, (low, high) in enumerate(zip(range_min, range_max), start=1):
        print(f"│ J{index:<5} │ {low:>10.2f} │ {high:>10.2f} │ {high-low:>10.2f} │")
    print("└────────┴────────────┴────────────┴────────────┘")


def main() -> int:
    parser = argparse.ArgumentParser(description="Star Arm 102 leader -> Lumos arm teleoperation")
    parser.add_argument("--leader-port", default="/dev/ttyUSB0", help="Star Arm 102 leader UART port")
    parser.add_argument("--can", default="can0", help="Lumos CAN interface")
    parser.add_argument("--sdk-root", type=Path,
                        help="Lumos SDK source root containing src/config/robot_kinematics.yaml")
    parser.add_argument("--joint-map", type=parse_joint_map, default=(0, 1, 2, 3, 4, 5),
                        help="StarArm servo IDs corresponding to Lumos joints 1..6")
    parser.add_argument("--calibration-file", type=Path,
                        default=Path.home() / ".config" / "stararm102_lumos" / "calibration.json")
    parser.add_argument("--calibrate", action="store_true",
                        help="Record neutral pose and leader ranges, then save calibration")
    parser.add_argument("--gripper", action="store_true",
                        help="Calibrate and control StarArm servo 6 -> Lumos gripper")
    parser.add_argument("--invert-gripper", action="store_true",
                        help="Reverse the calibrated gripper mapping if open/close moves the wrong way")
    parser.add_argument("--execute", action="store_true",
                        help="Send commands to Lumos; without this flag only print proposed targets")
    parser.add_argument("--diagnostics-file", type=Path,
                        help="Save loop timing and joint targets to CSV for delay diagnosis")
    button_group = parser.add_mutually_exclusive_group()
    button_group.add_argument("--button-enable", "--button_enable", dest="button_enabled",
                              action="store_true", help="Enable HD leader button (default: enabled)")
    button_group.add_argument("--button-disable", "--button_disable", dest="button_enabled",
                              action="store_false", help="Disable HD button for a leader without a button board")
    parser.set_defaults(button_enabled=HD_BUTTON_ENABLED)
    parser.add_argument("--button-id", "--button_id", type=int, choices=range(7, 254),
                        default=HD_BUTTON_ID, metavar="ID", help="HD button board ID, 7..253 (default: 7)")
    args = parser.parse_args()
    # Keep user paths relative to the launch directory, not the SDK directory.
    args.calibration_file = args.calibration_file.expanduser().resolve()
    if args.diagnostics_file is not None:
        args.diagnostics_file = args.diagnostics_file.expanduser().resolve()

    if len(JOINT_SIGNS) != 6 or any(sign not in (-1.0, 1.0) for sign in JOINT_SIGNS):
        parser.error("JOINT_SIGNS must contain six values, each 1.0 or -1.0")
    parameters = (FOLLOW_GAIN, MAX_SPEED_DEG_PER_SEC, MAX_TARGET_STEP_DEG,
                  CONTROL_RATE_HZ, FILTER_MIN_CUTOFF_HZ, FILTER_BETA, STATUS_RATE_HZ)
    if (not all(math.isfinite(value) for value in parameters)
            or not 0 < FOLLOW_GAIN <= 1 or MAX_SPEED_DEG_PER_SEC <= 0
            or MAX_TARGET_STEP_DEG <= 0 or not 0 < CONTROL_RATE_HZ <= 100
            or FILTER_MIN_CUTOFF_HZ <= 0 or FILTER_BETA < 0 or STATUS_RATE_HZ <= 0):
        parser.error("Check motion, filter, and rate parameters at the top of the script")

    try:
        sdk_root = find_sdk_root(args.sdk_root)
        serial, uservo, SingleArm = load_sdk()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2

    leader_uart = None
    lumos = None
    diagnostics_file = None
    try:
        leader_uart = serial.Serial(
            port=args.leader_port,
            baudrate=1_000_000,
            parity=serial.PARITY_NONE,
            stopbits=1,
            bytesize=8,
            timeout=0,
        )
        leader = uservo.UartServoManager(leader_uart)
        hd_button = HDButton(leader, args.button_id) if args.button_enabled else None
        if hd_button is not None:
            print(f"HD 按钮功能已开启（ID={hd_button.id}）；预览模式也会控制主臂悬停。")
            read_leader(leader, args.joint_map, args.gripper, hd_button)
        if args.calibrate:
            print("\n╔══════════════════════════════════════════════════════╗")
            print("║       Star Arm 102 → Lumos  校准向导                 ║")
            print("╚══════════════════════════════════════════════════════╝")
            print("请先将 Star Arm 102 与 Lumos 摆到对应的遥操作参考姿态。")
            print("Lumos 连接时会使能电机；确认急停可用、工作区域畅通。")
            input("准备好后按 Enter 连接并记录参考姿态……")
        if sdk_root is not None:
            print(f"Lumos SDK 配置：{sdk_root / 'src/config/robot_kinematics.yaml'}")
        try:
            with sdk_initialization_directory(sdk_root):
                lumos = SingleArm(can_interface_=args.can, gripper=args.gripper, enable_fd_=False)
        except Exception as exc:
            if "Failed to locate config file" in str(exc):
                raise RuntimeError(
                    "Lumos SDK 找不到配置。请检查 .dependencies/startouch_sdk/src/config/robot_kinematics.yaml；"
                    "SDK 在其他目录时，加 --sdk-root /实际路径/startouch_sdk。\n"
                    f"原始错误：{exc}"
                ) from exc
            raise
        time.sleep(2.0)

        if args.calibrate:
            print("\n[1/3] 参考姿态已记录")
            leader_home_and_gripper = read_leader(leader, args.joint_map, args.gripper, hd_button)
            leader_home_deg = leader_home_and_gripper[:6]
            lumos_home_rad = [float(value) for value in lumos.get_joint_positions()]
            if len(lumos_home_rad) != 6:
                raise RuntimeError(f"Lumos 应返回 6 个关节位置，实际返回 {len(lumos_home_rad)} 个")

            print("\n[2/3] 记录主臂关节范围")
            print("缓慢移动六个关节，覆盖实际遥操作会用到的范围；完成后按 Enter 停止。")
            range_min = [float("inf")] * 6
            range_max = [float("-inf")] * 6

            stop_recording = threading.Event()

            def wait_for_enter() -> None:
                input("按 Enter 停止范围记录……")
                stop_recording.set()

            threading.Thread(target=wait_for_enter, daemon=True).start()
            samples = 0
            last_report = time.monotonic()
            while not stop_recording.is_set():
                values = read_leader(leader, args.joint_map, hd_button=hd_button)
                range_min = [min(old, value) for old, value in zip(range_min, values)]
                range_max = [max(old, value) for old, value in zip(range_max, values)]
                samples += 1
                if time.monotonic() - last_report >= 1.0:
                    summary = "  ".join(f"J{i+1}:{lo:.0f}..{hi:.0f}°" for i, (lo, hi) in enumerate(zip(range_min, range_max)))
                    print(f"\r采集中 {samples:>5} 帧  {summary:<90}", end="", flush=True)
                    last_report = time.monotonic()
                time.sleep(1.0 / CONTROL_RATE_HZ)
            if any(hi - lo < 2.0 for lo, hi in zip(range_min, range_max)):
                raise RuntimeError("至少一个主臂关节记录范围不足 2 度；请重新校准并移动六个关节。")
            print("\n\n[3/3] 记录结果")
            print_joint_ranges(range_min, range_max)

            gripper_range = None
            if args.gripper:
                print("\n夹爪范围")
                input("把 StarArm 夹爪摆到完全闭合位置，按 Enter 记录……")
                closed = read_leader(leader, args.joint_map, True, hd_button)[-1]
                input("把 StarArm 夹爪摆到完全打开位置，按 Enter 记录……")
                opened = read_leader(leader, args.joint_map, True, hd_button)[-1]
                if abs(opened - closed) < 2.0:
                    raise RuntimeError("夹爪记录范围不足 2 度；请重新校准。")
                gripper_range = {"closed_deg": closed, "open_deg": opened}

            calibration = {
                "format_version": CALIBRATION_VERSION,
                "leader_port": args.leader_port,
                "can_interface": args.can,
                "joint_map": list(args.joint_map),
                "signs": list(JOINT_SIGNS),
                "gain": FOLLOW_GAIN,
                "max_speed_deg_per_sec": MAX_SPEED_DEG_PER_SEC,
                "leader_home_deg": leader_home_deg,
                "leader_range_min_deg": range_min,
                "leader_range_max_deg": range_max,
                "lumos_home_rad": lumos_home_rad,
                "gripper_enabled": args.gripper,
                "gripper_range": gripper_range,
            }
            args.calibration_file.parent.mkdir(parents=True, exist_ok=True)
            args.calibration_file.write_text(json.dumps(calibration, indent=2), encoding="utf-8")
            print(f"\n校准完成，已保存到：{args.calibration_file}")
            print("校准完成。先预览检查方向，确认后再使用 --execute。")
            return 0

        if not args.calibration_file.is_file():
            raise RuntimeError(f"没有校准文件：{args.calibration_file}。先加 --calibrate 运行校准。")
        calibration = json.loads(args.calibration_file.read_text(encoding="utf-8"))
        if calibration.get("format_version") != CALIBRATION_VERSION:
            raise RuntimeError("校准文件版本不兼容，请重新运行 --calibrate。")
        if calibration["leader_port"] != args.leader_port or calibration["can_interface"] != args.can:
            raise RuntimeError("端口与校准文件不一致，请使用原端口或重新校准。")
        if calibration["joint_map"] != list(args.joint_map):
            raise RuntimeError("--joint-map 与校准文件不一致，请重新校准。")
        if bool(calibration["gripper_enabled"]) != args.gripper:
            raise RuntimeError("夹爪设置与校准文件不一致；请使用相同的 --gripper 设置。")

        leader_home_deg = calibration["leader_home_deg"]
        leader_min_deg = calibration["leader_range_min_deg"]
        leader_max_deg = calibration["leader_range_max_deg"]
        lumos_home_rad = calibration["lumos_home_rad"]
        # Motion parameters are intentionally taken from the code constants above,
        # not the old calibration JSON, so edits here always take effect.
        signs = JOINT_SIGNS
        gain = FOLLOW_GAIN
        gripper_range = calibration["gripper_range"]
        previous_target = [float(value) for value in lumos.get_joint_positions()]
        if len(previous_target) != 6:
            raise RuntimeError(f"Lumos 应返回 6 个关节位置，实际返回 {len(previous_target)} 个")
        home_error = [abs(now - calibrated) for now, calibrated in zip(previous_target, lumos_home_rad)]
        if args.execute and any(error > 0.15 for error in home_error):
            raise RuntimeError(
                "Lumos 当前姿态与校准参考姿态相差超过 0.15 rad。请摆回参考姿态或重新校准。"
            )

        print("EXECUTE: 正在控制 Lumos" if args.execute else "预览模式：只显示目标，不驱动 Lumos")
        print(f"校准文件：{args.calibration_file}")
        print(f"固定参数：signs={list(JOINT_SIGNS)}, gain={FOLLOW_GAIN}, max_speed={MAX_SPEED_DEG_PER_SEC}°/秒, rate={CONTROL_RATE_HZ}Hz")
        print("Lumos 参考姿态 (rad)：", [round(v, 3) for v in lumos_home_rad])
        print("工作空间保持畅通；Ctrl+C 停止。")

        period = 1.0 / CONTROL_RATE_HZ
        next_tick = time.monotonic()
        started = next_tick
        last_sample = None
        last_status = started
        report_started = started
        report_frames = 0
        overrun_count = 0
        joint_filter = JointFilter()
        diagnostics = None
        if args.diagnostics_file is not None:
            args.diagnostics_file.parent.mkdir(parents=True, exist_ok=True)
            diagnostics_file = args.diagnostics_file.open("w", newline="", encoding="utf-8")
            diagnostics = csv.writer(diagnostics_file)
            diagnostics.writerow(["elapsed_s", "sample_interval_ms", "read_ms", "send_ms",
                                  "work_ms", "target_error_deg", "overrun"]
                                 + [f"leader_j{i}_deg" for i in range(1, 7)]
                                 + [f"target_j{i}_rad" for i in range(1, 7)])
        while True:
            loop_started = time.monotonic()
            feedback = read_leader(leader, args.joint_map, args.gripper, hd_button)
            sample_time = time.monotonic()
            dt = period if last_sample is None else sample_time - last_sample
            last_sample = sample_time
            leader_deg = feedback[:6]
            filtered_deg = joint_filter.update(leader_deg, dt)
            clipped = [max(lo, min(hi, value))
                       for value, lo, hi in zip(filtered_deg, leader_min_deg, leader_max_deg)]
            delta_rad = [math.radians(now - home) for now, home in zip(clipped, leader_home_deg)]
            desired = [home + sign * gain * delta
                       for home, sign, delta in zip(lumos_home_rad, signs, delta_rad)]
            target = limit_target(previous_target, desired, dt)

            send_started = time.monotonic()
            if args.execute:
                lumos.set_joint_raw(target, [0.0] * 6)
            previous_target = target

            line = f"leader_deg={[round(v, 1) for v in leader_deg]}"
            if hd_button is not None:
                line += " HD=悬停" if hd_button.locked else " HD=释放"
            if args.gripper:
                g = feedback[-1]
                closed = float(gripper_range["closed_deg"])
                opened = float(gripper_range["open_deg"])
                grip_ratio = max(0.0, min(1.0, (g - closed) / (opened - closed)))
                if args.invert_gripper:
                    grip_ratio = 1.0 - grip_ratio
                line += f" gripper={grip_ratio:.2f}"
                if args.execute:
                    lumos.setGripperPosition(grip_ratio)
            send_finished = time.monotonic()
            work_ms = (send_finished - loop_started) * 1000.0
            target_error = math.degrees(max(abs(new - sent) for new, sent in zip(desired, target)))
            overrun = work_ms > period * 1000.0
            overrun_count += int(overrun)
            report_frames += 1
            if diagnostics is not None:
                diagnostics.writerow([sample_time - started, dt * 1000.0,
                                      (sample_time - loop_started) * 1000.0,
                                      (send_finished - send_started) * 1000.0,
                                      work_ms, target_error, int(overrun)] + leader_deg + target)
            if send_finished - last_status >= 1.0 / STATUS_RATE_HZ:
                actual_hz = report_frames / max(send_finished - report_started, 1e-6)
                line += (f" rate={actual_hz:.1f}Hz read={(sample_time-loop_started)*1000:.1f}ms"
                         f" target_gap={target_error:.1f}° overruns={overrun_count}")
                print(line, end="\r", flush=True)
                last_status = send_finished
                if diagnostics_file is not None:
                    diagnostics_file.flush()
                if send_finished - report_started >= 1.0:
                    report_frames = 0
                    report_started = send_finished

            next_tick += period
            delay = next_tick - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_tick = time.monotonic()

    except KeyboardInterrupt:
        print("\n遥操作已停止。")
        return 0
    except Exception as exc:
        print(f"\n运行失败：{exc}", file=sys.stderr)
        return 1
    finally:
        if diagnostics_file is not None:
            diagnostics_file.close()
        if lumos is not None:
            try:
                lumos.cleanup()
            except Exception as exc:
                print(f"Lumos cleanup warning: {exc}", file=sys.stderr)
        if leader_uart is not None and leader_uart.is_open:
            leader_uart.close()


if __name__ == "__main__":
    raise SystemExit(main())
