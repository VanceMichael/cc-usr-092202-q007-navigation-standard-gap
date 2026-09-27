"""航标标准落地差距库：读取、结构校验与业务规则。

业务要点：
- 国际条款、官方译文（含勘误）、本国规范、课程、风险场景与差距逐项对应；
- 译文勘误只追加，不回溯改写已冻结的旧版培训资料；
- 自评 → 异国同行复核 → 证据补充 → 改进行动（可延期）→ 规则更新或实际演练关闭；
- 现场豁免必须有批准人与到期日，过期失效，且不能用于关闭差距；
- 国家规则更新只关闭确已解决的差距；
- 敏感设施与受限证据按国家隔离。
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any, Iterable

DOMAIN = "navigation-standard-gap"
SCHEMA_VERSION = 2
PROGRAM_OFFICE_COUNTRY = "XN"  # 联合项目办公室（跨国管理者视图）

COLLECTIONS = (
    "imports",
    "standards_clauses",
    "translations",
    "translation_corrigenda",
    "national_rules",
    "courses",
    "risk_scenarios",
    "agencies",
    "facilities",
    "gaps",
    "reviews",
    "evidence",
    "actions",
    "action_extensions",
    "exemptions",
    "drills",
    "rule_updates",
)

_TERMINAL_ACTION_STATUS = {"completed", "cancelled"}
_OPEN_GAP_STATUS = {"open", "in_review"}


def _parse_day(value: str) -> date:
    return date.fromisoformat(value)


def integrity_errors(data: dict[str, Any]) -> list[str]:
    """返回资料的结构性/引用性错误清单，空清单表示通过。"""
    errors: list[str] = []

    if data.get("domain") != DOMAIN:
        errors.append("领域标识不是 navigation-standard-gap")
    if data.get("version") != SCHEMA_VERSION:
        errors.append("资料版本不是 2")
    for key in ("sample_id", "as_of", "actors", "facts", "constraints", *COLLECTIONS):
        if key not in data:
            errors.append(f"缺少必要字段：{key}")
    if errors:
        return errors

    def index(collection: str) -> dict[str, dict]:
        rows = data[collection]
        seen: dict[str, dict] = {}
        for row in rows:
            rid = row.get("id", "<无标识>")
            if rid in seen:
                errors.append(f"{collection} 中标识重复：{rid}")
            seen[rid] = row
        return seen

    imports = data["imports"]
    clauses = index("standards_clauses")
    translations = index("translations")
    corrigenda = index("translation_corrigenda")
    rules = index("national_rules")
    courses = index("courses")
    scenarios = index("risk_scenarios")
    agencies = index("agencies")
    facilities = index("facilities")
    gaps = index("gaps")
    reviews = index("reviews")
    evidence = index("evidence")
    actions = index("actions")
    extensions = index("action_extensions")
    exemptions = index("exemptions")
    drills = index("drills")
    rule_updates = index("rule_updates")

    def must_exist(kind: str, table: dict, rid: str | None, where: str) -> bool:
        if rid is not None and rid not in table:
            errors.append(f"{where} 引用的 {kind} 不存在：{rid}")
            return False
        return True

    # ---- 译文与勘误 ----
    for tr in translations.values():
        must_exist("条款", clauses, tr["clause_id"], f"译文 {tr['id']}")
    for er in corrigenda.values():
        if must_exist("译文", translations, er["translation_id"], f"勘误 {er['id']}"):
            tr = translations[er["translation_id"]]
            if _parse_day(er["published_on"]) < _parse_day(tr["published_on"]):
                errors.append(f"勘误 {er['id']} 早于其译文发布，不允许回溯改写")

    # ---- 本国规范 ----
    for nr in rules.values():
        for cid in nr["clause_ids"]:
            must_exist("条款", clauses, cid, f"本国规范 {nr['id']}")

    # ---- 课程与风险场景 ----
    for cr in courses.values():
        for tid in cr.get("based_on_translation_ids", []):
            must_exist("译文", translations, tid, f"课程 {cr['id']}")
        for eid in cr.get("includes_corrigenda_ids", []):
            must_exist("勘误", corrigenda, eid, f"课程 {cr['id']}")
    for sc in scenarios.values():
        for cid in sc["clause_ids"]:
            must_exist("条款", clauses, cid, f"风险场景 {sc['id']}")
        must_exist("课程", courses, sc["source_course_id"], f"风险场景 {sc['id']}")

    imported_courses = {cid for batch in imports for cid in batch["course_ids"]}
    imported_scenarios = {sid for batch in imports for sid in batch["scenario_ids"]}
    for batch in imports:
        for cid in batch["course_ids"]:
            must_exist("课程", courses, cid, f"导入批次 {batch['id']}")
        for sid in batch["scenario_ids"]:
            must_exist("风险场景", scenarios, sid, f"导入批次 {batch['id']}")
    for cid in courses:
        if cid not in imported_courses:
            errors.append(f"课程 {cid} 未经导入批次登记")
    for sid in scenarios:
        if sid not in imported_scenarios:
            errors.append(f"风险场景 {sid} 未经导入批次登记")

    # ---- 机构与设施 ----
    def agency_country(agency_id: str) -> str | None:
        agency = agencies.get(agency_id)
        return agency["country_code"] if agency else None

    for fac in facilities.values():
        if must_exist("机构", agencies, fac["agency_id"], f"设施 {fac['id']}"):
            country = agency_country(fac["agency_id"])
            if country != fac["country_code"]:
                errors.append(f"设施 {fac['id']} 所属国家与管辖机构不一致")

    # ---- 差距 ----
    for gap in gaps.values():
        where = f"差距 {gap['id']}"
        must_exist("条款", clauses, gap["clause_id"], where)
        if must_exist("机构", agencies, gap["agency_id"], where):
            if agency_country(gap["agency_id"]) != gap["country_code"]:
                errors.append(f"{where} 所属国家与自评机构不一致")
        refs = gap.get("refs", {})
        for key, table in (
            ("translation_id", translations),
            ("corrigendum_id", corrigenda),
            ("national_rule_id", rules),
            ("course_id", courses),
            ("risk_scenario_id", scenarios),
            ("facility_id", facilities),
        ):
            must_exist(key, table, refs.get(key), where)
        if refs.get("facility_id"):
            fac = facilities[refs["facility_id"]]
            if fac["country_code"] != gap["country_code"]:
                errors.append(f"{where} 引用了他国设施 {fac['id']}")
        if gap["status"] == "closed" and "closure" not in gap:
            errors.append(f"{where} 已关闭但缺少关闭依据")

    # ---- 同行复核：必须来自差距所属国之外 ----
    for rv in reviews.values():
        where = f"同行复核 {rv['id']}"
        gap = gaps.get(rv["gap_id"])
        must_exist("差距", gaps, rv["gap_id"], where)
        if must_exist("复核机构", agencies, rv["reviewer_agency_id"], where):
            country = agency_country(rv["reviewer_agency_id"])
            if country != rv["reviewer_country_code"]:
                errors.append(f"{where} 复核机构国家与登记不一致")
            if country == PROGRAM_OFFICE_COUNTRY:
                errors.append(f"{where} 联合项目办公室不能担任同行复核人")
            if gap and country == gap["country_code"]:
                errors.append(f"{where} 复核人与差距同属 {country}，同行复核必须跨国")

    # ---- 证据 ----
    for ev in evidence.values():
        where = f"证据 {ev['id']}"
        gap = gaps.get(ev["gap_id"])
        must_exist("差距", gaps, ev["gap_id"], where)
        if must_exist("上传机构", agencies, ev["uploaded_by"], where) and gap:
            if agency_country(ev["uploaded_by"]) != gap["country_code"]:
                errors.append(f"{where} 只能由差距所属国机构补充")
        if ev.get("action_id"):
            act = actions.get(ev["action_id"])
            if act and gap and act["gap_id"] != gap["id"]:
                errors.append(f"{where} 关联的行动不属于同一差距")

    # ---- 行动与延期 ----
    for act in actions.values():
        where = f"行动 {act['id']}"
        must_exist("差距", gaps, act["gap_id"], where)
        must_exist("责任机构", agencies, act["owner_agency_id"], where)
        if act["status"] == "completed":
            if "completed_on" not in act:
                errors.append(f"{where} 已完成但缺少完成日期")
            elif _parse_day(act["completed_on"]) > _parse_day(act["due_on"]):
                errors.append(f"{where} 完成日期晚于当前期限，请补记延期")
    for ax in extensions.values():
        where = f"行动延期 {ax['id']}"
        act = actions.get(ax["action_id"])
        must_exist("行动", actions, ax["action_id"], where)
        if not ax.get("approver") or not ax.get("reason"):
            errors.append(f"{where} 缺少批准人或理由")
        prev_due = _parse_day(ax["previous_due_on"])
        new_due = _parse_day(ax["new_due_on"])
        if new_due <= prev_due:
            errors.append(f"{where} 新期限必须严格晚于原期限")
        if act and new_due != _parse_day(act["due_on"]):
            errors.append(f"{where} 新期限与行动当前期限 {act['due_on']} 不一致")

    # ---- 豁免：批准人 + 期限；过期不得关闭差距 ----
    for ex in exemptions.values():
        where = f"现场豁免 {ex['id']}"
        must_exist("差距", gaps, ex["gap_id"], where)
        if not ex.get("approver_name") or not ex.get("approver_role"):
            errors.append(f"{where} 缺少批准人")
        if _parse_day(ex["expiry_on"]) < _parse_day(ex["approved_on"]):
            errors.append(f"{where} 到期日早于批准日")

    # ---- 演练 ----
    for dr in drills.values():
        where = f"演练 {dr['id']}"
        gap = gaps.get(dr["gap_id"])
        act = actions.get(dr["action_id"])
        must_exist("差距", gaps, dr["gap_id"], where)
        must_exist("行动", actions, dr["action_id"], where)
        must_exist("风险场景", scenarios, dr["scenario_id"], where)
        if must_exist("验证机构", agencies, dr["verified_by"], where) and gap:
            if agency_country(dr["verified_by"]) == gap["country_code"]:
                errors.append(f"{where} 演练验证人必须由他国机构担任")
        if gap and act and act["gap_id"] != gap["id"]:
            errors.append(f"{where} 演练行动不属于该差距")
        if act and dr["result"] == "passed" and act["status"] == "completed":
            if _parse_day(dr["exercised_on"]) < _parse_day(act["completed_on"]):
                errors.append(f"{where} 演练日期早于行动完成日期，不能证明改进生效")

    # ---- 国家规则更新：只关闭确已解决的差距 ----
    for ru in rule_updates.values():
        where = f"规则更新 {ru['id']}"
        nr = rules.get(ru["national_rule_id"])
        must_exist("本国规范", rules, ru["national_rule_id"], where)
        if nr and nr["country_code"] != ru["country_code"]:
            errors.append(f"{where} 国家与规范所属国不一致")
        for gid in ru["closes_gap_ids"]:
            gap = gaps.get(gid)
            if not must_exist("差距", gaps, gid, where):
                continue
            if gap["country_code"] != ru["country_code"]:
                errors.append(f"{where} 不能关闭他国差距 {gid}")
                continue
            for reason in _closure_blockers(gap, data, basis="rule_update", ref_id=ru["id"]):
                errors.append(f"{where} 试图关闭 {gid}：{reason}")

    # ---- 差距关闭依据本身必须成立 ----
    for gap in gaps.values():
        closure = gap.get("closure")
        if gap["status"] == "closed" and closure:
            for reason in _closure_blockers(gap, data, basis=closure["basis"], ref_id=closure["ref_id"]):
                errors.append(f"差距 {gap['id']} 关闭无效：{reason}")

    return errors


def _confirmed_foreign_review(gap: dict, data: dict) -> dict | None:
    for rv in data["reviews"]:
        if (
            rv["gap_id"] == gap["id"]
            and rv["outcome"] == "confirmed"
            and rv["reviewer_country_code"] != gap["country_code"]
        ):
            return rv
    return None


def _closure_blockers(gap: dict, data: dict, *, basis: str, ref_id: str) -> list[str]:
    """差距按指定依据关闭时尚不满足的条件。"""
    blockers: list[str] = []
    if not any(ev["gap_id"] == gap["id"] for ev in data["evidence"]):
        blockers.append("缺少支撑证据")
    review = _confirmed_foreign_review(gap, data)
    if review is None:
        blockers.append("缺少他国同行复核的确认结论")

    if basis == "rule_update":
        ru = next((r for r in data["rule_updates"] if r["id"] == ref_id), None)
        if ru is None and ref_id != "__probe__":
            blockers.append("规则更新不存在")
        elif ru is not None and gap["country_code"] != ru["country_code"]:
            blockers.append("规则更新与差距分属不同国家")
        # 需演练验证的差距不能仅凭规则更新关闭
        for act in data["actions"]:
            if act["gap_id"] == gap["id"] and act["requires_drill"]:
                if not any(
                    d["gap_id"] == gap["id"]
                    and d["action_id"] == act["id"]
                    and d["result"] == "passed"
                    for d in data["drills"]
                ):
                    blockers.append(f"改进行动 {act['id']} 尚未通过实际演练")
                    break
    elif basis == "drill":
        dr = next((d for d in data["drills"] if d["id"] == ref_id), None)
        if dr is None:
            blockers.append("演练记录不存在")
        elif dr["gap_id"] != gap["id"]:
            blockers.append("演练记录不属于该差距")
        elif dr["result"] != "passed":
            blockers.append(f"演练结果为 {dr['result']}，未实际通过")
        else:
            act = next((a for a in data["actions"] if a["id"] == dr["action_id"]), None)
            if act is None or act["status"] != "completed":
                blockers.append("对应的改进行动尚未完成")
            elif _parse_day(dr["exercised_on"]) < _parse_day(act["completed_on"]):
                blockers.append("演练日期早于行动完成日期")
    else:
        blockers.append(f"不支持的关闭依据：{basis}（豁免不得用于关闭差距）")
    return blockers


class Registry:
    """差距库只读视图与工作流操作。"""

    def __init__(self, data: dict[str, Any], *, today: str | date | None = None, strict: bool = True):
        problems = integrity_errors(data)
        if strict and problems:
            raise ValueError("领域资料校验未通过：\n- " + "\n- ".join(problems))
        self.problems = problems
        self.data = data
        self.today = _parse_day(today) if isinstance(today, str) else (today or _parse_day(data["as_of"]))

    # ---- 读取 ----
    @classmethod
    def load(cls, path: str | Path, *, today: str | date | None = None, strict: bool = True) -> "Registry":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(data, today=today, strict=strict)

    def _all(self, collection: str) -> list[dict]:
        return self.data[collection]

    def _by_id(self, collection: str, rid: str) -> dict:
        for row in self.data[collection]:
            if row["id"] == rid:
                return row
        raise KeyError(f"{collection} 中无记录：{rid}")

    # ---- 条款对应视图 ----
    def clause_view(self, clause_id: str) -> dict[str, Any]:
        clause = self._by_id("standards_clauses", clause_id)
        translations = [t for t in self._all("translations") if t["clause_id"] == clause_id]
        current = next((t for t in translations if t["status"] == "current"), None)
        corrigenda = [
            er
            for er in self._all("translation_corrigenda")
            if er["translation_id"] in {t["id"] for t in translations}
        ]
        rules = [
            nr for nr in self._all("national_rules") if clause_id in nr["clause_ids"]
        ]
        return {
            "clause": clause,
            "current_translation": current,
            "translations": translations,
            "corrigenda": corrigenda,
            "national_rules": rules,
            "gaps": [g for g in self._all("gaps") if g["clause_id"] == clause_id],
        }

    def manager_clause_view(self, clause_id: str) -> dict[str, Any]:
        """管理者按条款核对：哪些差距仍影响服务一致性、改进是否经过演练。"""
        view = self.clause_view(clause_id)
        live_gaps = [g for g in view["gaps"] if g["status"] in _OPEN_GAP_STATUS]
        affecting = [g for g in live_gaps if g["affects_service_consistency"]]
        affected_countries = sorted({g["country_code"] for g in affecting})
        undrilled = []
        for gap in affecting:
            for act in self._actions_for_gap(gap["id"]):
                if act["requires_drill"] and not self._passed_drill(gap["id"], act["id"]):
                    undrilled.append({"gap_id": gap["id"], "action_id": act["id"]})
        expired = [
            ex for ex in self._all("exemptions")
            if ex["gap_id"] in {g["id"] for g in affecting} and self.exemption_state(ex) == "expired"
        ]
        overdue = [
            act["id"]
            for act in self._all("actions")
            if act["gap_id"] in {g["id"] for g in affecting} and self.is_overdue(act)
        ]
        return {
            "clause": view["clause"],
            "total_gaps": len(view["gaps"]),
            "live_gaps": live_gaps,
            "affecting_consistency": affecting,
            "affected_countries": affected_countries,
            "undrilled_actions": undrilled,
            "expired_exemptions": expired,
            "overdue_actions": overdue,
        }

    # ---- 译文勘误与冻结课程 ----
    def corrigendum_drift(self) -> list[dict[str, Any]]:
        """已发布但未进入任何冻结课程的勘误（旧资料不改写，须靠新版课程/增补页弥合）。"""
        drift = []
        for er in self._all("translation_corrigenda"):
            tr = self._by_id("translations", er["translation_id"])
            for cr in self._all("courses"):
                if tr["id"] not in cr.get("based_on_translation_ids", []):
                    continue
                if er["id"] in cr.get("includes_corrigenda_ids", []):
                    continue
                if _parse_day(cr["published_on"]) >= _parse_day(er["published_on"]):
                    continue  # 课程发布于勘误之后且未收录，属编制遗漏而非冻结快照
                linked = next(
                    (
                        g
                        for g in self._all("gaps")
                        if g.get("refs", {}).get("corrigendum_id") == er["id"]
                        and g.get("refs", {}).get("course_id") == cr["id"]
                    ),
                    None,
                )
                drift.append(
                    {
                        "corrigendum_id": er["id"],
                        "translation_id": tr["id"],
                        "course_id": cr["id"],
                        "frozen": cr["frozen"],
                        "gap_id": linked["id"] if linked else None,
                        "published_on": er["published_on"],
                        "course_published_on": cr["published_on"],
                    }
                )
        return drift

    # ---- 行动 / 延期 / 豁免 ----
    def _actions_for_gap(self, gap_id: str) -> list[dict]:
        return [a for a in self._all("actions") if a["gap_id"] == gap_id]

    def extensions_for_action(self, action_id: str) -> list[dict]:
        return sorted(
            (x for x in self._all("action_extensions") if x["action_id"] == action_id),
            key=lambda x: x["approved_on"],
        )

    def is_overdue(self, action: dict, *, on: str | date | None = None) -> bool:
        today = _parse_day(on) if isinstance(on, str) else (on or self.today)
        if action["status"] in _TERMINAL_ACTION_STATUS:
            return False
        return _parse_day(action["due_on"]) < today

    def exemption_state(self, exemption: dict, *, on: str | date | None = None) -> str:
        today = _parse_day(on) if isinstance(on, str) else (on or self.today)
        if exemption.get("revoked_on") and _parse_day(exemption["revoked_on"]) <= today:
            return "revoked"
        if _parse_day(exemption["expiry_on"]) < today:
            return "expired"
        if _parse_day(exemption["approved_on"]) > today:
            return "scheduled"
        return "active"

    def expired_exemptions(self, **kw) -> list[dict]:
        return [ex for ex in self._all("exemptions") if self.exemption_state(ex, **kw) == "expired"]

    def active_exemptions(self, **kw) -> list[dict]:
        return [ex for ex in self._all("exemptions") if self.exemption_state(ex, **kw) == "active"]

    def _passed_drill(self, gap_id: str, action_id: str) -> dict | None:
        return next(
            (
                d
                for d in self._all("drills")
                if d["gap_id"] == gap_id
                and d["action_id"] == action_id
                and d["result"] == "passed"
            ),
            None,
        )

    def drills_need_rerun(self) -> list[dict]:
        """行动要求演练、但尚无通过记录（含 partial/failed 后必须重练）。"""
        out = []
        for act in self._all("actions"):
            if act["requires_drill"] and not self._passed_drill(act["gap_id"], act["id"]):
                out.append(act)
        return out

    # ---- 国家隔离 ----
    def can_see_facility(self, facility: dict, viewer_country: str) -> bool:
        if not facility["sensitive"]:
            return True
        return viewer_country in (facility["country_code"], PROGRAM_OFFICE_COUNTRY)

    def can_see_evidence(self, evidence_row: dict, viewer_country: str) -> bool:
        if not evidence_row.get("restricted"):
            return True
        return viewer_country in (evidence_row["country_code"], PROGRAM_OFFICE_COUNTRY)

    def country_slice(self, viewer_country: str) -> dict[str, Any]:
        """按观察者国家裁剪后的资料副本：敏感设施与受限证据跨国不可见。"""
        clone = deepcopy(self.data)
        clone["facilities"] = [
            f for f in clone["facilities"] if self.can_see_facility(f, viewer_country)
        ]
        clone["evidence"] = [
            e for e in clone["evidence"] if self.can_see_evidence(e, viewer_country)
        ]
        hidden_facilities = {
            f["id"]
            for f in self.data["facilities"]
            if not self.can_see_facility(f, viewer_country)
        }
        if hidden_facilities:
            clone["gaps"] = [
                g
                for g in clone["gaps"]
                if g.get("refs", {}).get("facility_id") not in hidden_facilities
                or viewer_country == PROGRAM_OFFICE_COUNTRY
            ]
        clone["viewer_country"] = viewer_country
        return clone

    # ---- 关闭资格（供规则更新选择差距） ----
    def rule_closure_candidates(self, country_code: str) -> dict[str, list[str]]:
        eligible, blocked = [], []
        for gap in self._all("gaps"):
            if gap["country_code"] != country_code or gap["status"] not in _OPEN_GAP_STATUS:
                continue
            reasons = _closure_blockers(gap, self.data, basis="rule_update", ref_id="__probe__")
            reasons = [r for r in reasons if r != "规则更新不存在"]
            (eligible if not reasons else blocked).append(gap["id"])
        return {"eligible": eligible, "blocked": blocked}

    # ---- 工作流操作 ----
    def add_self_assessment(
        self,
        *,
        gap_id: str,
        clause_id: str,
        agency_id: str,
        kind: str,
        title: str,
        description: str,
        affects_service_consistency: bool,
        on: str | None = None,
        refs: dict | None = None,
    ) -> dict:
        if any(g["id"] == gap_id for g in self._all("gaps")):
            raise ValueError(f"差距标识已存在：{gap_id}")
        agency = self._by_id("agencies", agency_id)
        gap = {
            "id": gap_id,
            "clause_id": clause_id,
            "country_code": agency["country_code"],
            "agency_id": agency_id,
            "kind": kind,
            "title": title,
            "description": description,
            "affects_service_consistency": affects_service_consistency,
            "self_assessed_on": on or str(self.today),
            "status": "open",
        }
        if refs:
            gap["refs"] = refs
        self.data["gaps"].append(gap)
        return gap

    def add_peer_review(
        self,
        *,
        review_id: str,
        gap_id: str,
        reviewer_agency_id: str,
        outcome: str,
        comment: str,
        on: str | None = None,
    ) -> dict:
        gap = self._by_id("gaps", gap_id)
        agency = self._by_id("agencies", reviewer_agency_id)
        if agency["country_code"] == gap["country_code"]:
            raise ValueError("同行复核必须由差距所属国之外的成员机构承担")
        if agency["country_code"] == PROGRAM_OFFICE_COUNTRY:
            raise ValueError("联合项目办公室不能担任同行复核人")
        review = {
            "id": review_id,
            "gap_id": gap_id,
            "reviewer_agency_id": reviewer_agency_id,
            "reviewer_country_code": agency["country_code"],
            "reviewed_on": on or str(self.today),
            "outcome": outcome,
            "comment": comment,
        }
        self.data["reviews"].append(review)
        if outcome in {"confirmed", "changes_requested"} and gap["status"] == "open":
            gap["status"] = "in_review"
        return review

    def add_evidence(
        self,
        *,
        evidence_id: str,
        gap_id: str,
        kind: str,
        summary: str,
        uploaded_by: str,
        on: str | None = None,
        restricted: bool = False,
        action_id: str | None = None,
    ) -> dict:
        gap = self._by_id("gaps", gap_id)
        agency = self._by_id("agencies", uploaded_by)
        if agency["country_code"] != gap["country_code"]:
            raise ValueError("证据只能由差距所属国的成员机构补充")
        row = {
            "id": evidence_id,
            "gap_id": gap_id,
            "kind": kind,
            "country_code": gap["country_code"],
            "restricted": restricted,
            "uploaded_by": uploaded_by,
            "uploaded_on": on or str(self.today),
            "summary": summary,
        }
        if action_id:
            row["action_id"] = action_id
        self.data["evidence"].append(row)
        return row

    def extend_action(
        self,
        *,
        extension_id: str,
        action_id: str,
        new_due_on: str,
        approver: str,
        reason: str,
        approved_on: str | None = None,
    ) -> dict:
        action = self._by_id("actions", action_id)
        if not approver.strip() or not reason.strip():
            raise ValueError("行动延期必须记录批准人与理由")
        if _parse_day(new_due_on) <= _parse_day(action["due_on"]):
            raise ValueError(f"新期限 {new_due_on} 必须晚于当前期限 {action['due_on']}")
        extension = {
            "id": extension_id,
            "action_id": action_id,
            "previous_due_on": action["due_on"],
            "new_due_on": new_due_on,
            "approver": approver,
            "reason": reason,
            "approved_on": approved_on or str(self.today),
        }
        self.data["action_extensions"].append(extension)
        action["due_on"] = new_due_on
        return extension

    def grant_exemption(
        self,
        *,
        exemption_id: str,
        gap_id: str,
        scope: str,
        reason: str,
        approver_name: str,
        approver_role: str,
        expiry_on: str,
        approved_on: str | None = None,
    ) -> dict:
        self._by_id("gaps", gap_id)
        approved = approved_on or str(self.today)
        if not approver_name.strip() or not approver_role.strip():
            raise ValueError("现场豁免必须有批准人")
        if _parse_day(expiry_on) <= _parse_day(approved):
            raise ValueError("现场豁免必须给出晚于批准日的到期日")
        exemption = {
            "id": exemption_id,
            "gap_id": gap_id,
            "scope": scope,
            "reason": reason,
            "approver_name": approver_name,
            "approver_role": approver_role,
            "approved_on": approved,
            "expiry_on": expiry_on,
        }
        self.data["exemptions"].append(exemption)
        return exemption

    def record_drill(
        self,
        *,
        drill_id: str,
        gap_id: str,
        action_id: str,
        scenario_id: str,
        exercised_on: str,
        result: str,
        verified_by: str,
        summary: str,
    ) -> dict:
        gap = self._by_id("gaps", gap_id)
        action = self._by_id("actions", action_id)
        if action["gap_id"] != gap_id:
            raise ValueError("演练行动不属于该差距")
        verifier = self._by_id("agencies", verified_by)
        if verifier["country_code"] == gap["country_code"]:
            raise ValueError("演练验证必须由他国机构承担")
        drill = {
            "id": drill_id,
            "gap_id": gap_id,
            "action_id": action_id,
            "scenario_id": scenario_id,
            "exercised_on": exercised_on,
            "result": result,
            "verified_by": verified_by,
            "summary": summary,
        }
        self.data["drills"].append(drill)
        return drill

    def close_gap_with_drill(self, gap_id: str, *, closed_by: str, on: str | None = None) -> dict:
        gap = self._by_id("gaps", gap_id)
        passed = [
            d
            for d in self._all("drills")
            if d["gap_id"] == gap_id and d["result"] == "passed"
        ]
        if not passed:
            raise ValueError(f"差距 {gap_id} 尚无通过的实际演练，不能关闭")
        drill = max(passed, key=lambda d: d["exercised_on"])
        blockers = _closure_blockers(gap, self.data, basis="drill", ref_id=drill["id"])
        if blockers:
            raise ValueError(f"差距 {gap_id} 暂不能关闭：{'; '.join(blockers)}")
        gap["status"] = "closed"
        gap["affects_service_consistency"] = False
        gap["closure"] = {
            "basis": "drill",
            "ref_id": drill["id"],
            "closed_on": on or str(self.today),
            "closed_by": closed_by,
        }
        return gap

    def apply_rule_update(
        self,
        *,
        update_id: str,
        country_code: str,
        national_rule_id: str,
        title: str,
        effective_on: str,
        requested_gap_ids: Iterable[str],
        published_on: str | None = None,
        note: str = "",
    ) -> dict:
        """登记国家规则更新；只关闭确已解决的差距，其余原样保留并说明原因。"""
        self._by_id("national_rules", national_rule_id)
        closed, skipped = [], []
        for gid in requested_gap_ids:
            gap = self._by_id("gaps", gid)
            if gap["country_code"] != country_code:
                skipped.append((gid, "分属不同国家"))
                continue
            reasons = [
                r
                for r in _closure_blockers(gap, self.data, basis="rule_update", ref_id=update_id)
                if r not in {"规则更新不存在", "规则更新与差距分属不同国家"}
            ]
            if reasons:
                skipped.append((gid, "；".join(reasons)))
                continue
            closed.append(gid)

        update = {
            "id": update_id,
            "country_code": country_code,
            "national_rule_id": national_rule_id,
            "title": title,
            "effective_on": effective_on,
            "published_on": published_on or str(self.today),
            "closes_gap_ids": closed,
            "note": note,
        }
        self.data["rule_updates"].append(update)
        for gid in closed:
            gap = self._by_id("gaps", gid)
            gap["status"] = "closed"
            gap["affects_service_consistency"] = False
            gap["closure"] = {
                "basis": "rule_update",
                "ref_id": update_id,
                "closed_on": effective_on,
                "closed_by": "JPO",
            }
        update["skipped"] = [{"gap_id": gid, "reason": reason} for gid, reason in skipped]
        return update
