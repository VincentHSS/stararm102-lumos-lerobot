"""Convenience entry point; control and recording still use LeRobot's own CLIs."""

import argparse
import importlib
import importlib.metadata
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import draccus

from . import _legacy
from .common import load_limits, load_mapping
from .config import LumosConfig, StarArm102Config

RECORD_MARKER = "# lumos: store the action returned by send_action"


def resolve_path(value, base):
    path = Path(value).expanduser()
    return str((base / path).resolve() if not path.is_absolute() else path.resolve())


def load_session(path):
    path = Path(path).expanduser().resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Session configuration must be a JSON object")
    allowed = {"robot", "teleop", "fps", "teleop_time_s", "dataset"}
    if unknown := set(data) - allowed:
        raise ValueError(f"Unknown session fields: {sorted(unknown)}")
    if data.get("robot", {}).get("type") != "lumos":
        raise ValueError("robot.type must be lumos")
    if data.get("teleop", {}).get("type") != "stararm102":
        raise ValueError("teleop.type must be stararm102")
    data = deepcopy(data)
    for section, keys in (
        ("robot", ("sdk_root", "mapping_file", "joint_limits_file", "calibration_dir")),
        ("teleop", ("mapping_file", "calibration_dir")),
        ("dataset", ("root",)),
    ):
        for key in keys:
            value = data.get(section, {}).get(key)
            if value:
                data[section][key] = resolve_path(value, path.parent)
    if not isinstance(data.get("fps", 30), int) or not 0 < data.get("fps", 30) <= 100:
        raise ValueError("fps must be an integer in 1..100")
    return data


def validate_pair(data):
    robot, leader = data["robot"], data["teleop"]
    if robot.get("gripper", True) != leader.get("gripper", True):
        raise ValueError("Both devices must have the same gripper setting")
    if Path(robot["mapping_file"]) != Path(leader["mapping_file"]):
        raise ValueError("Both devices must use the same mapping_file")


def device_configs(data):
    # Use real draccus decoding for nested camera configurations and all field checks.
    return draccus.decode(
        LumosConfig, {k: v for k, v in data["robot"].items() if k != "type"}
    ), draccus.decode(
        StarArm102Config,
        {k: v for k, v in data["teleop"].items() if k != "type"},
    )


def command_for(mode, data):
    validate_pair(data)
    # Validate device field names, types and camera configs before invoking any hardware.
    device_configs(data)
    record = mode == "record"
    args = [
        sys.executable,
        "-m",
        "lerobot.scripts.lerobot_record" if record else "lerobot.scripts.lerobot_teleoperate",
    ]
    robot = deepcopy(data["robot"])
    robot["execute"] = mode != "preview"
    if mode == "preview" and not Path(robot.get("joint_limits_file") or "").is_file():
        robot.pop("joint_limits_file", None)
    for group, values in (("robot", robot), ("teleop", data["teleop"])):
        for key, value in values.items():
            if value is not None:
                encoded = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))
                args.append(f"--{group}.{key}={encoded}")
    if record:
        dataset = deepcopy(data.get("dataset", {}))
        if not dataset.get("repo_id") or not dataset.get("single_task"):
            raise ValueError("Recording requires dataset.repo_id and dataset.single_task")
        dataset.setdefault("fps", data.get("fps", 30))
        for key, value in dataset.items():
            if key in ("rgb_encoder", "depth_encoder") and isinstance(value, dict):
                for field_name, setting in value.items():
                    if setting is not None:
                        encoded = setting if isinstance(setting, str) else json.dumps(setting)
                        args.append(f"--dataset.{key}.{field_name}={encoded}")
                continue
            if value is not None:
                encoded = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))
                args.append(f"--dataset.{key}={encoded}")
        args += ["--play_sounds=false", "--display_data=false"]
    else:
        args.append(f"--fps={data.get('fps', 30)}")
        if "teleop_time_s" in data:
            args.append(f"--teleop_time_s={data['teleop_time_s']}")
    return args


def recorder_path():
    spec = importlib.util.find_spec("lerobot.scripts.lerobot_record")
    if spec is None or not spec.origin:
        raise RuntimeError("Cannot locate the installed LeRobot recorder")
    return Path(spec.origin)


def doctor(data):
    validate_pair(data)
    robot_cfg, leader_cfg = device_configs(data)
    from lerobot.robots import make_robot_from_config
    from lerobot.teleoperators import make_teleoperator_from_config
    from lerobot.utils.import_utils import register_third_party_plugins

    register_third_party_plugins()
    # Validate data separately; no SDK construction or ports opened here.
    mapping = load_mapping(robot_cfg.mapping_file, robot_cfg.gripper)
    if mapping["leader_port"] != leader_cfg.port or mapping["can_interface"] != robot_cfg.can_interface:
        raise ValueError(
            "Configured serial/CAN ports differ from mapping; recalibrate or use the original ports"
        )
    if mapping["joint_map"] != leader_cfg.joint_map:
        raise ValueError("joint_map differs from mapping")
    _legacy.find_sdk_root(Path(robot_cfg.sdk_root))
    for name in ("serial", "fashionstar_uart_sdk", "startouchclass"):
        importlib.import_module(name)
    if not callable(getattr(importlib.import_module("startouchclass"), "SingleArm", None)):
        raise ValueError("Installed startouchclass does not expose SingleArm")
    if robot_cfg.joint_limits_file and Path(robot_cfg.joint_limits_file).is_file():
        load_limits(robot_cfg.joint_limits_file)
        limits_status = "present (review model/order/coordinates before execution)"
    else:
        limits_status = "missing; preview available, execution unavailable"
    # Missing bounds are permitted for a read-only factory check.
    robot_cfg.execute = False
    if limits_status.startswith("missing"):
        robot_cfg.joint_limits_file = ""
    robot = make_robot_from_config(robot_cfg)
    leader = make_teleoperator_from_config(leader_cfg)
    if robot.action_features != leader.action_features:
        raise ValueError("Robot and teleoperator features differ")
    report = {
        "lerobot_version": importlib.metadata.version("lerobot"),
        "robot_factory": type(robot).__name__,
        "teleop_factory": type(leader).__name__,
        "action_keys": list(robot.action_features),
        "joint_limits": limits_status,
        "recording_patch": RECORD_MARKER in recorder_path().read_text(encoding="utf-8"),
        "hardware_connected": False,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))


def calibrate(data):
    validate_pair(data)
    robot, leader = device_configs(data)
    # Call the original paired-arm wizard with this session's settings.
    _legacy.JOINT_SIGNS = tuple(leader.signs)
    _legacy.FOLLOW_GAIN = leader.gain
    args = [
        "lumos-lerobot calibrate",
        "--leader-port",
        leader.port,
        "--can",
        robot.can_interface,
        "--sdk-root",
        robot.sdk_root,
        "--calibration-file",
        leader.mapping_file,
        "--calibrate",
        "--joint-map",
        ",".join(map(str, leader.joint_map)),
        "--button-id",
        str(leader.button_id),
    ]
    if leader.gripper:
        args.append("--gripper")
    if not leader.button_enabled:
        args.append("--button-disable")
    original_argv = sys.argv
    try:
        sys.argv = args
        return _legacy.main()
    finally:
        sys.argv = original_argv


def main():
    parser = argparse.ArgumentParser(description="StarArm102 / Lumos LeRobot launcher")
    parser.add_argument("mode", choices=("doctor", "calibrate", "preview", "teleop", "record"))
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument(
        "--print-command", action="store_true", help="Print argv JSON without connecting hardware"
    )
    args = parser.parse_args()
    try:
        # Register OpenCV's config before decoding the session.
        from lerobot.cameras.opencv import OpenCVCameraConfig  # noqa: F401

        data = load_session(args.config)
        if args.mode == "doctor":
            doctor(data)
            return
        if args.mode == "calibrate":
            if args.print_command:
                parser.error("--print-command is available for preview/teleop/record")
            raise SystemExit(calibrate(data))
        command = command_for(args.mode, data)
        if args.print_command:
            print(json.dumps(command, indent=2, ensure_ascii=False))
            return
        if args.mode != "preview":
            limits_file = data["robot"].get("joint_limits_file", "")
            if not load_limits(limits_file):
                raise ValueError("Execution requires a reviewed joint_limits_file")
        if args.mode == "record" and RECORD_MARKER not in recorder_path().read_text(encoding="utf-8"):
            raise ValueError(
                "Recorder patch is missing. Run scripts/install_lerobot_ubuntu.sh or tools/patch_record.py"
            )
        print(
            "Starting LeRobot. SingleArm initialization may enable motors, including in preview.", flush=True
        )
        raise SystemExit(subprocess.call(command))
    except (ValueError, OSError, ImportError) as exc:
        parser.exit(2, f"Configuration/setup error: {exc}\n")


if __name__ == "__main__":
    main()
