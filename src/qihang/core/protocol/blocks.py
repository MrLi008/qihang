"""块协议解析：行级状态机。

相对原文 demo 的修正（详见 docs/05-实现偏差记录.md）：
- D-4：允许标记行带前导空白（原文要求行首无缩进，模型输出常带缩进）
- D-3：嵌套块显式报 `NESTED_BLOCK`，不再静默丢失外层正文
- 解析结果按 `line_start` 升序，保证"文档序"
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from qihang.core.errors import BlockParseError

START = re.compile(r"^[ \t]*#>----#([A-Z][A-Z0-9_]*)(?::([A-Za-z0-9._-]+))?[ \t]*$")
END = re.compile(r"^[ \t]*#<----#([A-Z][A-Z0-9_]*)(?::([A-Za-z0-9._-]+))?[ \t]*$")


@dataclass(frozen=True, slots=True)
class Block:
    type: str
    id: str | None
    body: str
    line_start: int
    line_end: int


@dataclass(frozen=True, slots=True)
class ParseResult:
    blocks: tuple[Block, ...]
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


def parse(text: str) -> list[Block]:
    blocks: list[Block] = []
    stack: list[tuple[str, str | None, int, list[str]]] | None = None
    for lineno, line in enumerate(text.splitlines(), 1):
        m = START.match(line)
        if m:
            if stack is not None:
                raise BlockParseError(
                    f"L{lineno}: 块内出现新的开始标记（不支持嵌套）", line=lineno, code="NESTED_BLOCK"
                )
            stack = (m.group(1), m.group(2), lineno, [])
            continue

        m = END.match(line)
        if m:
            if stack is None:
                raise BlockParseError(f"L{lineno}: 结束标记无对应开始", line=lineno, code="UNEXPECTED_END")
            typ, bid, start, buf = stack
            if m.group(1) != typ or m.group(2) != bid:
                raise BlockParseError(
                    f"L{lineno}: 结束标记不匹配（开始 {typ}:{bid}，结束 {m.group(1)}:{m.group(2)}）",
                    line=lineno,
                    code="MISMATCHED_END",
                )
            blocks.append(Block(typ, bid, "\n".join(buf), start, lineno))
            stack = None
            continue

        if stack is not None:
            stack[3].append(line)
        elif line.strip():
            raise BlockParseError(f"L{lineno}: 块外出现非空内容", line=lineno, code="OUTSIDE_CONTENT")

    if stack is not None:
        raise BlockParseError(
            f"未闭合块 {stack[0]}:{stack[1]}（起始行 {stack[2]}）", line=stack[2], code="UNCLOSED_BLOCK"
        )
    blocks.sort(key=lambda b: b.line_start)
    return blocks


def parse_safe(text: str) -> ParseResult:
    try:
        return ParseResult(tuple(parse(text)))
    except BlockParseError as exc:
        return ParseResult((), (exc.code, f"L{exc.line}: {exc.message}" if exc.line else exc.message))


def render_block(block_type: str, block_id: str, body: str) -> str:
    return f"#>----#{block_type}:{block_id}\n{body}\n#<----#{block_type}:{block_id}"


def join_blocks(blocks: Iterable[Block]) -> str:
    return "\n".join(render_block(b.type, b.id or "noid", b.body) for b in blocks)
