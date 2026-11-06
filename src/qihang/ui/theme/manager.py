"""ThemeManager：唯一的颜色/间距来源。

- token 存于 `tokens/<name>.json`，QSS 存于 `app.qss`，两者都不含硬编码以外的逻辑；
- QSS 里的 `{{color.canvas}}` 由本模块替换，最后通过 `QApplication.setStyleSheet` 一次性应用；
- 组件不得自行 `setStyleSheet`，颜色一律 `theme.color("status.done")` 取用（`tools/check_theme.py` 会拦）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_THEME_DIR = Path(__file__).resolve().parent
_TOKEN_DIR = _THEME_DIR / "tokens"
_QSS_PATH = _THEME_DIR / "app.qss"


class ThemeError(KeyError):
    pass


class ThemeManager:
    def __init__(self, name: str = "light", *, token_dir: Path | None = None, qss_path: Path | None = None) -> None:
        self._token_dir = token_dir or _TOKEN_DIR
        self._qss_path = qss_path or _QSS_PATH
        self._name = name
        self._tokens: dict[str, Any] = {}
        self.load(name)

    # ---- token ----
    @property
    def name(self) -> str:
        return self._name

    def load(self, name: str) -> None:
        path = self._token_dir / f"{name}.json"
        if not path.exists():
            raise ThemeError(f"主题不存在: {name}（{path}）")
        self._tokens = json.loads(path.read_text(encoding="utf-8"))
        self._name = name

    def token(self, dotted: str, default: Any | None = None) -> Any:
        node: Any = self._tokens
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                if default is not None:
                    return default
                raise ThemeError(f"token 不存在: {dotted}")
            node = node[part]
        return node

    def color(self, dotted: str) -> str:
        """返回十六进制颜色字符串（供 QColor(...) 使用）。"""
        value = self.token(dotted if dotted.startswith("color.") else f"color.{dotted}")
        if not isinstance(value, str):
            raise ThemeError(f"{dotted} 不是颜色 token")
        return value

    def status_color(self, status: str) -> str:
        return self.color(f"status.{status.lower()}")

    # ---- QSS ----
    def render_qss(self) -> str:
        raw = self._qss_path.read_text(encoding="utf-8")
        out: list[str] = []
        i = 0
        while True:
            start = raw.find("{{", i)
            if start < 0:
                out.append(raw[i:])
                break
            out.append(raw[i:start])
            end = raw.find("}}", start)
            if end < 0:
                out.append(raw[start:])
                break
            key = raw[start + 2 : end].strip()
            out.append(str(self.token(key)))
            i = end + 2
        return "".join(out)

    def apply(self, app) -> None:
        """应用级 QSS：整个进程只在这里调用 setStyleSheet。"""
        app.setStyleSheet(self.render_qss())
