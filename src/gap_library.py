"""航标标准落地差距库：核心领域模型与工作流。

设计要点：
- 国际条款、官方译文（含勘误版本）、本国规则、现行流程、设备限制、改进行动逐项对应；
- 译文勘误只发布新版本，不改写旧版培训资料，旧课对应差距保留并要求复训；
- 国家规则更新只关闭"证据 + 复评 + 实际演练"均确认解决的差距；
- 现场豁免必须有期限与批准人，到期自动失效；
- 自评、同行复核（跨机构）、证据补充、行动延期全程留痕；
- 关闭差距前必须有通过的实际演练记录。
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DOMAIN = "navigation-standard-gap"

GAP_CATEGORIES = (
    "terminology",       # 风险术语不一致
    "equipment",         # 设备能力限制
    "process",           # 处置流程差异
    "training_material", # 培训资料滞后于译文/标准
    "rule",              # 本国规则缺位或滞后
)

# 差距状态机
STATUS_OPEN = "open"
STATUS_SELF_ASSESSED = "self_assessed"
STATUS_PEER_REVIEWED = "peer_reviewed"
STATUS_ACTION_PLANNED = "action_planned"
STATUS_IN_PROGRESS = "in_progress"
STATUS_ACTION_COMPLETE = "action_complete"
STATUS_VERIFIED = "verified"      # 已通过实际演练核对
STATUS_CLOSED = "closed"
STATUS_REOPENED = "reopened"

OPEN_STATUSES = {
    STATUS_OPEN,
    STATUS_SELF_ASSESSED,
    STATUS_PEER_REVIEWED,
    STATUS_ACTION_PLANNED,
    STATUS_IN_PROGRESS,
    STATUS_ACTION_COMPLETE,
    STATUS_VERIFIED,
    STATUS_REOPENED,
}

_ALLOWED_TRANSITIONS = {
    STATUS_OPEN: {STATUS_SELF_ASSESSED},
    STATUS_REOPENED: {STATUS_SELF_ASSESSED},
    STATUS_SELF_ASSESSED: {STATUS_PEER_REVIEWED},
    STATUS_PEER_REVIEWED: {STATUS_ACTION_PLANNED, STATUS_SELF_ASSESSED},
    STATUS_ACTION_PLANNED: {STATUS_IN_PROGRESS},
    STATUS_IN_PROGRESS: {STATUS_ACTION_COMPLETE},
    STATUS_ACTION_COMPLETE: {STATUS_VERIFIED},
    STATUS_VERIFIED: {STATUS_CLOSED},
    STATUS_CLOSED: {STATUS_REOPENED},
}


class GapError(ValueError):
    """差距库业务规则冲突。"""


# ---------------------------------------------------------------------------
# 构造与校验
# ---------------------------------------------------------------------------

def new_library(version: int = 2) -> dict:    return {
        "domain": DOMAIN,
        "version": version,
        "organizations": [],
        "clauses": [],
        "gaps": [],
        "courses": [],
        "risk_scenarios": [],
        "rule_updates": [],
        "drills": [],
    }


def _today(on_date: str | date | None) -> date:
    if on_date is None:
        return date.today()
    if isinstance(on_date, date):
        return on_date
    return date.fromisoformat(on_date)


def validate_library(data: dict) -> dict:
    """结构性校验：引用完整、关键字段齐备、跨机构复核与豁免字段有效。"""
    if data.get("domain") != DOMAIN:
        raise GapError("领域标识不正确")
    if not isinstance(data.get("version"), int) or data["version"] < 2:
        raise GapError("差距库版本号无效")

    org_ids = {o["org_id"] for o in data.get("organizations", [])}
    clause_ids = {c["clause_id"] for c in data.get("clauses", [])}

    for clause in data.get("clauses", []):
        translation = clause.get("official_translation")
        if translation:
            versions = translation.get("versions", [])
            if not versions:
                raise GapError(f"条款 {clause['clause_id']} 官方译文缺少版本")
            if any("errata" not in v for v in versions):
                raise GapError(f"条款 {clause['clause_id']} 译文版本缺少勘误说明字段")

    gap_ids: set[str] = set()
    for gap in data.get("gaps", []):
        gid = gap["gap_id"]
        if gid in gap_ids:
            raise GapError(f"差距标识重复：{gid}")
        gap_ids.add(gid)
        if gap["gap_id"] and gap["clause_id"] not in clause_ids:
            raise GapError(f"差距 {gid} 引用了未知条款 {gap['clause_id']}")
        if gap.get("category") not in GAP_CATEGORIES:
            raise GapError(f"差距 {gid} 类别无效")
        if gap["status"] not in OPEN_STATUSES | {STATUS_CLOSED}:
            raise GapError(f"差距 {gid} 状态无效：{gap['status']}")
        reporter = gap.get("reporter_org")
        if reporter and reporter not in org_ids:
            raise GapError(f"差距 {gid} 报告机构未知：{reporter}")
        for review in gap.get("peer_reviews", []):
            if review["reviewer_org"] == reporter:
                raise GapError(f"差距 {gid} 同行复核人不得来自报告机构自身")
            if review["reviewer_org"] not in org_ids:
                raise GapError(f"差距 {gid} 复核机构未知：{review['reviewer_org']}")
        exemption = gap.get("exemption")
        if exemption:
            if not exemption.get("approver"):
                raise GapError(f"差距 {gid} 现场豁免缺少批准人")
            if not exemption.get("expiry"):
                raise GapError(f"差距 {gid} 现场豁免缺少到期日")
            date.fromisoformat(exemption["expiry"])
        action = gap.get("action")
        if action and action.get("extensions"):
            previous = action.get("due_date")
            for ext in action["extensions"]:
                if not ext.get("reason") or not ext.get("approver"):
                    raise GapError(f"差距 {gid} 行动延期缺少理由或批准人")
                if ext["new_due_date"] <= previous:
                    raise GapError(f"差距 {gid} 延期后的期限必须晚于原期限")
                previous = ext["new_due_date"]
        if gap["status"] in {STATUS_VERIFIED, STATUS_CLOSED} and not gap.get("drill_id"):
            raise GapError(f"差距 {gid} 已演练/关闭但缺少演练记录")

    for drill in data.get("drills", []):
        for gid in drill.get("scope", []):
            if gid not in gap_ids:
                raise GapError(f"演练 {drill['drill_id']} 引用了未知差距 {gid}")
    return data


def load_library(path: str | Path) -> "GapLibrary":
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return GapLibrary(data)


def save_library(lib: "GapLibrary", path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(lib.data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# 辅助查询
# ---------------------------------------------------------------------------

class GapLibrary:
    def __init__(self, data: dict | None = None):
        self.data = validate_library(deepcopy(data)) if data else new_library()

    # ---- 基础资料 ----

    def add_organization(self, org_id: str, name: str, country_code: str) -> dict:
        if any(o["org_id"] == org_id for o in self.data["organizations"]):
            raise GapError(f"机构已存在：{org_id}")
        org = {"org_id": org_id, "name": name, "country_code": country_code}
        self.data["organizations"].append(org)
        return org

    def add_clause(
        self,
        clause_id: str,
        standard: str,
        title: str,
        source_text: str,
        translation_version: str,
        translation_date: str,
        translation_text: str,
        national_rule_ids: list[str] | None = None,
    ) -> dict:
        if any(c["clause_id"] == clause_id for c in self.data["clauses"]):
            raise GapError(f"条款已存在：{clause_id}")
        clause = {
            "clause_id": clause_id,
            "standard": standard,
            "title": title,
            "source_text": source_text,
            "official_translation": {
                "current_version": translation_version,
                "versions": [
                    {
                        "version": translation_version,
                        "date": translation_date,
                        "text": translation_text,
                        "errata": "初版官方译文，无勘误",
                    }
                ],
            },
            "national_rule_ids": national_rule_ids or [],
        }
        self.data["clauses"].append(clause)
        return clause

    def record_translation_erratum(
        self,
        clause_id: str,
        new_version: str,
        effective_date: str,
        corrected_text: str,
        changes: str,
    ) -> dict:
        """登记官方译文勘误。

        只新增译文版本，绝不改写任何旧版文本或培训资料；引用该条款的
        旧版培训资料对应差距自动标记需要复训。
        """
        clause = self._clause(clause_id)
        translation = clause["official_translation"]
        if any(v["version"] == new_version for v in translation["versions"]):
            raise GapError(f"译文版本已存在：{new_version}")
        translation["versions"].append(
            {
                "version": new_version,
                "date": effective_date,
                "text": corrected_text,
                "errata": changes,
            }
        )
        translation["current_version"] = new_version

        for gap in self.data["gaps"]:
            if gap["clause_id"] != clause_id:
                continue
            material = gap.get("training_material")
            if not material:
                continue
            if material.get("translation_version") != new_version:
                material["retrain_required"] = True
                self._log(gap, effective_date, "joint-project-office",
                          "translation_erratum",
                          f"官方译文更新至 {new_version}，旧版培训资料不作改写，需复训")
        return translation

    # ---- 差距登记 ----

    def report_gap(
        self,
        gap_id: str,
        clause_id: str,
        reporter_org: str,
        category: str,
        title: str,
        description: str,
        service_impact: str,
        *,
        sensitive: bool = False,
        facility: dict | None = None,
        current_term: str | None = None,
        standard_term: str | None = None,
        equipment_limit: dict | None = None,
        current_process: str | None = None,
        training_material: dict | None = None,
        national_rule_id: str | None = None,
        opened_date: str | None = None,
    ) -> dict:
        if category not in GAP_CATEGORIES:
            raise GapError(f"差距类别无效：{category}")
        if any(g["gap_id"] == gap_id for g in self.data["gaps"]):
            raise GapError(f"差距已存在：{gap_id}")
        self._clause(clause_id)
        self._org(reporter_org)
        gap = {
            "gap_id": gap_id,
            "clause_id": clause_id,
            "reporter_org": reporter_org,
            "country_code": self._org(reporter_org)["country_code"],
            "category": category,
            "title": title,
            "description": description,
            "service_impact": service_impact,
            "sensitive": sensitive,
            "status": STATUS_OPEN,
            "evidence": [],
            "peer_reviews": [],
            "history": [],
        }
        if sensitive:
            # 敏感设施信息仅按国家隔离保存，不进入通用描述字段
            gap["facility"] = facility or {}
        if category == "terminology":
            gap["term_diff"] = {"current": current_term, "standard": standard_term}
        if category == "equipment":
            gap["equipment_limit"] = equipment_limit or {}
        if category == "process":
            gap["current_process"] = current_process
        if category == "training_material":
            material = dict(training_material or {})
            material.setdefault("retrain_required", False)
            material["material_content_immutable"] = True
            gap["training_material"] = material
            clause = self._clause(clause_id)
            current_version = clause["official_translation"]["current_version"]
            if material.get("translation_version") != current_version:
                material["retrain_required"] = True
        if category == "rule" and national_rule_id:
            gap["national_rule_id"] = national_rule_id
        self._log(gap, opened_date or date.today().isoformat(), reporter_org,
                  "reported", "差距登记")
        self.data["gaps"].append(gap)
        return gap

    # ---- 自评 ----

    def submit_self_assessment(
        self,
        gap_id: str,
        org_id: str,
        assessed_on: str,
        capability_level: str,
        standard_requirement: str,
        conformance: str,
        notes: str = "",
    ) -> dict:
        gap = self._gap(gap_id)
        self._require_org_country(gap, org_id)
        if gap["status"] not in {STATUS_OPEN, STATUS_REOPENED, STATUS_PEER_REVIEWED}:
            raise GapError(f"差距 {gap_id} 当前状态 {gap['status']} 不能提交自评")
        gap["self_assessment"] = {
            "org_id": org_id,
            "date": assessed_on,
            "capability_level": capability_level,
            "standard_requirement": standard_requirement,
            "conformance": conformance,
            "notes": notes,
        }
        if gap["status"] != STATUS_PEER_REVIEWED:
            self._transition(gap, STATUS_SELF_ASSESSED)
        self._log(gap, assessed_on, org_id, "self_assessment", f"自评结论：{conformance}")
        return gap

    # ---- 同行复核 ----

    def submit_peer_review(
        self,
        gap_id: str,
        reviewer_org: str,
        reviewed_on: str,
        verdict: str,
        comments: str,
    ) -> dict:
        """跨机构同行复核。复核机构不得是报告机构自身。"""
        gap = self._gap(gap_id)
        if reviewer_org == gap["reporter_org"]:
            raise GapError("同行复核必须由报告机构以外的成员机构执行")
        reviewer = self._org(reviewer_org)
        if gap.get("sensitive") and reviewer["country_code"] != gap["country_code"]:
            raise GapError("敏感设施差距只接受同国成员机构复核")
        if gap["status"] not in {STATUS_SELF_ASSESSED, STATUS_PEER_REVIEWED}:
            raise GapError(f"差距 {gap_id} 尚未完成自评，不能进入同行复核")
        if verdict not in {"agree", "disagree", "escalate"}:
            raise GapError("复核结论无效")
        review = {
            "reviewer_org": reviewer_org,
            "date": reviewed_on,
            "verdict": verdict,
            "comments": comments,
        }
        gap["peer_reviews"].append(review)
        if verdict == "agree":
            self._transition(gap, STATUS_PEER_REVIEWED)
        elif verdict == "disagree":
            # 复核不通过：退回自评环节补充材料，复核意见留痕
            if gap["status"] == STATUS_PEER_REVIEWED:
                self._transition(gap, STATUS_SELF_ASSESSED)
        self._log(gap, reviewed_on, reviewer_org, "peer_review",
                  f"同行复核结论：{verdict}")
        return gap

    # ---- 证据补充 ----

    def add_evidence(self, gap_id: str, evidence_type: str, ref: str,
                     summary: str, added_by: str, added_on: str) -> dict:
        gap = self._gap(gap_id)
        self._org(added_by)
        item = {
            "type": evidence_type,   # document | photo | log | certificate | drill_report
            "ref": ref,
            "summary": summary,
            "added_by": added_by,
            "date": added_on,
        }
        gap["evidence"].append(item)
        self._log(gap, added_on, added_by, "evidence_added", f"补充证据：{evidence_type}")
        return item

    # ---- 改进行动 ----

    def plan_action(self, gap_id: str, description: str, owner_org: str,
                    due_date: str, planned_on: str) -> dict:
        gap = self._gap(gap_id)
        if gap["status"] != STATUS_PEER_REVIEWED:
            raise GapError(f"差距 {gap_id} 未通过同行复核，不能排定改进行动")
        self._require_org_country(gap, owner_org)
        gap["action"] = {
            "description": description,
            "owner_org": owner_org,
            "due_date": due_date,
            "extensions": [],
        }
        self._transition(gap, STATUS_ACTION_PLANNED)
        self._log(gap, planned_on, owner_org, "action_planned", f"期限 {due_date}")
        return gap["action"]

    def start_action(self, gap_id: str, started_on: str) -> None:
        gap = self._gap(gap_id)
        self._transition(gap, STATUS_IN_PROGRESS)
        self._log(gap, started_on, gap["action"]["owner_org"], "action_started", "")

    def complete_action(self, gap_id: str, completed_on: str,
                        resolution_summary: str) -> None:
        gap = self._gap(gap_id)
        if gap["status"] != STATUS_IN_PROGRESS:
            raise GapError(f"差距 {gap_id} 行动尚未实施")
        gap["action"]["completed_date"] = completed_on
        gap["action"]["resolution_summary"] = resolution_summary
        self._transition(gap, STATUS_ACTION_COMPLETE)
        self._log(gap, completed_on, gap["action"]["owner_org"],
                  "action_completed", resolution_summary)

    def extend_action(self, gap_id: str, new_due_date: str, reason: str,
                      approver: str, extended_on: str) -> dict:
        """行动延期：必须给出理由和批准人，新期限必须晚于原期限。"""
        gap = self._gap(gap_id)
        action = gap.get("action")
        if not action:
            raise GapError(f"差距 {gap_id} 尚无改进行动")
        current_due = (action["extensions"][-1]["new_due_date"]
                       if action["extensions"] else action["due_date"])
        if new_due_date <= current_due:
            raise GapError("延期后的期限必须晚于当前期限")
        if not reason.strip() or not approver.strip():
            raise GapError("行动延期必须填写理由与批准人")
        extension = {
            "new_due_date": new_due_date,
            "reason": reason,
            "approver": approver,
            "date": extended_on,
        }
        action["extensions"].append(extension)
        self._log(gap, extended_on, approver, "action_extended",
                  f"延期至 {new_due_date}：{reason}")
        return extension

    # ---- 现场豁免 ----

    def grant_exemption(self, gap_id: str, approver: str, granted_on: str,
                        expiry: str, scope_text: str) -> dict:
        """现场豁免：必须有批准人和到期日。"""
        gap = self._gap(gap_id)
        if not approver.strip():
            raise GapError("现场豁免必须登记批准人")
        if not expiry:
            raise GapError("现场豁免必须设定期限")
        if date.fromisoformat(expiry) <= date.fromisoformat(granted_on):
            raise GapError("豁免到期日必须晚于批准日")
        existing = gap.get("exemption")
        exemption = {
            "approver": approver,
            "granted_on": granted_on,
            "expiry": expiry,
            "scope": scope_text,
            "sequence": (existing["sequence"] + 1) if existing else 1,
            "status": "active",
        }
        gap["exemption"] = exemption
        self._log(gap, granted_on, approver, "exemption_granted",
                  f"豁免至 {expiry}")
        return exemption

    def exemption_active(self, gap: dict, on_date: str | date | None = None) -> bool:
        exemption = gap.get("exemption")
        if not exemption or exemption.get("status") != "active":
            return False
        return _today(on_date) <= date.fromisoformat(exemption["expiry"])

    def expired_exemptions(self, on_date: str | date | None = None) -> list[dict]:
        """到期未续的豁免：差距继续影响服务一致性，需重新处置。"""
        on = _today(on_date)
        result = []
        for gap in self.data["gaps"]:
            exemption = gap.get("exemption")
            if not exemption or exemption.get("status") != "active":
                continue
            if on > date.fromisoformat(exemption["expiry"]):
                result.append(gap)
        return result

    # ---- 实际演练核对 ----

    def record_drill(self, drill_id: str, org_id: str, drill_date: str,
                     scope: list[str], result: str, evidence_ref: str,
                     scenario_ref: str = "") -> dict:
        """登记实际演练。仅"通过"且时间晚于改进行动完成日，差距方可进入 verified。"""
        if any(d["drill_id"] == drill_id for d in self.data["drills"]):
            raise GapError(f"演练记录已存在：{drill_id}")
        if result not in {"pass", "fail"}:
            raise GapError("演练结论无效")
        drill = {
            "drill_id": drill_id,
            "org_id": org_id,
            "date": drill_date,
            "scope": list(scope),
            "result": result,
            "evidence_ref": evidence_ref,
            "scenario_ref": scenario_ref,
        }
        self.data["drills"].append(drill)
        for gid in scope:
            gap = self._gap(gid)
            self._log(gap, drill_date, org_id, "drill_recorded",
                      f"演练 {drill_id} 结论：{result}")
            if result != "pass":
                continue
            if gap["status"] != STATUS_ACTION_COMPLETE:
                raise GapError(
                    f"差距 {gid} 状态为 {gap['status']}，"
                    "改进行动未完成，演练不能作为关闭依据")
            completed = gap["action"].get("completed_date")
            if completed and drill_date < completed:
                raise GapError(f"差距 {gid} 演练日期早于改进行动完成日，需重新演练")
            gap["drill_id"] = drill_id
            self._transition(gap, STATUS_VERIFIED)
        return drill

    def close_gap(self, gap_id: str, closed_by: str, closed_on: str) -> None:
        gap = self._gap(gap_id)
        if gap["status"] != STATUS_VERIFIED:
            raise GapError("只有通过实际演练核对的差距才能关闭")
        if self.exemption_active(gap, closed_on):
            raise GapError("差距仍在豁免期内，应在豁免事项真正整改后再关闭")
        gap["closed"] = {"by": closed_by, "date": closed_on}
        self._transition(gap, STATUS_CLOSED)
        self._log(gap, closed_on, closed_by, "closed", "差距经演练核对后关闭")

    def reopen_gap(self, gap_id: str, reason: str, reopened_by: str,
                  reopened_on: str) -> None:
        gap = self._gap(gap_id)
        if not reason.strip():
            raise GapError("重新打开差距必须说明原因")
        if gap["status"] == STATUS_CLOSED:
            self._transition(gap, STATUS_REOPENED)
        self._log(gap, reopened_on, reopened_by, "reopened", reason)

    # ---- 国家规则更新 ----

    def apply_rule_update(
        self,
        update_id: str,
        national_rule_id: str,
        country_code: str,
        effective_date: str,
        reassessments: dict[str, dict],
        applied_by: str = "joint-project-office",
    ) -> dict:
        """国家规则更新：只关闭确已解决的差距。

        关闭条件（缺一不可）：
        1. 差距关联本次更新的本国规则且属于同一国家；
        2. 规则生效日后完成复评，结论为符合；
        3. 已有解决证据；
        4. 已通过实际演练（verified）。
        其余差距保持打开，并记录"规则已更新但差距未解决"。
        """
        if any(u["update_id"] == update_id for u in self.data["rule_updates"]):
            raise GapError(f"规则更新记录已存在：{update_id}")
        update = {
            "update_id": update_id,
            "national_rule_id": national_rule_id,
            "country_code": country_code,
            "effective_date": effective_date,
            "closed_gaps": [],
            "remaining_gaps": [],
        }
        candidates = [
            g for g in self.data["gaps"]
            if g.get("national_rule_id") == national_rule_id
            and g["country_code"] == country_code
            and g["status"] != STATUS_CLOSED
        ]
        for gap in candidates:
            reassessment = reassessments.get(gap["gap_id"])
            eligible, reason = self._resolution_confirmed(
                gap, reassessment, effective_date)
            self._log(gap, effective_date, applied_by, "rule_update_evaluated",
                      f"规则 {national_rule_id} 更新：{reason}")
            if eligible:
                gap["closed"] = {"by": applied_by, "date": effective_date,
                                 "rule_update": update_id}
                self._transition(gap, STATUS_CLOSED)
                update["closed_gaps"].append(gap["gap_id"])
                self._log(gap, effective_date, applied_by, "closed",
                          f"规则更新后经复评与演练确认解决，随 {update_id} 关闭")
            else:
                update["remaining_gaps"].append(
                    {"gap_id": gap["gap_id"], "reason": reason})
        self.data["rule_updates"].append(update)
        return update

    @staticmethod
    def _resolution_confirmed(gap: dict, reassessment: dict | None,
                              effective_date: str) -> tuple[bool, str]:
        if reassessment is None:
            return False, "缺少规则生效后的复评记录"
        if reassessment.get("date", "") < effective_date:
            return False, "复评日期早于规则生效日"
        if reassessment.get("conformance") != "符合":
            return False, "复评结论未确认符合"
        if not gap.get("evidence"):
            return False, "缺少解决证据"
        if gap["status"] != STATUS_VERIFIED:
            return False, "改进尚未通过实际演练核对"
        return True, "复评、证据与演练均确认解决"

    # ---- 管理视图 ----

    def gaps_by_clause(self, clause_id: str, *, include_closed: bool = False) -> list[dict]:
        gaps = [g for g in self.data["gaps"] if g["clause_id"] == clause_id]
        if not include_closed:
            gaps = [g for g in gaps if g["status"] != STATUS_CLOSED]
        return gaps

    def consistency_report(self, *, on_date: str | date | None = None) -> list[dict]:
        """按条款列出仍影响服务一致性的差距，并标注演练核对情况。"""
        on = _today(on_date)
        report = []
        for clause in self.data["clauses"]:
            entries = []
            for gap in self.gaps_by_clause(clause["clause_id"]):
                if not gap.get("service_impact"):
                    continue
                action = gap.get("action") or {}
                due = (action["extensions"][-1]["new_due_date"]
                       if action.get("extensions") else action.get("due_date"))
                overdue = bool(due and on > date.fromisoformat(due)
                               and gap["status"] != STATUS_VERIFIED)
                exemption_expired = (
                    gap.get("exemption") is not None
                    and not self.exemption_active(gap, on)
                )
                entries.append({
                    "gap_id": gap["gap_id"],
                    "country_code": gap["country_code"],
                    "category": gap["category"],
                    "title": gap["title"],
                    "status": gap["status"],
                    "service_impact": gap["service_impact"],
                    "due_date": due,
                    "overdue": overdue,
                    "exemption_expired": exemption_expired,
                    "drill_verified": gap["status"] == STATUS_VERIFIED
                                      or bool(gap.get("drill_id")),
                    "sensitive": gap["sensitive"],
                })
            if entries:
                report.append({
                    "clause_id": clause["clause_id"],
                    "standard": clause["standard"],
                    "title": clause["title"],
                    "open_count": len(entries),
                    "gaps": entries,
                })
        return report

    # ---- 内部工具 ----

    def _clause(self, clause_id: str) -> dict:
        for clause in self.data["clauses"]:
            if clause["clause_id"] == clause_id:
                return clause
        raise GapError(f"未知条款：{clause_id}")

    def _org(self, org_id: str) -> dict:
        for org in self.data["organizations"]:
            if org["org_id"] == org_id:
                return org
        raise GapError(f"未知机构：{org_id}")

    def _gap(self, gap_id: str) -> dict:
        for gap in self.data["gaps"]:
            if gap["gap_id"] == gap_id:
                return gap
        raise GapError(f"未知差距：{gap_id}")

    def _require_org_country(self, gap: dict, org_id: str) -> None:
        org = self._org(org_id)
        if org["country_code"] != gap["country_code"]:
            raise GapError("成员机构只能处置本国差距")

    @staticmethod
    def _transition(gap: dict, new_status: str) -> None:
        current = gap["status"]
        if new_status == current:
            return
        if new_status not in _ALLOWED_TRANSITIONS.get(current, set()):
            raise GapError(
                f"差距 {gap['gap_id']} 不允许从 {current} 转为 {new_status}")
        gap["status"] = new_status

    @staticmethod
    def _log(gap: dict, when: str, actor: str, action: str, detail: str) -> None:
        gap["history"].append(
            {"date": when, "actor": actor, "action": action, "detail": detail})
