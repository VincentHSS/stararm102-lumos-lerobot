import logging
import math
import time
from pathlib import Path

from lerobot.cameras import make_cameras_from_configs
from lerobot.robots import Robot

from . import _legacy
from .common import JOINT_KEYS, features, limit_target, load_limits, load_mapping, vector
from .config import LumosConfig

logger = logging.getLogger(__name__)


class Lumos(Robot):
    config_class = LumosConfig
    name = "lumos"

    def __init__(self, config: LumosConfig):
        self.config = config
        self.arm = None
        self.cameras = {}
        self.mapping = None
        self._previous_target = None
        self._last_send = None
        self.last_sent_action = None
        super().__init__(config)
        for value in (
            config.max_speed_deg_per_sec,
            config.max_target_step_deg,
            config.startup_tolerance_rad,
            config.startup_joint2_tolerance_rad,
            config.startup_wait_s,
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Motion and startup parameters must be finite and positive")
        self.limits = load_limits(config.joint_limits_file)
        if config.execute and self.limits is None:
            raise ValueError("Execution requires joint_limits_file with verified SDK-coordinate bounds")
        self.cameras = make_cameras_from_configs(config.cameras)

    @property
    def action_features(self):
        return features(self.config.gripper)

    @property
    def observation_features(self):
        return {
            **self.action_features,
            **{key: (cfg.height, cfg.width, 3) for key, cfg in self.config.cameras.items()},
        }

    @property
    def is_connected(self):
        return self.arm is not None and all(cam.is_connected for cam in self.cameras.values())

    @property
    def is_calibrated(self):
        return self.mapping is not None

    def calibrate(self):
        data = load_mapping(self.config.mapping_file, self.config.gripper)
        if data["can_interface"] != self.config.can_interface:
            raise ValueError("CAN interface differs from calibration")
        self.mapping = data

    def connect(self, calibrate=True):
        if self.arm is not None:
            raise RuntimeError("Lumos already connected")
        self.calibrate()
        if not self.config.sdk_root:
            raise ValueError("sdk_root is required: pass the startouch_sdk source directory")
        sdk_root = _legacy.find_sdk_root(Path(self.config.sdk_root))
        from startouchclass import SingleArm

        logger.warning("SingleArm construction may ENABLE MOTORS, including in preview mode")
        try:
            with _legacy.sdk_initialization_directory(sdk_root):
                self.arm = SingleArm(
                    can_interface_=self.config.can_interface,
                    gripper=self.config.gripper,
                    enable_fd_=False,
                )
            time.sleep(self.config.startup_wait_s)
            positions = vector(self.arm.get_joint_positions(), 6, "Lumos feedback")
            if self.config.execute:
                errors = [abs(a - b) for a, b in zip(positions, self.mapping["lumos_home_rad"])]
                tolerances = [self.config.startup_tolerance_rad] * 6
                tolerances[1] = self.config.startup_joint2_tolerance_rad
                if any(error > tolerance for error, tolerance in zip(errors, tolerances)):
                    raise RuntimeError(
                        "Lumos is away from calibrated home; restore pose or recalibrate "
                        f"(current={positions}, calibrated={self.mapping['lumos_home_rad']}, "
                        f"errors={errors}, tolerances={tolerances})"
                    )
                if any(not lo <= q <= hi for q, lo, hi in zip(positions, *self.limits)):
                    raise RuntimeError("Measured startup pose is outside configured joint limits")
            self._previous_target = positions
            self._last_send = time.monotonic()
            self.last_sent_action = None
            for cam in self.cameras.values():
                cam.connect()
            self.configure()
        except Exception:
            self.disconnect()
            raise

    def configure(self):
        # Keep the SDK's own motor/torque configuration and protections unchanged.
        pass

    def get_observation(self):
        if not self.is_connected:
            raise RuntimeError("Lumos is not connected")
        positions = vector(self.arm.get_joint_positions(), 6, "Lumos feedback")
        obs = dict(zip(JOINT_KEYS, positions))
        if self.config.gripper:
            opening = float(self.arm.get_gripper_position())
            if not math.isfinite(opening):
                raise RuntimeError("Invalid gripper feedback")
            obs["gripper.pos"] = opening
        for key, cam in self.cameras.items():
            obs[key] = cam.async_read()
        return obs

    def send_action(self, action):
        if not self.is_connected:
            raise RuntimeError("Lumos is not connected")
        if set(action) != set(self.action_features):
            raise ValueError(f"Expected action keys: {list(self.action_features)}")
        desired = vector([action[key] for key in JOINT_KEYS], 6, "Lumos action")
        grip = None
        if self.config.gripper:
            grip = float(action["gripper.pos"])
            if not math.isfinite(grip):
                raise ValueError("Invalid gripper action")
            grip = max(0.0, min(1.0, grip))
        if self.limits is not None:
            desired = [max(lo, min(hi, q)) for q, lo, hi in zip(desired, *self.limits)]
        now = time.monotonic()
        target = limit_target(
            self._previous_target,
            desired,
            now - self._last_send,
            self.config.max_speed_deg_per_sec,
            self.config.max_target_step_deg,
        )
        if self.config.execute:
            if self.arm.set_joint_raw(target, [0.0] * 6) is False:
                raise RuntimeError("SDK rejected joint command")
            if grip is not None and self.arm.setGripperPosition(grip) is False:
                raise RuntimeError("SDK rejected gripper command")
        self._previous_target = target
        self._last_send = now
        sent = dict(zip(JOINT_KEYS, target))
        if grip is not None:
            sent["gripper.pos"] = grip
        self.last_sent_action = sent.copy()
        if not self.config.execute:
            logger.info("PREVIEW only, no motion target sent: %s", sent)
        return sent

    def disconnect(self):
        for cam in self.cameras.values():
            try:
                if cam.is_connected:
                    cam.disconnect()
            except Exception:
                logger.exception("Camera disconnect failed")
        arm, self.arm = self.arm, None
        if arm is not None:
            try:
                arm.cleanup()
            except Exception:
                logger.exception("Lumos cleanup failed")
        self._previous_target = None
        self._last_send = None
