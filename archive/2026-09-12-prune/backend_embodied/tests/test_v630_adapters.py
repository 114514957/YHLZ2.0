"""
YHLZ Embodied AI V6.3 - 真实感知引擎单元测试 (Tesseract & Template)

覆盖 (adapters/tesseract_ocr.py, template_detector.py):
    - Tesseract: skipIf 无环境保护 / Mock 同接口 / 信息
    - 模板匹配: 真实 OpenCV 测试 / 阈值 / 无 OpenCV 保护
"""
import unittest

from backend.embodied.companion.perception import (
    TemplateDetectorAdapter,
    TesseractOCRAdapter,
)

try:
    import cv2  # noqa
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


def make_scene_with_square():
    """构造含白色方块场景"""
    scene = np.zeros((200, 200), dtype=np.uint8)
    cv2.rectangle(scene, (50, 50), (100, 100), 255, -1)
    tpl = np.zeros((51, 51), dtype=np.uint8)
    cv2.rectangle(tpl, (0, 0), (50, 50), 255, -1)
    return scene, tpl


class TestTesseractAdapter(unittest.TestCase):
    """Tesseract OCR 适配器"""

    def test_is_available_bool(self):
        """无 pytesseract 环境 → False (不崩溃)"""
        a = TesseractOCRAdapter()
        self.assertIsInstance(a.is_available(), bool)

    def test_info_structure(self):
        a = TesseractOCRAdapter()
        info = a.get_info()
        for key in ("name", "source", "available"):
            self.assertIn(key, info)
        self.assertEqual(info["source"], "tesseract")

    def test_name(self):
        a = TesseractOCRAdapter()
        self.assertEqual(a.name, "tesseract_ocr")

    def test_ocr_without_env_raises(self):
        a = TesseractOCRAdapter()
        if not a.is_available():
            with self.assertRaises(RuntimeError):
                a.ocr(image="dummy")

    def test_ocr_no_image_raises(self):
        a = TesseractOCRAdapter()
        if a.is_available():
            with self.assertRaises(ValueError):
                a.ocr(image=None)

    def test_detect_empty(self):
        a = TesseractOCRAdapter()
        r = a.detect()
        self.assertEqual(r.objects, [])

    def test_custom_cmd_kept(self):
        a = TesseractOCRAdapter(tesseract_cmd="/tmp/ts")
        self.assertEqual(a._tesseract_cmd, "/tmp/ts")

    @unittest.skipIf(True, "Tesseract 环境不可用示例")
    def test_skip_protection_example(self):
        """skipIf 保护示例 (真实环境测试用)"""
        a = TesseractOCRAdapter()
        self.assertTrue(a.is_available())


class TestTemplateDetector(unittest.TestCase):
    """模板匹配检测适配器"""

    def test_available_bool(self):
        a = TemplateDetectorAdapter()
        self.assertIsInstance(a.is_available(), bool)

    def test_info(self):
        a = TemplateDetectorAdapter()
        info = a.get_info()
        self.assertEqual(info["source"], "template")
        self.assertIn("templates", info)

    def test_name(self):
        a = TemplateDetectorAdapter()
        self.assertEqual(a.name, "template_detector")

    def test_no_template_not_available(self):
        a = TemplateDetectorAdapter(templates={})
        self.assertFalse(a.is_available())

    def test_add_template(self):
        a = TemplateDetectorAdapter()
        a.add_template("x", "dummy")
        self.assertIn("x", a._templates)

    def test_remove_template(self):
        a = TemplateDetectorAdapter(templates={"x": "d"})
        self.assertTrue(a.remove_template("x"))
        self.assertFalse(a.remove_template("x"))

    def test_ocr_empty(self):
        a = TemplateDetectorAdapter()
        r = a.ocr()
        self.assertEqual(r.text, "")

    def test_detect_no_image_raises(self):
        a = TemplateDetectorAdapter(templates={"x": "dummy"})
        if a.is_available():
            with self.assertRaises(ValueError):
                a.detect(image=None)

    @unittest.skipUnless(HAS_CV2, "OpenCV 不可用")
    def test_detect_square(self):
        """真实模板匹配: 场景含方块 → 匹配"""
        scene, tpl = make_scene_with_square()
        a = TemplateDetectorAdapter(
            templates={"square": tpl}, match_threshold=0.7,
        )
        r = a.detect(scene)
        self.assertGreaterEqual(len(r.objects), 1)
        self.assertEqual(r.objects[0]["label"], "square")
        self.assertGreaterEqual(r.objects[0]["confidence"], 0.7)

    @unittest.skipUnless(HAS_CV2, "OpenCV 不可用")
    def test_detect_bbox(self):
        scene, tpl = make_scene_with_square()
        a = TemplateDetectorAdapter(
            templates={"square": tpl}, match_threshold=0.7,
        )
        r = a.detect(scene)
        bbox = r.objects[0]["bbox"]
        self.assertEqual(len(bbox), 4)

    @unittest.skipUnless(HAS_CV2, "OpenCV 不可用")
    def test_detect_no_match(self):
        """场景无目标 → 无匹配 (带噪声底避免零方差)"""
        rng = np.random.default_rng(42)
        scene = rng.integers(0, 40, size=(200, 200),
                             dtype=np.uint8)
        tpl = np.zeros((51, 51), dtype=np.uint8)
        cv2.rectangle(tpl, (0, 0), (50, 50), 255, -1)
        a = TemplateDetectorAdapter(
            templates={"square": tpl}, match_threshold=0.9,
        )
        r = a.detect(scene)
        self.assertEqual(r.objects, [])

    @unittest.skipUnless(HAS_CV2, "OpenCV 不可用")
    def test_detect_threshold_effect(self):
        """阈值语义: 精确匹配通过, 噪声场景被拒绝"""
        scene, tpl = make_scene_with_square()
        rng = np.random.default_rng(7)
        noise = rng.integers(0, 40, size=(200, 200),
                             dtype=np.uint8)
        exact = TemplateDetectorAdapter(
            templates={"square": tpl}, match_threshold=0.9,
        )
        r_exact = exact.detect(scene)
        self.assertGreaterEqual(len(r_exact.objects), 1)
        # 噪声场景无目标 → 即使低阈值也不匹配 (confidence≈0)
        loose = TemplateDetectorAdapter(
            templates={"square": tpl}, match_threshold=0.05,
        )
        r_noise = loose.detect(noise)
        self.assertEqual(r_noise.objects, [])

    @unittest.skipUnless(HAS_CV2, "OpenCV 不可用")
    def test_detect_color_image(self):
        """BGR 彩色图像自动转灰度"""
        scene, tpl = make_scene_with_square()
        scene_color = cv2.cvtColor(scene, cv2.COLOR_GRAY2BGR)
        tpl_color = cv2.cvtColor(tpl, cv2.COLOR_GRAY2BGR)
        a = TemplateDetectorAdapter(
            templates={"square": tpl_color},
            match_threshold=0.7,
        )
        r = a.detect(scene_color)
        self.assertGreaterEqual(len(r.objects), 1)

    @unittest.skipUnless(HAS_CV2, "OpenCV 不可用")
    def test_detect_multiple_templates(self):
        """多模板: 只匹配存在的 (不存在的模板带特征避免零方差)"""
        scene, tpl = make_scene_with_square()
        other = np.zeros((40, 40), dtype=np.uint8)
        cv2.circle(other, (20, 20), 10, 255, -1)  # 场景中无圆圈
        a = TemplateDetectorAdapter(
            templates={"square": tpl, "other": other},
            match_threshold=0.9,
        )
        r = a.detect(scene)
        labels = [o["label"] for o in r.objects]
        self.assertIn("square", labels)
        self.assertNotIn("other", labels)

    @unittest.skipUnless(HAS_CV2, "OpenCV 不可用")
    def test_detect_template_larger_than_scene(self):
        """模板大于场景 → 跳过不崩溃"""
        scene = np.zeros((30, 30), dtype=np.uint8)
        tpl = np.zeros((51, 51), dtype=np.uint8)
        a = TemplateDetectorAdapter(
            templates={"big": tpl}, match_threshold=0.7,
        )
        r = a.detect(scene)
        self.assertEqual(r.objects, [])

    @unittest.skipUnless(HAS_CV2, "OpenCV 不可用")
    def test_detect_confidence_in_result(self):
        scene, tpl = make_scene_with_square()
        a = TemplateDetectorAdapter(
            templates={"square": tpl}, match_threshold=0.7,
        )
        r = a.detect(scene)
        self.assertGreater(r.confidence, 0.0)


if __name__ == "__main__":
    unittest.main()
