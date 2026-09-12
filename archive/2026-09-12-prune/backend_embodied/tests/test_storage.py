"""
YHLZ Embodied AI V6.0 - 统一存储单元测试 (JSONL Storage)

覆盖 (persistence/storage.py):
    - 原子写入 / 读取
    - 记录格式: schema_version / type / timestamp / data
    - 损坏行跳过 (不崩溃)
    - 校验规则
    - 异常处理
"""
import os
import shutil
import tempfile
import unittest

from backend.embodied.companion.persistence import (
    JSONLStorage,
    REQUIRED_FIELDS,
    StorageError,
)


class StorageTestBase(unittest.TestCase):
    """临时文件基类"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="yhlz_sto_")
        self.path = os.path.join(self.tmp, "state.jsonl")
        self.storage = JSONLStorage()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestStorageInit(unittest.TestCase):
    """初始化"""

    def test_default_init(self):
        s = JSONLStorage()
        self.assertEqual(s._schema_version, "9.5.0")

    def test_custom_version(self):
        s = JSONLStorage(schema_version="9.5.0")
        self.assertEqual(s._schema_version, "9.5.0")

    def test_empty_version_validation(self):
        with self.assertRaises(StorageError):
            JSONLStorage(schema_version="")

    def test_required_fields(self):
        self.assertEqual(
            set(REQUIRED_FIELDS),
            {"schema_version", "type", "timestamp", "data"},
        )


class TestWrite(StorageTestBase):
    """写入"""

    def test_write_empty(self):
        n = self.storage.write(self.path, [])
        self.assertEqual(n, 0)
        self.assertTrue(os.path.exists(self.path))

    def test_write_records(self):
        recs = [
            self.storage.build_record("experience", {"id": "e1"}),
            self.storage.build_record("reflection", {"id": "r1"}),
        ]
        n = self.storage.write(self.path, recs)
        self.assertEqual(n, 2)

    def test_write_creates_dir(self):
        sub = os.path.join(self.tmp, "sub", "deep", "s.jsonl")
        recs = [self.storage.build_record("experience", {"id": "e1"})]
        self.storage.write(sub, recs)
        self.assertTrue(os.path.exists(sub))
        os.remove(sub)

    def test_write_no_path(self):
        with self.assertRaises(StorageError):
            self.storage.write("", [])

    def test_write_atomic_no_tmp_left(self):
        recs = [self.storage.build_record("experience", {"id": "e1"})]
        self.storage.write(self.path, recs)
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_write_invalid_record(self):
        with self.assertRaises(StorageError):
            self.storage.write(self.path, [{"bad": "record"}])

    def test_write_overwrites(self):
        recs1 = [self.storage.build_record("experience", {"id": "e1"})]
        recs2 = [self.storage.build_record("reflection", {"id": "r1"})]
        self.storage.write(self.path, recs1)
        self.storage.write(self.path, recs2)
        records, _ = self.storage.read(self.path)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["type"], "reflection")


class TestRead(StorageTestBase):
    """读取"""

    def test_read_empty_file(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("")
        records, skipped = self.storage.read(self.path)
        self.assertEqual(records, [])
        self.assertEqual(skipped, 0)

    def test_read_records(self):
        recs = [
            self.storage.build_record("experience", {"id": "e1"}),
            self.storage.build_record("reflection", {"id": "r1"}),
        ]
        self.storage.write(self.path, recs)
        records, skipped = self.storage.read(self.path)
        self.assertEqual(len(records), 2)
        self.assertEqual(skipped, 0)

    def test_read_missing_file(self):
        with self.assertRaises(StorageError):
            self.storage.read(os.path.join(self.tmp, "nope.jsonl"))

    def test_read_no_path(self):
        with self.assertRaises(StorageError):
            self.storage.read("")

    def test_read_skip_invalid_json(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("not json\n")
            f.write('{"schema_version": "9.5.0", "type": "x",'
                    ' "timestamp": 1.0, "data": {"ok": 1}}\n')
            f.write('{"a": 1}\n')
        records, skipped = self.storage.read(self.path)
        self.assertEqual(len(records), 1)
        self.assertEqual(skipped, 2)

    def test_read_skip_missing_fields(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write('{"schema_version": "9.5.0", "type": "x"}\n')
        records, skipped = self.storage.read(self.path)
        self.assertEqual(records, [])
        self.assertEqual(skipped, 1)

    def test_read_skip_non_dict_data(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write('{"schema_version": "9.5.0", "type": "x",'
                    ' "timestamp": 1.0, "data": [1,2]}\n')
        records, skipped = self.storage.read(self.path)
        self.assertEqual(records, [])
        self.assertEqual(skipped, 1)

    def test_read_skip_blank_lines_ok(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("\n\n")
            f.write('{"schema_version": "9.5.0", "type": "x",'
                    ' "timestamp": 1.0, "data": {}}\n')
        records, skipped = self.storage.read(self.path)
        self.assertEqual(len(records), 1)
        self.assertEqual(skipped, 0)

    def test_read_roundtrip_data(self):
        recs = [self.storage.build_record(
            "experience", {"id": "e1", "trigger": "拾取"},
        )]
        self.storage.write(self.path, recs)
        records, _ = self.storage.read(self.path)
        self.assertEqual(records[0]["data"]["trigger"], "拾取")

    def test_read_utf8_content(self):
        recs = [self.storage.build_record(
            "experience", {"id": "e1", "lesson": "中文经验教训"},
        )]
        self.storage.write(self.path, recs)
        records, _ = self.storage.read(self.path)
        self.assertEqual(records[0]["data"]["lesson"], "中文经验教训")


class TestBuildRecord(StorageTestBase):
    """记录构造"""

    def test_build_record(self):
        rec = self.storage.build_record("experience", {"id": "e1"})
        for key in REQUIRED_FIELDS:
            self.assertIn(key, rec)
        self.assertEqual(rec["schema_version"], "9.5.0")
        self.assertEqual(rec["type"], "experience")
        self.assertGreater(rec["timestamp"], 0.0)

    def test_build_record_timestamp_override(self):
        rec = self.storage.build_record("x", {}, timestamp=123.0)
        self.assertEqual(rec["timestamp"], 123.0)

    def test_build_record_empty_type(self):
        with self.assertRaises(StorageError):
            self.storage.build_record("", {})

    def test_build_record_non_dict_data(self):
        with self.assertRaises(StorageError):
            self.storage.build_record("x", [1, 2])


class TestValidate(StorageTestBase):
    """校验"""

    def test_validate_ok(self):
        line = '{"schema_version": "9.5.0", "type": "x",' \
               ' "timestamp": 1.0, "data": {}}'
        ok, rec, reason = self.storage.validate_line(line)
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_validate_bad_json(self):
        ok, rec, reason = self.storage.validate_line("{bad")
        self.assertFalse(ok)
        self.assertIn("JSON", reason)

    def test_validate_missing_field(self):
        line = '{"schema_version": "9.5.0", "type": "x"}'
        ok, rec, reason = self.storage.validate_line(line)
        self.assertFalse(ok)
        self.assertIn("缺字段", reason)

    def test_validate_data_not_dict(self):
        line = '{"schema_version": "9.5.0", "type": "x",' \
               ' "timestamp": 1.0, "data": "str"}'
        ok, rec, reason = self.storage.validate_line(line)
        self.assertFalse(ok)

    def test_validate_unicode(self):
        line = '{"schema_version": "9.5.0", "type": "x",' \
               ' "timestamp": 1.0, "data": {"a": "中文"}}'
        ok, rec, reason = self.storage.validate_line(line)
        self.assertTrue(ok)
        self.assertEqual(rec["data"]["a"], "中文")


class TestAppend(StorageTestBase):
    """追加"""

    def test_append(self):
        self.storage.append(self.path, self.storage.build_record(
            "experience", {"id": "e1"},
        ))
        self.storage.append(self.path, self.storage.build_record(
            "reflection", {"id": "r1"},
        ))
        records, _ = self.storage.read(self.path)
        self.assertEqual(len(records), 2)

    def test_append_no_path(self):
        with self.assertRaises(StorageError):
            self.storage.append("", self.storage.build_record("x", {}))

    def test_append_invalid(self):
        with self.assertRaises(StorageError):
            self.storage.append(self.path, {"bad": 1})


class TestStats(StorageTestBase):
    """统计"""

    def test_by_type(self):
        recs = [
            {"type": "experience"}, {"type": "experience"},
            {"type": "reflection"},
        ]
        out = JSONLStorage.by_type(recs)
        self.assertEqual(out["experience"], 2)
        self.assertEqual(out["reflection"], 1)

    def test_stats(self):
        recs = [{"type": "experience"}]
        st = self.storage.stats(recs)
        self.assertEqual(st["mode"], "rule_based")
        self.assertEqual(st["total"], 1)
        self.assertEqual(st["schema_version"], "9.5.0")


class TestEdgeCases(StorageTestBase):
    """边界"""

    def test_write_large_record(self):
        big = {"id": "big", "data": "x" * 10000}
        recs = [self.storage.build_record("experience", big)]
        self.storage.write(self.path, recs)
        records, skipped = self.storage.read(self.path)
        self.assertEqual(len(records), 1)
        self.assertEqual(skipped, 0)

    def test_skip_only_corrupt_not_all(self):
        recs = [
            self.storage.build_record("experience", {"id": "e1"}),
        ]
        self.storage.write(self.path, recs)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write("garbage\n")
            f.write('{"schema_version": "9.5.0", "type": "y",'
                    ' "timestamp": 1.0, "data": {"ok": 1}}\n')
        records, skipped = self.storage.read(self.path)
        self.assertEqual(len(records), 2)
        self.assertEqual(skipped, 1)

    def test_repeated_roundtrip(self):
        for i in range(5):
            recs = [self.storage.build_record(
                "experience", {"id": f"e{i}"},
            )]
            self.storage.write(self.path, recs)
            records, _ = self.storage.read(self.path)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["data"]["id"], f"e{i}")


if __name__ == "__main__":
    unittest.main()
