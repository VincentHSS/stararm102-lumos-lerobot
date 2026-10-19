from dataclasses import dataclass, field

from lerobot.cameras import CameraConfig
from lerobot.robots import RobotConfig
from lerobot.teleoperators import TeleoperatorConfig


@RobotConfig.register_subclass("lumos")
@dataclass
class LumosConfig(RobotConfig):
    can_interface: str = "can0"
    sdk_root: str = ""
    mapping_file: str = ""
    gripper: bool = True
    # This prevents motion commands, NOT motor enabling during SDK construction.
    execute: bool = False
    startup_tolerance_rad: float = 0.15
    startup_wait_s: float = 2.0
    max_speed_deg_per_sec: float = 50.0
    max_target_step_deg: float = 2.0
    # Optional in preview; mandatory for execution. Bounds use SDK joint radians.
    joint_limits_file: str = ""
    cameras: dict[str, CameraConfig] = field(default_factory=dict)


@TeleoperatorConfig.register_subclass("stararm102")
@dataclass
class StarArm102Config(TeleoperatorConfig):
    port: str = "/dev/ttyUSB0"
    mapping_file: str = ""
    gripper: bool = True
    invert_gripper: bool = False
    button_enabled: bool = True
    button_id: int = 7
    joint_map: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5])
    signs: list[float] = field(default_factory=lambda: [-1, 1, 1, 1, -1, -1])
    gain: float = 1.0
