# Changelog

## 0.2.0

- 发布包补入 `qihang/specs/*.yaml`，安装后 CLI 不再依赖仓库目录。
- `ui-qt` 固定 `PyQt6==6.6.1` + `PyQt6-Qt6==6.6.2`，规避部分 Windows 环境的 DLL 加载问题。
- 新增 `qihang-gui` 入口与 `tools/check_release.py` 发布守卫。

## 0.1.0

- 首个阶段一骨架：Mock 执行器、可观测 DAG、CLI 演示与最小 PyQt 视图。
