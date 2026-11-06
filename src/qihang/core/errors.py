"""内核错误类型：全部带稳定错误码，便于事件与 UI 直接展示。"""

from __future__ import annotations


class QihangError(Exception):
    code = "QIHANG_ERROR"

    def __init__(self, message: str, *, line: int | None = None, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.line = line
        if code:
            self.code = code

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"code": self.code, "message": self.message}
        if self.line is not None:
            payload["line"] = self.line
        return payload


class SpecError(QihangError):
    code = "SPEC_INVALID"


class BlockParseError(QihangError):
    code = "BLOCK_INVALID"


class DataRefError(QihangError):
    code = "REF_INVALID"


class TemplateError(QihangError):
    code = "TEMPLATE_INVALID"


class PlanError(QihangError):
    code = "PLAN_INVALID"
