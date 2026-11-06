# 契衡 · 阶段一代码（Mock 执行器 + 可观测 DAG）

变更记录见 [CHANGELOG.md](CHANGELOG.md)。

前置条件：

- Windows + Python **3.11**（`>=3.11,<3.12`，不要用 3.12+）。
- CLI：`ruamel.yaml` 或 `PyYAML` 任一即可；`jsonschema` 可选（装了 `[validation]` 会启用严格 schema 校验，不装也能用内置轻量校验）。
- GUI：额外需要 `PyQt6`（推荐按 `ui-qt` extras 的固定版本安装）。

### CLI

双击 `run.cmd`（无参数时会打印用法并 `pause`，不会闪退）；或在 `code\` 目录下：

```bat
python run.py run --scenario a4
run.cmd run --scenario a4
```

在任意当前目录运行 CLI 时，用启动器的完整路径（把 `<code 目录>` 换成实际位置）：

```bat
python <code 目录>\run.py run --scenario a4
```

需要指定解释器（例如某个 conda 环境）时，只对本次命令生效：

```bat
set QIHANG_PYTHON=<python.exe 路径>
run.cmd run --scenario a4
```

PowerShell 等价写法（`QIHANG_PYTHON` 只影响当前窗口）：

```powershell
$env:QIHANG_PYTHON = "<python.exe 路径>"
.\run.cmd run --scenario a4
```

### GUI

```bat
python run.py --gui
gui.cmd
```

无显示环境可用离屏自检（构造窗口并退出，不进入事件循环）：

```bat
set QT_QPA_PLATFORM=offscreen
python run.py --gui --self-check
```

PowerShell：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python run.py --gui --self-check
```

### 为什么不能直接 `python -m qihang`

项目是 `src` 布局且未安装，`python -m qihang` 依赖 `site-packages` 里的包注册，未安装时必然报 `No module named 'qihang'`。零安装请使用 `run.py` / `run.cmd` / `gui.cmd`；只有执行了下面的"安装方式"之后，`python -m qihang` 才可用。

`python cli.py` 现在也能跑（入口会自行补齐 `sys.path`），但不推荐：它没有正常的包上下文，后续扩展容易踩坑。

## 安装方式（可选，两种方式都能用）

```bat
cd code
python -m pip install -e .              :: CLI（core-only，不含 Qt）
python -m pip install -e ".[ui-qt]"     :: GUI（固定 PyQt6 6.6.1 / Qt 6.6.2）
```

安装后可用 `qihang run --scenario a4`、`qihang-gui`（等价于 `python -m qihang run`）。

| 方式 | 命令 | 适用 |
|---|---|---|
| 免安装（推荐给临时试用） | `run.cmd run --scenario a4` / `gui.cmd` | 不改环境、不需要网络 |
| editable 安装 | `pip install -e ".[ui-qt]"` 后 `qihang run` / `qihang-gui` | 需要 `python -m` / `qihang` 命令 / 长期开发 |
| wheel 安装 | `pip install qihang-0.3.0-py3-none-any.whl[ui-qt]` | 离线分发、内网源 |

依赖分组：core-only = `ruamel.yaml`；`validation` = `jsonschema`（可选，启用严格 schema 校验）；`ui-qt` = `PyQt6==6.6.1` + `PyQt6-Qt6==6.6.2`；`dev` = pytest / pytest-qt / coverage / hypothesis / ruff / build / twine。

### PyQt6 版本注意

PyQt6 **6.11 及以上**在部分 Windows 环境存在 DLL 加载失败风险（典型报错 `0xC0000139`，入口点找不到）。`ui-qt` extras 已固定到 6.6.1 / Qt 6.6.2；手动安装时用：

```bat
python -m pip install PyQt6==6.6.1 PyQt6-Qt6==6.6.2
```

启动器检测到 PyQt6 不可用（缺失或 DLL 加载失败）时会输出上述中文提示并以退出码 4 结束，而不是抛裸 traceback；缺 `ruamel.yaml`/`PyYAML` 时同理。

## 启动自检

- 缺 YAML 依赖：`启动失败：缺少 YAML 解析依赖...`，退出码 4。
- 缺 PyQt6 / DLL 加载失败：`启动失败：PyQt6 加载失败...` + 安装与降级命令，退出码 4。
- 缺 `jsonschema`：只提示，不阻断；内置轻量校验照常工作。
- spec 不合法：CLI 打印 `spec 错误：...`（含字段路径）并以退出码 3 结束；GUI 在添加/导入弹窗中提示，不写坏文件。

## GUI 添加 Agent

主窗口的 Agent 下拉列表从 `specs/` 目录动态加载（新增/导入后重启仍在）：

- “添加 Agent”：填写标识、展示名、角色、子任务模式、展开方式、实例数、是否可动态扩展，保存前即做校验；
- “导入 Spec”：选择 YAML，校验通过后复制进 `specs/`；
- 字段级说明见 [../docs/07-元数据定义.md](../docs/07-元数据定义.md)。

## 规模压测

A7 场景默认展开 500 个子实例（S1 → E1 fan-out `S2.1..S2.500` → J1 → S3），数量来自 `specs/a7.yaml` 的 `parameters.list_size` / `E1.max_instances`，代码不写死。

```bat
python run.py --gui --scenario A7 --delay 0.02 --bench
```

- `--delay 0.02`：本次运行的单任务基础耗时；默认 1.0 不变，压测时显式压低，避免 500 实例 × 1s。
- `--bench`：跑完自动汇总、落盘 `bench-out/gui_A7_505nodes.json` 并退出；有桌面会真实上屏，无显示用 `QT_QPA_PLATFORM=offscreen`。
- `--bench-out` / `--bench-timeout`：产物目录与最长等待秒数。

指标怎么看：

| 指标 | 含义 | 达标线 |
| --- | --- | --- |
| 心跳漂移 p99 | 100ms QTimer 的实际间隔 − 100ms | ≤ 100ms |
| DAG 每批渲染 p99 | 一次 `apply_events` 的耗时 | 越低越好 |
| 估算帧率 | 相邻渲染批间隔折算 | ≥ 30fps |
| 实例树最大单批 | 批量插入/更新耗时 | 越低越好 |
| 事件总数 / 单批最大 | 事件吞吐与批大小 | 观察项 |
| 内存峰值 | tracemalloc 进程内峰值 | 观察项 |

不达标时 JSON 的 `bottleneck_hint` 会指出是事件批节奏、DAG 布局重排还是实例树整批更新。

## CLI 输出

```text
[069] RUN_FINISHED      /A4       status=DONE total=8 wall=3813ms
实例树终态：
  A4       DONE     844ms  outputs=artifact
    S1       DONE     969ms  outputs=file_list
    ...
完成：status=DONE instances=8 done=8 failed=0 wall=3812ms events=69
```

运行产物写到 `code/.qihang/runs/<run_id>/`（`journal.jsonl`、`tree.json`），与当前目录无关。

## 目录速览

```text
code/
├─ run.py / run.cmd / gui.cmd     # 零安装启动入口
├─ pyproject.toml                 # core-only / ui-qt / dev 三组依赖
├─ specs/                         # A3/A4/A5/A6/A7 定义（开发用；发布副本在 src/qihang/specs）
├─ src/qihang/
│  ├─ core/                       # 编排内核（零 PyQt）
│  ├─ app/                        # 应用服务（含 spec 列表/校验/落盘）
│  ├─ schemas/                    # Agent Spec JSON Schema（随 wheel 分发）
│  ├─ ui/                         # PyQt6 视图（theme/bridge/models/views/windows/bench）
│  ├─ preflight.py                # 启动自检（中文依赖提示）
│  └─ cli.py
├─ tests/                         # unit / e2e / ui
└─ tools/                         # S-1/S-3 压测、主题与线程守卫、截图
```
