"""差距库管理者命令行：按条款核对差距、演练、豁免与勘误漂移。

用法示例：
  python -m src.cli clauses
  python -m src.cli clause C-5200
  python -m src.cli exemptions
  python -m src.cli undrilled
  python -m src.cli drift
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.registry import PROGRAM_OFFICE_COUNTRY, Registry

DEFAULT_DATA = Path("fixtures/context.json")


def _print_header(title: str) -> None:
    print(f"\n=== {title} ===")


def cmd_clauses(reg: Registry, _args) -> None:
    _print_header("按条款汇总（仍影响服务一致性的差距）")
    for clause in reg._all("standards_clauses"):
        view = reg.manager_clause_view(clause["id"])
        flag = "！" if view["affecting_consistency"] else " "
        countries = ",".join(view["affected_countries"]) or "-"
        print(
            f"{flag} {clause['id']} [{clause['consistency_aspect']}] "
            f"{clause['number']} {clause['title']} | "
            f"未决差距 {len(view['live_gaps'])} 影响一致性 {len(view['affecting_consistency'])} "
            f"国家 {countries}"
        )


def cmd_clause(reg: Registry, args) -> None:
    view = reg.manager_clause_view(args.clause_id)
    clause = view["clause"]
    _print_header(f"条款 {clause['id']} {clause['number']} {clause['title']}")
    print(f"标准：{clause['standard']}（{clause['status']}）")
    print(f"要求：{clause['text_summary']}")

    detail = reg.clause_view(args.clause_id)
    if detail["current_translation"]:
        tr = detail["current_translation"]
        print(f"\n现行官方译文（{tr['id']} v{tr['version']}，{tr['published_on']}）：{tr['text']}")
    if detail["corrigenda"]:
        print("译文勘误：")
        for er in detail["corrigenda"]:
            print(f"  - {er['id']} [{er['severity']}] {er['published_on']}："
                  f"“{er['original_reading']}”→“{er['corrected_reading']}”")
    if detail["national_rules"]:
        print("对应本国规范：")
        for nr in detail["national_rules"]:
            print(f"  - {nr['id']}（{nr['country_code']}，{nr['effective_on']} 生效，{nr['status']}）{nr['title']}")

    print(f"\n差距总数 {view['total_gaps']}，未决 {len(view['live_gaps'])}，"
          f"仍影响服务一致性 {len(view['affecting_consistency'])}，国家：{','.join(view['affected_countries']) or '无'}")
    for gap in view["live_gaps"]:
        mark = "影响一致性" if gap["affects_service_consistency"] else "不影响"
        print(f"  [{gap['status']}] {gap['id']} ({gap['country_code']}/{gap['kind']}) {gap['title']} — {mark}")
    if view["undrilled_actions"]:
        print("改进尚未通过实际演练：")
        for item in view["undrilled_actions"]:
            print(f"  - 差距 {item['gap_id']} 的行动 {item['action_id']}")
    if view["overdue_actions"]:
        print(f"已逾期行动：{', '.join(view['overdue_actions'])}")
    if view["expired_exemptions"]:
        for ex in view["expired_exemptions"]:
            print(f"  ! 豁免 {ex['id']} 已于 {ex['expiry_on']} 到期（批准人：{ex['approver_name']}/{ex['approver_role']}）")


def cmd_exemptions(reg: Registry, _args) -> None:
    _print_header("现场豁免（必须有批准人与期限）")
    for ex in reg._all("exemptions"):
        state = reg.exemption_state(ex)
        print(f"  {ex['id']} 差距 {ex['gap_id']} 状态 {state} "
              f"批准 {ex['approved_on']} 到期 {ex['expiry_on']} "
              f"批准人 {ex['approver_name']}（{ex['approver_role']}）范围：{ex['scope']}")


def cmd_undrilled(reg: Registry, _args) -> None:
    _print_header("需演练验证但尚无通过记录的改进行动")
    for act in reg.drills_need_rerun():
        overdue = "（已逾期）" if reg.is_overdue(act) else ""
        print(f"  {act['id']} 差距 {act['gap_id']} 期限 {act['due_on']} 状态 {act['status']} {act['title']}{overdue}")


def cmd_drift(reg: Registry, _args) -> None:
    _print_header("勘误—冻结课程漂移（旧版资料不改写，需新课程/增补页弥合）")
    for item in reg.corrigendum_drift():
        linked = f"已登记差距 {item['gap_id']}" if item["gap_id"] else "尚未登记差距"
        print(f"  勘误 {item['corrigendum_id']}（{item['published_on']}）未进入 "
              f"{item['course_id']}（发布于 {item['course_published_on']}，frozen={item['frozen']}）— {linked}")


def cmd_country(reg: Registry, args) -> None:
    _print_header(f"国家隔离视图：观察者 {args.country}")
    sliced = reg.country_slice(args.country)
    print(f"可见设施 {len(sliced['facilities'])} 个：")
    for fac in sliced["facilities"]:
        tag = "敏感" if fac["sensitive"] else "一般"
        print(f"  - {fac['id']} [{tag}] {fac['label']}（{fac['country_code']}）")
    print(f"可见证据 {len(sliced['evidence'])} 份；可见差距 {len(sliced['gaps'])} 项。")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="航标标准落地差距库管理者工具")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="领域资料 JSON 路径")
    parser.add_argument("--today", help="覆盖当前日期（YYYY-MM-DD），默认取资料 as_of")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("clauses", help="按条款汇总").set_defaults(func=cmd_clauses)
    p_clause = sub.add_parser("clause", help="单条款管理者视图")
    p_clause.add_argument("clause_id")
    p_clause.set_defaults(func=cmd_clause)
    sub.add_parser("exemptions", help="列出豁免与到期状态").set_defaults(func=cmd_exemptions)
    sub.add_parser("undrilled", help="未通过演练的改进行动").set_defaults(func=cmd_undrilled)
    sub.add_parser("drift", help="勘误与冻结课程漂移").set_defaults(func=cmd_drift)
    p_country = sub.add_parser("country", help="按国家隔离的裁剪视图")
    p_country.add_argument("country", help=f"国家代码；{PROGRAM_OFFICE_COUNTRY} 为项目办公室全量视图")
    p_country.set_defaults(func=cmd_country)

    args = parser.parse_args(argv)
    reg = Registry.load(args.data, today=args.today)
    args.func(reg, args)


if __name__ == "__main__":
    main()
