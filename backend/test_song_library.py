"""Finished-songs library tests (ledger 0460)."""
import pathlib
import tempfile
import unittest

import backend.song_library as sl


class SongLibraryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self._dir, self._idx = sl.SONGS_DIR, sl.INDEX
        sl.SONGS_DIR = self.tmp / "songs"
        sl.INDEX = sl.SONGS_DIR / "songs.json"
        self.wav = self.tmp / "cover.wav"
        self.wav.write_bytes(b"RIFFxxxx")

    def tearDown(self):
        sl.SONGS_DIR, sl.INDEX = self._dir, self._idx

    def test_save_list_resolve(self):
        a = sl.save("第一首", self.wav, source="test")
        b = sl.save("小星星翻唱", self.wav, source="test")
        items = sl.list_songs()
        self.assertEqual(len(items), 2)
        # newest first
        self.assertEqual(items[0]["id"], b["id"])
        self.assertEqual(sl.resolve(a["id"])["title"], "第一首")
        self.assertEqual(sl.resolve("1")["id"], b["id"])       # 1-based index
        self.assertEqual(sl.resolve("星星")["id"], b["id"])     # title keyword
        self.assertIsNone(sl.resolve("不存在"))

    def test_song_path_and_play_message(self):
        a = sl.save("测试曲", self.wav)
        p = sl.song_path(a["id"])
        self.assertTrue(p and p.is_file())
        msg = sl.play(a["id"])
        self.assertIn("测试曲", msg)
        self.assertIn("没有这首歌", sl.play("nope"))

    def test_list_tool_text(self):
        from backend.target_scheduler_tools import song_list_text

        self.assertIn("空", song_list_text())
        sl.save("歌A", self.wav)
        self.assertIn("歌A", song_list_text())


if __name__ == "__main__":
    unittest.main()
