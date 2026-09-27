"""差距库核心工作流测试。"""

import unittest
from pathlib import Path

from src.gap_library import (
    GapError,
    GapLibrary,
    load_library,
    STATUS_CLOSED,
    STATUS_VERIFIED,
    STATUS_PEER_REVIEWED,
    STATUS_SELF_ASSESSED,
)
from scripts.seed_fixture import build

FIXTURE = Path("fixtures/gap_library.json")
TERM_GAP = "gap-scenario-001-org-gamma-terminology"
EQUIP_GAP = "gap-scenario-001-org-gamma-equipment"
PROCESS_GAP = "gap-scenario-001-org-gamma-process"
ALPHA_GAP = "gap-scenario-002-org-alpha-process"
TRAINING_GAP = "gap-tm-course-risk-101-IALA-G1151-3.2-org-alpha"


def fresh_lib() -> GapLibrary:
    lib = GapLibrary()
    lib.add_organization("o-a", "甲国 A 机构", "CN")
    lib.add_organization("o-b", "甲国 B 机构", "CN")
    lib.add_organization("o-c", "乙国 C 机构", "XY")
    lib.add_clause(
        "C-1", "IALA G1151", "术语条款", "source ...",
        "V1", "2025-01-01", "旧译文",
    )
    return lib


class FixtureTest(unittest.TestCase):
    def test_seed_fixture_loads_and_matches_scenario(self):
        lib = load_library(FIXTURE)
        ids = {g["gap_id"] for g in lib.data["gaps"]}
        self.assertEqual(len(ids), 7)

        term = lib._gap(TERM_GAP)
        self.assertEqual(term["status"], STATUS_CLOSED)
        self.assertEqual(term["drill_id"], "drill-2026-06-gamma")

        equip = lib._gap(EQUIP_GAP)
        self.assertEqual(equip["status"], "in_progress")
        self.assertTrue(lib.exemption_active(equip, "2026-09-27"))
        self.assertFalse(lib.exemption_active(equip, "2027-01-01"))

        alpha = lib._gap(ALPHA_GAP)
        self.assertEqual(alpha["status"], STATUS_CLOSED)
        self.assertEqual(alpha["closed"]["rule_update"],
                         "rule-update-CN-2026-08")

        # 规则更新只关闭确已解决的差距：未整改的培训资料差距仍然打开
        training = lib._gap(TRAINING_GAP)
        self.assertNotEqual(training["status"], STATUS_CLOSED)
        update = lib.data["rule_updates"][0]
        self.assertIn(ALPHA_GAP, update["closed_gaps"])
        self.assertIn(TRAINING_GAP,
                      [item["gap_id"] for item in update["remaining_gaps"]])


class TranslationErrataTest(unittest.TestCase):
    def test_erratum_adds_version_without_rewriting_old_material(self):
        lib = fresh_lib()
        lib.record_translation_erratum(
            "C-1", "V2", "2026-02-01", "新译文", "勘误：术语更正")
        clause = lib._clause("C-1")
        versions = clause["official_translation"]["versions"]
        self.assertEqual([v["version"] for v in versions], ["V1", "V2"])
        # 旧版译文原样保留
        self.assertEqual(versions[0]["text"], "旧译文")
        self.assertEqual(clause["official_translation"]["current_version"], "V2")

    def test_old_course_gap_flagged_for_retraining(self):
        lib = fresh_lib()
        # 先有引用 V1 旧译文的培训资料差距，再出勘误
        lib.report_gap(
            "g-1", "C-1", "o-a", "training_material", "旧课", "d", "影响",
            training_material={"course_id": "crs", "edition": "2024版",
                               "translation_version": "V1"})
        lib.record_translation_erratum(
            "C-1", "V2", "2026-02-01", "新译文", "勘误：术语更正")
        gap = lib._gap("g-1")
        self.assertTrue(gap["training_material"]["retrain_required"])
        self.assertTrue(gap["training_material"]["material_content_immutable"])
        self.assertEqual(gap["training_material"]["translation_version"], "V1")


class WorkflowTest(unittest.TestCase):
    def _terminology_gap(self, lib):
        return lib.report_gap(
            "g-1", "C-1", "o-a", "terminology", "术语不一致", "d",
            "影响服务一致性", current_term="风险概率",
            standard_term="剩余风险等级")

    def test_self_assessment_limited_to_same_country(self):
        lib = fresh_lib()
        self._terminology_gap(lib)
        with self.assertRaises(GapError):
            lib.submit_self_assessment(
                "g-1", "o-c", "2026-03-01", "低", "统一术语", "不符合")

    def test_peer_review_must_come_from_another_organization(self):
        lib = fresh_lib()
        self._terminology_gap(lib)
        lib.submit_self_assessment(
            "g-1", "o-a", "2026-03-01", "低", "统一术语", "不符合")
        with self.assertRaises(GapError):
            lib.submit_peer_review("g-1", "o-a", "2026-03-05", "agree", "x")

    def test_disagree_sends_gap_back_to_self_assessment(self):
        lib = fresh_lib()
        self._terminology_gap(lib)
        lib.submit_self_assessment(
            "g-1", "o-a", "2026-03-01", "低", "统一术语", "不符合")
        lib.submit_peer_review("g-1", "o-b", "2026-03-05", "agree", "确认")
        self.assertEqual(lib._gap("g-1")["status"], STATUS_PEER_REVIEWED)
        lib.submit_peer_review("g-1", "o-c", "2026-03-08", "disagree", "证据不足")
        self.assertEqual(lib._gap("g-1")["status"], STATUS_SELF_ASSESSED)

    def test_action_extension_requires_reason_approver_and_later_date(self):
        lib = fresh_lib()
        self._terminology_gap(lib)
        lib.submit_self_assessment(
            "g-1", "o-a", "2026-03-01", "低", "统一术语", "不符合")
        lib.submit_peer_review("g-1", "o-b", "2026-03-05", "agree", "确认")
        lib.plan_action("g-1", "整改", "o-a", "2026-05-01", "2026-03-06")
        with self.assertRaises(GapError):
            lib.extend_action("g-1", "2026-04-01", "理由", "批准人", "2026-03-10")
        with self.assertRaises(GapError):
            lib.extend_action("g-1", "2026-06-01", "  ", "批准人", "2026-03-10")
        lib.extend_action("g-1", "2026-06-01", "避让专项任务", "张主管",
                          "2026-03-10")
        self.assertEqual(lib._gap("g-1")["action"]["extensions"][0]["approver"],
                         "张主管")

    def test_illegal_transition_rejected(self):
        lib = fresh_lib()
        self._terminology_gap(lib)
        # open 状态不能直接排定改进行动（须先自评、同行复核）
        with self.assertRaises(GapError):
            lib.plan_action("g-1", "整改", "o-a", "2026-05-01", "2026-03-06")


class DrillAndClosureTest(unittest.TestCase):
    def _completed_gap(self, lib, gap_id="g-1"):
        lib.report_gap(
            gap_id, "C-1", "o-a", "process", "流程差异", "d", "影响")
        lib.submit_self_assessment(
            gap_id, "o-a", "2026-03-01", "部分具备", "要求", "不符合")
        lib.submit_peer_review(gap_id, "o-b", "2026-03-05", "agree", "确认")
        lib.plan_action(gap_id, "整改", "o-a", "2026-05-01", "2026-03-06")
        lib.start_action(gap_id, "2026-04-01")
        lib.complete_action(gap_id, "2026-04-20", "整改完成")

    def test_close_requires_passing_drill_after_completion(self):
        lib = fresh_lib()
        self._completed_gap(lib)
        with self.assertRaises(GapError):  # 无演练不能关闭
            lib.close_gap("g-1", "jpo", "2026-04-21")
        lib.record_drill("d-1", "o-a", "2026-04-25", ["g-1"], "pass", "RPT-1")
        self.assertEqual(lib._gap("g-1")["status"], STATUS_VERIFIED)
        lib.close_gap("g-1", "jpo", "2026-04-26")
        self.assertEqual(lib._gap("g-1")["status"], STATUS_CLOSED)

    def test_drill_before_action_completion_is_not_evidence(self):
        lib = fresh_lib()
        lib.report_gap("g-1", "C-1", "o-a", "process", "流程差异", "d", "影响")
        lib.submit_self_assessment(
            "g-1", "o-a", "2026-03-01", "部分具备", "要求", "不符合")
        lib.submit_peer_review("g-1", "o-b", "2026-03-05", "agree", "确认")
        lib.plan_action("g-1", "整改", "o-a", "2026-05-01", "2026-03-06")
        lib.start_action("g-1", "2026-04-01")
        with self.assertRaises(GapError):
            lib.record_drill("d-1", "o-a", "2026-04-10", ["g-1"], "pass", "RPT")

    def test_stale_drill_before_completion_rejected(self):
        lib = fresh_lib()
        self._completed_gap(lib)
        with self.assertRaises(GapError):  # 演练日期早于整改完成日
            lib.record_drill("d-1", "o-a", "2026-04-01", ["g-1"], "pass", "RPT")

    def test_failed_drill_does_not_verify(self):
        lib = fresh_lib()
        self._completed_gap(lib)
        lib.record_drill("d-1", "o-a", "2026-04-25", ["g-1"], "fail", "RPT-1")
        self.assertEqual(lib._gap("g-1")["status"], "action_complete")
        lib.record_drill("d-2", "o-a", "2026-04-28", ["g-1"], "pass", "RPT-2")
        self.assertEqual(lib._gap("g-1")["status"], STATUS_VERIFIED)

    def test_closed_gap_can_reopen_with_reason(self):
        lib = fresh_lib()
        self._completed_gap(lib)
        lib.record_drill("d-1", "o-a", "2026-04-25", ["g-1"], "pass", "RPT-1")
        lib.close_gap("g-1", "jpo", "2026-04-26")
        with self.assertRaises(GapError):
            lib.reopen_gap("g-1", "  ", "o-a", "2026-05-01")
        lib.reopen_gap("g-1", "复演中再次发现同类偏差", "o-a", "2026-05-01")
        self.assertEqual(lib._gap("g-1")["status"], "reopened")


class ExemptionTest(unittest.TestCase):
    def test_exemption_requires_approver_and_expiry(self):
        lib = fresh_lib()
        lib.report_gap("g-1", "C-1", "o-a", "equipment", "设备差距", "d", "影响")
        with self.assertRaises(GapError):
            lib.grant_exemption("g-1", "", "2026-03-01", "2026-12-31", "范围")
        with self.assertRaises(GapError):
            lib.grant_exemption("g-1", "李司长", "2026-03-01", "", "范围")
        with self.assertRaises(GapError):  # 到期日不得早于批准日
            lib.grant_exemption("g-1", "李司长", "2026-03-01", "2026-02-01", "范围")

    def test_cannot_close_gap_while_exemption_active(self):
        lib = fresh_lib()
        lib.report_gap("g-1", "C-1", "o-a", "equipment", "设备差距", "d", "影响")
        lib.grant_exemption("g-1", "李司长", "2026-03-01", "2026-12-31",
                            "设备列编前")
        lib.submit_self_assessment(
            "g-1", "o-a", "2026-03-02", "不具备", "要求", "不符合")
        lib.submit_peer_review("g-1", "o-b", "2026-03-05", "agree", "确认")
        lib.plan_action("g-1", "采购", "o-a", "2027-03-31", "2026-03-06")
        lib.start_action("g-1", "2026-04-01")
        lib.complete_action("g-1", "2026-06-01", "提前完成采购")
        lib.record_drill("d-1", "o-a", "2026-06-10", ["g-1"], "pass", "RPT")
        with self.assertRaises(GapError):
            lib.close_gap("g-1", "jpo", "2026-06-11")
        # 豁免到期后才能关闭
        lib.close_gap("g-1", "jpo", "2027-01-02")
        self.assertEqual(lib._gap("g-1")["status"], STATUS_CLOSED)

    def test_expired_exemptions_listed(self):
        lib = build()
        expired = lib.expired_exemptions("2027-01-01")
        self.assertEqual([g["gap_id"] for g in expired], [EQUIP_GAP])
        self.assertEqual(lib.expired_exemptions("2026-09-27"), [])


class RuleUpdateTest(unittest.TestCase):
    def test_rule_update_closes_only_confirmed_gaps(self):
        lib = GapLibrary()
        lib.add_organization("o-a", "甲国 A", "CN")
        lib.add_organization("o-b", "甲国 B", "CN")
        lib.add_clause("C-9", "STD", "规则条款", "src", "V1", "2025-01-01",
                       "译文", national_rule_ids=["R-1"])
        # g-ok 将完整整改并演练；g-lag 仅规则更新，不做整改
        for gid in ("g-ok", "g-lag"):
            lib.report_gap(gid, "C-9", "o-a", "rule", gid, "d", "影响",
                           national_rule_id="R-1")
            lib.submit_self_assessment(
                gid, "o-a", "2026-02-01", "低", "要求", "不符合")
            lib.submit_peer_review(gid, "o-b", "2026-02-05", "agree", "确认")
            lib.plan_action(gid, "整改", "o-a", "2026-06-30", "2026-02-06")
        lib.start_action("g-ok", "2026-03-01")
        lib.complete_action("g-ok", "2026-05-01", "完成")
        lib.add_evidence("g-ok", "document", "SOP-1", "整改记录",
                         "o-a", "2026-05-02")
        lib.record_drill("d-1", "o-a", "2026-05-10", ["g-ok"], "pass", "RPT")

        # g-lag 虽有复评与证据，但没有实际演练，不允许关闭
        lib.add_evidence("g-lag", "document", "MEMO-1", "规则已更新说明",
                         "o-a", "2026-07-02")
        update = lib.apply_rule_update(
            "u-1", "R-1", "CN", "2026-07-01",
            {"g-ok": {"date": "2026-07-05", "conformance": "符合"},
             "g-lag": {"date": "2026-07-05", "conformance": "符合"}},
        )
        self.assertEqual(update["closed_gaps"], ["g-ok"])
        self.assertEqual(lib._gap("g-ok")["status"], STATUS_CLOSED)
        # g-lag 虽复评自称符合，但没有实际演练，不允许关闭
        self.assertNotEqual(lib._gap("g-lag")["status"], STATUS_CLOSED)
        reason = update["remaining_gaps"][0]["reason"]
        self.assertIn("演练", reason)

    def test_reassessment_before_effective_date_does_not_close(self):
        lib = build()
        training = lib._gap(TRAINING_GAP)
        before = training["status"]
        lib.apply_rule_update(
            "u-other", "CN-海标-2024-07", "CN", "2026-09-01",
            {TRAINING_GAP: {"date": "2026-08-15", "conformance": "符合"}},
        )
        self.assertEqual(lib._gap(TRAINING_GAP)["status"], before)


class ReportTest(unittest.TestCase):
    def test_report_groups_open_gaps_by_clause(self):
        lib = build()
        report = lib.consistency_report(on_date="2026-09-27")
        by_clause = {row["clause_id"]: row for row in report}
        # 已关闭的术语差距与甲国流程差距不再出现在开放清单
        for row in report:
            self.assertNotIn(TERM_GAP, [g["gap_id"] for g in row["gaps"]])
            self.assertNotIn(ALPHA_GAP, [g["gap_id"] for g in row["gaps"]])
        # 5.3 条款下设备差距在豁免有效期内、流程差距待复核
        clause_53 = by_clause["IALA-G1151-5.3"]
        ids = {g["gap_id"] for g in clause_53["gaps"]}
        self.assertIn(EQUIP_GAP, ids)
        self.assertIn(PROCESS_GAP, ids)
        equip_entry = next(g for g in clause_53["gaps"]
                           if g["gap_id"] == EQUIP_GAP)
        self.assertFalse(equip_entry["exemption_expired"])
        self.assertFalse(equip_entry["drill_verified"])

    def test_report_flags_overdue_and_expired_exemption(self):
        lib = build()
        report = lib.consistency_report(on_date="2027-04-01")
        entries = {g["gap_id"]: g for row in report for g in row["gaps"]}
        equip = entries[EQUIP_GAP]
        self.assertTrue(equip["exemption_expired"])
        self.assertTrue(equip["overdue"])


if __name__ == "__main__":
    unittest.main()
