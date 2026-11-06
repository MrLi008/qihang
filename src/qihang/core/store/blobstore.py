"""内容寻址产物存储：先算 hash 再落盘，artifact_id 由 hash 派生。"""

from __future__ import annotations

import hashlib
from pathlib import Path


class BlobStore:
    def __init__(self, root: Path | None = None) -> None:
        self._root = root
        self._memory: dict[str, str] = {}
        self._hashes: dict[str, str] = {}
        if root is not None:
            root.mkdir(parents=True, exist_ok=True)

    def put(self, text: str, *, prefix: str = "art") -> tuple[str, str]:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        artifact_id = f"{prefix}-{digest[:12]}"
        if artifact_id not in self._hashes:
            self._hashes[artifact_id] = digest
            if self._root is None:
                self._memory[artifact_id] = text
            else:
                path = self._root / digest[:2] / f"{digest}.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists():
                    path.write_text(text, encoding="utf-8")
        return artifact_id, digest

    def get(self, artifact_id: str) -> str:
        if artifact_id in self._memory:
            return self._memory[artifact_id]
        digest = self._hashes.get(artifact_id)
        if digest is None or self._root is None:
            raise KeyError(f"未知产物: {artifact_id}")
        return (self._root / digest[:2] / f"{digest}.md").read_text(encoding="utf-8")
