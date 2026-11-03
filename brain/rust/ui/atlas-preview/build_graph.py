#!/usr/bin/env python3
"""Build a force-graph slice shaped like the AI Model Atlas.

Each project is a community. Inside it, every memory links to its nearest
memories. A few links also reach into neighboring projects, so the force
layout grows filaments between the blobs. Size is how many entities a
memory mentions. Nothing is uploaded.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
DB = ROOT / "brain" / "rust" / "brain.db"
OUT = Path(__file__).resolve().parent / "public" / "graph.json"

MIN_PROJECT = 40
K = 3
CROSS_NEIGHBORS = 2
CROSS_LINKS = 4
DIM = 768


def settle_centers(centroids: np.ndarray, spans: np.ndarray) -> np.ndarray:
    """Place projects in 3D by similarity, then push clouds apart until they only touch."""
    centered = centroids - centroids.mean(axis=0, keepdims=True)
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    pos = centered @ vt[:3].T
    pos -= pos.mean(axis=0)
    pos *= np.median(spans) * 1.6 / (np.std(pos) + 1e-6)

    sims = centroids @ centroids.T
    np.fill_diagonal(sims, -np.inf)
    nearest = np.argsort(-sims, axis=1)[:, :2]
    count = len(pos)

    for _ in range(220):
        force = np.zeros_like(pos)
        for i in range(count):
            for j in range(i + 1, count):
                delta = pos[i] - pos[j]
                dist = float(np.linalg.norm(delta)) + 1e-6
                gap = 1.05 * (spans[i] + spans[j])
                if dist < gap:
                    push = ((gap - dist) / dist) * delta
                    force[i] += push
                    force[j] -= push
            for j in nearest[i]:
                delta = pos[int(j)] - pos[i]
                dist = float(np.linalg.norm(delta)) + 1e-6
                desired = 1.2 * (spans[i] + spans[int(j)])
                force[i] += 0.05 * ((dist - desired) / dist) * delta
        force -= 0.015 * pos
        pos += np.clip(force, -30, 30)
    return pos


def cloud_coords(matrix: np.ndarray) -> np.ndarray:
    centered = matrix - matrix.mean(axis=0, keepdims=True)
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    coords = centered @ vt[:3].T
    peak = float(np.percentile(np.linalg.norm(coords, axis=1), 92))
    return coords / max(peak, 1e-6)


def clean_type(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    return text or "unknown"


def label_of(title: str | None, content: str | None) -> str:
    text = (title or "").strip() or (content or "")
    return " ".join(text.split())[:90]


def main() -> None:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    projects = [
        row[0]
        for row in conn.execute(
            """
            SELECT project FROM memories
            WHERE embedding IS NOT NULL
              AND superseded_by IS NULL
              AND project IS NOT NULL AND project != ''
            GROUP BY project
            HAVING COUNT(*) >= ?
            ORDER BY COUNT(*) DESC
            """,
            (MIN_PROJECT,),
        )
    ]

    points: list[dict] = []
    vectors_by_project: dict[str, np.ndarray] = {}
    index_by_project: dict[str, np.ndarray] = {}
    links: set[tuple[str, str]] = set()

    for project in projects:
        rows = conn.execute(
            """
            SELECT m.id, m.type, m.title, substr(m.content, 1, 180), m.embedding,
                   (SELECT COUNT(*) FROM edges e WHERE e.src_memory_id = m.id)
            FROM memories m
            WHERE m.project = ?
              AND m.embedding IS NOT NULL
              AND m.superseded_by IS NULL
            ORDER BY m.timestamp DESC
            """,
            (project,),
        ).fetchall()
        if len(rows) < 2:
            continue

        ids = []
        vecs = []
        start = len(points)
        for row in rows:
            memory_id = row[0]
            ids.append(memory_id)
            points.append(
                {
                    "id": memory_id,
                    "label": label_of(row[2], row[3]),
                    "project": project,
                    "type": clean_type(row[1]),
                    "reach": int(row[5]) + 1,
                }
            )
            vecs.append(np.frombuffer(row[4], dtype="<f4", count=DIM))

        matrix = np.stack(vecs).astype(np.float32)
        matrix /= np.clip(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-8, None)
        vectors_by_project[project] = matrix
        index_by_project[project] = np.array(ids)

        sims = matrix @ matrix.T
        np.fill_diagonal(sims, -np.inf)
        k = min(K, len(rows) - 1)
        neighbors = np.argpartition(-sims, kth=k - 1, axis=1)[:, :k]
        for src in range(len(rows)):
            for dst in neighbors[src]:
                a, b = ids[src], ids[int(dst)]
                if a == b:
                    continue
                links.add(tuple(sorted((a, b))))
        print(f"{project}: {len(rows)} memories")

    names = list(vectors_by_project)
    centroids = np.stack([vectors_by_project[name].mean(axis=0) for name in names])
    centroids /= np.clip(np.linalg.norm(centroids, axis=1, keepdims=True), 1e-8, None)
    near = centroids @ centroids.T
    np.fill_diagonal(near, -np.inf)

    pairs: set[tuple[str, str]] = set()
    for i, name in enumerate(names):
        order = np.argsort(-near[i])[:CROSS_NEIGHBORS]
        for j in order:
            pairs.add(tuple(sorted((name, names[int(j)]))))

    for left, right in pairs:
        a = vectors_by_project[left]
        b = vectors_by_project[right]
        cross = a @ b.T
        flat = np.argpartition(cross.ravel(), -CROSS_LINKS)[-CROSS_LINKS:]
        ids_a = index_by_project[left]
        ids_b = index_by_project[right]
        for cell in flat:
            src, dst = divmod(int(cell), cross.shape[1])
            links.add(tuple(sorted((str(ids_a[src]), str(ids_b[dst])))))

    id_to_index = {point["id"]: index for index, point in enumerate(points)}
    spans = np.array(
        [55 + 6 * np.sqrt(len(vectors_by_project[name])) for name in names],
        dtype=np.float64,
    )
    centers = settle_centers(centroids, spans)
    for name, center, span in zip(names, centers, spans):
        local = cloud_coords(vectors_by_project[name]) * span
        for memory_id, xyz in zip(index_by_project[name], local + center):
            point = points[id_to_index[str(memory_id)]]
            point["x"], point["y"], point["z"] = (round(float(v), 2) for v in xyz)

    payload = {
        "points": points,
        "links": [{"source": a, "target": b} for a, b in links],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, separators=(",", ":")))
    print(
        f"wrote {OUT} — {len(points)} points, {len(payload['links'])} links, {len(names)} projects"
    )


if __name__ == "__main__":
    main()
