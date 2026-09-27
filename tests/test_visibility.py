"""敏感设施信息国家隔离测试。"""

import unittest

from scripts.seed_fixture import build
from src.gap_library import GapError
from src.visibility import (
    ROLE_JPO,
    ROLE_MEMBER,
    Viewer,
    can_peer_review,
    view_gap,
    view_report,
    visible_gaps,
)

EQUIP_GAP = "gap-scenario-001-org-gamma-equipment"


class VisibilityTest(unittest.TestCase):
    def setUp(self):
        self.lib = build()
        self.equip = self.lib._gap(EQUIP_GAP)
        self.term = self.lib._gap(
            "gap-scenario-001-org-gamma-terminology")

    def test_same_country_member_sees_facility(self):
        viewer = Viewer("org-delta", "XY", ROLE_MEMBER)
        shown = view_gap(self.equip, viewer)
        self.assertIn("facility", shown)
        self.assertTrue(can_peer_review(self.equip, viewer))

    def test_other_country_member_facility_redacted(self):
        viewer = Viewer("org-alpha", "CN", ROLE_MEMBER)
        shown = view_gap(self.equip, viewer)
        self.assertNotIn("facility", shown)
        self.assertTrue(shown["facility_redacted"])
        # 差距本身仍可用于一致性判断：条款、影响、设备能力差异保留
        self.assertEqual(shown["clause_id"], "IALA-G1151-5.3")
        self.assertIn("equipment_limit", shown)
        self.assertFalse(can_peer_review(self.equip, viewer))

    def test_jpo_sees_gap_but_not_facility_details(self):
        viewer = Viewer("jpo", "INT", ROLE_JPO)
        shown = view_gap(self.equip, viewer)
        self.assertNotIn("facility", shown)
        self.assertTrue(shown["facility_redacted"])
        # 非敏感差距正常可见
        self.assertIn("term_diff", view_gap(self.term, viewer))

    def test_visible_gaps_batch(self):
        viewer = Viewer("org-alpha", "CN", ROLE_MEMBER)
        shown = visible_gaps(self.lib.data["gaps"], viewer)
        sensitive = [g for g in shown if g["gap_id"] == EQUIP_GAP][0]
        self.assertNotIn("facility", sensitive)

    def test_report_redaction_flags(self):
        report = self.lib.consistency_report(on_date="2026-09-27")
        cn_view = view_report(
            report, Viewer("org-alpha", "CN", ROLE_MEMBER))
        for row in cn_view:
            for entry in row["gaps"]:
                if entry["gap_id"] == EQUIP_GAP:
                    self.assertTrue(entry["facility_redacted"])
                else:
                    self.assertFalse(entry["facility_redacted"])

    def test_cross_country_peer_review_of_sensitive_gap_rejected(self):
        with self.assertRaises(GapError):
            self.lib.submit_peer_review(
                EQUIP_GAP, "org-alpha", "2026-06-01", "agree", "试图跨国复核")


if __name__ == "__main__":
    unittest.main()
