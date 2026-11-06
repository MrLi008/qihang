"""Run journal：JSONL 追加写，作为事件流的权威副本（SQLite 索引为阶段一之后的投影）。"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from qihang.core.model.events import RunEvent


class JsonlJournal:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = path.open("a", encoding="utf-8", newline="\n")

    def append(self, event: RunEvent) -> None:
        self._fh.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "JsonlJournal":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
