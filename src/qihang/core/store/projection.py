"""SQLite 索引投影：journal 是权威副本，这里只做"只写增量"的批量投影。

阶段一只实现最小写入路径（S1-10 / S-3 压测用）：
- 单写者：构造时记录属主线程，之后任何非属主线程调用都抛错（对应 03 "SQLite 写只在 GUI 线程"）；
- 批量：`enqueue` 只入内存缓冲，`drain` 按批 `executemany + commit`，返回本批耗时与积压时延。

注意：本模块属于 STORE 层，不得 import Qt；真正的 GUI 线程接线在 ui/bridge 中完成。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq       INTEGER PRIMARY KEY,
    run_id    TEXT NOT NULL,
    kind      TEXT NOT NULL,
    task_path TEXT,
    ts        REAL NOT NULL,
    payload   TEXT NOT NULL
)
"""


class WriterThreadError(RuntimeError):
    code = "WRITER_WRONG_THREAD"


@dataclass(frozen=True, slots=True)
class BatchStat:
    rows: int
    batch_ms: float
    lag_ms: float
    backlog: int


class ProjectionWriter:
    """GUI 线程单写的 SQLite 投影。

    `drain(limit=N)` 一次最多提交 N 行，调用方按每帧预算反复调用即可实现"批 ≤ 8ms"。
    """

    def __init__(self, db_path: str | Path, *, batch_size: int = 800, clock=time.monotonic) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._batch_size = batch_size
        self._clock = clock
        self._owner = threading.get_ident()
        self._buffer: list[tuple[int, str, str, str | None, float, str]] = []
        self._enqueued_at: dict[int, float] = {}
        self._conn = sqlite3.connect(self._path, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute(_SCHEMA)

    # ---- 单写者约束 ----
    def _require_owner(self) -> None:
        if threading.get_ident() != self._owner:
            raise WriterThreadError(
                f"ProjectionWriter 只能在属主线程调用（owner={self._owner}）"
            )

    # ---- 写入路径 ----
    def enqueue(self, event) -> None:
        self._require_owner()
        self._enqueued_at[event.seq] = self._clock()
        self._buffer.append(
            (
                event.seq,
                event.run_id,
                event.kind,
                event.task_path,
                float(event.ts),
                json.dumps(event.payload, ensure_ascii=False, sort_keys=True),
            )
        )

    def enqueue_many(self, events: Sequence) -> None:
        for event in events:
            self.enqueue(event)

    def drain(self, limit: int | None = None) -> BatchStat:
        """按 FIFO 提交一批（默认 batch_size，上限 limit）。"""
        self._require_owner()
        if not self._buffer:
            return BatchStat(0, 0.0, 0.0, 0)
        n = min(limit or self._batch_size, self._batch_size, len(self._buffer))
        rows = self._buffer[:n]
        del self._buffer[:n]
        started = self._clock()
        self._conn.execute("BEGIN")
        self._conn.executemany("INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,?)", rows)
        self._conn.execute("COMMIT")
        batch_ms = (self._clock() - started) * 1000.0
        lag = max(self._clock() - self._enqueued_at.pop(seq, started) for seq, *_ in rows)
        return BatchStat(n, round(batch_ms, 3), round(lag * 1000.0, 3), len(self._buffer))

    def flush(self) -> list[BatchStat]:
        stats: list[BatchStat] = []
        while self._buffer:
            stats.append(self.drain())
        return stats

    def count(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM events")
        return int(cur.fetchone()[0])

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ProjectionWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
