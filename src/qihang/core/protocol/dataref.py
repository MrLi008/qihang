"""DataRef 解析（阶段一最小实现：7 个作用域）。

相对原文 demo 的修正：
- D-1：`siblings.S2.2.outputs.x` 用正则整体匹配实例 id（含点），不再 `split(".", 1)`
- D-2：`children.*` 只在 JOIN 聚合上下文可用，其他位置显式报 `REF_AGGREGATE_CONTEXT`
- D-5：解析结果强制校验目标状态与字段存在
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from qihang.core.errors import DataRefError
from qihang.core.model.runtime import Resolved, TaskInstance

REF_RE = re.compile(r"^\{\{(.+?)\}\}$")
IID = r"[A-Za-z][A-Za-z0-9_]*(?:\.\d+)*"
BY_ID_RE = re.compile(rf"^by_id\.({IID})\.(.+)$")
SIBLING_RE = re.compile(rf"^({IID})\.(outputs\..+)$")
UPSTREAM_RE = re.compile(rf"^(?:artifact|outputs)\.(.+)$")
ANCESTOR_RE = re.compile(rf"^by_id\.({IID})\.(outputs\..+)$")
DESCENDANTS_RE = re.compile(r"^by_kind\.([a-z_]+)\.(outputs\..+)$")
OWNER_CHILD_RE = re.compile(rf"^({IID})\.(outputs\..+)$")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class ResolveContext:
    run_id: str
    task_path: str
    lookup: Callable[[str], TaskInstance | None]
    artifact_text: Callable[[str], str]
    project: Mapping[str, str] = field(default_factory=dict)
    fanout_value: str | None = None
    fanout_index: int | None = None
    plan_item: Mapping[str, Any] | None = None
    children: Callable[[str], Sequence[TaskInstance]] | None = None

    def child(self, path: str) -> "ResolveContext":
        inst = self.lookup(path)
        return ResolveContext(
            run_id=self.run_id,
            task_path=path,
            lookup=self.lookup,
            artifact_text=self.artifact_text,
            project=self.project,
            fanout_value=inst.fanout_value if inst else None,
            fanout_index=inst.fanout_index if inst else None,
            plan_item=inst.plan_item if inst else None,
            children=self.children,
        )


def parse_expr(ref: str) -> str:
    m = REF_RE.match(ref.strip())
    if not m:
        raise DataRefError(f"非法引用（缺少 {{{{ }}}}）: {ref}", code="REF_SYNTAX")
    return m.group(1).strip()


def _synthetic(ref: str, expr: str, value: str) -> Resolved:
    return Resolved(ref=ref, task_path="", output=expr, artifact_ref="", value_hash=_digest(value), text=value)


def _from_instance(ref: str, target: str, output: str, ctx: ResolveContext) -> Resolved:
    inst = ctx.lookup(target)
    if inst is None:
        raise DataRefError(f"路径不存在: {target}", code="REF_NOT_FOUND")
    if inst.status.value != "DONE":
        raise DataRefError(f"目标未 DONE: {target} ({inst.status.value})", code="REF_NOT_DONE")
    art = inst.outputs.get(output)
    if art is None:
        raise DataRefError(f"字段不存在: {target}.outputs.{output}", code="REF_FIELD_MISSING")
    text = ctx.artifact_text(art.artifact_id)
    return Resolved(
        ref=ref, task_path=target, output=output, artifact_ref=art.artifact_id, value_hash=art.content_hash, text=text
    )


def _resolve_children(ref: str, rest: str, ctx: ResolveContext, *, allow_aggregate: bool) -> Resolved:
    """`children.by_id.*` 支持跨层链式解析（A9 的 E1/T1/E2/T1.1/...）。"""
    base = ctx.task_path
    while True:
        if rest.startswith("by_id."):
            m = BY_ID_RE.match(rest)
            if not m:
                raise DataRefError(f"children.by_id 语法错误: {rest}", code="REF_SYNTAX")
            target = f"{base}/{m.group(1)}"
            rest = m.group(2)
            if rest.startswith("children."):
                base = target
                rest = rest[len("children."):]
                continue
            if rest.startswith("*."):
                if not allow_aggregate:
                    raise DataRefError(
                        "children.* 只能出现在 JOIN 聚合输入中", code="REF_AGGREGATE_CONTEXT"
                    )
                return Resolved(
                    ref=ref, task_path=f"{target}/*", output=rest[2:], artifact_ref="", value_hash="", text=""
                )
            if not rest.startswith("outputs."):
                raise DataRefError(f"实例引用必须指向 outputs.*: {rest}", code="REF_SYNTAX")
            return _from_instance(ref, target, rest[len("outputs."):], ctx)
        if rest.startswith("*."):
            if not allow_aggregate:
                raise DataRefError(
                    "children.* 只能出现在 JOIN 聚合输入中", code="REF_AGGREGATE_CONTEXT"
                )
            return Resolved(
                ref=ref, task_path=f"{base}/*", output=rest[2:], artifact_ref="", value_hash="", text=""
            )
        raise DataRefError(f"children 语法错误: {rest}", code="REF_SYNTAX")


def _resolve_ancestors(ref: str, rest: str, ctx: ResolveContext) -> Resolved:
    m = ANCESTOR_RE.match(rest)
    if not m:
        raise DataRefError(f"ancestors.by_id 语法错误: {rest}", code="REF_SYNTAX")
    needed, tail = m.group(1), m.group(2)
    current = ctx.task_path
    while True:
        parent = current.rsplit("/", 1)[0] or "/"
        if parent == "/":
            raise DataRefError(f"找不到上层节点 {needed}: {ctx.task_path}", code="REF_NOT_FOUND")
        if parent.rsplit("/", 1)[-1] == needed:
            return _from_instance(ref, parent, tail[len("outputs."):], ctx)
        current = parent


def _resolve_owner(ref: str, rest: str, ctx: ResolveContext) -> Resolved:
    """子实例读取创建它的任务（展开节点所属父实例）下的已确认产物。

    `/A9/E1/T1` 的 owner 是 `/A9`；`/A9/E1/T1/E2/T1.1` 的 owner 是 `/A9/E1/T1`。
    """
    m = OWNER_CHILD_RE.match(rest)
    if not m:
        raise DataRefError(f"owner 语法错误: {rest}", code="REF_SYNTAX")
    parent_of_expand = ctx.task_path.rsplit("/", 1)[0] or "/"
    owner = parent_of_expand.rsplit("/", 1)[0] or "/"
    target = f"{owner}/{m.group(1)}"
    return _from_instance(ref, target, m.group(2)[len("outputs."):], ctx)


def _resolve_descendants(ref: str, rest: str, ctx: ResolveContext) -> Resolved:
    m = DESCENDANTS_RE.match(rest)
    if not m:
        raise DataRefError(f"descendants 语法错误: {rest}", code="REF_SYNTAX")
    if ctx.children is None:
        raise DataRefError("当前上下文不支持 descendants 遍历", code="REF_CONTEXT")
    kind, tail = m.group(1), m.group(2)
    output = tail[len("outputs."):]
    entries: dict[str, str] = {}

    def walk(path: str) -> None:
        for child in ctx.children(path):
            if child.node_kind.value == kind:
                # 多级汇总容忍失败：失败实例不进产物表，但会出现在其所在层聚合的 failures 中。
                if child.status.value == "DONE":
                    art = child.outputs.get(output)
                    if art is None:
                        raise DataRefError(
                            f"字段不存在: {child.task_path}.outputs.{output}", code="REF_FIELD_MISSING"
                        )
                    entries[child.task_path] = ctx.artifact_text(art.artifact_id)
            walk(child.task_path)

    walk(ctx.task_path)
    text = json.dumps(entries, ensure_ascii=False, sort_keys=True)
    return Resolved(
        ref=ref, task_path=f"{ctx.task_path}/**", output=output, artifact_ref="", value_hash=_digest(text), text=text
    )


def resolve_ref(ref: str, ctx: ResolveContext, *, allow_aggregate: bool = False) -> Resolved:
    expr = parse_expr(ref)
    scope, _, rest = expr.partition(".")
    if not rest:
        raise DataRefError(f"引用缺少字段路径: {expr}", code="REF_SYNTAX")

    if scope == "self":
        target = ctx.task_path
    elif scope == "parent":
        target = ctx.task_path.rsplit("/", 1)[0] or "/"
    elif scope == "children":
        return _resolve_children(ref, rest, ctx, allow_aggregate=allow_aggregate)
    elif scope == "ancestors":
        return _resolve_ancestors(ref, rest, ctx)
    elif scope == "owner":
        return _resolve_owner(ref, rest, ctx)
    elif scope == "descendants":
        return _resolve_descendants(ref, rest, ctx)
    elif scope == "siblings":
        m = SIBLING_RE.match(rest)
        if not m:
            raise DataRefError(f"siblings 语法错误: {rest}", code="REF_SYNTAX")
        parent = ctx.task_path.rsplit("/", 1)[0] or "/"
        target = f"{parent}/{m.group(1)}"
        rest = m.group(2)
    elif scope == "upstream":
        agent, _, tail = rest.partition(".")
        if not tail:
            raise DataRefError(f"upstream 缺少字段: {rest}", code="REF_SYNTAX")
        target = f"/{agent}"
        m = UPSTREAM_RE.match(tail)
        if not m:
            raise DataRefError(f"upstream 语法错误: {tail}", code="REF_SYNTAX")
        rest = f"outputs.{m.group(1)}"
    elif scope == "project":
        value = str(ctx.project.get(rest, ""))
        return Resolved(
            ref=ref, task_path="project", output=rest, artifact_ref="project_ctx", value_hash=_digest(value), text=value
        )
    elif scope == "fanout":
        if rest == "item":
            return _synthetic(ref, expr, ctx.fanout_value or "")
        if rest == "index":
            return _synthetic(ref, expr, str(ctx.fanout_index or 0))
        raise DataRefError(f"fanout 语法错误: {rest}", code="REF_SYNTAX")
    elif scope == "plan":
        if ctx.plan_item is None:
            raise DataRefError("当前实例没有 plan.item 上下文", code="REF_PLAN_CONTEXT")
        field_name = rest[len("item."):] if rest.startswith("item.") else rest
        return _synthetic(ref, expr, str(ctx.plan_item.get(field_name, "")))
    else:
        raise DataRefError(f"未知作用域: {scope}", code="REF_UNKNOWN_SCOPE")

    if not rest.startswith("outputs."):
        raise DataRefError(f"实例引用必须指向 outputs.*: {rest}", code="REF_SYNTAX")
    output = rest[len("outputs."):]
    return _from_instance(ref, target, output, ctx)


def resolve_source(source: str, ctx: ResolveContext, *, allow_aggregate: bool = False) -> Resolved:
    text = source.strip()
    if text.startswith("{{"):
        return resolve_ref(text, ctx, allow_aggregate=allow_aggregate)
    return resolve_ref(f"{{{{{text}}}}}", ctx, allow_aggregate=allow_aggregate)
