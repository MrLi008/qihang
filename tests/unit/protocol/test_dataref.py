from qihang.core.errors import DataRefError
from qihang.core.model.enums import NodeKind, Status
from qihang.core.model.runtime import ArtifactRef
from qihang.core.protocol.dataref import ResolveContext, resolve_ref
from qihang.core.runtime.task_tree import TaskTree
from qihang.core.store.blobstore import BlobStore


def _done(tree: TaskTree, path: str, output: str, text: str, store: BlobStore) -> None:
    inst = tree.require(path)
    for status in (Status.READY, Status.RUNNING, Status.CHECK, Status.DONE):
        tree.transition(path, status)
    artifact_id, digest = store.put(text)
    inst.outputs[output] = ArtifactRef(artifact_id, digest, output)


def _fixture() -> tuple[TaskTree, BlobStore, ResolveContext]:
    tree = TaskTree()
    store = BlobStore()
    tree.create("/A4", parent_path="/", spec_ref="A4", node_kind=NodeKind.TASK)
    tree.create("/A4/S1", parent_path="/A4", spec_ref="A4", node_kind=NodeKind.TASK)
    tree.create("/A4/E1", parent_path="/A4", spec_ref="A4", node_kind=NodeKind.EXPAND)
    tree.create("/A4/E1/S2.1", parent_path="/A4/E1", spec_ref="A4", node_kind=NodeKind.TASK)
    tree.create("/A4/E1/S2.2", parent_path="/A4/E1", spec_ref="A4", node_kind=NodeKind.TASK)
    _done(tree, "/A4/S1", "file_list", '["auth.py", "login.py"]', store)
    _done(tree, "/A4/E1/S2.2", "patch", "patch-2", store)
    ctx = ResolveContext(
        run_id="R-T",
        task_path="/A4/E1/S2.1",
        lookup=tree.lookup,
        artifact_text=store.get,
        project={"constraints": "python3.11"},
        fanout_value="auth.py",
        fanout_index=1,
    )
    return tree, store, ctx


def test_self_and_siblings_with_dotted_instance_id() -> None:
    """D-1：siblings.S2.2 不能因为 split('.', 1) 被切成 S2 + 2.outputs.patch。"""
    _, _, ctx = _fixture()
    resolved = resolve_ref("{{siblings.S2.2.outputs.patch}}", ctx)
    assert resolved.task_path == "/A4/E1/S2.2"
    assert resolved.text == "patch-2"


def test_children_by_id_from_parent_context() -> None:
    tree, store, _ = _fixture()
    ctx = ResolveContext("R-T", "/A4", tree.lookup, store.get)
    resolved = resolve_ref("{{children.by_id.S1.outputs.file_list}}", ctx)
    assert resolved.text.startswith('["auth.py"')


def test_children_aggregate_requires_join_context() -> None:
    tree, store, _ = _fixture()
    ctx = ResolveContext("R-T", "/A4", tree.lookup, store.get)
    try:
        resolve_ref("{{children.*.outputs.patch}}", ctx)
    except DataRefError as exc:
        assert exc.code == "REF_AGGREGATE_CONTEXT"
    else:  # pragma: no cover
        raise AssertionError("应当在非 JOIN 上下文失败")


def test_fanout_and_project() -> None:
    _, _, ctx = _fixture()
    assert resolve_ref("{{fanout.item}}", ctx).text == "auth.py"
    assert resolve_ref("{{fanout.index}}", ctx).text == "1"
    assert resolve_ref("{{project.constraints}}", ctx).text == "python3.11"


def _multilevel_fixture() -> tuple[TaskTree, BlobStore, ResolveContext]:
    tree = TaskTree()
    store = BlobStore()
    for path, parent, kind in [
        ("/A9", "/", NodeKind.TASK),
        ("/A9/DECOMPOSE", "/A9", NodeKind.DECOMPOSE),
        ("/A9/E1", "/A9", NodeKind.DYNAMIC_EXPAND),
        ("/A9/E1/T1", "/A9/E1", NodeKind.TASK),
        ("/A9/E1/T1/DECOMPOSE", "/A9/E1/T1", NodeKind.DECOMPOSE),
        ("/A9/E1/T1/E2", "/A9/E1/T1", NodeKind.DYNAMIC_EXPAND),
        ("/A9/E1/T1/E2/T1.1", "/A9/E1/T1/E2", NodeKind.TASK),
        ("/A9/E1/T1/E2/T1.1/DECOMPOSE", "/A9/E1/T1/E2/T1.1", NodeKind.DECOMPOSE),
        ("/A9/E1/T1/E2/T1.1/E3", "/A9/E1/T1/E2/T1.1", NodeKind.DYNAMIC_EXPAND),
        ("/A9/E1/T1/E2/T1.1/E3/T1.1.1", "/A9/E1/T1/E2/T1.1/E3", NodeKind.TASK),
    ]:
        tree.create(path, parent_path=parent, spec_ref="A9", node_kind=kind)
    _done(tree, "/A9/DECOMPOSE", "plan", "root-plan", store)
    _done(tree, "/A9/E1/T1/DECOMPOSE", "plan", "l1-plan", store)
    _done(tree, "/A9/E1/T1/E2/T1.1/DECOMPOSE", "plan", "l2-plan", store)
    _done(tree, "/A9/E1/T1/E2/T1.1/E3/T1.1.1", "patch", "leaf-patch", store)
    _done(tree, "/A9/E1/T1", "patch", "l1-patch", store)
    _done(tree, "/A9/E1/T1/E2/T1.1/E3", "aggregate", '{"coverage":"2/2"}', store)
    ctx = ResolveContext(
        "R-T", "/A9", tree.lookup, store.get, children=tree.children
    )
    return tree, store, ctx


def test_multilevel_children_chain_resolves_leaf_artifact() -> None:
    _, _, ctx = _multilevel_fixture()
    ref = "{{children.by_id.E1.children.by_id.T1.children.by_id.E2.children.by_id.T1.1.children.by_id.E3.outputs.aggregate}}"
    resolved = resolve_ref(ref, ctx)
    assert resolved.task_path == "/A9/E1/T1/E2/T1.1/E3"
    assert resolved.text == '{"coverage":"2/2"}'


def test_owner_scope_reads_upper_confirmed_plan() -> None:
    _, _, ctx = _multilevel_fixture()
    deep = ResolveContext(
        run_id="R-T",
        task_path="/A9/E1/T1/E2/T1.1/E3/T1.1.1",
        lookup=ctx.lookup,
        artifact_text=ctx.artifact_text,
        children=ctx.children,
    )
    assert resolve_ref("{{owner.DECOMPOSE.outputs.plan}}", deep).text == "l2-plan"


def test_ancestors_scope_finds_nearest_done_ancestor() -> None:
    _, _, ctx = _multilevel_fixture()
    deep = ResolveContext(
        run_id="R-T",
        task_path="/A9/E1/T1/E2/T1.1/E3/T1.1.1",
        lookup=ctx.lookup,
        artifact_text=ctx.artifact_text,
        children=ctx.children,
    )
    assert resolve_ref("{{ancestors.by_id.T1.outputs.patch}}", deep).text == "l1-patch"


def test_descendants_aggregate_across_levels_skips_failed() -> None:
    tree, _, ctx = _multilevel_fixture()
    tree.transition("/A9/E1/T1/E2/T1.1", Status.READY)
    tree.transition("/A9/E1/T1/E2/T1.1", Status.RUNNING)
    tree.transition("/A9/E1/T1/E2/T1.1", Status.FAILED)
    text = resolve_ref("{{descendants.by_kind.task.outputs.patch}}", ctx).text
    assert "/A9/E1/T1/E2/T1.1/E3/T1.1.1" in text
    assert '"/A9/E1/T1/E2/T1.1":' not in text


def test_not_done_target_is_rejected() -> None:
    tree, store, _ = _fixture()
    ctx = ResolveContext("R-T", "/A4/E1/S2.1", tree.lookup, store.get)
    try:
        resolve_ref("{{siblings.S2.1.outputs.patch}}", ctx)
    except DataRefError as exc:
        assert exc.code == "REF_NOT_DONE"
    else:  # pragma: no cover
        raise AssertionError("PENDING 实例不应解析成功")
