"""课程与风险场景导入测试。"""

import json
import unittest
from pathlib import Path

from src.gap_library import GapLibrary, GapError
from src.importers import (
    assess_scenario,
    import_courses,
    import_risk_scenarios,
)

ROOT = Path(__file__).resolve().parents[1]


def base_lib() -> GapLibrary:
    lib = GapLibrary()
    lib.add_organization("org-alpha", "甲国 A", "CN")
    lib.add_organization("org-beta", "甲国 B", "CN")
    lib.add_organization("org-gamma", "乙国 C", "XY")
    lib.add_clause(
        "IALA-G1151-3.2", "IALA G1151", "术语条款", "src",
        "V2", "2026-03-01", "新译文")
    lib.add_clause(
        "IALA-G1151-5.3", "IALA G1151", "恢复时限", "src",
        "V2", "2023-09-01", "四小时")
    lib.add_clause(
        "IALA-G1151-4.1", "IALA G1151", "告警分级", "src",
        "V1", "2022-06-01", "译文")
    return lib


class CourseImportTest(unittest.TestCase):
    def test_outdated_translation_creates_retraining_gaps(self):
        lib = base_lib()
        courses = json.loads(
            (ROOT / "fixtures/imports/courses.json").read_text("utf-8"))
        # 只保留引用 3.2 的课程，其 V1 译文已落后于现行 V2
        courses = [c for c in courses if c["course_id"] == "course-risk-101"]
        gaps = import_courses(lib, courses, "2026-04-01")
        # 三个采用机构各生成一条培训资料差距（3.2 落后；5.3 不在该课程）
        self.assertEqual(len(gaps), 3)
        for gap in gaps:
            self.assertEqual(gap["category"], "training_material")
            self.assertTrue(gap["training_material"]["retrain_required"])
            self.assertTrue(gap["training_material"]["material_content_immutable"])

    def test_current_translation_creates_no_gap(self):
        lib = base_lib()
        courses = [{
            "course_id": "course-equip-204",
            "title": "应急布设",
            "edition": "2024版",
            "adopting_orgs": ["org-alpha"],
            "clause_refs": [{"clause_id": "IALA-G1151-5.3",
                             "translation_version": "V2"}],
        }]
        self.assertEqual(import_courses(lib, courses, "2026-04-01"), [])

    def test_import_is_idempotent(self):
        lib = base_lib()
        courses = json.loads(
            (ROOT / "fixtures/imports/courses.json").read_text("utf-8"))
        import_courses(lib, courses, "2026-04-01")
        first_count = len(lib.data["gaps"])
        import_courses(lib, courses, "2026-04-02")
        self.assertEqual(len(lib.data["gaps"]), first_count)

    def test_old_material_cannot_be_overwritten(self):
        lib = base_lib()
        courses = [{
            "course_id": "crs-1", "title": "课", "edition": "2023版",
            "adopting_orgs": ["org-alpha"],
            "clause_refs": [{"clause_id": "IALA-G1151-5.3",
                             "translation_version": "V2"}],
        }]
        import_courses(lib, courses, "2026-04-01")
        changed = [{**courses[0], "edition": "2026修订版"}]
        with self.assertRaises(GapError):
            import_courses(lib, changed, "2026-04-01")


class ScenarioImportTest(unittest.TestCase):
    def test_scenario_self_assessment_generates_gaps_by_kind(self):
        lib = base_lib()
        scenarios = json.loads(
            (ROOT / "fixtures/imports/risk_scenarios.json").read_text("utf-8"))
        import_risk_scenarios(lib, scenarios)
        gaps = assess_scenario(
            lib, "scenario-001", "org-gamma", {
                "date": "2026-05-10",
                "mismatches": [
                    {"kind": "terminology", "current": "风险概率",
                     "standard": "剩余风险等级", "impact": "升级口径不一"},
                    {"kind": "equipment",
                     "equipment_limit": {"actual": "12 小时"},
                     "impact": "恢复超时"},
                    {"kind": "process", "current_process": "缺临时警戒",
                     "impact": "过渡措施缺失"},
                ],
            })
        self.assertEqual({g["category"] for g in gaps},
                         {"terminology", "equipment", "process"})
        term = [g for g in gaps if g["category"] == "terminology"][0]
        self.assertEqual(term["term_diff"]["standard"], "剩余风险等级")

    def test_repeated_assessment_does_not_duplicate_gap(self):
        lib = base_lib()
        import_risk_scenarios(lib, [{
            "scenario_id": "s-1", "title": "t",
            "clause_id": "IALA-G1151-5.3", "hazard": "h",
            "required_capability": "4 小时",
        }])
        payload = {
            "date": "2026-05-10",
            "mismatches": [{"kind": "process", "current_process": "旧流程",
                            "impact": "影响"}],
        }
        first = assess_scenario(lib, "s-1", "org-alpha", payload)
        second = assess_scenario(lib, "s-1", "org-alpha",
                                 {**payload, "date": "2026-06-10"})
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])


if __name__ == "__main__":
    unittest.main()
