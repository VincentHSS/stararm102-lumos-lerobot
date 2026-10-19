"""Importing this installed plugin registers BOTH hardware types."""

from .config import LumosConfig, StarArm102Config
from .lumos import Lumos
from .stararm102 import StarArm102

__all__ = ["LumosConfig", "Lumos", "StarArm102Config", "StarArm102"]
