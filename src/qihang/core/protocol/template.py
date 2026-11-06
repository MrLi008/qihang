"""模板渲染：`{{变量名}}` → 契约绑定的源 DSL 解析结果。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from qihang.core.errors import DataRefError, TemplateError
from qihang.core.model.runtime import Resolved
from qihang.core.model.spec import InputBinding
from qihang.core.protocol.dataref import ResolveContext, resolve_source

VAR_RE = re.compile(r"\{\{\s*(.+?)\s*\}\}")


@dataclass(frozen=True, slots=True)
class RenderResult:
    text: str
    resolved: Mapping[str, Resolved] = field(default_factory=dict)


def render(template: str, bindings: Sequence[InputBinding], ctx: ResolveContext) -> RenderResult:
    table: dict[str, InputBinding] = {b.name: b for b in bindings}
    out: dict[str, Resolved] = {}

    def replace(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        binding = table.get(name)
        if binding is not None:
            if binding.literal is not None:
                resolved = Resolved(
                    ref=name,
                    task_path="",
                    output=name,
                    artifact_ref="",
                    value_hash="",
                    text=binding.literal,
                )
            elif binding.source:
                try:
                    resolved = resolve_source(binding.source, ctx)
                except DataRefError as exc:
                    raise TemplateError(f"变量 {{{{{name}}}}} 解析失败: {exc.message}", code=exc.code) from exc
            else:
                raise TemplateError(f"变量 {{{{{name}}}}} 既无 source 也无 literal", code="TEMPLATE_BINDING")
            out[name] = resolved
            return resolved.text

        # 未在契约里声明：允许直接写完整 DataRef（阶段一便捷通道）
        if "." in name:
            try:
                resolved = resolve_source(name, ctx)
            except DataRefError as exc:
                raise TemplateError(f"引用 {{{{{name}}}}} 解析失败: {exc.message}", code=exc.code) from exc
            out[name] = resolved
            return resolved.text

        raise TemplateError(f"模板变量未在 message_contract.inputs 中声明: {name}", code="TEMPLATE_UNDECLARED")

    rendered = VAR_RE.sub(replace, template)
    return RenderResult(text=rendered, resolved=out)
