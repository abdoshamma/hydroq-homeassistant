"""Hardware abstraction layer.

Import backends from submodules (esphome_backend / mock_backend) to avoid
pulling Home Assistant into lightweight unit tests.
"""

from .hal import HardwareHAL

__all__ = ["HardwareHAL"]
