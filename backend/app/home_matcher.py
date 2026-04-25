from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image


@dataclass
class HomeConsistencyModel:
    """
    Lightweight visual-consistency model for listing photos.

    It computes simple image embeddings (color + edge profile) and keeps
    images that are visually similar to the listing's dominant style.
    """

    min_similarity: float = 0.72

    def _embed(self, path: Path) -> np.ndarray:
        with Image.open(path) as img:
            rgb = img.convert("RGB").resize((256, 256), Image.Resampling.LANCZOS)
            arr = np.asarray(rgb, dtype=np.float32) / 255.0

        # Color histogram feature (3x16 bins).
        hist_parts: list[np.ndarray] = []
        for ch in range(3):
            hist, _ = np.histogram(arr[:, :, ch], bins=16, range=(0.0, 1.0))
            hist_parts.append(hist.astype(np.float32))
        color = np.concatenate(hist_parts)
        color = color / (np.linalg.norm(color) + 1e-8)

        # Edge-density feature for structural similarity.
        gray = arr.mean(axis=2)
        gx = np.abs(np.diff(gray, axis=1, prepend=gray[:, :1]))
        gy = np.abs(np.diff(gray, axis=0, prepend=gray[:1, :]))
        edge = np.sqrt(gx * gx + gy * gy)
        edge_hist, _ = np.histogram(edge, bins=8, range=(0.0, 1.0))
        edge_feat = edge_hist.astype(np.float32)
        edge_feat = edge_feat / (np.linalg.norm(edge_feat) + 1e-8)

        emb = np.concatenate([color, edge_feat])
        emb = emb / (np.linalg.norm(emb) + 1e-8)
        return emb

    def _cosine(self, a: np.ndarray, b: np.ndarray) -> float:
        return float(np.dot(a, b) / ((np.linalg.norm(a) * np.linalg.norm(b)) + 1e-8))

    def select_consistent_images(self, image_paths: list[Path], max_count: int) -> list[Path]:
        if not image_paths:
            return []
        if len(image_paths) <= 2:
            return image_paths[:max_count]

        embeddings = [self._embed(path) for path in image_paths]

        # Medoid anchor: image most similar to the rest.
        medoid_idx = 0
        best_score = -1.0
        for i, emb_i in enumerate(embeddings):
            sims = [self._cosine(emb_i, emb_j) for emb_j in embeddings if emb_j is not emb_i]
            score = float(np.mean(sims)) if sims else 1.0
            if score > best_score:
                best_score = score
                medoid_idx = i

        anchor = embeddings[medoid_idx]
        scored: list[tuple[Path, float]] = []
        for path, emb in zip(image_paths, embeddings, strict=True):
            scored.append((path, self._cosine(anchor, emb)))

        scored.sort(key=lambda item: item[1], reverse=True)
        consistent = [path for path, sim in scored if sim >= self.min_similarity]

        # Guarantee at least 2 frames by taking nearest images if threshold is too strict.
        if len(consistent) < min(2, len(scored)):
            consistent = [path for path, _ in scored[: min(2, len(scored))]]

        return consistent[:max_count]
