# 航标标准落地差距库

比对国际航标标准与各成员机构实际流程，跟踪差距改进。目标是让各地导助航服务**趋于一致**——不以证书数量判定落地，而以条款级证据、同行复核与实际演练为准。

## 业务事实

- 培训由交通运输部海事局与国际航标组织联合主办
- 项目新增风险管理专项培训
- 历史学员来自四十多个国家和地区
- 联合项目办公室（JPO）维护条款与各成员机构实施情况的逐项对应差距库

## 模型（`contracts/domain.schema.json`，v2）

- `standards_clauses` / `translations` / `translation_corrigenda`：国际条款、官方译文与**只追加**的勘误
- `national_rules` / `rule_updates`：本国规范及其更新
- `courses` / `risk_scenarios` / `imports`：已导入课程与风险场景；课程按发布时快照冻结
- `agencies` / `facilities`：成员机构与现场设施（`sensitive` 设施按国家隔离）
- `gaps`：逐项差距（条款 × 国家 × 机构），带自评、状态与关闭依据
- `reviews` / `evidence`：异国同行复核与可持续补充的证据（可标记受限）
- `actions` / `action_extensions`：改进行动与延期留痕
- `exemptions`：现场豁免（必须有批准人与到期日）
- `drills`：实际演练记录

## 固化的业务规则（见 `src/registry.py`）

1. **逐项对应**：条款原文、官方译文、勘误、本国规范、现行流程、设备限制、改进行动通过差距记录互相链接，引用完整性受校验。
2. **勘误不回溯**：已冻结旧版培训资料不被改写；`corrigendum_drift()` 列出“勘误已发布但旧课程未纳入”的漂移项，由新课程或增补页弥合。
3. **自评 → 同行复核 → 证据**：复核人必须来自差距所属国**之外**的成员机构（JPO 不能兼任）；证据只能由所属国机构补充，可多次补充。
4. **行动延期**：必须记录批准人、理由，且新期限严格晚于原期限。
5. **现场豁免**：必须有批准人（姓名+职务）与到期日；到期自动判为 `expired`；豁免**不能**作为关闭差距的依据。
6. **规则更新选择性关闭**：只关闭同国、证据齐备、异国复核确认，且不依赖演练验证的差距；其余原样保留并返回原因。
7. **演练核对**：要求演练的行动必须有“通过”的实际演练（演练日期不早于行动完成日、由他国机构验证）才能关闭差距；`partial`/`failed` 必须重练。
8. **国家隔离**：敏感设施与受限证据对他国成员机构不可见，挂接敏感设施的差距在跨国视图中一并隐藏；JPO（国家代码 `XN`）持有全量管理者视图。

## 管理者命令行

```bash
python -m src.cli clauses            # 按条款查看哪些差距仍影响服务一致性
python -m src.cli clause C-5200      # 单条款：译文/勘误/规范/差距/演练/豁免
python -m src.cli exemptions         # 豁免与过期状态
python -m src.cli undrilled          # 改进已完成但未通过实际演练
python -m src.cli drift              # 勘误—冻结课程漂移
python -m src.cli country MY         # 某成员机构的国家隔离视图
python -m src.cli country XN         # 项目办公室全量视图
```

可用 `--today YYYY-MM-DD` 覆盖当前日期，便于核对豁免到期与行动逾期。

## 目录说明

- `contracts/domain.schema.json` 定义共享资料字段与约束（JSON Schema 2020-12）。
- `fixtures/context.json` 提供不含真实个人信息的虚构样例（3 门课程、3 个风险场景、3 国 9 项差距，覆盖开放/复核中/关闭、过期豁免、延期行动、部分通过演练等情形）。
- `src/registry.py` 为差距库领域规则与视图；`src/records.py` 保留 v1/v2 兼容读取；`src/cli.py` 为管理者命令行。

## 本地检查

```bash
python -m unittest discover -s tests   # 39 个用例：完整性、隔离、工作流与关闭规则
```

安装可选依赖 `jsonschema` 后，测试还会校验样例与契约一致。样例中不包含账号、密钥或连接凭据。
