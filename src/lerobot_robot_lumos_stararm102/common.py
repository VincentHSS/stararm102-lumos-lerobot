import json
import math
from pathlib import Path

JOINT_KEYS = tuple(f"joint_{i}.pos" for i in range(1, 7))


def vector(values, size: int, name: str) -> list[float]:
    result = [float(v) for v in values]
    if len(result) != size or not all(math.isfinite(v) for v in result):
        raise ValueError(f"{name} must contain {size} finite numbers")
    return result


def load_mapping(path: str, gripper: bool) -> dict:
    if not path:
        raise ValueError("mapping_file is required; run the original --calibrate first")
    data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if data.get("format_version") != 1:
        raise ValueError("Unsupported calibration version; run the original --calibrate")
    if data.get("gripper_enabled") is not gripper:
        raise ValueError("gripper must match the calibration file")
    for key in ("leader_home_deg", "leader_range_min_deg", "leader_range_max_deg", "lumos_home_rad"):
        data[key] = vector(data[key], 6, key)
    low, high = data["leader_range_min_deg"], data["leader_range_max_deg"]
    if any(hi - lo < 2 for lo, hi in zip(low, high)):
        raise ValueError("Leader calibration range must be at least two degrees per joint")
    if gripper:
        closed, opened = vector(
            [data["gripper_range"]["closed_deg"], data["gripper_range"]["open_deg"]],
            2,
            "gripper_range",
        )
        if abs(opened - closed) < 2:
            raise ValueError("Invalid calibrated gripper range")
    return data


def features(gripper: bool) -> dict:
    result = dict.fromkeys(JOINT_KEYS, float)
    if gripper:
        result["gripper.pos"] = float
    return result


def limit_target(previous, desired, dt, speed_deg_per_sec, max_step_deg):
    previous = vector(previous, 6, "previous target")
    desired = vector(desired, 6, "desired target")
    if not all(math.isfinite(v) and v > 0 for v in (speed_deg_per_sec, max_step_deg)):
        raise ValueError("Motion limits must be finite and positive")
    if not math.isfinite(dt) or dt < 0:
        raise ValueError("Invalid elapsed time")
    step = math.radians(min(max_step_deg, speed_deg_per_sec * dt))
    return [old + max(-step, min(step, new - old)) for old, new in zip(previous, desired)]


def load_limits(path: str):
    if not path:
        return None
    data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    low = vector(data["lower_rad"], 6, "lower_rad")
    high = vector(data["upper_rad"], 6, "upper_rad")
    if any(lo >= hi for lo, hi in zip(low, high)):
        raise ValueError("Each lower joint bound must be smaller than its upper bound")
    return low, high
