import unittest
from copy import deepcopy
from datetime import date
from pathlib import Path

from src.records import load_records
from src.registry import DOMAIN, Registry, integrity_errors

FIXTURE = Path("fixtures/context.json")
TODAY = "2026-09-27"


class FixtureTest(unittest.TestCase):
    def setUp(self):
        self.data = load_records(FIXTURE)
        self.registry = Registry(deepcopy(self.data), today=TODAY)

    def test_fixture_domain_and_integrity(self):
        self.assertEqual(self.data["domain"], DOMAIN)
        self.assertEqual(self.data["version"], 2)
        self.assertEqual(integrity_errors(self.data), [])

    def test_courses_and_scenarios_were_imported(self):
        batch = self.data["imports"][0]
        self.assertEqual(
            set(batch["course_ids"]), {"CR-RISK-2024", "CR-RISK-2026", "CR-EQ-2025"}
        )
        self.assertEqual(
            set(batch["scenario_ids"]), {"RS-001", "RS-002", "RS-003"}
        )

    def test_reference_integrity_catches_bad_links(self):
        broken = deepcopy(self.data)
        broken["gaps"][0]["clause_id"] = "C-NOPE"
        errors = integrity_errors(broken)
        self.assertTrue(any("C-NOPE" in e for e in errors))

    def test_duplicate_ids_rejected(self):
        broken = deepcopy(self.data)
        broken["actions"][1]["id"] = broken["actions"][0]["id"]
        self.assertTrue(any("标识重复" in e for e in integrity_errors(broken)))


class CorrigendumAndFrozenCourseTest(unittest.TestCase):
    def setUp(self):
        self.registry = Registry.load(FIXTURE, today=TODAY)

    def test_frozen_courses_keep_old_wording_and_show_drift(self):
        drift = self.registry.corrigendum_drift()
        pairs = {(d["corrigendum_id"], d["course_id"]) for d in drift}
        self.assertIn(("ER-001", "CR-RISK-2024"), pairs)
        self.assertIn(("ER-002", "CR-EQ-2025"), pairs)
        # 2026 班已收录 ER-001，不产生漂移
        self.assertNotIn(("ER-001", "CR-RISK-2026"), pairs)

    def test_new_corrigendum_does_not_rewrite_frozen_snapshot(self):
        data = deepcopy(self.registry.data)
        data["translation_corrigenda"].append({
            "id": "ER-999",
            "translation_id": "T-4330-v1",
            "published_on": "2026-09-01",
            "severity": "editorial",
            "original_reading": "维持",
            "corrected_reading": "持续维持",
        })
        reg = Registry(data, today=TODAY)
        drift = {(d["corrigendum_id"], d["course_id"]) for d in reg.corrigendum_drift()}
        # 旧冻结课程照样列示，课程文本快照本身未被修改
        self.assertIn(("ER-999", "CR-EQ-2025"), drift)
        course = reg._by_id("courses", "CR-EQ-2025")
        self.assertTrue(course["frozen"])
        self.assertNotIn("ER-999", course.get("includes_corrigenda_ids", []))

    def test_corrigendum_older_than_translation_rejected(self):
        broken = deepcopy(self.registry.data)
        broken["translation_corrigenda"][0]["published_on"] = "2000-01-01"
        self.assertTrue(any("不允许回溯改写" in e for e in integrity_errors(broken)))


class SelfAssessmentAndReviewTest(unittest.TestCase):
    def setUp(self):
        self.registry = Registry.load(FIXTURE, today=TODAY)

    def _assess(self, reg, agency="EG-RSA", gap_id="G-EG-NEW"):
        return reg.add_self_assessment(
            gap_id=gap_id,
            clause_id="C-3102",
            agency_id=agency,
            kind="risk_terminology",
            title="新自评差距",
            description="虚构描述",
            affects_service_consistency=True,
        )

    def test_self_assessment_open_and_country_inferred(self):
        gap = self._assess(self.registry)
        self.assertEqual(gap["status"], "open")
        self.assertEqual(gap["country_code"], "EG")

    def test_same_country_review_rejected(self):
        self._assess(self.registry)
        with self.assertRaises(ValueError):
            self.registry.add_peer_review(
                review_id="RV-X", gap_id="G-EG-NEW",
                reviewer_agency_id="EG-RSA", outcome="confirmed", comment="x",
            )

    def test_program_office_cannot_review(self):
        self._assess(self.registry)
        with self.assertRaises(ValueError):
            self.registry.add_peer_review(
                review_id="RV-X", gap_id="G-EG-NEW",
                reviewer_agency_id="JPO", outcome="confirmed", comment="x",
            )

    def test_foreign_review_moves_gap_to_in_review(self):
        self._assess(self.registry)
        rv = self.registry.add_peer_review(
            review_id="RV-X", gap_id="G-EG-NEW",
            reviewer_agency_id="CN-MSA-DH", outcome="confirmed", comment="已核对",
        )
        self.assertEqual(rv["reviewer_country_code"], "CN")
        self.assertEqual(self.registry._by_id("gaps", "G-EG-NEW")["status"], "in_review")

    def test_fixture_reviews_are_all_cross_border(self):
        for rv in self.registry.data["reviews"]:
            gap = self.registry._by_id("gaps", rv["gap_id"])
            self.assertNotEqual(rv["reviewer_country_code"], gap["country_code"])


class EvidenceTest(unittest.TestCase):
    def setUp(self):
        self.registry = Registry.load(FIXTURE, today=TODAY)

    def test_foreign_agency_cannot_add_evidence(self):
        with self.assertRaises(ValueError):
            self.registry.add_evidence(
                evidence_id="EV-X", gap_id="G-EG-001", kind="rule_text",
                summary="越权补充", uploaded_by="CN-MSA-DH",
            )

    def test_evidence_can_be_supplemented_repeatedly(self):
        before = len(self.registry.data["evidence"])
        self.registry.add_evidence(
            evidence_id="EV-X1", gap_id="G-EG-001", kind="sop_excerpt",
            summary="补充SOP页", uploaded_by="EG-RSA",
        )
        self.registry.add_evidence(
            evidence_id="EV-X2", gap_id="G-EG-001", kind="other",
            summary="再次补充", uploaded_by="EG-RSA", restricted=True,
        )
        self.assertEqual(len(self.registry.data["evidence"]), before + 2)


class ActionExtensionTest(unittest.TestCase):
    def setUp(self):
        self.registry = Registry.load(FIXTURE, today=TODAY)

    def test_extension_requires_approver_reason_and_later_due(self):
        with self.assertRaises(ValueError):
            self.registry.extend_action(
                extension_id="AX-X", action_id="A-006",
                new_due_on="2026-12-31", approver="", reason="x",
            )
        with self.assertRaises(ValueError):
            self.registry.extend_action(
                extension_id="AX-X", action_id="A-006",
                new_due_on="2026-10-01", approver="主管", reason="",
            )
        with self.assertRaises(ValueError):
            self.registry.extend_action(
                extension_id="AX-X", action_id="A-006",
                new_due_on="2026-09-01", approver="主管", reason="采购延期",
            )

    def test_valid_extension_keeps_history_and_updates_due(self):
        ax = self.registry.extend_action(
            extension_id="AX-X", action_id="A-006",
            new_due_on="2027-03-31", approver="办公室主任",
            reason="第二批设备到货推迟", approved_on="2026-09-20",
        )
        self.assertEqual(ax["previous_due_on"], "2026-12-31")
        self.assertEqual(self.registry._by_id("actions", "A-006")["due_on"], "2027-03-31")
        self.assertEqual(len(self.registry.extensions_for_action("A-006")), 2)

    def test_completed_after_due_without_extension_is_flagged(self):
        broken = deepcopy(self.registry.data)
        broken["actions"][0]["completed_on"] = "2026-09-01"  # A-001 due 2026-05-10
        self.assertTrue(any("补记延期" in e for e in integrity_errors(broken)))

    def test_overdue_detection(self):
        action = self.registry._by_id("actions", "A-007")  # due 2026-06-30, in_progress
        self.assertTrue(self.registry.is_overdue(action))
        self.assertFalse(self.registry.is_overdue(
            self.registry._by_id("actions", "A-003")))  # due 2027-03-31


class ExemptionTest(unittest.TestCase):
    def setUp(self):
        self.registry = Registry.load(FIXTURE, today=TODAY)

    def test_exemption_requires_approver_and_expiry(self):
        with self.assertRaises(ValueError):
            self.registry.grant_exemption(
                exemption_id="EX-X", gap_id="G-EG-001", scope="s", reason="r",
                approver_name="", approver_role="主管", expiry_on="2026-12-31",
            )
        with self.assertRaises(ValueError):
            self.registry.grant_exemption(
                exemption_id="EX-X", gap_id="G-EG-001", scope="s", reason="r",
                approver_name="主管", approver_role="角色", expiry_on="2026-01-01",
            )

    def test_expiry_state(self):
        active = self.registry._by_id("exemptions", "EX-001")
        expired = self.registry._by_id("exemptions", "EX-002")
        self.assertEqual(self.registry.exemption_state(active), "active")
        self.assertEqual(self.registry.exemption_state(expired), "expired")
        self.assertEqual(
            [e["id"] for e in self.registry.expired_exemptions()], ["EX-002"]
        )

    def test_exemption_cannot_be_closure_basis(self):
        gap = self.registry._by_id("gaps", "G-EG-002")
        with self.assertRaises(ValueError):
            self.registry.close_gap_with_drill(gap["id"], closed_by="JPO")
        # 即便手工写入豁免依据，完整性检查也判为关闭无效
        hacked = deepcopy(self.registry.data)
        target = next(g for g in hacked["gaps"] if g["id"] == "G-EG-002")
        target["status"] = "closed"
        target["closure"] = {
            "basis": "exemption", "ref_id": "EX-002",
            "closed_on": "2026-09-01", "closed_by": "JPO",
        }
        self.assertTrue(any("关闭无效" in e for e in integrity_errors(hacked)))


class DrillClosureTest(unittest.TestCase):
    def setUp(self):
        self.registry = Registry.load(FIXTURE, today=TODAY)

    def test_partial_drill_does_not_close(self):
        # G-CN-003: SOP完成且复核确认，但 D-002 仅部分通过
        with self.assertRaises(ValueError):
            self.registry.close_gap_with_drill("G-CN-003", closed_by="JPO")
        self.assertIn(
            "A-002", [a["id"] for a in self.registry.drills_need_rerun()]
        )

    def test_drill_before_action_completion_rejected(self):
        broken = deepcopy(self.registry.data)
        broken["drills"][0]["exercised_on"] = "2026-04-01"  # A-001 completed 2026-05-01
        self.assertTrue(any("演练日期早于行动完成日期" in e
                            for e in integrity_errors(broken)))

    def test_same_country_verifier_rejected(self):
        with self.assertRaises(ValueError):
            self.registry.record_drill(
                drill_id="D-X", gap_id="G-EG-001", action_id="A-006",
                scenario_id="RS-002", exercised_on="2026-09-15",
                result="passed", verified_by="EG-RSA", summary="自验",
            )

    def test_passing_drill_after_fix_closes_gap_end_to_end(self):
        reg = Registry(deepcopy(self.registry.data), today=TODAY)
        # 补齐 G-EG-002：行动获准延期后完成 → 他国验证演练通过 → 关闭
        reg.extend_action(
            extension_id="AX-EG002", action_id="A-007",
            new_due_on="2026-09-30", approver="联合项目办公室主任（虚构）",
            reason="值班调度系统改造排期", approved_on="2026-06-25",
        )
        action = reg._by_id("actions", "A-007")
        action["status"] = "completed"
        action["completed_on"] = "2026-09-10"
        reg.add_evidence(
            evidence_id="EV-EG007", gap_id="G-EG-002", kind="sop_excerpt",
            summary="新值班调度机制文件", uploaded_by="EG-RSA",
        )
        reg.add_peer_review(
            review_id="RV-EG002", gap_id="G-EG-002",
            reviewer_agency_id="MY-MARITIME", outcome="confirmed",
            comment="调度机制满足时限", on="2026-09-12",
        )
        reg.record_drill(
            drill_id="D-EG002", gap_id="G-EG-002", action_id="A-007",
            scenario_id="RS-001", exercised_on="2026-09-18",
            result="passed", verified_by="MY-MARITIME",
            summary="连续两次漂移事件均在4小时内完成核实上报",
        )
        gap = reg.close_gap_with_drill("G-EG-002", closed_by="JPO")
        self.assertEqual(gap["status"], "closed")
        self.assertFalse(gap["affects_service_consistency"])
        self.assertEqual(gap["closure"]["ref_id"], "D-EG002")
        self.assertEqual(integrity_errors(reg.data), [])


class RuleUpdateTest(unittest.TestCase):
    def setUp(self):
        self.registry = Registry.load(FIXTURE, today=TODAY)

    def test_fixture_rule_update_only_closed_resolved_gap(self):
        ru = self.registry._by_id("rule_updates", "RU-MY-001")
        self.assertEqual(ru["closes_gap_ids"], ["G-MY-001"])
        gap = self.registry._by_id("gaps", "G-MY-001")
        self.assertEqual(gap["closure"]["basis"], "rule_update")
        # 中国规则更新已生效，但冻结课程差距仍打开
        cn_update = self.registry._by_id("rule_updates", "RU-CN-001")
        self.assertEqual(cn_update["closes_gap_ids"], [])
        self.assertEqual(
            self.registry._by_id("gaps", "G-CN-001")["status"], "open"
        )

    def test_apply_rule_update_skips_unresolved_gaps(self):
        reg = Registry(deepcopy(self.registry.data), today=TODAY)
        update = reg.apply_rule_update(
            update_id="RU-EG-X", country_code="EG",
            national_rule_id="NR-EG-01", title="设备令修订",
            effective_on="2026-10-01",
            requested_gap_ids=["G-EG-001", "G-EG-002", "G-MY-001"],
            note="试提交",
        )
        self.assertEqual(update["closes_gap_ids"], [])
        skipped = {row["gap_id"]: row["reason"] for row in update["skipped"]}
        self.assertIn("不同国家", skipped["G-MY-001"])
        self.assertIn("演练", skipped["G-EG-001"])
        for gid in ("G-EG-001", "G-EG-002"):
            self.assertNotEqual(reg._by_id("gaps", gid)["status"], "closed")

    def test_rule_update_cannot_close_foreign_gap(self):
        broken = deepcopy(self.registry.data)
        ru = next(r for r in broken["rule_updates"] if r["id"] == "RU-MY-001")
        ru["closes_gap_ids"].append("G-EG-001")
        self.assertTrue(any("他国差距" in e for e in integrity_errors(broken)))

    def test_rule_update_cannot_bypass_drill_requirement(self):
        # G-CN-003 有证据+异国确认，但演练 partial：无资格按规则更新关闭
        result = self.registry.rule_closure_candidates("CN")
        self.assertIn("G-CN-003", result["blocked"])


class CountryIsolationTest(unittest.TestCase):
    def setUp(self):
        self.registry = Registry.load(FIXTURE, today=TODAY)

    def test_sensitive_facilities_isolated_by_country(self):
        my = self.registry.country_slice("MY")
        self.assertEqual({f["id"] for f in my["facilities"]}, {"F-MY-001"})
        eg = self.registry.country_slice("EG")
        self.assertIn("F-EG-001", {f["id"] for f in eg["facilities"]})
        self.assertNotIn("F-CN-001", {f["id"] for f in eg["facilities"]})

    def test_restricted_evidence_isolated(self):
        cn_ids = {e["id"] for e in self.registry.country_slice("CN")["evidence"]}
        my_ids = {e["id"] for e in self.registry.country_slice("MY")["evidence"]}
        self.assertIn("EV-002", cn_ids)       # 中国受限证据本国有
        self.assertNotIn("EV-002", my_ids)    # 马来西亚不可见
        self.assertIn("EV-003", my_ids)       # 非受限证据跨国可见

    def test_gap_on_hidden_sensitive_facility_dropped_for_foreigners(self):
        my = self.registry.country_slice("MY")
        gap_ids = {g["id"] for g in my["gaps"]}
        self.assertNotIn("G-CN-004", gap_ids)  # 挂接中国敏感设施
        self.assertIn("G-EG-003", gap_ids)     # 无设施挂接的差距仍可见

    def test_program_office_sees_everything(self):
        xn = self.registry.country_slice("XN")
        self.assertEqual(
            {f["id"] for f in xn["facilities"]},
            {"F-CN-001", "F-MY-001", "F-EG-001"},
        )
        self.assertEqual(len(xn["evidence"]), len(self.registry.data["evidence"]))


class ManagerClauseViewTest(unittest.TestCase):
    def setUp(self):
        self.registry = Registry.load(FIXTURE, today=TODAY)

    def test_clause_view_lists_mappings(self):
        view = self.registry.clause_view("C-3101")
        self.assertEqual(view["current_translation"]["id"], "T-3101-v2")
        self.assertEqual({e["id"] for e in view["corrigenda"]}, {"ER-001"})
        self.assertEqual(
            {nr["id"] for nr in view["national_rules"]}, {"NR-CN-02"}
        )

    def test_manager_view_flags_consistency_impact_and_drill_status(self):
        view = self.registry.manager_clause_view("C-5200")
        ids = {g["id"] for g in view["affecting_consistency"]}
        self.assertEqual(ids, {"G-MY-002", "G-EG-002"})
        # 已关闭的 G-MY-001 不再影响一致性
        self.assertNotIn("G-MY-001", ids)
        self.assertEqual(
            view["undrilled_actions"],
            [{"gap_id": "G-EG-002", "action_id": "A-007"}],
        )
        self.assertEqual(view["overdue_actions"], ["A-007"])
        self.assertEqual(
            [e["id"] for e in view["expired_exemptions"]], ["EX-002"]
        )

    def test_closed_drill_verified_gap_absent_from_live_list(self):
        view = self.registry.manager_clause_view("C-4330")
        self.assertEqual(view["affecting_consistency"], [])
        self.assertEqual(view["affected_countries"], [])

    def test_today_is_date_object(self):
        self.assertIsInstance(self.registry.today, date)


if __name__ == "__main__":
    unittest.main()
