"""敏感设施信息的国家隔离。

差距本身（条款、术语、处置流程差异）可供联合项目办公室与同行按权限查看；
但设施位置、布设细节、设备弱点等敏感信息仅对同国成员机构开放，
跨国家查看时只保留"存在敏感差距"的标记，具体字段整段屏蔽。
"""

from __future__ import annotations

from copy import deepcopy

# 联合项目办公室可跨国查看差距对服务一致性的影响，但不获取设施敏感明细
ROLE_JPO = "joint_project_office"
ROLE_MEMBER = "member_organization"

SENSITIVE_KEYS = ("facility",)


class Viewer:
    def __init__(self, org_id: str, country_code: str,
                 role: str = ROLE_MEMBER):
        if role not in {ROLE_JPO, ROLE_MEMBER}:
            raise ValueError("查看者角色无效")
        self.org_id = org_id
        self.country_code = country_code
        self.role = role


def can_see_facility(gap: dict, viewer: Viewer) -> bool:
    return (viewer.country_code == gap["country_code"]
            and viewer.role == ROLE_MEMBER)


def view_gap(gap: dict, viewer: Viewer) -> dict:
    """返回按查看者国家/角色过滤后的差距视图。"""
    result = deepcopy(gap)
    if result.get("sensitive") and not can_see_facility(result, viewer):
        for key in SENSITIVE_KEYS:
            result.pop(key, None)
        result["facility_redacted"] = True
    return result


def visible_gaps(gaps: list[dict], viewer: Viewer) -> list[dict]:
    return [view_gap(gap, viewer) for gap in gaps]


def view_report(report: list[dict], viewer: Viewer) -> list[dict]:
    """对一致性报告逐差距套用国家隔离。"""
    masked = deepcopy(report)
    for clause in masked:
        for entry in clause["gaps"]:
            gap_id = entry["gap_id"]
            # 报告条目本身不含设施明细，仅补充是否已屏蔽的提示
            entry["facility_redacted"] = False
            if entry.get("sensitive"):
                same_country = viewer.country_code == entry["country_code"]
                if not (same_country and viewer.role == ROLE_MEMBER):
                    entry["facility_redacted"] = True
    return masked


def can_peer_review(gap: dict, viewer: Viewer) -> bool:
    """同行复核可跨国进行；敏感设施差距只接受同国机构复核。"""
    if not gap.get("sensitive"):
        return True
    return viewer.country_code == gap["country_code"]
