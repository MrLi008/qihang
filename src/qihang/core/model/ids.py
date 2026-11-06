"""公共标识类型。

阶段一只用字符串别名，不引入 NewType，避免序列化与日志里多一层包装。
"""

from __future__ import annotations

RunId = str
TaskPath = str
GateId = str
AgentId = str
SpecRef = str
