"""Tests for the side-effect-free target environment probe."""

from __future__ import annotations

import unittest

from backend.session_kernel import AudioRoute
from backend.target_probe import (
    DeviceSelectionError,
    ProbeStatus,
    TargetEnvironmentProbe,
    select_input_device,
)


class FakeSoundDevice:
    def __init__(self) -> None:
        self.queries = 0

    def query_devices(self):
        self.queries += 1
        return [
            {
                "name": "fake speaker mic",
                "max_input_channels": 1,
                "max_output_channels": 2,
                "default_samplerate": 48_000,
            },
            {
                "name": "output only",
                "max_input_channels": 0,
                "max_output_channels": 2,
                "default_samplerate": 44_100,
            },
        ]


class TargetEnvironmentProbeTests(unittest.TestCase):
    def test_missing_dependencies_are_reported_without_importing_or_opening_audio(self) -> None:
        probe = TargetEnvironmentProbe(
            dependency_names=("sounddevice", "numpy"),
            dependency_finder=lambda name: None,
        )
        report = probe.inspect()
        self.assertEqual(report.status, ProbeStatus.UNAVAILABLE)
        self.assertFalse(report.device_query_attempted)
        self.assertFalse(report.c_verified)
        self.assertIn("missing_dependencies:sounddevice,numpy", report.reasons)

    def test_fake_dependency_and_device_query_are_read_only_and_never_c_proof(self) -> None:
        fake_sd = FakeSoundDevice()
        probe = TargetEnvironmentProbe(
            dependency_names=("sounddevice",),
            dependency_finder=lambda name: object(),
            sounddevice_module=fake_sd,
        )
        report = probe.inspect()
        self.assertEqual(report.status, ProbeStatus.READY)
        self.assertTrue(report.device_query_attempted)
        self.assertEqual(fake_sd.queries, 1)
        self.assertEqual(len(report.devices), 2)
        self.assertEqual(report.devices[0].input_channels, 1)
        self.assertEqual(report.devices[1].output_channels, 2)
        self.assertFalse(report.c_verified)
        payload = report.to_dict()
        self.assertFalse(payload["c_verified"])
        self.assertEqual(payload["verification"], "not_run")
        self.assertIn("c_authentication_not_run", payload["reasons"])

    def test_device_query_failure_is_explicit(self) -> None:
        class BrokenSoundDevice:
            def query_devices(self):
                raise OSError("no host api")

        probe = TargetEnvironmentProbe(
            dependency_names=("sounddevice",),
            dependency_finder=lambda name: object(),
            sounddevice_module=BrokenSoundDevice(),
        )
        report = probe.inspect()
        self.assertEqual(report.status, ProbeStatus.ERROR)
        self.assertTrue(report.device_query_attempted)
        self.assertIn("device_query:OSError", report.reasons)
        self.assertFalse(report.c_verified)

    def test_device_probe_is_still_available_when_model_dependencies_are_missing(self) -> None:
        fake_sd = FakeSoundDevice()

        def finder(name):
            return object() if name == "sounddevice" else None

        report = TargetEnvironmentProbe(
            dependency_names=("sounddevice", "faster_whisper"),
            dependency_finder=finder,
            sounddevice_module=fake_sd,
        ).inspect()

        self.assertEqual(report.status, ProbeStatus.PARTIAL)
        self.assertTrue(report.device_query_attempted)
        self.assertEqual(fake_sd.queries, 1)
        self.assertEqual(len(report.devices), 2)
        self.assertIn("missing_dependencies:faster_whisper", report.reasons)
        self.assertFalse(report.c_verified)

    def test_explicit_input_selection_never_inferrs_route_or_c(self) -> None:
        fake_sd = FakeSoundDevice()
        report = TargetEnvironmentProbe(
            dependency_names=("sounddevice",),
            dependency_finder=lambda name: object(),
            sounddevice_module=fake_sd,
        ).inspect()

        selection = select_input_device(report, "0")
        self.assertEqual(selection.device.route, AudioRoute.UNKNOWN.value)
        self.assertFalse(selection.device.reference_available)
        self.assertFalse(selection.c_verified)
        self.assertFalse(selection.to_dict()["c_verified"])

        speaker = select_input_device(
            report,
            "0",
            route=AudioRoute.SPEAKER_MIC.value,
            reference_available=True,
        )
        self.assertTrue(speaker.device.reference_available)
        with self.assertRaises(DeviceSelectionError):
            select_input_device(report, "1")
        with self.assertRaises(DeviceSelectionError):
            select_input_device(report, "0", reference_available=True)

    def test_input_selection_requires_an_explicit_supported_capture_channel_count(self) -> None:
        class StereoInputSoundDevice:
            def query_devices(self):
                return [{
                    "name": "stereo microphone",
                    "max_input_channels": 2,
                    "max_output_channels": 0,
                    "default_samplerate": 48_000,
                }]

        report = TargetEnvironmentProbe(
            dependency_names=("sounddevice",),
            dependency_finder=lambda name: object(),
            sounddevice_module=StereoInputSoundDevice(),
        ).inspect()

        mono = select_input_device(report, "0")
        self.assertEqual(mono.device.input_channels, 1)
        stereo = select_input_device(report, "0", input_channels=2)
        self.assertEqual(stereo.device.input_channels, 2)
        with self.assertRaises(DeviceSelectionError):
            select_input_device(report, "0", input_channels=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
