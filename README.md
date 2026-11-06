# 契衡 · 阶段一代码（Mock 执行器 + 可观测 DAG）

变更记录见 [CHANGELOG.md](CHANGELOG.md)。

前置条件：

- Windows + Python **3.11**（`>=3.11,<3.12`，不要用 3.12+）。
- CLI：`ruamel.yaml` 或 `PyYAML` 任一即可（`jsonschema` 阶段一未使用，可缺）。
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
| wheel 安装 | `pip install qihang-0.1.0-py3-none-any.whl[ui-qt]` | 离线分发、内网源 |

依赖分组：core-only = `ruamel.yaml`；`validation` = `jsonschema`（阶段一未使用）；`ui-qt` = `PyQt6==6.6.1` + `PyQt6-Qt6==6.6.2`；`dev` = pytest / pytest-qt / coverage / hypothesis / ruff / build / twine。

### PyQt6 版本注意

PyQt6 **6.11 及以上**在部分 Windows 环境存在 DLL 加载失败风险（典型报错 `0xC0000139`，入口点找不到）。`ui-qt` extras 已固定到 6.6.1 / Qt 6.6.2；手动安装时用：

```bat
python -m pip install PyQt6==6.6.1 PyQt6-Qt6==6.6.2
```

启动器检测到 PyQt6 不可用（缺失或 DLL 加载失败）时会输出上述中文提示并以退出码 4 结束，而不是抛裸 traceback；缺 `ruamel.yaml`/`PyYAML` 时同理。

## 启动自检

- 缺 YAML 依赖：`启动失败：缺少 YAML 解析依赖...`，退出码 4。
- 缺 PyQt6 / DLL 加载失败：`启动失败：PyQt6 加载失败...` + 安装与降级命令，退出码 4。
- 缺 `jsonschema`：只提示，不阻断 CLI（阶段一未使用）。

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
├─ specs/                         # A3/A4/A5/A6 定义（开发用；发布副本在 src/qihang/specs）
├─ src/qihang/
│  ├─ core/                       # 编排内核（零 PyQt）
│  ├─ app/                        # 应用服务
│  ├─ ui/                         # PyQt6 视图（theme/bridge/models/views/windows）
│  ├─ preflight.py                # 启动自检（中文依赖提示）
│  └─ cli.py
├─ tests/                         # unit / e2e / ui
└─ tools/                         # S-1/S-3 压测、主题与线程守卫、截图
```
