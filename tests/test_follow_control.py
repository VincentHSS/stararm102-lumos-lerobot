import importlib.util
import csv
import io
import json
import math
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "teleop", Path(__file__).resolve().parents[1] / "stararm102_lumos_teleop.py"
)
teleop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(teleop)


class FollowControlTests(unittest.TestCase):
    def test_sdk_root_discovery_and_initialization_directory(self):
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "startouch_sdk"
            config = root / "src/config/robot_kinematics.yaml"
            config.parent.mkdir(parents=True)
            config.write_text("test: true", encoding="utf-8")
            self.assertEqual(teleop.find_sdk_root(root), root.resolve())
            with patch.object(teleop, "__file__", str(Path(directory) / "teleop.py")):
                self.assertEqual(teleop.find_sdk_root(), root.resolve())
            with self.assertRaisesRegex(RuntimeError, "初始化失败"):
                with teleop.sdk_initialization_directory(root):
                    self.assertEqual(Path.cwd(), root.resolve())
                    raise RuntimeError("初始化失败")
            self.assertEqual(Path.cwd(), original)
            with self.assertRaises(RuntimeError):
                teleop.find_sdk_root(Path(directory) / "missing")

    def test_speed_independent_of_normal_loop_rate(self):
        for hz in (25, 50, 100):
            with self.subTest(hz=hz):
                position = [0.0] * 6
                for _ in range(hz):
                    position = teleop.limit_target(position, [math.pi] * 6, 1.0 / hz)
                self.assertAlmostEqual(math.degrees(position[0]), 50.0)

    def test_stalled_read_cannot_cause_large_target_jump(self):
        position = teleop.limit_target([0.0] * 6, [math.pi] * 6, 0.8)
        self.assertAlmostEqual(math.degrees(position[0]), 2.0)

    def test_reversal_and_arrival_do_not_overshoot(self):
        self.assertEqual(teleop.limit_target([0.01] * 6, [0.0] * 6, 0.02), [0.0] * 6)
        result = teleop.limit_target([0.0] * 6, [-math.pi] * 6, 0.02)
        self.assertAlmostEqual(math.degrees(result[0]), -1.0)

    def test_filter_starts_at_actual_pose(self):
        pose = [10.0, -20.0, 90.0, 40.0, -50.0, 60.0]
        self.assertEqual(teleop.JointFilter().update(pose, 0.02), pose)

    def test_small_stationary_noise_is_reduced(self):
        filt = teleop.JointFilter()
        filt.update([0.0] * 6, 0.02)
        values = []
        for i in range(100):
            result = filt.update([0.1 if i % 2 else -0.1] * 6, 0.02)
            if i >= 50:
                values.append(result[0])
        rms = math.sqrt(sum(x * x for x in values) / len(values))
        self.assertLess(rms, 0.04)

    def test_fast_ramp_has_small_filter_lag(self):
        filt = teleop.JointFilter()
        filt.update([0.0] * 6, 0.02)
        for i in range(1, 101):
            result = filt.update([float(i)] * 6, 0.02)
        self.assertLess(100.0 - result[0], 1.0)

    def test_invalid_joint_feedback_is_rejected(self):
        for bad in (float("nan"), float("inf")):
            with self.assertRaises(RuntimeError):
                teleop.JointFilter().update([bad] * 6, 0.02)

    def test_preview_and_execute_with_old_calibration_and_diagnostics(self):
        for execute in (False, True):
            with self.subTest(execute=execute), tempfile.TemporaryDirectory() as directory:
                directory = Path(directory)
                calibration = directory / "calibration.json"
                calibration.write_text(json.dumps({
                    "format_version": 1, "leader_port": "mock", "can_interface": "can0",
                    "joint_map": list(range(6)), "gripper_enabled": True,
                    "leader_home_deg": [0.0] * 6,
                    "leader_range_min_deg": [-90.0] * 6,
                    "leader_range_max_deg": [90.0] * 6,
                    "lumos_home_rad": [0.0] * 6, "max_step_deg": 1.0,
                    "gripper_range": {"closed_deg": 0, "open_deg": 90},
                }), encoding="utf-8")
                uart = SimpleNamespace(is_open=True)
                uart.close = lambda: setattr(uart, "is_open", False)
                leader = SimpleNamespace(servos={
                    i: SimpleNamespace(angle_monitor=0.0) for i in range(7)
                })
                frames = 0

                def monitor(ids):
                    nonlocal frames
                    frames += 1
                    if frames > 20:
                        raise KeyboardInterrupt
                    for i in ids:
                        leader.servos[i].angle_monitor = 30.0 if i == 6 else frames * 0.5

                leader.send_sync_servo_monitor = monitor
                commands, grips, cleanups = [], [], []
                arm = SimpleNamespace(
                    get_joint_positions=lambda: [0.0] * 6,
                    set_joint_raw=lambda q, v: commands.append((q, v)),
                    setGripperPosition=lambda g: grips.append(g),
                    cleanup=lambda: cleanups.append(True),
                )
                serial = SimpleNamespace(Serial=lambda **kwargs: uart, PARITY_NONE="N")
                sdk = SimpleNamespace(UartServoManager=lambda uart: leader)
                clock = 0.0

                def now():
                    nonlocal clock
                    clock += 0.005
                    return clock

                log = directory / "diagnostics.csv"
                argv = ["teleop", "--leader-port", "mock", "--gripper", "--button-disable",
                        "--calibration-file", str(calibration), "--diagnostics-file", str(log)]
                if execute:
                    argv.append("--execute")
                with (patch.object(teleop, "load_sdk", return_value=(serial, sdk, lambda **kw: arm)),
                      patch.object(teleop.time, "monotonic", side_effect=now),
                      patch.object(teleop.time, "sleep"), patch("sys.argv", argv),
                      redirect_stdout(io.StringIO())):
                    self.assertEqual(teleop.main(), 0)
                with log.open(encoding="utf-8", newline="") as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 20)
                self.assertTrue(all(float(row["read_ms"]) > 0 for row in rows))
                self.assertEqual(len(commands), 20 if execute else 0)
                self.assertEqual(len(grips), 20 if execute else 0)
                self.assertTrue(all(abs(g - 1 / 3) < 1e-9 for g in grips))
                previous = [0.0] * 6
                for q, v in commands:
                    self.assertEqual(v, [0.0] * 6)
                    self.assertLessEqual(max(abs(a-b) for a,b in zip(q, previous)),
                                         math.radians(2.0) + 1e-9)
                    previous = q
                self.assertFalse(uart.is_open)
                self.assertEqual(cleanups, [True])


if __name__ == "__main__":
    unittest.main()
