"""读取并检查共享领域资料（兼容 v1 简表与 v2 差距库）。"""

import json
from pathlib import Path

from src.registry import DOMAIN, SCHEMA_VERSION, integrity_errors

_REQUIRED_V1 = {"domain", "version", "sample_id", "actors", "facts", "constraints", "records"}


def load_records(path: Path) -> dict:
    """返回结构完整的领域资料。

    v2 资料按差距库规则做引用完整性检查；v1 简表保留原有最小校验。
    """
    value = json.loads(path.read_text(encoding="utf-8"))

    if value.get("version") == SCHEMA_VERSION:
        problems = integrity_errors(value)
        if problems:
            raise ValueError("领域资料校验未通过：\n- " + "\n- ".join(problems))
        return value

    if not _REQUIRED_V1.issubset(value):
        raise ValueError("领域资料缺少必要字段")
    if value["version"] < 1 or len(value["actors"]) < 2 or len(value["records"]) < 2:
        raise ValueError("领域资料内容不完整")
    if len({record["id"] for record in value["records"]}) != len(value["records"]):
        raise ValueError("领域记录标识重复")
    if value.get("domain") != DOMAIN:
        raise ValueError("领域标识不是 navigation-standard-gap")
    return value
