# Changelog

## 0.4.0

- 新增 A9 多层动态展开场景（`parameters.levels` / `branch` 驱动三层 DECOMPOSE，默认 30 实例），CLI/GUI 可直接选择。
- 新增跨层 DataRef：链式 `children.by_id`、`ancestors`、`owner`、`descendants.by_kind` 多级聚合。
- JOIN 新增 `join_from` 显式聚合来源，修正 D-02“首个 dep children”隐式回退；A9 已显式声明。
- Agent Spec 升到 `schema_version 6`（兼容 4–6），新增节点 `level` 字段；文档见 `docs/07-元数据定义.md`。

## 0.3.0

- 新增机器可读 Agent Spec 规范：包内 `schemas/agent_spec.schema.json`，加载器接入 schema 校验，未知字段/类型/缺必填给中文路径错误；`[validation]` extras 可升级为严格校验。
- 新增 A7 规模场景（默认 500 子实例）与 GUI 动态 Agent 列表、新建/导入 spec；新增 GUI 压测指标（心跳漂移、DAG 渲染、实例树批量、事件与内存）。

## 0.2.0

- 发布包补入 `qihang/specs/*.yaml`，安装后 CLI 不再依赖仓库目录。
- `ui-qt` 固定 `PyQt6==6.6.1` + `PyQt6-Qt6==6.6.2`，规避部分 Windows 环境的 DLL 加载问题。
- 新增 `qihang-gui` 入口与 `tools/check_release.py` 发布守卫。

## 0.1.0

- 首个阶段一骨架：Mock 执行器、可观测 DAG、CLI 演示与最小 PyQt 视图。
