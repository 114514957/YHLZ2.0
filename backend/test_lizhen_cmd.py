"""The real CMD executor is non-elevated, bounded and workspace scoped."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
TOOLS=Path(__file__).resolve().parents[1]/'tools'
if str(TOOLS) not in sys.path:sys.path.insert(0,str(TOOLS))
import lizhen_cmd_mcp as cmd

@unittest.skipUnless(os.name=='nt','Windows CMD')
class CmdTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        patcher=patch.object(cmd,'WORKSPACE',self.root);patcher.start();self.addCleanup(patcher.stop)
    def test_real_cmd_read_and_identity(self):
        (self.root/'probe.txt').write_text('CMD_FIXTURE_318',encoding='utf-8')
        result=cmd.execute_command('type probe.txt')
        self.assertEqual(result['exit_code'],0);self.assertIn('CMD_FIXTURE_318',result['stdout'])
        self.assertFalse(result['elevated']);self.assertEqual(result['shell'],'cmd.exe')
    def test_non_ascii_path_survives_capture(self):
        sub=self.root/'中文目录';sub.mkdir()
        result=cmd.execute_command('cd',relative_dir='中文目录')
        self.assertEqual(result['exit_code'],0);self.assertIn('中文目录',result['stdout'])
    def test_refuses_powershell_and_elevation(self):
        for text in ['powershell -Command echo hi','pwsh.exe -c echo hi','runas /user:Administrator cmd']:
            with self.assertRaises(PermissionError):cmd.execute_command(text)
    def test_cwd_cannot_escape_job(self):
        with self.assertRaises(PermissionError):cmd.execute_command('dir',relative_dir='..')
    def test_timeout_kills_command(self):
        result=cmd.execute_command('ping -n 8 127.0.0.1 >nul',timeout_seconds=1)
        self.assertTrue(result['timed_out']);self.assertNotEqual(result['exit_code'],0)
