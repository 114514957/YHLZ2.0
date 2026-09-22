"""GPU interlock tests (ledger 0459)."""
import time
import unittest

import backend.gpu_lock as gl


class GpuLockTest(unittest.TestCase):
    def setUp(self):
        gl.release_sing()
        while gl.chat_active() > 0:
            gl.chat_exit()

    def tearDown(self):
        gl.release_sing()
        while gl.chat_active() > 0:
            gl.chat_exit()

    def test_sing_exclusive_two_phase(self):
        self.assertTrue(gl.acquire_sing())
        self.assertFalse(gl.acquire_sing())      # only one job at a time
        self.assertFalse(gl.chat_blocked())      # prep stage coexists
        self.assertTrue(gl.chat_enter())
        gl.chat_exit()
        self.assertTrue(gl.enter_window())
        self.assertTrue(gl.chat_blocked())       # SVC window blocks chat
        self.assertFalse(gl.chat_enter())
        gl.release_sing()
        self.assertFalse(gl.chat_blocked())
        self.assertTrue(gl.chat_enter())
        gl.chat_exit()

    def test_wait_chat_idle(self):
        self.assertTrue(gl.acquire_sing())
        self.assertTrue(gl.chat_enter())
        t0 = time.time()
        self.assertFalse(gl.wait_chat_idle(timeout=1.0))
        self.assertGreaterEqual(time.time() - t0, 0.9)
        gl.chat_exit()
        self.assertTrue(gl.wait_chat_idle(timeout=1.0))

    def test_busy_message_mentions_singing(self):
        self.assertTrue(gl.acquire_sing())
        self.assertTrue(gl.enter_window())
        try:
            self.assertIn("唱歌", gl.busy_message())
        finally:
            gl.release_sing()


if __name__ == "__main__":
    unittest.main()
