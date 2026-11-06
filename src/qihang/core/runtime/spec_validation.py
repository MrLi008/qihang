"""Spec 校验：同一份 JSON Schema，两条实现路径。

- 默认：内置轻量校验器（只依赖标准库，不新增硬依赖）；
- 可选：安装 `[validation]` extras（jsonschema）后升级为 Draft 2020-12 严格校验；
- 两条路径读取同一份 `qihang/schemas/agent_spec.schema.json`，接受/拒绝结果一致；
- 错误统一为中文可读文本，并给出字段路径（如 `subtasks.items[0].max_instances`）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from qihang.core.errors import SpecError
from qihang.paths import SCHEMAS_DIR

SCHEMA_PATH = SCHEMAS_DIR / "agent_spec.schema.json"

_CACHE: dict[str, Any] = {}

_TYPE_NAMES = {
    "object": "对象",
    "array": "数组",
    "string": "字符串",
    "integer": "整数",
    "number": "数字",
    "boolean": "布尔值",
    "null": "null",
}


@dataclass(frozen=True, slots=True)
class Issue:
    path: str
    message: str

    def format(self) -> str:
        return f"{self.path}：{self.message}" if self.path else self.message


def load_schema() -> dict[str, Any]:
    cached = _CACHE.get("schema")
    if cached is None:
        cached = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        _CACHE["schema"] = cached
    return cached


def jsonschema_available() -> bool:
    try:
        import jsonschema  # noqa: F401
    except ImportError:  # pragma: no cover - 取决于环境
        return False
    return True


def validate_spec_data(
    data: Any,
    *,
    engine: str = "auto",
    schema: Mapping[str, Any] | None = None,
) -> list[Issue]:
    """返回按字段路径排序的问题列表；engine=light/strict/auto。

    auto：jsonschema 可用则走严格路径，否则走轻量路径。
    """
    schema = schema or load_schema()
    if engine not in ("auto", "light", "strict"):
        raise ValueError(f"未知校验引擎: {engine}")
    if engine == "strict" or (engine == "auto" and jsonschema_available()):
        issues = _validate_with_jsonschema(data, schema)
    else:
        issues = _validate_light(data, schema, schema, "")
    return sorted(issues, key=lambda item: (item.path, item.message))


def ensure_spec_valid(
    data: Any,
    *,
    source: str = "<inline>",
    engine: str = "auto",
) -> None:
    issues = validate_spec_data(data, engine=engine)
    if not issues:
        return
    lines = "\n".join(f"  - {issue.format()}" for issue in issues)
    raise SpecError(f"{source} 校验失败：\n{lines}", code="SPEC_SCHEMA")


# --------------------------------------------------------------------------- 轻量实现
def _actual_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "布尔值"
    if isinstance(value, int):
        return "整数"
    if isinstance(value, float):
        return "数字"
    if isinstance(value, str):
        return "字符串"
    if isinstance(value, dict):
        return "对象"
    if isinstance(value, list):
        return "数组"
    return type(value).__name__


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else str(key)


def _index(path: str, index: int) -> str:
    return f"{path}[{index}]"


def _resolve_ref(root: Mapping[str, Any], ref: str) -> Mapping[str, Any]:
    if not ref.startswith("#/"):
        raise ValueError(f"轻量校验器只支持本地 $ref: {ref}")
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _validate_light(
    value: Any,
    schema: Mapping[str, Any],
    root: Mapping[str, Any],
    path: str,
) -> list[Issue]:
    if "$ref" in schema:
        return _validate_light(value, _resolve_ref(root, str(schema["$ref"])), root, path)

    issues: list[Issue] = []
    if "allOf" in schema:
        for sub in schema["allOf"]:
            issues.extend(_validate_light(value, sub, root, path))

    if "oneOf" in schema:
        branches = list(schema["oneOf"])
        branch_issues = [_validate_light(value, sub, root, path) for sub in branches]
        valid = sum(1 for item in branch_issues if not item)
        if valid == 0:
            best = min(branch_issues, key=len)
            issues.extend(best or [Issue(path, "取值不符合允许的任一结构")])
        elif valid > 1:
            issues.append(Issue(path, "取值同时符合多个互斥结构（oneOf）"))
        return issues

    if "type" in schema:
        expected = schema["type"]
        types = [expected] if isinstance(expected, str) else list(expected)
        if not any(_type_matches(value, item) for item in types):
            names = " 或 ".join(_TYPE_NAMES.get(item, item) for item in types)
            issues.append(Issue(path, f"类型错误：应为{names}，实际为{_actual_type(value)}"))
            return issues

    if "enum" in schema and value not in schema["enum"]:
        allowed = " / ".join(str(item) for item in schema["enum"])
        issues.append(Issue(path, f"取值非法：必须是 {allowed} 之一，实际为 {value!r}"))

    if isinstance(value, str):
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            issues.append(Issue(path, f"长度不足：至少 {schema['minLength']} 个字符"))
        if "pattern" in schema:
            import re

            if re.search(str(schema["pattern"]), value) is None:
                issues.append(Issue(path, f"格式不正确：不匹配模式 {schema['pattern']}"))

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            issues.append(Issue(path, f"取值过小：不能小于 {schema['minimum']}"))
        if "maximum" in schema and value > schema["maximum"]:
            issues.append(Issue(path, f"取值过大：不能大于 {schema['maximum']}"))

    if isinstance(value, dict):
        required = schema.get("required") or []
        for key in required:
            if key not in value:
                issues.append(Issue(_join(path, key), "缺少必填字段"))
        properties = schema.get("properties") or {}
        for key, sub in properties.items():
            if key in value:
                issues.extend(_validate_light(value[key], sub, root, _join(path, key)))
        additional = schema.get("additionalProperties", True)
        if additional is False:
            for key in value:
                if key not in properties:
                    allowed = "、".join(properties) or "（无）"
                    issues.append(
                        Issue(_join(path, key), f"未知字段（允许的字段：{allowed}）")
                    )
        elif isinstance(additional, Mapping):
            for key, item in value.items():
                if key not in properties:
                    issues.extend(_validate_light(item, additional, root, _join(path, key)))

    if isinstance(value, list):
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            issues.append(Issue(path, f"元素过少：至少 {schema['minItems']} 个"))
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            issues.append(Issue(path, f"元素过多：最多 {schema['maxItems']} 个"))
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                issues.extend(_validate_light(item, item_schema, root, _index(path, index)))
    return issues


# --------------------------------------------------------------------------- 严格实现
def _format_js_path(parts) -> str:
    out = ""
    for part in parts:
        if isinstance(part, int):
            out = f"{out}[{part}]"
        else:
            out = f"{out}.{part}" if out else str(part)
    return out


def _js_message(error) -> Issue:
    path = _format_js_path(list(error.absolute_path))
    validator = error.validator
    if validator == "required":
        missing = [key for key in error.validator_value if key not in error.instance]
        key = missing[0] if missing else "?"
        return Issue(_join(path, str(key)), "缺少必填字段")
    if validator == "additionalProperties":
        unexpected = getattr(error, "message", "").split("'")
        key = unexpected[1] if len(unexpected) > 2 else "?"
        return Issue(_join(path, key), "未知字段")
    if validator == "type":
        expected = error.validator_value
        types = [expected] if isinstance(expected, str) else list(expected)
        names = " 或 ".join(_TYPE_NAMES.get(item, item) for item in types)
        return Issue(path, f"类型错误：应为{names}，实际为{_actual_type(error.instance)}")
    if validator == "enum":
        allowed = " / ".join(str(item) for item in error.validator_value)
        return Issue(path, f"取值非法：必须是 {allowed} 之一，实际为 {error.instance!r}")
    if validator == "minimum":
        return Issue(path, f"取值过小：不能小于 {error.validator_value}")
    if validator == "maximum":
        return Issue(path, f"取值过大：不能大于 {error.validator_value}")
    if validator == "minLength":
        return Issue(path, f"长度不足：至少 {error.validator_value} 个字符")
    if validator == "minItems":
        return Issue(path, f"元素过少：至少 {error.validator_value} 个")
    if validator == "maxItems":
        return Issue(path, f"元素过多：最多 {error.validator_value} 个")
    if validator == "pattern":
        return Issue(path, f"格式不正确：不匹配模式 {error.validator_value}")
    if validator == "oneOf":
        return Issue(path, "取值不符合允许的任一结构")
    return Issue(path, f"校验失败（{validator}）：{error.message}")


def _validate_with_jsonschema(data: Any, schema: Mapping[str, Any]) -> list[Issue]:
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:  # pragma: no cover - engine=strict 显式请求时
        raise RuntimeError("未安装 jsonschema，无法使用严格校验路径") from exc

    validator = Draft202012Validator(schema)
    issues = [_js_message(error) for error in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))]
    return sorted(issues, key=lambda item: (item.path, item.message))
