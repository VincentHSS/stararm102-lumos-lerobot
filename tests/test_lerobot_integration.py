"""Real LeRobot imports, registry, CLI config, processors and dataset; fake hardware only.

Run after installation: python -m unittest discover -s tests -p 'test_*.py' -v
No physical devices, real keyboard listener, or Hub upload are used.
"""

import io
import json
import math
import sys
import tempfile
import types
import unittest
from contextlib import ExitStack, contextmanager, redirect_stdout
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import numpy as np
from lerobot.cameras.opencv import OpenCVCameraConfig
from lerobot.robots import make_robot_from_config
from lerobot.teleoperators import make_teleoperator_from_config
from lerobot.utils.import_utils import register_third_party_plugins

from lerobot_robot_lumos_stararm102 import LumosConfig, StarArm102Config
from lerobot_robot_lumos_stararm102.cli import command_for, doctor, load_session
from lerobot_robot_lumos_stararm102.common import JOINT_KEYS, limit_target


@contextmanager
def hardware_modules(modules):
    # Only restore these device modules. patch.dict(sys.modules) would also remove
    # newly imported LeRobot modules while leaving draccus registry entries alive.
    missing = object()
    previous = {name: sys.modules.get(name, missing) for name in modules}
    sys.modules.update(modules)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


class FakeArm:
    instances = []
    home = [0.0, 0.0, -1.0, 0.0, 0.0, 0.0]

    def __init__(self, **kwargs):
        self.positions = self.home.copy()
        self.gripper = 0.4
        self.commands = []
        self.grip_commands = []
        self.cleaned = False
        self.instances.append(self)

    def get_joint_positions(self):
        return self.positions.copy()

    def get_gripper_position(self):
        return self.gripper

    def set_joint_raw(self, q, velocities):
        self.commands.append(q.copy())
        self.positions = q.copy()
        return True

    def setGripperPosition(self, value):
        self.grip_commands.append(value)
        self.gripper = value
        return True

    def cleanup(self):
        self.cleaned = True


class FakeUART:
    def __init__(self, **kwargs):
        self.is_open = True

    def close(self):
        self.is_open = False


class FakeManager:
    def __init__(self, uart):
        self.servos = {i: types.SimpleNamespace(angle_monitor=10.0) for i in range(8)}
        self.controls = []

    def ping(self, servo_id):
        return True

    def send_sync_servo_monitor(self, ids):
        pass

    def stop_on_control_mode(self, servo_id, mode, extra):
        self.controls.append((servo_id, mode, extra))


class FakeCamera:
    def __init__(self, config):
        self.height, self.width = config.height, config.width
        self.is_connected = False

    def connect(self):
        self.is_connected = True

    def disconnect(self):
        self.is_connected = False

    def async_read(self):
        return np.full((self.height, self.width, 3), 127, dtype=np.uint8)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        sdk = self.root / "sdk/src/config"
        sdk.mkdir(parents=True)
        (sdk / "robot_kinematics.yaml").write_text("{}", encoding="utf-8")
        self.mapping = self.root / "calibration.json"
        self.mapping.write_text(
            json.dumps(
                {
                    "format_version": 1,
                    "gripper_enabled": True,
                    "leader_port": "mock-uart",
                    "can_interface": "mock-can",
                    "joint_map": list(range(6)),
                    "leader_home_deg": [0.0] * 6,
                    "leader_range_min_deg": [-90.0] * 6,
                    "leader_range_max_deg": [90.0] * 6,
                    "lumos_home_rad": FakeArm.home,
                    "gripper_range": {"closed_deg": 0, "open_deg": 100},
                }
            ),
            encoding="utf-8",
        )
        self.limits = self.root / "limits.json"
        self.limits.write_text(
            json.dumps({"lower_rad": [-2.0] * 6, "upper_rad": [2.0] * 6}), encoding="utf-8"
        )
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        sdk_module = types.ModuleType("startouchclass")
        sdk_module.SingleArm = FakeArm
        uart_module = types.ModuleType("fashionstar_uart_sdk")
        uart_module.UartServoManager = FakeManager
        self.stack.enter_context(
            hardware_modules({"startouchclass": sdk_module, "fashionstar_uart_sdk": uart_module})
        )
        self.stack.enter_context(patch("serial.Serial", FakeUART))
        self.stack.enter_context(
            patch(
                "lerobot_robot_lumos_stararm102.lumos.make_cameras_from_configs",
                lambda configs: {key: FakeCamera(cfg) for key, cfg in configs.items()},
            )
        )
        register_third_party_plugins()

    def configs(self, execute=True, camera=False):
        robot = LumosConfig(
            id="unit-lumos",
            calibration_dir=self.root / "robot-calibration",
            can_interface="mock-can",
            sdk_root=str(self.root / "sdk"),
            mapping_file=str(self.mapping),
            joint_limits_file=str(self.limits),
            execute=execute,
            startup_wait_s=0.001,
            cameras={"front": OpenCVCameraConfig(index_or_path=0, width=32, height=24, fps=30)}
            if camera
            else {},
        )
        leader = StarArm102Config(
            id="unit-leader",
            calibration_dir=self.root / "leader-calibration",
            port="mock-uart",
            mapping_file=str(self.mapping),
            button_enabled=False,
        )
        return robot, leader

    def test_real_factories_and_preconnect_features(self):
        rc, tc = self.configs(camera=True)
        robot, leader = make_robot_from_config(rc), make_teleoperator_from_config(tc)
        self.assertEqual(type(robot).__name__, "Lumos")
        self.assertEqual(type(leader).__name__, "StarArm102")
        self.assertEqual(robot.action_features, leader.action_features)
        self.assertEqual(robot.observation_features["front"], (24, 32, 3))
        self.assertFalse(robot.is_connected)

    def test_mapping_limits_and_real_observation(self):
        rc, tc = self.configs()
        robot, leader = make_robot_from_config(rc), make_teleoperator_from_config(tc)
        self.addCleanup(robot.disconnect)
        self.addCleanup(leader.disconnect)
        leader.connect()
        robot.connect()
        action = leader.get_action()
        self.assertAlmostEqual(action["joint_1.pos"], -math.radians(10))
        self.assertAlmostEqual(action["joint_2.pos"], math.radians(10))
        self.assertAlmostEqual(action["gripper.pos"], 0.1)
        action.update(dict.fromkeys(JOINT_KEYS, 100.0))
        robot._last_send -= 1
        sent = robot.send_action(action)
        self.assertAlmostEqual(sent["joint_1.pos"], math.radians(2))
        self.assertEqual(robot.arm.commands[-1], [sent[k] for k in JOINT_KEYS])
        self.assertAlmostEqual(robot.get_observation()["joint_1.pos"], sent["joint_1.pos"])
        count = len(robot.arm.commands)
        with self.assertRaises(ValueError):
            robot.send_action(action | {"gripper.pos": float("nan")})
        self.assertEqual(len(robot.arm.commands), count)

    def test_preview_sends_no_targets(self):
        rc, tc = self.configs(execute=False)
        robot, leader = make_robot_from_config(rc), make_teleoperator_from_config(tc)
        self.addCleanup(robot.disconnect)
        self.addCleanup(leader.disconnect)
        leader.connect()
        robot.connect()
        robot.send_action(leader.get_action())
        self.assertEqual(robot.arm.commands, [])
        self.assertEqual(robot.arm.grip_commands, [])

    def test_hd_button_only_holds_six_joints(self):
        _, tc = self.configs()
        tc.button_enabled = True
        leader = make_teleoperator_from_config(tc)
        self.addCleanup(leader.disconnect)
        leader.connect()
        leader.leader.servos[7].angle_monitor = 180.0
        leader.get_action()
        self.assertEqual(leader.leader.controls, [(i, 0x11, 0) for i in range(6)])
        leader.leader.servos[7].angle_monitor = 0.0
        leader.get_action()
        self.assertEqual(leader.leader.controls[6:], [(i, 0x10, 0) for i in range(6)])

    def test_no_gripper_six_dimensional_interface(self):
        rc, tc = self.configs()
        rc.gripper = tc.gripper = False
        mapping = json.loads(self.mapping.read_text(encoding="utf-8"))
        mapping["gripper_enabled"] = False
        self.mapping.write_text(json.dumps(mapping), encoding="utf-8")
        robot, leader = make_robot_from_config(rc), make_teleoperator_from_config(tc)
        self.addCleanup(robot.disconnect)
        self.addCleanup(leader.disconnect)
        leader.connect()
        robot.connect()
        self.assertEqual(len(robot.action_features), 6)
        self.assertEqual(len(robot.get_observation()), 6)
        self.assertEqual(len(robot.send_action(leader.get_action())), 6)
        self.assertEqual(robot.arm.grip_commands, [])

    def test_doctor_never_constructs_sdk(self):
        data = load_session(Path(__file__).resolve().parents[1] / "configs/example.json")
        data["robot"].update(
            sdk_root=str(self.root / "sdk"),
            mapping_file=str(self.mapping),
            joint_limits_file=str(self.limits),
            can_interface="mock-can",
            calibration_dir=str(self.root / "doctor-robot"),
        )
        data["teleop"].update(
            port="mock-uart",
            mapping_file=str(self.mapping),
            calibration_dir=str(self.root / "doctor-leader"),
        )
        before = len(FakeArm.instances)
        stream = io.StringIO()
        with redirect_stdout(stream):
            doctor(data)
        report = json.loads(stream.getvalue())
        self.assertFalse(report["hardware_connected"])
        self.assertEqual(report["robot_factory"], "Lumos")
        self.assertEqual(len(FakeArm.instances), before)

    def test_real_native_teleop_cli(self):
        from lerobot.scripts import lerobot_teleoperate

        rc, tc = self.configs(execute=False)
        # Actual parser.wrap reads the real CLI arguments and builds nested device configs.
        args = [
            "lerobot-teleoperate",
            "--robot.type=lumos",
            "--teleop.type=stararm102",
            f"--robot.sdk_root={rc.sdk_root}",
            f"--robot.mapping_file={rc.mapping_file}",
            f"--robot.joint_limits_file={rc.joint_limits_file}",
            "--robot.can_interface=mock-can",
            "--robot.startup_wait_s=0.001",
            "--robot.execute=false",
            f"--robot.calibration_dir={rc.calibration_dir}",
            f"--teleop.calibration_dir={tc.calibration_dir}",
            f"--teleop.mapping_file={tc.mapping_file}",
            "--teleop.port=mock-uart",
            "--teleop.button_enabled=false",
            "--fps=30",
            "--teleop_time_s=0.12",
        ]
        before = len(FakeArm.instances)
        with patch("sys.argv", args):
            lerobot_teleoperate.main()
        self.assertEqual(len(FakeArm.instances), before + 1)
        self.assertTrue(FakeArm.instances[-1].cleaned)
        self.assertEqual(FakeArm.instances[-1].commands, [])

    def test_real_record_loop_and_dataset_roundtrip(self):
        import pyarrow.parquet as pq
        from lerobot.configs.dataset import DatasetRecordConfig
        from lerobot.datasets import LeRobotDataset
        from lerobot.scripts import lerobot_record

        rc, tc = self.configs(camera=True)
        cfg = lerobot_record.RecordConfig(
            robot=rc,
            teleop=tc,
            dataset=DatasetRecordConfig(
                repo_id="local/offline_integration",
                root=self.root / "dataset",
                single_task="Offline mock hardware integration",
                fps=30,
                num_episodes=1,
                episode_time_s=0.15,
                reset_time_s=0,
                push_to_hub=False,
                no_stamp=True,
                video=False,
            ),
            play_sounds=False,
        )
        events = {"exit_early": False, "stop_recording": False, "rerecord_episode": False}
        # Only the hardware, camera and real keyboard capture are replaced.
        with patch.object(lerobot_record, "init_keyboard_listener", return_value=(None, events)):
            dataset = lerobot_record.record(cfg)
        self.assertEqual(dataset.num_episodes, 1)
        self.assertGreater(dataset.num_frames, 0)
        self.assertTrue(FakeArm.instances[-1].cleaned)
        parquet = sorted((self.root / "dataset/data").rglob("*.parquet"))
        self.assertTrue(parquet)
        rows = pq.read_table(parquet[0]).to_pylist()
        sent = FakeArm.instances[-1].commands
        self.assertEqual(len(rows), len(sent))
        for row, target in zip(rows, sent):
            np.testing.assert_allclose(row["action"][:6], target, atol=1e-6)
        # The first large leader delta must not appear as an unclipped training label.
        self.assertLessEqual(abs(rows[0]["action"][0]), math.radians(2) + 1e-6)
        loaded = LeRobotDataset("local/offline_integration", root=self.root / "dataset", video_backend="pyav")
        item = loaded[0]
        self.assertEqual(tuple(item["action"].shape), (7,))
        self.assertEqual(tuple(item["observation.images.front"].shape), (3, 24, 32))

        from lerobot.scripts import lerobot_replay

        replay_cfg = lerobot_replay.ReplayConfig(
            robot=rc,
            dataset=lerobot_replay.DatasetReplayConfig(
                repo_id="local/offline_integration",
                root=self.root / "dataset",
                episode=0,
            ),
            play_sounds=False,
        )
        lerobot_replay.replay(replay_cfg)
        self.assertEqual(len(FakeArm.instances[-1].commands), len(rows))
        self.assertTrue(FakeArm.instances[-1].cleaned)

    def test_real_record_cli_mp4_roundtrip(self):
        from lerobot.datasets import LeRobotDataset
        from lerobot.scripts import lerobot_record

        # Native record parser + actual H.264 encoder/decoder, no fake dataset layer.
        rc, tc = self.configs(camera=True)
        root = self.root / "video-dataset"
        args = [
            "lerobot-record",
            "--robot.type=lumos",
            "--teleop.type=stararm102",
            f"--robot.sdk_root={rc.sdk_root}",
            f"--robot.mapping_file={rc.mapping_file}",
            f"--robot.joint_limits_file={rc.joint_limits_file}",
            "--robot.can_interface=mock-can",
            "--robot.startup_wait_s=0.001",
            "--robot.execute=true",
            f"--robot.calibration_dir={rc.calibration_dir}",
            "--robot.cameras={front: {type: opencv, index_or_path: 0, width: 32, height: 24, fps: 30}}",
            f"--teleop.calibration_dir={tc.calibration_dir}",
            f"--teleop.mapping_file={tc.mapping_file}",
            "--teleop.port=mock-uart",
            "--teleop.button_enabled=false",
            "--play_sounds=false",
            "--dataset.repo_id=local/video_integration",
            f"--dataset.root={root}",
            "--dataset.single_task=Offline video smoke test",
            "--dataset.fps=30",
            "--dataset.num_episodes=1",
            "--dataset.episode_time_s=0.15",
            "--dataset.reset_time_s=0",
            "--dataset.push_to_hub=false",
            "--dataset.no_stamp=true",
            "--dataset.video=true",
            "--dataset.rgb_encoder.vcodec=h264",
            "--dataset.rgb_encoder.preset=ultrafast",
        ]
        events = {"exit_early": False, "stop_recording": False, "rerecord_episode": False}
        with (
            patch("sys.argv", args),
            patch.object(
                lerobot_record,
                "init_keyboard_listener",
                return_value=(None, events),
            ),
        ):
            lerobot_record.main()
        self.assertTrue(list(root.rglob("*.mp4")))
        loaded = LeRobotDataset("local/video_integration", root=root, video_backend="pyav")
        self.assertGreater(loaded.num_frames, 0)
        self.assertEqual(tuple(loaded[0]["observation.images.front"].shape), (3, 24, 32))
        self.assertEqual(tuple(loaded[0]["action"].shape), (7,))

    def test_launcher_paths_and_mode(self):
        source = Path(__file__).resolve().parents[1] / "configs/example.json"
        data = load_session(source)
        self.assertTrue(Path(data["robot"]["sdk_root"]).is_absolute())
        args = command_for("preview", data)
        self.assertIn("--robot.execute=false", args)
        self.assertIn("--robot.type=lumos", args)
        self.assertIn("--robot.execute=true", command_for("record", data))
        self.assertIn("--dataset.rgb_encoder.vcodec=h264", command_for("record", data))
        invalid = deepcopy(data)
        invalid["teleop"]["gripper"] = False
        with self.assertRaises(ValueError):
            command_for("preview", invalid)

    def test_safety_dt_and_bad_startup(self):
        self.assertAlmostEqual(limit_target([0] * 6, [1] * 6, 0.01, 50, 2)[0], math.radians(0.5))
        rc, _ = self.configs()
        robot = make_robot_from_config(rc)
        with patch.object(FakeArm, "home", [0.3] * 6):
            with self.assertRaises(RuntimeError):
                robot.connect()
        self.assertFalse(robot.is_connected)
        self.assertTrue(FakeArm.instances[-1].cleaned)


if __name__ == "__main__":
    unittest.main()
