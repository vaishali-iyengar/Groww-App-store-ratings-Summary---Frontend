"""Sentence embeddings for clean reviews, cached on disk by review_id."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np

# Takes a list of texts, returns an (n, dim) array.
Encoder = Callable[[List[str]], np.ndarray]


def review_text(row: Dict[str, Any]) -> str:
    title = (row.get("title") or "").strip()
    return "%s. %s" % (title, row["text"]) if title else row["text"]


def cache_path(cache_dir: Path, model_name: str) -> Path:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", model_name).strip("_")
    return cache_dir / ("embeddings_%s.npz" % slug)


def sentence_encoder(model_name: str) -> Encoder:
    from sentence_transformers import SentenceTransformer  # heavy import, load lazily

    model = SentenceTransformer(model_name)

    def encode(texts: List[str]) -> np.ndarray:
        return model.encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False)

    return encode


LSA_MODEL = "tfidf-lsa"  # torch-free option: TF-IDF reduced with truncated SVD
NO_ENCODER_ENV = "PULSE_NO_ENCODER"  # set on Vercel: the bundle has no sentence-transformers


class EmbeddingError(RuntimeError):
    pass


def lsa_vectors(texts: List[str], dims: int = 100) -> np.ndarray:
    from sklearn.decomposition import TruncatedSVD
    from sklearn.feature_extraction.text import TfidfVectorizer

    tfidf = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), min_df=2, sublinear_tf=True)
    matrix = tfidf.fit_transform(texts)
    dims = max(1, min(dims, matrix.shape[1] - 1, len(texts) - 1))
    return TruncatedSVD(n_components=dims, random_state=0).fit_transform(matrix)


def _load_cache(path: Path) -> Dict[str, np.ndarray]:
    if not path.exists():
        return {}
    data = np.load(path, allow_pickle=False)
    return dict(zip(data["ids"].tolist(), data["vectors"]))


def embed_reviews(
    rows: List[Dict[str, Any]], cache_dir: Path, model_name: str, encoder: Optional[Encoder] = None
) -> np.ndarray:
    """Return L2-normalised vectors in the order of `rows`, encoding only uncached reviews."""
    if model_name == LSA_MODEL:  # fitted on this corpus, so never cached
        matrix = lsa_vectors([review_text(r) for r in rows]).astype(np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        return matrix / np.where(norms == 0, 1, norms)
    path = cache_path(cache_dir, model_name)
    cache = _load_cache(path)
    missing = [r for r in rows if r["review_id"] not in cache]
    if missing and encoder is None and os.environ.get(NO_ENCODER_ENV):
        raise EmbeddingError("Embeddings missing for %d reviews in this snapshot; rebuild the deploy bundle"
                             % len(missing))
    if missing:
        encoder = encoder or sentence_encoder(model_name)
        vectors = np.asarray(encoder([review_text(r) for r in missing]), dtype=np.float32)
        for row, vec in zip(missing, vectors):
            cache[row["review_id"]] = vec
        cache_dir.mkdir(parents=True, exist_ok=True)
        ids = sorted(cache)
        np.savez(path, ids=np.array(ids), vectors=np.stack([cache[i] for i in ids]))

    matrix = np.stack([cache[r["review_id"]] for r in rows]).astype(np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1, norms)
