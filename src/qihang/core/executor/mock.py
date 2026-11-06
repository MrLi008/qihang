"""Mock 执行器：与真实 LLM 执行器共用 `Executor` 接口。

- 每个 `generate` 默认耗时 1 秒（±0.2s 抖动），耗时来自注入的 `Clock.sleep`，
  因此真实运行时它发生在 I/O 线程池里，不会阻塞 GUI。
- 输出是可被块协议解析的确定性文本，用于回归。
- `decompose` 返回固定 3 项的 `subtask_plan_v1`，用于演示动态展开。
"""

from __future__ import annotations

import json
import random
from typing import Mapping, Sequence

from qihang.core.model.spec import OutputDecl
from qihang.core.ports import (
    Clock,
    DecomposeRequest,
    ExecutionResult,
    GenerateRequest,
    ReviewRequest,
    TokenUsage,
)

DEFAULT_FILES = ("auth.py", "login.py", "session.py")


class MockExecutor:
    kind = "mock"

    def __init__(
        self,
        clock: Clock,
        *,
        base_delay_s: float = 1.0,
        jitter_s: float = 0.2,
        seed: int = 20261105,
        fail_inject: Mapping[str, str] | None = None,
        files: Sequence[str] = DEFAULT_FILES,
        plan_items: Sequence[Mapping[str, str]] | None = None,
    ) -> None:
        self._clock = clock
        self._base = base_delay_s
        # 抖动随基础耗时等比收缩：压测把 delay 压到 0.02 时不会被固定 0.2 的抖动淹没。
        self._jitter = min(jitter_s, base_delay_s * 0.25) if base_delay_s > 0 else 0.0
        self._seed = seed
        self._fail_inject = dict(fail_inject or {})
        self._files = tuple(files)
        self._plan_items = tuple(
            plan_items
            or (
                {"id": "T1", "agent_ref": "A6.refactor", "target": "auth.py", "rule": "提取登录流程为独立函数"},
                {"id": "T2", "agent_ref": "A6.refactor", "target": "login.py", "rule": "合并重复的参数校验"},
                {"id": "T3", "agent_ref": "A6.refactor", "target": "session.py", "rule": "替换过期的 token 过期判断"},
            )
        )

    # ---- 内部 ----
    def _mode_for(self, task_path: str) -> str | None:
        for key, mode in self._fail_inject.items():
            if task_path.endswith(key) or f"/{key}/" in task_path:
                return mode
        return None

    def _delay(self, task_path: str) -> float:
        rng = random.Random(f"{self._seed}:{task_path}")
        return max(0.0, self._base + rng.uniform(-self._jitter, self._jitter))

    def _usage(self, req_text: str, out_text: str) -> TokenUsage:
        return TokenUsage(prompt_tokens=max(1, len(req_text) // 4), completion_tokens=max(1, len(out_text) // 4))

    @staticmethod
    def _block(block_type: str, block_id: str, body: str) -> str:
        return f"#>----#{block_type}:{block_id}\n{body}\n#<----#{block_type}:{block_id}"

    def _body_for(self, output: OutputDecl, req: GenerateRequest) -> str:
        if output.name == "file_list":
            list_size = req.parameters.get("list_size")
            if list_size is not None:
                count = max(0, int(list_size))
                return json.dumps([f"file_{i:03d}.py" for i in range(1, count + 1)], ensure_ascii=False)
            return json.dumps(list(self._files), ensure_ascii=False)
        if output.name == "aggregate":
            return json.dumps(
                {"coverage": "n/a", "source": "mock", "task": req.task_path}, ensure_ascii=False, indent=2
            )
        head = req.rendered_prompt.strip().splitlines()[:6]
        return "\n".join(
            [
                f"## {req.task_path}",
                f"agent: {req.agent_id or req.spec_ref}",
                "## 输入摘要",
                *[f"> {line}" for line in head],
                "## 产出",
                f"字段 {output.name} 由 mock 生成（executor=mock, attempt={req.attempt}）",
                "DELIVERY_STATUS: COMPLETE",
            ]
        )

    # ---- Executor 接口 ----
    def generate(self, req: GenerateRequest) -> ExecutionResult:
        delay = self._delay(req.task_path)
        self._clock.sleep(delay)
        mode = self._mode_for(req.task_path)
        if mode == "raise":
            raise RuntimeError(f"mock 注入异常: {req.task_path}")

        parts: list[str] = []
        for output in req.outputs:
            body = self._body_for(output, req)
            if mode == "empty_artifact":
                body = ""
            parts.append(self._block(output.block_type, f"{req.task_path.strip('/').replace('/', '-')}-{output.name}", body))
        text = "\n".join(parts)
        if mode == "closed_missing" and parts:
            text = text.rsplit("\n", 1)[0]  # 去掉最后一个结束标记
        latency_ms = int(delay * 1000)
        return ExecutionResult(
            text=text,
            latency_ms=latency_ms,
            executor=self.kind,
            usage=self._usage(req.rendered_prompt, text),
        )

    def decompose(self, req: DecomposeRequest) -> ExecutionResult:
        delay = self._delay(req.task_path)
        self._clock.sleep(delay)
        doc = {"plan_id": f"{req.task_path.strip('/')}-P1", "subtasks": [dict(x) for x in self._plan_items]}
        text = self._block("PLAN", "plan", json.dumps(doc, ensure_ascii=False, indent=2))
        return ExecutionResult(
            text=text,
            latency_ms=int(delay * 1000),
            executor=self.kind,
            usage=self._usage(req.goal or req.agent_id, text),
        )

    def review(self, req: ReviewRequest) -> ExecutionResult:
        # 阶段一没有 LLM，复查通道统一返回 SKIPPED，由调用方决定降级标记（阶段二实现）
        return ExecutionResult(text="", latency_ms=0, executor=self.kind, usage=TokenUsage())
