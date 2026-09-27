"""已有课程与风险场景样例的导入。

- 课程：联合项目办公室维护的培训资料。课程一经发布内容不可改写；当条款官方
  译文出现勘误、课程引用的译文版本落后时，为每个采用该课程的成员机构生成
  "培训资料"类差距，并标记需要复训。
- 风险场景：标准处置能力的考核样例。成员机构对照场景自评，术语、设备能力、
  处置流程三类不达标项各自生成差距。
- 导入幂等：重复导入同编号资料不会产生重复记录或重复差距。
"""

from __future__ import annotations

from .gap_library import GapLibrary, GapError


def import_courses(lib: GapLibrary, courses: list[dict],
                   on_date: str) -> list[dict]:
    created_gaps: list[dict] = []
    for course in courses:
        cid = course["course_id"]
        existing = next((c for c in lib.data["courses"]
                         if c["course_id"] == cid), None)
        if existing is None:
            stored = {
                "course_id": cid,
                "title": course["title"],
                "edition": course["edition"],
                "material_immutable": True,
                "adopting_orgs": list(course.get("adopting_orgs", [])),
                "clause_refs": course["clause_refs"],
            }
            lib.data["courses"].append(stored)
        else:
            # 旧版资料不改写：编号相同即同一版本，拒绝覆盖内容
            if existing["edition"] != course["edition"]:
                raise GapError(
                    f"课程 {cid} 版本冲突：旧版培训资料不可改写，请使用新课程编号")
            stored = existing

        for ref in stored["clause_refs"]:
            clause = lib._clause(ref["clause_id"])
            current_version = clause["official_translation"]["current_version"]
            outdated = ref["translation_version"] != current_version
            for org_id in stored["adopting_orgs"]:
                gap_id = f"gap-tm-{cid}-{ref['clause_id']}-{org_id}"
                if any(g["gap_id"] == gap_id for g in lib.data["gaps"]):
                    continue
                if not outdated:
                    continue
                lib.report_gap(
                    gap_id=gap_id,
                    clause_id=ref["clause_id"],
                    reporter_org=org_id,
                    category="training_material",
                    title=f"课程《{stored['title']}》译文版本落后",
                    description=(
                        f"课程 {cid}（{stored['edition']}）依据译文 "
                        f"{ref['translation_version']} 编写，"
                        f"现行官方译文已更新至 {current_version}；"
                        "旧版资料不改写，需按新译文组织复训。"),
                    service_impact="术语讲解与现行标准不一致，延续培训后的操作分歧",
                    training_material={
                        "course_id": cid,
                        "edition": stored["edition"],
                        "translation_version": ref["translation_version"],
                    },
                    opened_date=on_date,
                )
                created_gaps.append(lib._gap(gap_id))
    return created_gaps


def import_risk_scenarios(lib: GapLibrary, scenarios: list[dict]) -> list[dict]:
    stored: list[dict] = []
    for scenario in scenarios:
        sid = scenario["scenario_id"]
        lib._clause(scenario["clause_id"])
        existing = next((s for s in lib.data["risk_scenarios"]
                         if s["scenario_id"] == sid), None)
        if existing is not None:
            stored.append(existing)
            continue
        item = {
            "scenario_id": sid,
            "title": scenario["title"],
            "clause_id": scenario["clause_id"],
            "hazard": scenario["hazard"],
            "standard_terms": list(scenario.get("standard_terms", [])),
            "required_capability": scenario["required_capability"],
            "expected_process": list(scenario.get("expected_process", [])),
            "required_equipment": list(scenario.get("required_equipment", [])),
        }
        lib.data["risk_scenarios"].append(item)
        stored.append(item)
    return stored


def assess_scenario(lib: GapLibrary, scenario_id: str, org_id: str,
                    assessment: dict) -> list[dict]:
    """成员机构对照风险场景自评，按不达标项生成差距。

    assessment 结构：
    {
      "date": "2026-09-01",
      "capability_level": "...",
      "conformance": "不符合",
      "mismatches": [
        {"kind": "terminology", "current": "...", "standard": "...", "impact": "..."},
        {"kind": "equipment", "equipment_limit": {...}, "impact": "..."},
        {"kind": "process", "current_process": "...", "impact": "..."}
      ],
      "sensitive": false,
      "facility": null
    }
    """
    scenario = next((s for s in lib.data["risk_scenarios"]
                     if s["scenario_id"] == scenario_id), None)
    if scenario is None:
        raise GapError(f"未知风险场景：{scenario_id}")
    org = lib._org(org_id)
    created: list[dict] = []
    for mismatch in assessment.get("mismatches", []):
        kind = mismatch["kind"]
        if kind not in {"terminology", "equipment", "process"}:
            raise GapError(f"场景自评不支持的差距类别：{kind}")
        gap_id = f"gap-{scenario_id}-{org_id}-{kind}"
        if any(g["gap_id"] == gap_id for g in lib.data["gaps"]):
            # 已登记过的同类差距不重复生成，走证据补充/重新评估流程
            continue
        title_map = {
            "terminology": f"风险术语与标准不一致：{scenario['title']}",
            "equipment": f"设备能力不满足场景要求：{scenario['title']}",
            "process": f"处置流程与标准不一致：{scenario['title']}",
        }
        kwargs = dict(
            gap_id=gap_id,
            clause_id=scenario["clause_id"],
            reporter_org=org_id,
            category=kind,
            title=title_map[kind],
            description=(
                f"对照风险场景 {scenario_id} 自评发现：{mismatch.get('detail', '')}"),
            service_impact=mismatch.get("impact", scenario["hazard"]),
            sensitive=assessment.get("sensitive", False),
            facility=assessment.get("facility"),
            opened_date=assessment["date"],
        )
        if kind == "terminology":
            kwargs["current_term"] = mismatch["current"]
            kwargs["standard_term"] = mismatch["standard"]
        elif kind == "equipment":
            kwargs["equipment_limit"] = mismatch.get("equipment_limit", {})
        else:
            kwargs["current_process"] = mismatch["current_process"]
        lib.report_gap(**kwargs)
        created.append(lib._gap(gap_id))
    return created
