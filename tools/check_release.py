"""发布守卫：扫描包内源码与发布配置，发现绝对路径/凭据/本机环境信息即失败。

用法：`python tools/check_release.py`；退出码 0=PASS，1=发现违规。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()

SKIP_DIRS = {"__pycache__", ".qihang", "bench-out", "build", "dist", ".git"}
TEXT_SUFFIXES = {".py", ".toml", ".md", ".txt", ".yaml", ".yml", ".json", ".qss", ".cmd", ".in", ".cfg", ".ini"}

RULES = [
    ("绝对路径（Windows 盘符）", re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/]")),
    ("绝对路径（用户目录）", re.compile(r"(?<![\w.])/(?:Users|home)/")),
    ("本机用户名", re.compile(r"\bAdministrator\b|ADMINI~1", re.IGNORECASE)),
    ("本机主机名", re.compile(r"\bDESKTOP-[A-Z0-9]{4,}\b", re.IGNORECASE)),
    ("本机 conda 环境名", re.compile(r"(?<![\w-])(?:pycuda|n_c_r_release)(?![\w-])", re.IGNORECASE)),
    ("发行版环境特例", re.compile(r"\bAnaconda\b", re.IGNORECASE)),
    ("内部仓库标识", re.compile(r"mrli008|auto_code_demo", re.IGNORECASE)),
    ("凭据：PyPI token", re.compile(r"pypi-AgEI[A-Za-z0-9_-]{10,}")),
    ("凭据：私钥", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("凭据：URL 内嵌账号密码", re.compile(r"https?://[^\s/@:]+:[^\s/@]+@")),
    (
        "凭据：密码赋值",
        re.compile(
            r"(?:TWINE_PASSWORD|password|passwd)\s*[:=]\s*['\"]?(?!\.{3}|<)[^\s'\"#]{6,}",
            re.IGNORECASE,
        ),
    ),
]


def _targets() -> list[Path]:
    files: list[Path] = []
    for name in ("pyproject.toml", "MANIFEST.in", "README.md", "CHANGELOG.md", "LICENSE",
                 "run.py", "run.cmd", "gui.cmd", "setup.py"):
        path = ROOT / name
        if path.is_file():
            files.append(path)
    for folder in ("src", "tests", "tools", "specs", ".github"):
        base = ROOT / folder
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path == SELF:
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.suffix.lower() in TEXT_SUFFIXES:
                files.append(path)
    return files


def main() -> int:
    violations: list[str] = []
    scanned = 0
    for path in _targets():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        scanned += 1
        for lineno, line in enumerate(text.splitlines(), 1):
            for rule, pattern in RULES:
                if pattern.search(line):
                    rel = path.relative_to(ROOT).as_posix()
                    violations.append(f"{rel}:{lineno}  {rule}  ->  {line.strip()[:120]}")
    if violations:
        print(f"[FAIL] 发布守卫：{len(violations)} 处敏感信息")
        for item in violations:
            print("  " + item)
        return 1
    print(f"[PASS] 发布守卫：扫描 {scanned} 个文件，未发现绝对路径/凭据/本机环境信息")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
