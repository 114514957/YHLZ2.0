"""
YHLZ Personality Engine V3.4 - Schema 单元测试

覆盖:
    - 枚举: PersonalityTrait / PersonalityStatus
    - PersonalityPreferences 序列化
    - PersonalityProfile 默认值 / create / from_dict / to_dict
    - PersonalityQuery 序列化
"""
import unittest

from backend.personality.schema import (
    PersonalityPreferences,
    PersonalityProfile,
    PersonalityQuery,
    PersonalityStatus,
    PersonalityTrait,
)


class TestPersonalityTrait(unittest.TestCase):

    def test_five_dimensions(self):
        dims = {t.value for t in PersonalityTrait}
        self.assertEqual(dims, {"friendliness", "humor", "rigor", "warmth", "conciseness"})

    def test_default_traits_neutral(self):
        traits = PersonalityTrait.default_traits()
        self.assertEqual(len(traits), 5)
        for v in traits.values():
            self.assertEqual(v, 3.0)


class TestPersonalityStatus(unittest.TestCase):

    def test_status_values(self):
        self.assertEqual(PersonalityStatus.OK.value, "ok")
        self.assertEqual(PersonalityStatus.PERMISSION_DENIED.value, "denied")
        self.assertEqual(PersonalityStatus.NOT_FOUND.value, "not_found")
        self.assertEqual(PersonalityStatus.INVALID.value, "invalid")


class TestPersonalityPreferences(unittest.TestCase):

    def test_defaults(self):
        p = PersonalityPreferences()
        self.assertEqual(p.address_user, "你")
        self.assertEqual(p.response_length, "简洁")
        self.assertFalse(p.use_emojis)

    def test_roundtrip(self):
        p = PersonalityPreferences(address_user="您", response_length="详细", use_emojis=True)
        d = p.to_dict()
        p2 = PersonalityPreferences.from_dict(d)
        self.assertEqual(p2.address_user, "您")
        self.assertEqual(p2.response_length, "详细")
        self.assertTrue(p2.use_emojis)

    def test_from_none(self):
        p = PersonalityPreferences.from_dict(None)
        self.assertEqual(p.address_user, "你")


class TestPersonalityProfile(unittest.TestCase):

    def test_default_profile(self):
        p = PersonalityProfile.default_profile()
        self.assertEqual(p.name, "YHLZ 默认人格")
        self.assertTrue(p.active)
        self.assertEqual(p.traits["warmth"], 4.5)
        self.assertEqual(p.traits["friendliness"], 4.5)
        self.assertEqual(p.traits["conciseness"], 4.0)
        self.assertTrue(p.profile_id)

    def test_create_fills_missing_traits(self):
        p = PersonalityProfile.create(name="测试人格", traits={"warmth": 5.0})
        for t in PersonalityTrait:
            self.assertIn(t.value, p.traits)
        self.assertEqual(p.traits["warmth"], 5.0)
        self.assertEqual(p.traits["humor"], 3.0)

    def test_to_dict_roundtrip(self):
        p = PersonalityProfile.create(
            name="工程师人格",
            description="严谨认真",
            traits={"rigor": 4.5},
            tone="严谨",
            preferences={"address_user": "您"},
            guidelines=["保持严谨"],
            active=True,
        )
        d = p.to_dict()
        self.assertEqual(d["name"], "工程师人格")
        self.assertEqual(d["traits"]["rigor"], 4.5)
        self.assertTrue(d["active"])
        self.assertEqual(d["preferences"]["address_user"], "您")
        p2 = PersonalityProfile.from_dict(d)
        self.assertEqual(p2.profile_id, p.profile_id)
        self.assertEqual(p2.name, p.name)
        self.assertEqual(p2.traits["rigor"], 4.5)
        self.assertEqual(p2.guidelines, ["保持严谨"])
        self.assertEqual(p2.preferences.address_user, "您")
        self.assertTrue(p2.active)

    def test_from_dict_empty_has_all_traits(self):
        p = PersonalityProfile.from_dict({})
        for t in PersonalityTrait:
            self.assertEqual(p.traits[t.value], 3.0)

    def test_uuid_unique(self):
        a = PersonalityProfile.default_profile()
        b = PersonalityProfile.default_profile()
        self.assertNotEqual(a.profile_id, b.profile_id)


class TestPersonalityQuery(unittest.TestCase):

    def test_defaults(self):
        q = PersonalityQuery()
        self.assertIsNone(q.keyword)
        self.assertFalse(q.active_only)
        self.assertEqual(q.limit, 20)
        self.assertEqual(q.offset, 0)

    def test_roundtrip(self):
        q = PersonalityQuery(
            keyword="温暖",
            trait_filter={"warmth": 4.0},
            active_only=True,
            limit=5,
            offset=10,
        )
        q2 = PersonalityQuery.from_dict(q.to_dict())
        self.assertEqual(q2.keyword, "温暖")
        self.assertEqual(q2.trait_filter, {"warmth": 4.0})
        self.assertTrue(q2.active_only)
        self.assertEqual(q2.limit, 5)
        self.assertEqual(q2.offset, 10)


if __name__ == "__main__":
    unittest.main()
