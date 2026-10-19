import math
import time

from lerobot.teleoperators import Teleoperator

from . import _legacy
from .common import JOINT_KEYS, features, load_mapping, vector
from .config import StarArm102Config


class StarArm102(Teleoperator):
    config_class = StarArm102Config
    name = "stararm102"

    def __init__(self, config: StarArm102Config):
        self.config = config
        self.uart = None
        self.leader = None
        self.hd_button = None
        self.mapping = None
        self._last_sample = None
        self._filter = _legacy.JointFilter()
        super().__init__(config)
        if sorted(config.joint_map) != list(range(6)):
            raise ValueError("joint_map must be a permutation of 0..5")
        if len(config.signs) != 6 or any(v not in (-1, 1) for v in config.signs):
            raise ValueError("signs must contain six values, each -1 or 1")
        if not math.isfinite(config.gain) or not 0 < config.gain <= 1:
            raise ValueError("gain must be in (0, 1]")
        if not 7 <= config.button_id <= 253:
            raise ValueError("button_id must be in 7..253")

    @property
    def action_features(self):
        return features(self.config.gripper)

    @property
    def feedback_features(self):
        return {}

    @property
    def is_connected(self):
        return self.uart is not None and self.uart.is_open and self.leader is not None

    @property
    def is_calibrated(self):
        return self.mapping is not None

    def calibrate(self):
        # This is a paired-arm mapping, not a MotorCalibration file.
        data = load_mapping(self.config.mapping_file, self.config.gripper)
        if data["joint_map"] != self.config.joint_map:
            raise ValueError("joint_map differs from calibration")
        if data["leader_port"] != self.config.port:
            raise ValueError("Leader port differs from calibration; recalibrate or use the original port")
        self.mapping = data

    def connect(self, calibrate=True):
        if self.is_connected:
            raise RuntimeError("StarArm102 already connected")
        # Always validate the existing mapping; never run paired-arm calibration implicitly.
        self.calibrate()
        import fashionstar_uart_sdk as uservo
        import serial

        try:
            self.uart = serial.Serial(
                port=self.config.port,
                baudrate=1_000_000,
                parity=serial.PARITY_NONE,
                stopbits=1,
                bytesize=8,
                timeout=0,
            )
            self.leader = uservo.UartServoManager(self.uart)
            for servo_id in list(self.config.joint_map) + ([6] if self.config.gripper else []):
                if not self.leader.ping(servo_id):
                    raise RuntimeError(f"StarArm servo {servo_id} did not respond")
            self.hd_button = (
                _legacy.HDButton(self.leader, self.config.button_id) if self.config.button_enabled else None
            )
            self._last_sample = None
            self._filter = _legacy.JointFilter()
            self.configure()
        except Exception:
            self.disconnect()
            raise

    def configure(self):
        # Serial settings are configured in connect; HD updates happen when sampling.
        pass

    def get_action(self):
        if not self.is_connected:
            raise RuntimeError("StarArm102 is not connected")
        values = vector(
            _legacy.read_leader(
                self.leader,
                self.config.joint_map,
                self.config.gripper,
                self.hd_button,
            ),
            7 if self.config.gripper else 6,
            "leader feedback",
        )
        now = time.monotonic()
        dt = 0.02 if self._last_sample is None else max(1e-6, now - self._last_sample)
        self._last_sample = now
        filtered = self._filter.update(values[:6], dt)
        mapping = self.mapping
        clipped = [
            max(lo, min(hi, q))
            for q, lo, hi in zip(
                filtered,
                mapping["leader_range_min_deg"],
                mapping["leader_range_max_deg"],
            )
        ]
        targets = [
            home + sign * self.config.gain * math.radians(q - leader_home)
            for q, leader_home, home, sign in zip(
                clipped,
                mapping["leader_home_deg"],
                mapping["lumos_home_rad"],
                self.config.signs,
            )
        ]
        action = dict(zip(JOINT_KEYS, targets))
        if self.config.gripper:
            closed = mapping["gripper_range"]["closed_deg"]
            opened = mapping["gripper_range"]["open_deg"]
            ratio = max(0.0, min(1.0, (values[6] - closed) / (opened - closed)))
            action["gripper.pos"] = 1.0 - ratio if self.config.invert_gripper else ratio
        return action

    def send_feedback(self, feedback):
        # There is no force-feedback channel; the HD button is serviced by get_action.
        pass

    def disconnect(self):
        uart, self.uart = self.uart, None
        self.leader = None
        self.hd_button = None
        if uart is not None and uart.is_open:
            uart.close()
