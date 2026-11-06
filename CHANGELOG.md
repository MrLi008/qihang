# Changelog

## 0.3.0

- 新增机器可读 Agent Spec 规范：包内 `schemas/agent_spec.schema.json`，加载器接入 schema 校验，未知字段/类型/缺必填给中文路径错误；`[validation]` extras 可升级为严格校验。
- 新增 A7 规模场景（默认 500 子实例）与 GUI 动态 Agent 列表、新建/导入 spec；新增 GUI 压测指标（心跳漂移、DAG 渲染、实例树批量、事件与内存）。

## 0.2.0

- 发布包补入 `qihang/specs/*.yaml`，安装后 CLI 不再依赖仓库目录。
- `ui-qt` 固定 `PyQt6==6.6.1` + `PyQt6-Qt6==6.6.2`，规避部分 Windows 环境的 DLL 加载问题。
- 新增 `qihang-gui` 入口与 `tools/check_release.py` 发布守卫。

## 0.1.0

- 首个阶段一骨架：Mock 执行器、可观测 DAG、CLI 演示与最小 PyQt 视图。
