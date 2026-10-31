"""No-hardware tests for the preflight's evidence boundaries."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools import voice_real_machine_preflight as preflight

class PreflightTests(unittest.TestCase):
    def test_project_modules_are_discoverable(self):
        self.assertTrue(preflight._module_status('backend.voice_trace')['available'])

    def test_missing_module_is_reported(self):
        self.assertFalse(preflight._module_status('yhlz_missing_preflight_module')['available'])

    def test_write_probe_does_not_overwrite_existing_file(self):
        with tempfile.TemporaryDirectory() as root:
            existing = Path(root) / '.preflight_write_probe'
            existing.write_text('keep', encoding='utf-8')
            self.assertTrue(preflight._writable_probe(Path(root))['writable'])
            self.assertEqual(existing.read_text(encoding='utf-8'), 'keep')
            self.assertEqual(list(Path(root).iterdir()), [existing])

    def test_enumeration_pass_does_not_certify_headset(self):
        audio = {'available': True, 'devices': [{'max_input_channels': 1, 'max_output_channels': 2}]}
        with tempfile.TemporaryDirectory() as root, patch.object(preflight, 'ROOT', Path(root)), patch.object(preflight, '_sound_devices', return_value=audio), patch.object(preflight, '_module_status', return_value={'available': True}):
            result = preflight.collect()
        self.assertTrue(result['software_preflight_passed'])
        self.assertFalse(result['ready_for_supervised_headset_bench'])
        self.assertTrue(result['headset_manual_confirmation_required'])
