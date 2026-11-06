"""CLI 演示：`python -m qihang run --scenario a4`。

终端上按事件顺序打印事件流，结束后打印实例树终态与摘要。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

if __package__ in (None, ""):  # 支持 `python src/qihang/cli.py run`（不推荐，但不再抛 ModuleNotFoundError）
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qihang.app.run_session import create_session
from qihang.core.errors import SpecError
from qihang.core.runtime.scheduler import RunLoop
from qihang.paths import default_runs_dir, default_specs_dir
from qihang.preflight import require_core


def _event_line(event) -> str:
    payload = event.payload
    kind = event.kind
    path = event.task_path or "-"
    detail = ""
    if kind == "RUN_STARTED":
        detail = f"agent={payload.get('agent')}"
    elif kind == "INSTANCE_CREATED":
        detail = f"{payload.get('node_kind')} by={payload.get('created_by')}"
    elif kind == "INSTANCE_STATE":
        detail = f"{payload.get('from')} -> {payload.get('to')}"
        if payload.get("duration_ms") is not None:
            detail += f" ({payload['duration_ms']}ms)"
    elif kind == "LLM_REQUEST":
        detail = f"executor={payload.get('executor')} outputs={payload.get('outputs')}"
    elif kind == "LLM_RESPONSE":
        detail = f"latency={payload.get('latency_ms')}ms tokens={payload.get('tokens')}"
    elif kind == "ARTIFACT_WRITTEN":
        detail = f"{payload.get('output')} hash={payload.get('hash')} size={payload.get('size')}"
    elif kind == "EXPAND_PLANNED":
        detail = f"{payload.get('stage')} count={payload.get('count')} slots={payload.get('slots')}"
    elif kind == "JOIN_DONE":
        detail = f"{payload.get('stage')} coverage={payload.get('coverage')} failures={payload.get('failures')}"
    elif kind == "ERROR":
        detail = f"{payload.get('code')}: {payload.get('message')} line={payload.get('line')}"
    elif kind == "RUN_FINISHED":
        detail = f"status={payload.get('status')} total={payload.get('total')} wall={payload.get('wall_time_ms')}ms"
    return f"[{event.seq:03d}] {kind:<17} {path:<24} {detail}"


def _print_tree(tree, root: str) -> None:
    def walk(path: str, depth: int) -> None:
        inst = tree.require(path)
        duration = f"{inst.duration_ms}ms" if inst.duration_ms is not None else "-"
        outputs = ",".join(inst.outputs) or "-"
        error = f" error={inst.error}" if inst.error else ""
        print(f"  {'  ' * depth}{path.rsplit('/', 1)[-1]:<8} {inst.status.value:<7} {duration:>6}  outputs={outputs}{error}")
        for child in tree.children(path):
            walk(child.task_path, depth + 1)

    print("\n实例树终态：")
    walk(root, 0)


def _dump_tree(tree, root: str) -> list[dict]:
    out = []

    def walk(path: str) -> None:
        inst = tree.require(path)
        out.append(
            {
                "task_path": inst.task_path,
                "parent_path": inst.parent_path,
                "node_kind": inst.node_kind.value,
                "status": inst.status.value,
                "created_by": inst.created_by,
                "deps": list(inst.deps),
                "duration_ms": inst.duration_ms,
                "outputs": {k: asdict(v) for k, v in inst.outputs.items()},
                "input_snapshot": {k: asdict(v) for k, v in inst.input_snapshot.items()},
                "error": inst.error,
            }
        )
        for child in tree.children(path):
            walk(child.task_path)

    walk(root)
    return out


def _run_one(agent_id: str, args: argparse.Namespace, run_id: str) -> dict:
    run_dir = Path(args.runs_dir) / run_id
    session = create_session(
        Path(args.specs_dir),
        run_dir,
        run_id=run_id,
        delay_s=args.delay,
        fail_inject={k: "closed_missing" for k in args.fail},
    )
    print(f"\n=== Run {run_id} · agent {agent_id} ===")
    root = session.orchestrator.start(agent_id)
    kernel = RunLoop(session.orchestrator)
    kernel.start()
    started = time.monotonic()
    events_total = 0
    try:
        while kernel.is_alive() or not session.orchestrator.is_finished():
            batch = session.bus.drain(500)
            for event in batch:
                session.journal.append(event)
                if not args.quiet:
                    print(_event_line(event))
                events_total += 1
            if not batch:
                time.sleep(0.01)
        # 收尾事件
        for event in session.bus.drain(500):
            session.journal.append(event)
            if not args.quiet:
                print(_event_line(event))
            events_total += 1
        summary = session.orchestrator.summary()
        tree = session.orchestrator.tree
        if not args.quiet:
            _print_tree(tree, root)
        elapsed = int((time.monotonic() - started) * 1000)
        payload = {
            "run_id": run_id,
            "agent": agent_id,
            "status": summary.status.value,
            "instances": summary.total_instances,
            "done": summary.done,
            "failed": summary.failed,
            "blocked": summary.blocked,
            "wall_time_ms": elapsed,
            "events": events_total,
            "tree": _dump_tree(tree, root),
        }
        (run_dir / "tree.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            f"完成：status={summary.status.value} instances={summary.total_instances} "
            f"done={summary.done} failed={summary.failed} wall={elapsed}ms events={events_total}"
        )
        return payload
    finally:
        kernel.stop()
        kernel.join(timeout=2)
        session.close()


def main(argv: list[str] | None = None) -> int:
    require_core()
    parser = argparse.ArgumentParser(prog="qihang", description="契衡编排平台 · 阶段一 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="跑一个 mock 场景")
    run.add_argument("--scenario", choices=["a3", "a4", "a5", "a6", "a7", "all"], default="a4")
    run.add_argument("--delay", type=float, default=1.0, help="每个任务的基础耗时（秒，默认 1.0）")
    run.add_argument("--fail", action="append", default=[], help="注入失败的任务路径后缀，如 S2.3")
    run.add_argument("--specs-dir", default=str(default_specs_dir()))
    run.add_argument("--runs-dir", default=str(default_runs_dir()))
    run.add_argument("--quiet", action="store_true", help="只打印最终摘要")
    args = parser.parse_args(argv)

    if args.command == "run":
        scenarios = ["A3", "A4", "A5", "A6"] if args.scenario == "all" else [args.scenario.upper()]
        results = []
        try:
            for i, agent in enumerate(scenarios, 1):
                run_id = f"R-{i:03d}-{agent}"
                results.append(_run_one(agent, args, run_id))
        except SpecError as exc:
            print(f"spec 错误：{exc.message}", file=sys.stderr)
            print("请修正 spec 后重试；字段说明见 docs/07-元数据定义.md。", file=sys.stderr)
            return 3
        except KeyError as exc:
            print(f"场景不存在：{exc}。可选：a3/a4/a5/a6/a7/all", file=sys.stderr)
            return 3
        if len(results) > 1:
            print("\n汇总：")
            for r in results:
                print(
                    f"  {r['run_id']:<12} {r['status']:<7} instances={r['instances']:<3} "
                    f"done={r['done']:<3} failed={r['failed']:<3} wall={r['wall_time_ms']}ms"
                )
        return 0 if all(r["status"] == "DONE" for r in results) else 2
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
