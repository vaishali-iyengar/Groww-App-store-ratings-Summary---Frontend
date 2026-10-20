"""k-means clustering, then merge the smallest clusters into their nearest neighbour."""
from __future__ import annotations

from typing import Tuple

import numpy as np
from sklearn.cluster import KMeans

SEED = 0  # fixed so two runs on the same data give the same clusters


def _centroids(vectors: np.ndarray, labels: np.ndarray, ids: np.ndarray) -> np.ndarray:
    cents = np.stack([vectors[labels == c].mean(axis=0) for c in ids])
    norms = np.linalg.norm(cents, axis=1, keepdims=True)
    return cents / np.where(norms == 0, 1, norms)


def merge_smallest(vectors: np.ndarray, labels: np.ndarray, max_clusters: int) -> np.ndarray:
    """Fold the smallest cluster into the one with the most similar centroid until <= max_clusters."""
    labels = labels.copy()
    while len(np.unique(labels)) > max_clusters:
        ids, counts = np.unique(labels, return_counts=True)
        cents = _centroids(vectors, labels, ids)
        small = int(np.argmin(counts))  # ties go to the lowest id, so this is deterministic
        sims = cents @ cents[small]
        sims[small] = -np.inf
        labels[labels == ids[small]] = ids[int(np.argmax(sims))]
    return labels


def cluster(vectors: np.ndarray, k: int, max_clusters: int) -> Tuple[np.ndarray, np.ndarray]:
    """Return (labels 0..m-1 ordered by cluster size desc, unit centroids), with m <= max_clusters."""
    k = max(1, min(k, len(vectors)))
    labels = KMeans(n_clusters=k, n_init=10, random_state=SEED).fit_predict(vectors)
    labels = merge_smallest(vectors, labels, max_clusters)

    ids, counts = np.unique(labels, return_counts=True)
    order = ids[np.lexsort((ids, -counts))]  # biggest first, id breaks ties
    remap = {int(old): new for new, old in enumerate(order)}
    labels = np.array([remap[int(x)] for x in labels])
    return labels, _centroids(vectors, labels, np.arange(len(order)))
