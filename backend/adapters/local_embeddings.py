"""Local ONNX embeddings with a persistent text/model cache."""

import hashlib
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from contextlib import closing
from pathlib import Path
from typing import Protocol

import numpy as np
from fastembed import TextEmbedding


class ModelUnavailable(Exception):
    pass


class Encoder(Protocol):
    model_id: str

    def embed(self, texts: list[str]) -> Iterable[np.ndarray]: ...


class FastEmbedEncoder:
    def __init__(
        self, model_name: str, cache_dir: Path, model_path: Path | None, offline: bool
    ) -> None:
        if model_path is not None and not model_path.is_dir():
            raise ModelUnavailable(f"模型目录不存在：{model_path}")
        cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._model = TextEmbedding(
                model_name=model_name,
                cache_dir=str(cache_dir),
                specific_model_path=str(model_path) if model_path else None,
                local_files_only=offline,
            )
        except Exception as exc:
            mode = "离线加载" if offline else "下载或加载"
            raise ModelUnavailable(
                f"向量模型{mode}失败（{type(exc).__name__}）；请检查模型名称、目录与网络"
            ) from exc
        self.model_id = f"{model_name}:{self._fingerprint()}"

    def _fingerprint(self) -> str:
        loaded_path = getattr(self._model.model, "_model_dir", None)
        if loaded_path is None:
            raise ModelUnavailable("无法定位已加载模型的权重目录")
        model_dir = Path(loaded_path)
        if not model_dir.is_dir():
            raise ModelUnavailable("向量模型目录不存在")
        digest = hashlib.sha256()
        for path in sorted(file for file in model_dir.rglob("*") if file.is_file()):
            digest.update(str(path.relative_to(model_dir)).encode())
            with path.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
        return digest.hexdigest()[:16]

    def embed(self, texts: list[str]) -> Iterable[np.ndarray]:
        return self._model.embed(texts, batch_size=32)


SCHEMA = """
CREATE TABLE IF NOT EXISTS embedding_cache (
    model_id TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    dimension INTEGER NOT NULL,
    vector BLOB NOT NULL,
    PRIMARY KEY (model_id, text_hash)
);
"""


class EmbeddingCache:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "embeddings.sqlite3"

    def vectors(
        self,
        encoder: Encoder,
        texts: Sequence[str],
        on_call: Callable[[list[str]], None] | None = None,
    ) -> dict[str, np.ndarray]:
        unique = list(dict.fromkeys(texts))
        if not unique:
            return {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            connection.executescript(SCHEMA)
            results: dict[str, np.ndarray] = {}
            missing: list[str] = []
            for text in unique:
                key = hashlib.sha256(text.encode()).hexdigest()
                row = connection.execute(
                    "SELECT dimension, vector FROM embedding_cache "
                    "WHERE model_id = ? AND text_hash = ?",
                    (encoder.model_id, key),
                ).fetchone()
                if row is None:
                    missing.append(text)
                else:
                    results[text] = np.frombuffer(row[1], dtype=np.float32, count=row[0])
            for start in range(0, len(missing), 32):
                batch = missing[start : start + 32]
                try:
                    vectors = list(encoder.embed(batch))
                except Exception as exc:
                    raise ModelUnavailable(f"向量编码失败（{type(exc).__name__}）") from exc
                finally:
                    if on_call is not None:
                        on_call(batch)
                if len(vectors) != len(batch):
                    raise ModelUnavailable("向量模型返回数量与输入不一致")
                for text, value in zip(batch, vectors, strict=True):
                    vector = np.asarray(value, dtype=np.float32).reshape(-1)
                    if (
                        not vector.size
                        or not np.isfinite(vector).all()
                        or not np.linalg.norm(vector)
                    ):
                        raise ModelUnavailable("向量模型返回无效向量")
                    results[text] = vector
                    connection.execute(
                        "INSERT OR IGNORE INTO embedding_cache "
                        "(model_id, text_hash, dimension, vector) VALUES (?, ?, ?, ?)",
                        (
                            encoder.model_id,
                            hashlib.sha256(text.encode()).hexdigest(),
                            int(vector.size),
                            vector.tobytes(),
                        ),
                    )
            connection.commit()
        return results
