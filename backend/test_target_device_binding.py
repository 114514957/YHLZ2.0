"""Tests for target_device_binding.py — P0-1 explicit device identity."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.target_device_binding import (
    DeviceBindingError,
    TargetDeviceBinding,
    resolve_devices,
)

APIS = [{"name": "MME"}, {"name": "Windows DirectSound"}, {"name": "Windows WASAPI"}]
DEVICES = [
    {"name": "扬声器 (Realtek(R) Audio)", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2},
    {"name": "扬声器 (Realtek(R) Audio)", "hostapi": 1, "max_input_channels": 0, "max_output_channels": 2},
    {"name": "扬声器 (Realtek(R) Audio)", "hostapi": 2, "max_input_channels": 0, "max_output_channels": 2},
    {"name": "麦克风阵列 (Realtek(R) Audio)", "hostapi": 0, "max_input_channels": 1, "max_output_channels": 0},
]


def _make_sd(devices=None, apis=None):
    sd = MagicMock()
    sd.query_devices.return_value = devices or DEVICES
    sd.query_hostapis.return_value = apis or APIS
    return sd


class TestTargetDeviceBinding(unittest.TestCase):
    def test_valid_binding(self):
        b = TargetDeviceBinding("mic", "spk", route="headset")
        self.assertIsNone(b.input_hostapi_name)
        self.assertIsNone(b.output_hostapi_name)

    def test_binding_with_hostapi(self):
        b = TargetDeviceBinding("mic", "spk", route="speaker_mic",
                                input_hostapi_name="MME",
                                output_hostapi_name="Windows WASAPI")
        self.assertEqual(b.input_hostapi_name, "MME")
        self.assertEqual(b.output_hostapi_name, "Windows WASAPI")

    def test_empty_name_rejected(self):
        with self.assertRaises(DeviceBindingError):
            TargetDeviceBinding("", "spk")
        with self.assertRaises(DeviceBindingError):
            TargetDeviceBinding("mic", "  ")

    def test_bad_route_rejected(self):
        with self.assertRaises(DeviceBindingError):
            TargetDeviceBinding("mic", "spk", route="bogus")


class TestResolveDevices(unittest.TestCase):
    def test_disambiguate_by_hostapi(self):
        sd = _make_sd()
        b = TargetDeviceBinding("麦克风阵列 (Realtek(R) Audio)",
                                "扬声器 (Realtek(R) Audio)",
                                output_hostapi_name="MME")
        r = resolve_devices(sd, b)
        self.assertEqual(r.output_index, 0)
        self.assertEqual(r.output_hostapi, 0)
        self.assertEqual(r.input_index, 3)

    def test_ambiguous_without_hostapi(self):
        sd = _make_sd()
        b = TargetDeviceBinding("麦克风阵列 (Realtek(R) Audio)",
                                "扬声器 (Realtek(R) Audio)")
        with self.assertRaisesRegex(DeviceBindingError, "AMBIGUOUS"):
            resolve_devices(sd, b)

    def test_missing_device(self):
        sd = _make_sd()
        b = TargetDeviceBinding("不存在的设备", "扬声器 (Realtek(R) Audio)",
                                output_hostapi_name="MME")
        with self.assertRaisesRegex(DeviceBindingError, "MISSING"):
            resolve_devices(sd, b)

    def test_wrong_hostapi_missing(self):
        sd = _make_sd()
        b = TargetDeviceBinding("麦克风阵列 (Realtek(R) Audio)",
                                "扬声器 (Realtek(R) Audio)",
                                output_hostapi_name="不存在的API")
        with self.assertRaisesRegex(DeviceBindingError, "MISSING"):
            resolve_devices(sd, b)

    def test_format_unsupported(self):
        sd = _make_sd()
        sd.check_output_settings.side_effect = RuntimeError("Invalid sample rate")
        b = TargetDeviceBinding("麦克风阵列 (Realtek(R) Audio)",
                                "扬声器 (Realtek(R) Audio)",
                                output_hostapi_name="MME")
        with self.assertRaisesRegex(DeviceBindingError, "FORMAT-UNSUPPORTED"):
            resolve_devices(sd, b)

    def test_unique_name_resolves_without_hostapi(self):
        devices = [
            {"name": "Headphones (Realtek HD Audio 2nd output)", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2},
            {"name": "麦克风阵列 (Realtek(R) Audio)", "hostapi": 0, "max_input_channels": 1, "max_output_channels": 0},
        ]
        sd = _make_sd(devices=devices)
        b = TargetDeviceBinding("麦克风阵列 (Realtek(R) Audio)",
                                "Headphones (Realtek HD Audio 2nd output)")
        r = resolve_devices(sd, b)
        self.assertEqual(r.output_index, 0)

    def test_verify_detects_change(self):
        sd = _make_sd()
        b = TargetDeviceBinding("麦克风阵列 (Realtek(R) Audio)",
                                "扬声器 (Realtek(R) Audio)",
                                output_hostapi_name="MME")
        r = resolve_devices(sd, b)
        # device removed -> MISSING on re-resolve
        sd.query_devices.return_value = DEVICES[:2]
        with self.assertRaisesRegex(DeviceBindingError, "MISSING"):
            r.verify(sd)

    def test_verify_detects_reorder(self):
        sd = _make_sd()
        b = TargetDeviceBinding("麦克风阵列 (Realtek(R) Audio)",
                                "扬声器 (Realtek(R) Audio)",
                                output_hostapi_name="MME")
        r = resolve_devices(sd, b)
        # reorder devices so indices shift -> CHANGED
        sd.query_devices.return_value = list(reversed(DEVICES))
        with self.assertRaisesRegex(DeviceBindingError, "CHANGED"):
            r.verify(sd)

    def test_wapi_specific(self):
        sd = _make_sd()
        b = TargetDeviceBinding("麦克风阵列 (Realtek(R) Audio)",
                                "扬声器 (Realtek(R) Audio)",
                                output_hostapi_name="Windows WASAPI")
        r = resolve_devices(sd, b)
        self.assertEqual(r.output_index, 2)
        self.assertEqual(r.output_hostapi, 2)


if __name__ == "__main__":
    unittest.main()
