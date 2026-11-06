"""编排器：单线程状态机。

一次 `tick()` 做四件事，全部非阻塞：
1. 轮询已提交的 Future（结果由 I/O 线程池产生）
2. 完成"等子实例"的逻辑节点（expand / dynamic_expand）
3. 把依赖满足的 PENDING 提升为 READY
4. 派发 READY（提交执行器 / 做 JOIN / 规划展开点）

GUI 只读事件队列，永不调用 tick。
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import Future
from typing import Any, Mapping

from qihang.core.errors import BlockParseError, PlanError, QihangError
from qihang.core.model.enums import EventKind, NodeKind, Status
from qihang.core.model.events import EventBus
from qihang.core.model.runtime import ArtifactRef, Resolved, RunSummary
from qihang.core.model.spec import AgentSpec, SubtaskNode
from qihang.core.ports import (
    Clock,
    DecomposeRequest,
    ExecutionResult,
    Executor,
    GenerateRequest,
    OutputDeclView,
    TaskRunner,
)
from qihang.core.protocol import blocks as block_protocol
from qihang.core.protocol.dataref import ResolveContext, resolve_source
from qihang.core.protocol.template import render
from qihang.core.runtime import join
from qihang.core.runtime.planner import FanoutPlan, parse_plan_doc, plan_static, values_from_text
from qihang.core.runtime.task_tree import TaskTree
from qihang.core.store.blobstore import BlobStore


class Orchestrator:
    def __init__(
        self,
        specs: Mapping[str, AgentSpec],
        executor: Executor,
        clock: Clock,
        runner: TaskRunner,
        artifacts: BlobStore,
        bus: EventBus,
        *,
        run_id: str = "R-001",
        project: Mapping[str, str] | None = None,
    ) -> None:
        self._specs = dict(specs)
        self._exec = executor
        self._clock = clock
        self._runner = runner
        self._artifacts = artifacts
        self._bus = bus
        self._run_id = run_id
        self._project = dict(project or {})
        self._tree = TaskTree()
        self._futures: dict[str, Future[ExecutionResult]] = {}
        self._root: str | None = None
        self._started_at = 0.0
        self._finished = False

    # ------------------------------------------------------------------ 启动
    def start(self, agent_id: str) -> str:
        if agent_id not in self._specs:
            raise KeyError(f"未知 agent: {agent_id}")
        spec = self._specs[agent_id]
        self._started_at = self._clock.now()
        root = f"/{agent_id}"
        self._root = root
        self._tree.create(root, parent_path="/", spec_ref=agent_id, node_kind=NodeKind.TASK)
        self._bus.emit(EventKind.RUN_STARTED, root, ts=self._started_at, agent=agent_id, run_id=self._run_id)
        self._emit_created(root)
        self._create_children(root, spec, parent_level=0)
        return root

    def _levels_for(self, spec: AgentSpec) -> int:
        """动态展开层数：取 parameters.levels，受 decomposition.max_depth 与已声明展开点限制。"""
        declared = max((n.level for n in spec.expandables if n.node_kind is NodeKind.DYNAMIC_EXPAND), default=1)
        cap = spec.decomposition.max_depth if spec.decomposition else declared
        requested = spec.parameters.get("levels", cap)
        try:
            levels = int(requested)
        except (TypeError, ValueError):
            levels = cap
        return max(1, min(levels, cap, declared))

    def _create_children(self, parent_path: str, spec: AgentSpec, *, parent_level: int) -> None:
        if spec.dynamic_expand:
            levels = self._levels_for(spec)
            if parent_level >= levels:
                return
            decompose_path = f"{parent_path}/DECOMPOSE"
            self._tree.create(
                decompose_path,
                parent_path=parent_path,
                spec_ref=spec.agent_id,
                node_kind=NodeKind.DECOMPOSE,
                level=parent_level,
            )
            self._emit_created(decompose_path)
            next_node = next(
                (
                    n
                    for n in spec.expandables
                    if n.node_kind is NodeKind.DYNAMIC_EXPAND and n.level == parent_level + 1
                ),
                None,
            )
            if next_node is not None:
                deps = next_node.deps or ("DECOMPOSE",)
                path = f"{parent_path}/{next_node.id}"
                self._tree.create(
                    path,
                    parent_path=parent_path,
                    spec_ref=spec.agent_id,
                    node_kind=next_node.node_kind,
                    deps=deps,
                    level=next_node.level,
                )
                self._emit_created(path)
            if parent_level == 0:
                for node in spec.subtasks:
                    path = f"{parent_path}/{node.id}"
                    self._tree.create(
                        path,
                        parent_path=parent_path,
                        spec_ref=spec.agent_id,
                        node_kind=node.node_kind,
                        deps=node.deps,
                        level=0,
                    )
                    self._emit_created(path)
            return

        for node in spec.subtasks:
            path = f"{parent_path}/{node.id}"
            self._tree.create(
                path,
                parent_path=parent_path,
                spec_ref=spec.agent_id,
                node_kind=node.node_kind,
                deps=node.deps,
                level=0,
            )
            self._emit_created(path)

    def _emit_created(self, path: str) -> None:
        inst = self._tree.require(path)
        self._bus.emit(
            EventKind.INSTANCE_CREATED,
            path,
            ts=self._clock.now(),
            parent=inst.parent_path,
            node_kind=inst.node_kind.value,
            created_by=inst.created_by,
            deps=list(inst.deps),
        )

    # ------------------------------------------------------------------ 主循环
    def tick(self) -> bool:
        progress = False
        progress |= self._poll_futures()
        progress |= self._complete_logic_nodes()
        progress |= self._promote_pending()
        progress |= self._start_ready()
        progress |= self._maybe_finish_run()
        return progress

    @property
    def tree(self) -> TaskTree:
        return self._tree

    def is_finished(self) -> bool:
        if self._root is None:
            return False
        inst = self._tree.lookup(self._root)
        return inst is not None and inst.is_terminal

    def summary(self) -> RunSummary:
        assert self._root is not None
        insts = self._tree.all_instances()
        root = self._tree.require(self._root)
        done = sum(1 for i in insts if i.status is Status.DONE)
        failed = sum(1 for i in insts if i.status is Status.FAILED)
        blocked = sum(1 for i in insts if i.status is Status.BLOCKED)
        wall = int(round((self._clock.now() - self._started_at) * 1000))
        coverage = None
        root_art = root.outputs.get("artifact")
        if root_art is not None:
            coverage = f"{done}/{len(insts)}"
        return RunSummary(
            run_id=self._run_id,
            root_path=self._root,
            status=root.status,
            total_instances=len(insts),
            done=done,
            failed=failed,
            blocked=blocked,
            wall_time_ms=wall,
            coverage=coverage,
        )

    # ------------------------------------------------------------------ 1. 轮询
    def _poll_futures(self) -> bool:
        progress = False
        for path, future in list(self._futures.items()):
            if not future.done():
                continue
            del self._futures[path]
            inst = self._tree.require(path)
            try:
                result = future.result()
            except Exception as exc:  # 工作线程异常
                self._fail(inst, "EXECUTOR_ERROR", f"{type(exc).__name__}: {exc}")
                progress = True
                continue
            try:
                if inst.node_kind is NodeKind.DECOMPOSE:
                    self._on_decompose(inst, result)
                else:
                    self._on_generate(inst, result)
            except QihangError as exc:
                self._fail(inst, exc.code, exc.message, line=exc.line)
            progress = True
        return progress

    def _on_generate(self, inst: Any, result: ExecutionResult) -> None:
        self._bus.emit(
            EventKind.LLM_RESPONSE,
            inst.task_path,
            ts=self._clock.now(),
            executor=result.executor,
            latency_ms=result.latency_ms,
            ok=result.ok,
            tokens=result.usage.total,
        )
        text = result.text
        parsed = block_protocol.parse(text)
        self._bus.emit(
            EventKind.BLOCK_PARSED,
            inst.task_path,
            ts=self._clock.now(),
            count=len(parsed),
            types=[b.type for b in parsed],
        )
        decls = self._expected_outputs(inst)
        unused = list(parsed)
        for decl in decls:
            matched = next((b for b in unused if b.type == decl.block_type), None)
            if matched is None:
                if unused:
                    matched = unused[0]
                else:
                    raise BlockParseError(
                        f"缺少输出块 {decl.name}({decl.block_type})", code="OUTPUT_MISSING"
                    )
            unused.remove(matched)
            if not matched.body.strip():
                raise BlockParseError(f"输出块 {decl.name} 正文为空", code="EMPTY_ARTIFACT")
            artifact_id, digest = self._artifacts.put(matched.body, prefix="art")
            inst.outputs[decl.name] = ArtifactRef(
                artifact_id=artifact_id, content_hash=digest, output=decl.name, size=len(matched.body)
            )
            self._bus.emit(
                EventKind.ARTIFACT_WRITTEN,
                inst.task_path,
                ts=self._clock.now(),
                output=decl.name,
                artifact_id=artifact_id,
                hash=digest[:12],
                size=len(matched.body),
            )
        self._to(inst, Status.CHECK)
        self._to(inst, Status.DONE)

    def _on_decompose(self, inst: Any, result: ExecutionResult) -> None:
        self._bus.emit(
            EventKind.LLM_RESPONSE,
            inst.task_path,
            ts=self._clock.now(),
            executor=result.executor,
            latency_ms=result.latency_ms,
            ok=result.ok,
            tokens=result.usage.total,
        )
        parsed = block_protocol.parse(result.text)
        plan_block = next((b for b in parsed if b.type == "PLAN"), None)
        if plan_block is None:
            raise BlockParseError("分解结果缺少 PLAN 块", code="PLAN_MISSING")
        try:
            doc = json.loads(plan_block.body)
        except json.JSONDecodeError as exc:
            raise PlanError(f"PLAN 不是合法 JSON: {exc}", code="PLAN_JSON") from exc
        spec = self._specs[inst.spec_ref]
        dec = spec.decomposition
        items = parse_plan_doc(
            doc,
            max_fanout=dec.max_fanout if dec else 8,
            allowed_agent_refs=dec.allowed_agent_refs if dec else (),
        )
        inst.plan_doc = {"plan_id": doc.get("plan_id"), "subtasks": items}
        artifact_id, digest = self._artifacts.put(plan_block.body, prefix="plan")
        inst.outputs["plan"] = ArtifactRef(
            artifact_id=artifact_id, content_hash=digest, output="plan", size=len(plan_block.body)
        )
        self._bus.emit(
            EventKind.BLOCK_PARSED,
            inst.task_path,
            ts=self._clock.now(),
            count=len(parsed),
            types=[b.type for b in parsed],
        )
        self._bus.emit(
            EventKind.ARTIFACT_WRITTEN,
            inst.task_path,
            ts=self._clock.now(),
            output="plan",
            artifact_id=artifact_id,
            hash=digest[:12],
            size=len(plan_block.body),
        )
        self._to(inst, Status.CHECK)
        self._to(inst, Status.DONE)

    # ------------------------------------------------------------------ 2. 逻辑节点收口
    def _complete_logic_nodes(self) -> bool:
        progress = False
        for inst in self._tree.all_instances():
            if inst.node_kind not in (NodeKind.EXPAND, NodeKind.DYNAMIC_EXPAND):
                continue
            if inst.status is not Status.RUNNING:
                continue
            children = self._tree.children(inst.task_path)
            if not children or not all(c.is_terminal for c in children):
                continue
            report = join.evaluate(children, output=self._child_output_name(inst))
            artifact_id, digest = self._artifacts.put(report.to_text(), prefix="agg")
            inst.outputs["aggregate"] = ArtifactRef(
                artifact_id=artifact_id, content_hash=digest, output="aggregate", size=len(report.to_text())
            )
            self._bus.emit(
                EventKind.JOIN_DONE,
                inst.task_path,
                ts=self._clock.now(),
                stage="expand",
                coverage=report.coverage,
                failures=list(report.failures),
            )
            spec = self._specs[inst.spec_ref]
            if spec.failure_policy == "strict" and report.failed:
                self._to(inst, Status.BLOCKED, error=f"展开子任务失败 {report.coverage}")
                self._bus.emit(
                    EventKind.ERROR, inst.task_path, ts=self._clock.now(), code="EXPAND_FAILED", message=report.coverage
                )
            else:
                self._to(inst, Status.DONE)
            progress = True
        return progress

    # ------------------------------------------------------------------ 3. 提升
    def _promote_pending(self) -> bool:
        progress = False
        for inst in self._tree.all_instances():
            if inst.status is not Status.PENDING:
                continue
            if not self._deps_done(inst):
                continue
            children = self._tree.children(inst.task_path)
            if children and not all(c.is_terminal for c in children):
                continue  # 子图根节点等子任务全部结束
            if inst.created_by == "fanout":
                parent = self._tree.lookup(inst.parent_path)
                if parent is not None and parent.status not in (Status.RUNNING, Status.DONE):
                    continue
            self._to(inst, Status.READY)
            progress = True
        return progress

    def _deps_done(self, inst: Any) -> bool:
        for dep in inst.deps:
            dep_path = f"{inst.parent_path}/{dep}"
            inst_dep = self._tree.lookup(dep_path)
            if inst_dep is None:
                if inst.parent_path == "/" and dep in self._specs:
                    continue
                return False
            if inst_dep.status is not Status.DONE:
                return False
        return True

    # ------------------------------------------------------------------ 4. 派发
    def _start_ready(self) -> bool:
        progress = False
        for inst in self._tree.all_instances():
            if inst.status is not Status.READY:
                continue
            try:
                if inst.node_kind is NodeKind.TASK:
                    self._start_task(inst)
                elif inst.node_kind is NodeKind.EXPAND:
                    self._start_expand(inst)
                elif inst.node_kind is NodeKind.JOIN:
                    self._start_join(inst)
                elif inst.node_kind is NodeKind.DECOMPOSE:
                    self._start_decompose(inst)
                elif inst.node_kind is NodeKind.DYNAMIC_EXPAND:
                    self._start_dynamic_expand(inst)
                else:  # pragma: no cover
                    raise QihangError(f"未知节点类型 {inst.node_kind}", code="NODE_KIND")
            except QihangError as exc:
                self._fail(inst, exc.code, exc.message, line=exc.line)
            progress = True
        return progress

    def _start_task(self, inst: Any) -> None:
        spec = self._specs[inst.spec_ref]
        node = self._node_for(inst)
        if inst.task_path == self._root:
            ctx = self._ctx(inst.task_path)
            rendered = render(spec.generation_template, spec.inputs, ctx)
            prompt, snapshot = rendered.text, dict(rendered.resolved)
        else:
            prompt, snapshot = self._subtask_prompt(inst, node)
        inst.input_snapshot = snapshot
        decls = self._expected_outputs(inst)
        req = GenerateRequest(
            run_id=self._run_id,
            task_path=inst.task_path,
            attempt=inst.attempt,
            spec_ref=inst.spec_ref,
            rendered_prompt=prompt,
            input_snapshot_hash=self._snapshot_hash(snapshot),
            outputs=tuple(OutputDeclView(d.name, d.block_type) for d in decls),
            agent_id=spec.agent_id,
            role_definition=spec.role_definition,
            parameters=dict(spec.parameters),
        )
        self._to(inst, Status.RUNNING)
        self._bus.emit(
            EventKind.LLM_REQUEST,
            inst.task_path,
            ts=self._clock.now(),
            executor=self._exec.kind,
            prompt_chars=len(prompt),
            outputs=[d.name for d in decls],
            attempt=inst.attempt,
        )
        self._futures[inst.task_path] = self._runner.submit(lambda: self._exec.generate(req))

    def _start_expand(self, inst: Any) -> None:
        node = self._node_for(inst)
        if node is None or not node.fanout_by:
            raise PlanError(f"展开点 {inst.task_path} 缺少 fanout_by", code="SPEC_FANOUT")
        ctx = self._ctx(inst.parent_path)
        resolved = resolve_source(node.fanout_by, ctx)
        values = values_from_text(resolved.text)
        plan = plan_static(inst.task_path, node, values)
        self._to(inst, Status.RUNNING)
        self._materialize(inst, plan)
        self._bus.emit(
            EventKind.EXPAND_PLANNED,
            inst.task_path,
            ts=self._clock.now(),
            stage="static",
            count=len(plan.items),
            max_instances=node.max_instances,
            slots=[p.rsplit("/", 1)[-1] for p in plan.instance_paths],
        )

    def _start_join(self, inst: Any) -> None:
        node = self._node_for(inst)
        output_name = node.outputs[0].name if node and node.outputs else "aggregate"
        sources, source_node = self._join_sources(inst, node)
        child_output = self._child_output_name(source_node)
        report = join.evaluate(sources, output=child_output)
        artifact_id, digest = self._artifacts.put(report.to_text(), prefix="agg")
        self._to(inst, Status.RUNNING)
        inst.outputs[output_name] = ArtifactRef(
            artifact_id=artifact_id, content_hash=digest, output=output_name, size=len(report.to_text())
        )
        self._bus.emit(
            EventKind.ARTIFACT_WRITTEN,
            inst.task_path,
            ts=self._clock.now(),
            output=output_name,
            artifact_id=artifact_id,
            hash=digest[:12],
            size=len(report.to_text()),
        )
        self._bus.emit(
            EventKind.JOIN_DONE,
            inst.task_path,
            ts=self._clock.now(),
            stage="join",
            coverage=report.coverage,
            failures=list(report.failures),
            total=report.total,
        )
        self._to(inst, Status.CHECK)
        self._to(inst, Status.DONE)

    def _start_decompose(self, inst: Any) -> None:
        spec = self._specs[inst.spec_ref]
        dec = spec.decomposition
        req = DecomposeRequest(
            run_id=self._run_id,
            task_path=inst.task_path,
            agent_id=spec.agent_id,
            goal=spec.role_definition,
            output_schema=dec.output_schema if dec else "subtask_plan_v1",
            allowed_agent_refs=dec.allowed_agent_refs if dec else (),
            max_fanout=dec.max_fanout if dec else 8,
            parameters=dict(spec.parameters),
        )
        self._to(inst, Status.RUNNING)
        self._bus.emit(
            EventKind.LLM_REQUEST,
            inst.task_path,
            ts=self._clock.now(),
            executor=self._exec.kind,
            purpose="decompose",
            output_schema=req.output_schema,
        )
        self._futures[inst.task_path] = self._runner.submit(lambda: self._exec.decompose(req))

    def _start_dynamic_expand(self, inst: Any) -> None:
        node = self._node_for(inst)
        if node is None:
            raise PlanError(f"动态展开点 {inst.task_path} 未在 expandables 中声明", code="SPEC_DYNAMIC")
        decompose = self._tree.lookup(f"{inst.parent_path}/DECOMPOSE")
        if decompose is None or not decompose.plan_doc:
            raise PlanError("缺少 DECOMPOSE 产出的 plan", code="PLAN_MISSING")
        items = decompose.plan_doc["subtasks"]
        if len(items) > node.max_instances:
            raise PlanError(
                f"动态展开 {len(items)} 超过 max_instances={node.max_instances}", code="FANOUT_EXCEEDED"
            )
        self._to(inst, Status.RUNNING)
        paths = []
        spec = self._specs[inst.spec_ref]
        for i, item in enumerate(items, 1):
            sid = node.instance_id_pattern.format(index=i, key=str(item.get("id", i)))
            path = f"{inst.task_path}/{sid}"
            created = self._tree.create(
                path,
                parent_path=inst.task_path,
                spec_ref=inst.spec_ref,
                node_kind=NodeKind.TASK,
                created_by="plan",
                level=node.level,
            )
            created.plan_item = dict(item)
            self._emit_created(path)
            self._create_children(path, spec, parent_level=node.level)
            paths.append(path)
        self._bus.emit(
            EventKind.EXPAND_PLANNED,
            inst.task_path,
            ts=self._clock.now(),
            stage="dynamic",
            count=len(paths),
            slots=[p.rsplit("/", 1)[-1] for p in paths],
            plan_id=(decompose.plan_doc or {}).get("plan_id"),
        )

    def _materialize(self, inst: Any, plan: FanoutPlan) -> None:
        node = self._node_for(inst)
        assert node is not None
        for item, path in zip(plan.items, plan.instance_paths):
            if self._tree.lookup(path) is not None:
                raise PlanError(f"展开实例路径冲突: {path}", code="FANOUT_DUP")
            created = self._tree.create(
                path,
                parent_path=inst.task_path,
                spec_ref=inst.spec_ref,
                node_kind=NodeKind.TASK,
                created_by="fanout",
            )
            created.fanout_value = item.value
            created.fanout_index = item.index
            self._emit_created(path)

    # ------------------------------------------------------------------ 辅助
    def _node_for(self, inst: Any) -> SubtaskNode | None:
        spec = self._specs[inst.spec_ref]
        own_id = inst.task_path.rsplit("/", 1)[-1]
        node = spec.subtask_by_id(own_id)
        if node is not None:
            return node
        parent_id = inst.parent_path.rsplit("/", 1)[-1]
        return spec.subtask_by_id(parent_id)

    def _expected_outputs(self, inst: Any):
        spec = self._specs[inst.spec_ref]
        node = self._node_for(inst)
        if node is not None and node.outputs:
            return node.outputs
        return spec.outputs

    def _join_sources(self, inst: Any, node: SubtaskNode | None) -> tuple[list[Any], Any]:
        """JOIN 的聚合来源。

        - 优先使用 spec 的 `join_from` 显式声明（D-02 修正）：每个条目相对 JOIN 的父路径
          解析到实例，取该实例的 children；叶子实例则取自身。
        - 未声明时才回退到历史行为（首个 dep 的 children），仅为 a3–a7 兼容。
        """
        if node is not None and node.join_from:
            sources: list[Any] = []
            seen: set[str] = set()
            first = None
            for ref in node.join_from:
                base = ref if ref.startswith("/") else f"{inst.parent_path}/{ref}"
                target = self._tree.lookup(base)
                if target is None:
                    raise PlanError(
                        f"JOIN {inst.task_path} 的聚合来源不存在: {base}", code="SPEC_JOIN_SOURCE"
                    )
                if first is None:
                    first = target
                children = self._tree.children(target.task_path) or [target]
                for child in children:
                    if child.task_path not in seen:
                        seen.add(child.task_path)
                        sources.append(child)
            return sources, first

        sources = self._tree.children(inst.task_path)
        dep_inst = self._tree.lookup(f"{inst.parent_path}/{inst.deps[0]}") if inst.deps else None
        if not sources and dep_inst is not None:
            sources = self._tree.children(dep_inst.task_path)
        return sources, dep_inst

    def _child_output_name(self, parent: Any) -> str:
        if parent is None:
            return "patch"
        node = self._node_for(parent)
        if node is not None and node.outputs:
            return node.outputs[0].name
        for child in self._tree.children(parent.task_path):
            if child.outputs:
                return next(iter(child.outputs))
        return "patch"

    def _subtask_prompt(self, inst: Any, node: SubtaskNode | None) -> tuple[str, dict[str, Resolved]]:
        ctx = self._ctx(inst.task_path)
        lines: list[str] = []
        snapshot: dict[str, Resolved] = {}
        for binding in node.inputs_template if node else ():
            if binding.source:
                resolved = resolve_source(binding.source, ctx)
            else:
                resolved = Resolved(binding.name, "", binding.name, "", "", binding.literal or "")
            snapshot[binding.name] = resolved
            lines.append(f"{binding.name}: {resolved.text}")
        if not lines:
            node_id = node.id if node else inst.task_path.rsplit("/", 1)[-1]
            lines.append(f"subtask: {node_id} of {inst.spec_ref}, deps={list(inst.deps)}")
        return "\n".join(lines), snapshot

    def _ctx(self, task_path: str) -> ResolveContext:
        inst = self._tree.lookup(task_path)
        return ResolveContext(
            run_id=self._run_id,
            task_path=task_path,
            lookup=self._tree.lookup,
            artifact_text=self._artifacts.get,
            project=self._project,
            fanout_value=inst.fanout_value if inst else None,
            fanout_index=inst.fanout_index if inst else None,
            plan_item=inst.plan_item if inst else None,
            children=self._tree.children,
        )

    def _snapshot_hash(self, snapshot: Mapping[str, Resolved]) -> str:
        payload = json.dumps({k: v.value_hash for k, v in snapshot.items()}, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def _to(self, inst: Any, to: Status, *, error: str | None = None) -> None:
        prev = inst.status
        self._tree.transition(inst.task_path, to)
        now = self._clock.now()
        if to is Status.RUNNING and inst.started_at is None:
            inst.started_at = now
        if to in (Status.DONE, Status.FAILED, Status.BLOCKED, Status.CANCELLED):
            inst.finished_at = now
        if error:
            inst.error = error
        self._bus.emit(
            EventKind.INSTANCE_STATE,
            inst.task_path,
            ts=now,
            **{"from": prev.value, "to": to.value, "node_kind": inst.node_kind.value, "duration_ms": inst.duration_ms},
        )

    def _fail(self, inst: Any, code: str, message: str, *, line: int | None = None) -> None:
        payload: dict[str, Any] = {"code": code, "message": message}
        if line is not None:
            payload["line"] = line
        target = Status.FAILED if inst.status in (Status.RUNNING, Status.CHECK) else Status.BLOCKED
        self._to(inst, target, error=f"{code}: {message}")
        self._bus.emit(EventKind.ERROR, inst.task_path, ts=self._clock.now(), **payload)

    def _maybe_finish_run(self) -> bool:
        if self._finished or self._root is None:
            return False
        root = self._tree.lookup(self._root)
        if root is None or not root.is_terminal:
            return False
        self._finished = True
        summary = self.summary()
        self._bus.emit(
            EventKind.RUN_FINISHED,
            self._root,
            ts=self._clock.now(),
            status=root.status.value,
            total=summary.total_instances,
            done=summary.done,
            failed=summary.failed,
            wall_time_ms=summary.wall_time_ms,
        )
        return True
