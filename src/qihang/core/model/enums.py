"""运行期枚举：节点类型、实例状态、事件种类、执行器种类。"""

from __future__ import annotations

from enum import Enum


class NodeKind(str, Enum):
    TASK = "task"
    EXPAND = "expand"
    JOIN = "join"
    DECOMPOSE = "decompose"
    DYNAMIC_EXPAND = "dynamic_expand"


class Status(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    CHECK = "CHECK"
    DONE = "DONE"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    STALE = "STALE"
    CANCELLED = "CANCELLED"


TERMINAL_STATUSES = frozenset({Status.DONE, Status.FAILED, Status.BLOCKED, Status.CANCELLED})
SUCCESS_STATUSES = frozenset({Status.DONE})


class EventKind(str, Enum):
    RUN_STARTED = "RUN_STARTED"
    RUN_FINISHED = "RUN_FINISHED"
    INSTANCE_CREATED = "INSTANCE_CREATED"
    INSTANCE_STATE = "INSTANCE_STATE"
    LLM_REQUEST = "LLM_REQUEST"
    LLM_RESPONSE = "LLM_RESPONSE"
    BLOCK_PARSED = "BLOCK_PARSED"
    ARTIFACT_WRITTEN = "ARTIFACT_WRITTEN"
    EXPAND_PLANNED = "EXPAND_PLANNED"
    JOIN_DONE = "JOIN_DONE"
    ERROR = "ERROR"


class Verdict(str, Enum):
    ACCEPTED = "ACCEPTED"
    FAILED = "FAILED"
    PENDING_CONFIRM = "PENDING_CONFIRM"
    SKIPPED = "SKIPPED"
