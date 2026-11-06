"""setuptools 构建钩子：sdist 归档前剔除自动生成的 egg-info，避免本地元数据随包发布。"""

from __future__ import annotations

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.sdist import sdist


class CleanSdist(sdist):
    def make_release_tree(self, base_dir, files):  # type: ignore[override]
        super().make_release_tree(base_dir, files)
        for egg in Path(base_dir).rglob("*.egg-info"):
            shutil.rmtree(egg, ignore_errors=True)


setup(cmdclass={"sdist": CleanSdist})
