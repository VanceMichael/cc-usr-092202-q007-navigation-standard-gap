"""生成 fixtures/gap_library.json 样例（不含真实个人信息与凭据）。

运行：python -m scripts.seed_fixture
样例剧情：
- 甲国两家机构 + 乙国两家机构；条款 3.2 官方译文发布 V2 勘误，旧版课程不改写；
- 乙国机构对照浓雾场景自评出术语/设备/流程三类差距，设备差距含敏感设施信息；
- 术语差距走完自评、跨国同行复核、行动延期、演练、关闭；
- 设备差距办了有期限和批准人的现场豁免，仍在整改；
- 甲国流程差距经演练验证后，借国家规则更新关闭；同规则关联的培训资料差距
  因未整改，规则更新时不予关闭。
"""

from __future__ import annotations

import json
from pathlib import Path

from src.gap_library import GapLibrary, save_library
from src.importers import (
    assess_scenario,
    import_courses,
    import_risk_scenarios,
)

ROOT = Path(__file__).resolve().parents[1]


def build() -> GapLibrary:
    lib = GapLibrary()

    # ---- 成员机构（两国四家） ----
    lib.add_organization("org-alpha", "甲国 A 港航标处", "CN")
    lib.add_organization("org-beta", "甲国 B 海区航标站", "CN")
    lib.add_organization("org-gamma", "乙国 C 港务航标局", "XY")
    lib.add_organization("org-delta", "乙国 D 湾航标队", "XY")

    # ---- 国际条款与官方译文 ----
    lib.add_clause(
        "IALA-G1151-3.2", "IALA G1151", "风险等级与剩余风险术语",
        "The authority shall use residual risk levels consistently in "
        "notification and escalation.",
        "V1", "2022-06-01", "主管机关应在通报与升级中统一使用风险等级术语。",
    )
    lib.add_clause(
        "IALA-G1151-4.1", "IALA G1151", "告警分级与抑制",
        "Alerts shall be graded before suppression; misreport rate shall be "
        "monitored.",
        "V1", "2022-06-01", "告警抑制前应先分级，并监测误报率。",
        national_rule_ids=["CN-海标-2024-07"],
    )
    lib.add_clause(
        "IALA-G1151-5.3", "IALA G1151", "导助航应急恢复时限",
        "Temporary aids shall be deployed and navigational warnings issued "
        "within four hours.",
        "V2", "2023-09-01", "应在四小时内布设临时标志并发布航行警告。",
    )

    # ---- 官方译文勘误：只发新版，不动旧版培训资料 ----
    lib.record_translation_erratum(
        "IALA-G1151-3.2", "V2", "2026-03-01",
        "主管机关应在通报与升级中统一使用剩余风险等级术语。",
        "勘误：将“风险等级”明确为“剩余风险等级”，避免与初始风险混用",
    )

    # ---- 导入已有课程与风险场景 ----
    courses = json.loads((ROOT / "fixtures/imports/courses.json").read_text("utf-8"))
    import_courses(lib, courses, "2026-04-01")

    scenarios = json.loads(
        (ROOT / "fixtures/imports/risk_scenarios.json").read_text("utf-8"))
    import_risk_scenarios(lib, scenarios)

    # ---- 乙国机构对照浓雾场景自评 ----
    # 术语/流程差距不涉及设施明细，可跨国同行复核
    assess_scenario(lib, "scenario-001", "org-gamma", {
        "date": "2026-05-10",
        "conformance": "不符合",
        "mismatches": [
            {
                "kind": "terminology",
                "detail": "现场通报仍使用“风险概率”，未使用“剩余风险等级”",
                "current": "风险概率",
                "standard": "剩余风险等级",
                "impact": "跨国联合演练中升级判定口径不一致，临时警戒启动偏晚",
            },
            {
                "kind": "process",
                "detail": "处置流程缺少“临时警戒”步骤",
                "current_process": "确认失效 → 布设标志 → 发布警告 → 复盘",
                "impact": "标志恢复前缺乏过渡性交通组织措施",
            },
        ],
    })
    # 设备差距含敏感设施信息，单独自评并按国家隔离
    assess_scenario(lib, "scenario-001", "org-gamma", {
        "date": "2026-05-10",
        "conformance": "不符合",
        "sensitive": True,
        "facility": {
            "site_name": "C 港进口航道 3 号灯浮（示例位置）",
            "vulnerability": "仅单船待命，夜间出动准备时间约 3 小时",
        },
        "mismatches": [
            {
                "kind": "equipment",
                "detail": "无快速布设艇与备用灯浮，实际恢复约 12 小时",
                "equipment_limit": {
                    "required": "4 小时内恢复",
                    "actual": "约 12 小时",
                    "missing": ["快速布设艇", "AIS 虚拟航标授权"],
                },
                "impact": "浓雾夜航时导助航中断窗口远超标准时限",
            },
        ],
    })

    # ---- 甲国机构对照告警风暴场景自评 ----
    assess_scenario(lib, "scenario-002", "org-alpha", {
        "date": "2026-05-10",
        "conformance": "部分符合",
        "mismatches": [
            {
                "kind": "process",
                "detail": "现场先抑制后分级，顺序与标准相反",
                "current_process": "发现告警风暴 → 直接抑制 → 事后分级",
                "impact": "抑制缺少分级依据，可能掩盖真实告警",
            },
        ],
    })

    # 把甲国流程差距与一条培训资料差距关联到本国规则，
    # 用于验证规则更新的关闭口径
    lib._gap("gap-scenario-002-org-alpha-process")["national_rule_id"] = \
        "CN-海标-2024-07"
    alpha_training_gap = lib._gap(
        "gap-tm-course-risk-101-IALA-G1151-3.2-org-alpha")
    alpha_training_gap["national_rule_id"] = "CN-海标-2024-07"

    # ---- 术语差距：自评 → 跨国同行复核 → 行动（含延期）→ 演练 → 关闭 ----
    term_gap = "gap-scenario-001-org-gamma-terminology"
    lib.submit_self_assessment(
        term_gap, "org-gamma", "2026-05-15",
        capability_level="部分具备", standard_requirement="统一使用剩余风险等级",
        conformance="不符合", notes="旧版课程用词尚未更新")
    lib.submit_peer_review(
        term_gap, "org-alpha", "2026-05-20", "agree",
        "确认术语差异影响联合演练升级判定，建议同步修订通报模板")
    lib.plan_action(term_gap, "修订现场通报模板并组织术语专项复训",
                    "org-gamma", "2026-07-31", "2026-05-25")
    lib.extend_action(term_gap, "2026-08-31",
                      "复训需避让当地伏休监管任务期", "联合项目办公室 王专员",
                      "2026-07-25")
    lib.start_action(term_gap, "2026-06-01")
    lib.complete_action(term_gap, "2026-06-20",
                        "新通报模板发布，两轮专项复训共 38 人完成")
    lib.add_evidence(term_gap, "document", "SOP-GAMMA-2026-018",
                     "修订后的通报模板与复训签到记录", "org-gamma", "2026-06-21")
    lib.record_drill("drill-2026-06-gamma", "org-gamma", "2026-06-25",
                     [term_gap], "pass", "DRILL-RPT-2026-06-GAMMA",
                     scenario_ref="scenario-001")
    lib.close_gap(term_gap, "joint-project-office", "2026-06-26")

    # ---- 设备差距：有期限、有批准人的现场豁免；同国同行复核；仍在整改 ----
    equip_gap = "gap-scenario-001-org-gamma-equipment"
    lib.grant_exemption(
        equip_gap, "乙国主管部门 李司长", "2026-05-12", "2026-12-31",
        "仅在快速布设艇列编前对 C 港进口航道适用，期间执行加强瞭望与拖轮待命")
    lib.submit_self_assessment(
        equip_gap, "org-gamma", "2026-05-15",
        capability_level="不具备", standard_requirement="4 小时内恢复",
        conformance="不符合", notes="已申请预算采购快速布设艇")
    lib.submit_peer_review(
        equip_gap, "org-delta", "2026-05-22", "agree",
        "确认设备能力差距属实；敏感设施细节按乙国隔离，未在复核意见中转引")
    lib.plan_action(equip_gap, "采购快速布设艇并取得 AIS 虚拟航标授权",
                    "org-gamma", "2027-03-31", "2026-05-28")
    lib.start_action(equip_gap, "2026-08-01")
    lib.add_evidence(equip_gap, "document", "BUDGET-XY-2026-221",
                     "快速布设艇采购立项批复（示例编号）", "org-gamma",
                     "2026-07-10")

    # ---- 流程差距：仅自评，尚未进入同行复核 ----
    lib.submit_self_assessment(
        "gap-scenario-001-org-gamma-process", "org-gamma", "2026-05-15",
        capability_level="部分具备", standard_requirement="先临时警戒再恢复标志",
        conformance="不符合", notes="拟结合处置手册修订补充该步骤")

    # ---- 甲国流程差距：演练验证后，随国家规则更新关闭 ----
    alpha_gap = "gap-scenario-002-org-alpha-process"
    lib.submit_self_assessment(
        alpha_gap, "org-alpha", "2026-05-12",
        capability_level="具备能力，流程顺序错误",
        standard_requirement="先分级后抑制", conformance="部分符合")
    lib.submit_peer_review(
        alpha_gap, "org-beta", "2026-05-18", "agree",
        "远程监控平台支持先分级，问题在现场处置单顺序")
    lib.plan_action(alpha_gap, "修订处置单与值班规程，落实先分级后抑制",
                    "org-alpha", "2026-06-30", "2026-05-22")
    lib.start_action(alpha_gap, "2026-06-02")
    lib.complete_action(alpha_gap, "2026-06-25",
                        "处置单 V3 发布，值班规程同步更新")
    lib.add_evidence(alpha_gap, "document", "SOP-ALPHA-2026-031",
                     "处置单 V3 与规程修订页", "org-alpha", "2026-06-25")
    lib.record_drill("drill-2026-07-alpha", "org-alpha", "2026-07-18",
                     [alpha_gap], "pass", "DRILL-RPT-2026-07-ALPHA",
                     scenario_ref="scenario-002")

    # 国家规则更新：已演练验证且复评符合的差距关闭；未整改的培训差距保留
    lib.apply_rule_update(
        update_id="rule-update-CN-2026-08",
        national_rule_id="CN-海标-2024-07",
        country_code="CN",
        effective_date="2026-08-01",
        reassessments={
            alpha_gap: {"date": "2026-08-05", "conformance": "符合",
                        "notes": "规则条款与 IALA G1151-4.1 对齐，演练验证通过"},
            alpha_training_gap["gap_id"]: {
                "date": "2026-08-05", "conformance": "部分符合",
                "notes": "规则已更新，但旧版课程复训尚未完成"},
        },
    )

    return lib


def main() -> None:
    lib = build()
    out = ROOT / "fixtures/gap_library.json"
    save_library(lib, out)
    print(f"已写入 {out}：{len(lib.data['gaps'])} 条差距，"
          f"{len(lib.data['clauses'])} 条条款，{len(lib.data['drills'])} 次演练")


if __name__ == "__main__":
    main()
