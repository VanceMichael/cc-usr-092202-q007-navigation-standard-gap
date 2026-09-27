# 航标标准落地差距库

比对国际航标标准与各成员机构实际流程，跟踪风险术语、设备能力与处置流程差距的整改落地。
培训证书数量不作为落地依据；库中只承认"自评 → 同行复核 → 证据 → 改进行动 → 实际演练 → 关闭"完整链路。

## 业务规则

1. **逐项对应**：每条差距关联国际标准条款（原文）、官方译文（含勘误版本链）、本国规则、现行流程/设备限制与改进行动。
2. **译文勘误不改写旧版资料**：勘误只新增译文版本；引用旧译文的培训资料保持原样，自动生成培训资料差距并标记需复训。
3. **规则更新只关闭确已解决的差距**：国家规则生效后，须同时满足生效日后复评符合、有解决证据、改进通过实际演练，差距才随规则更新关闭；其余差距保持打开并记录原因。
4. **现场豁免必须有期限和批准人**：到期自动失效（`expired_exemptions` 可查）；豁免有效期内即使整改完成也不得关闭差距。
5. **行动延期必须有理由和批准人**，新期限须晚于当前期限，延期链完整留痕。
6. **同行复核必须跨机构**（复核人不得是报告机构自身）；复核不通过退回自评。
7. **敏感设施信息按国家隔离**：设施明细仅同国成员机构可见，跨国查看与联合项目办公室视图整段屏蔽；敏感差距只接受同国机构复核。
8. **关闭前必须有实际演练**：演练结论为通过，且演练日期晚于改进行动完成日，差距才进入 `verified`；早于整改日的旧演练不予承认。

### 差距状态机

```
open → self_assessed → peer_reviewed → action_planned → in_progress
     → action_complete → verified → closed
peer_reviewed ──disagree──▶ self_assessed（退回补充）
closed ──发现问题（须填原因）──▶ reopened → self_assessed …
```

## 目录说明

- `contracts/domain.schema.json` — 共享领域资料基础契约（v1，保持兼容）。
- `contracts/gap-library.schema.json` — 差距库完整契约（v2）。
- `src/gap_library.py` — 核心模型：差距登记、自评、同行复核、证据、行动/延期、豁免、演练、规则更新、一致性报告。
- `src/importers.py` — 已有课程与风险场景样例导入、按场景自评生成差距（幂等）。
- `src/visibility.py` — 敏感设施信息的国家隔离视图与复核权限。
- `fixtures/imports/courses.json`、`fixtures/imports/risk_scenarios.json` — 课程与风险场景样例。
- `fixtures/gap_library.json` — 由种子脚本生成的完整样例库（7 条差距 / 3 条条款 / 2 次演练）。
- `scripts/seed_fixture.py` — 样例库生成脚本，同时演示完整工作流。

### 样例剧情

- 乙国机构对照"浓雾夜航浮标失效"场景自评出术语、设备、流程三类差距；设备差距含敏感设施信息。
- 术语差距经甲国机构跨国复核、一次有批准人的行动延期、演练通过后关闭。
- 设备差距持有批准人、到期日为 2026-12-31 的现场豁免，整改仍在进行。
- 甲国流程差距演练验证后，随国家规则更新关闭；同规则关联的旧版课程培训差距因未复训，规则更新时不予关闭。

## 使用示例

```python
from src.gap_library import load_library

lib = load_library("fixtures/gap_library.json")

# 管理者：按条款查看仍影响服务一致性的差距（含逾期、豁免到期、演练核对标记）
for row in lib.consistency_report(on_date="2026-09-27"):
    print(row["clause_id"], row["open_count"])

# 豁免到期清单
lib.expired_exemptions("2027-01-01")
```

```python
from src.visibility import Viewer, ROLE_MEMBER, view_gap

# 甲国机构查看乙国敏感差距：设施明细被屏蔽，差距影响仍可判读
view_gap(gap, Viewer("org-alpha", "CN", ROLE_MEMBER))
```

## 本地检查

```bash
python -m scripts.seed_fixture        # 重新生成样例库
python -m unittest discover -s tests  # 33 个用例覆盖全部业务规则
```

样例中不包含真实个人信息、账号、密钥或连接凭据；人名均为示例职务称呼。
