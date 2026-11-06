from qihang.core.errors import BlockParseError
from qihang.core.protocol.blocks import parse, parse_safe, render_block


def test_parse_two_blocks_in_document_order() -> None:
    text = "\n".join(
        [
            render_block("THINK", "a4-gen-001", "先想"),
            render_block("ARTIFACT", "a4-art-001", "## 代码\nprint(1)"),
        ]
    )
    blocks = parse(text)
    assert [b.type for b in blocks] == ["THINK", "ARTIFACT"]
    assert blocks[1].body == "## 代码\nprint(1)"
    assert blocks[0].line_start == 1
    assert blocks[1].line_start > blocks[0].line_end


def test_leading_whitespace_is_tolerated() -> None:
    text = "  #>----#DATA:file_list\n  [\"a.py\"]\n  #<----#DATA:file_list"
    blocks = parse(text)
    assert blocks[0].type == "DATA"
    assert blocks[0].body.strip() == "[\"a.py\"]"


def test_unclosed_block_reports_code() -> None:
    result = parse_safe("#>----#ARTIFACT:x\nbody")
    assert not result.ok
    assert "UNCLOSED_BLOCK" in result.errors[0]


def test_mismatched_end_reports_line() -> None:
    try:
        parse("#>----#ARTIFACT:x\nbody\n#<----#THINK:y")
    except BlockParseError as exc:
        assert exc.code == "MISMATCHED_END"
        assert exc.line == 3
    else:  # pragma: no cover
        raise AssertionError("应当抛 BlockParseError")


def test_outside_content_is_rejected() -> None:
    result = parse_safe("hello\n#>----#DATA:x\n1\n#<----#DATA:x")
    assert not result.ok
    assert "OUTSIDE_CONTENT" in result.errors[0]


def test_nested_block_is_rejected_not_silently_lost() -> None:
    """原文 demo 会静默丢外层正文（D-3），这里必须显式失败。"""
    result = parse_safe("#>----#ARTIFACT:x\n#>----#THINK:y\n1\n#<----#THINK:y\n#<----#ARTIFACT:x")
    assert not result.ok
    assert "NESTED_BLOCK" in result.errors[0]
