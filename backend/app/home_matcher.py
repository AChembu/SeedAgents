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
    min_width: int = 480
    min_height: int = 320
    min_file_size_bytes: int = 15_000
    min_aspect_ratio: float = 0.6
    max_aspect_ratio: float = 2.2
    dedupe_hamming_threshold: int = 6
    max_pair_similarity: float = 0.94

    def _passes_photo_quality_gate(self, path: Path) -> bool:
        if path.stat().st_size < self.min_file_size_bytes:
            return False
        with Image.open(path) as img:
            width, height = img.size
        if width < self.min_width or height < self.min_height:
            return False
        aspect = width / max(height, 1)
        if aspect < self.min_aspect_ratio or aspect > self.max_aspect_ratio:
            return False
        return True

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

    def _dhash(self, path: Path, hash_size: int = 16) -> int:
        with Image.open(path) as img:
            gray = img.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
            arr = np.asarray(gray, dtype=np.int16)
        diff = arr[:, 1:] > arr[:, :-1]
        bits = 0
        for flag in diff.flatten():
            bits = (bits << 1) | int(flag)
        return bits

    def _hamming_distance(self, a: int, b: int) -> int:
        return int((a ^ b).bit_count())

    def _dedupe_near_identical(self, paths: list[Path]) -> list[Path]:
        kept: list[Path] = []
        hashes: list[int] = []
        for path in paths:
            current = self._dhash(path)
            if any(self._hamming_distance(current, h) <= self.dedupe_hamming_threshold for h in hashes):
                continue
            kept.append(path)
            hashes.append(current)
        return kept

    def _cosine(self, a: np.ndarray, b: np.ndarray) -> float:
        return float(np.dot(a, b) / ((np.linalg.norm(a) * np.linalg.norm(b)) + 1e-8))

    def select_consistent_images(self, image_paths: list[Path], max_count: int) -> list[Path]:
        if not image_paths:
            return []

        quality_candidates = [path for path in image_paths if self._passes_photo_quality_gate(path)]
        if not quality_candidates:
            # If every image is low quality, keep at least one to avoid hard failure.
            return image_paths[:1]
        quality_candidates = self._dedupe_near_identical(quality_candidates)
        if len(quality_candidates) <= 2:
            return quality_candidates[:max_count]

        embeddings = [self._embed(path) for path in quality_candidates]

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
        for path, emb in zip(quality_candidates, embeddings, strict=True):
            scored.append((path, self._cosine(anchor, emb)))

        scored.sort(key=lambda item: item[1], reverse=True)
        consistent = [path for path, sim in scored if sim >= self.min_similarity]

        # Guarantee at least 2 frames by taking nearest images if threshold is too strict.
        if len(consistent) < min(2, len(scored)):
            consistent = [path for path, _ in scored[: min(2, len(scored))]]

        if len(consistent) <= 2:
            return consistent[:max_count]

        # Diversity pass: farthest-point sampling on embedding distance
        # plus a hard pairwise-similarity cap to avoid same-room duplicates.
        emb_map = {path: self._embed(path) for path in consistent}
        chosen: list[Path] = []
        remaining = list(consistent)

        # Start with medoid-like representative.
        chosen.append(remaining.pop(0))

        while remaining and len(chosen) < max_count:
            best_path: Path | None = None
            best_distance = -1.0
            for candidate in remaining:
                pair_sims = [self._cosine(emb_map[candidate], emb_map[chosen_item]) for chosen_item in chosen]
                if pair_sims and max(pair_sims) >= self.max_pair_similarity:
                    # Too close to an already-selected view; likely same room/angle cluster.
                    continue
                min_distance = min(1.0 - sim for sim in pair_sims) if pair_sims else 1.0
                if min_distance > best_distance:
                    best_distance = min_distance
                    best_path = candidate

            if best_path is None:
                break
            chosen.append(best_path)
            remaining = [item for item in remaining if item != best_path]

        # If filter is too strict, backfill with best remaining non-identical options.
        if len(chosen) < min(max_count, len(consistent)):
            for candidate in consistent:
                if candidate in chosen:
                    continue
                pair_sims = [self._cosine(emb_map[candidate], emb_map[chosen_item]) for chosen_item in chosen]
                if pair_sims and max(pair_sims) >= 0.985:
                    continue
                chosen.append(candidate)
                if len(chosen) >= max_count:
                    break

        return chosen[:max_count]
