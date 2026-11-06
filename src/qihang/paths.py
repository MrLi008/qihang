"""资源与默认路径解析：源码运行与 wheel 安装共用同一套逻辑。

- specs 随包安装（`qihang/specs/*.yaml`），不依赖仓库根目录是否存在；
- 默认运行产物目录：源码仓库内落在仓库根 `.qihang/`，安装后落在当前目录 `.qihang/`，
  避免向 site-packages 写入。
"""

from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
SPECS_DIR = PACKAGE_ROOT / "specs"
SCHEMAS_DIR = PACKAGE_ROOT / "schemas"


def _dev_repo_root() -> Path | None:
    candidate = PACKAGE_ROOT.parents[1]
    if (candidate / "pyproject.toml").is_file() and (candidate / "src").is_dir():
        return candidate
    return None


def default_specs_dir() -> Path:
    """优先当前目录的 specs/（便于用户自定义场景），否则使用随包安装的内置 specs。"""
    local = Path.cwd() / "specs"
    if (local / "a4.yaml").is_file():
        return local
    return SPECS_DIR


def default_runs_dir() -> Path:
    root = _dev_repo_root() or Path.cwd()
    return root / ".qihang" / "runs"


def default_bench_dir() -> Path:
    """压测产物目录：源码仓库内落在 `bench-out/`，安装后落在当前目录。"""
    root = _dev_repo_root() or Path.cwd()
    return root / "bench-out"
