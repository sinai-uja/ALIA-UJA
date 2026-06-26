import argparse
import asyncio
import csv
import hashlib
import html
import json
import math
import pickle
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml
from openai import AsyncOpenAI
from tqdm import tqdm

try:
    import numpy as np
except ImportError:
    np = None


TOKEN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9_]+", re.UNICODE)

SPANISH_STOPWORDS = {
    "a",
    "al",
    "algo",
    "ante",
    "como",
    "con",
    "contra",
    "cual",
    "cuando",
    "de",
    "del",
    "desde",
    "donde",
    "el",
    "ella",
    "ellas",
    "ellos",
    "en",
    "entre",
    "era",
    "eres",
    "es",
    "esa",
    "esas",
    "ese",
    "eso",
    "esos",
    "esta",
    "estas",
    "este",
    "esto",
    "estos",
    "gracias",
    "ha",
    "han",
    "hay",
    "la",
    "las",
    "le",
    "les",
    "lo",
    "los",
    "me",
    "mi",
    "mis",
    "muchas",
    "muy",
    "no",
    "nos",
    "o",
    "para",
    "pero",
    "podrías",
    "por",
    "porque",
    "que",
    "quiero",
    "se",
    "sea",
    "ser",
    "si",
    "sin",
    "sobre",
    "son",
    "su",
    "sus",
    "te",
    "tienen",
    "tu",
    "un",
    "una",
    "unas",
    "uno",
    "unos",
    "y",
    "ya",
}


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tokenize(text: str) -> list[str]:
    return [
        token
        for token in TOKEN_RE.findall(text.lower())
        if len(token) >= 3 and token not in SPANISH_STOPWORDS
    ]


def load_prompts(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            item = json.loads(line)
            prompt = normalize_text(item.get("prompt"))
            if prompt:
                rows.append(
                    {
                        "line": line_number,
                        "prompt_id": item.get("prompt_id", ""),
                        "prompt": prompt,
                    }
                )
    return rows


def load_embedding_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def normalize_dense_values(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if not norm:
        return values
    return [value / norm for value in values]


async def create_embedding_batch(
    client: AsyncOpenAI,
    model: str,
    texts: list[str],
    start_index: int,
) -> tuple[int, list[list[float]]]:
    response = await client.embeddings.create(model=model, input=texts)
    embeddings = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
    return start_index, embeddings


async def create_embedding_batch_with_retry(
    client: AsyncOpenAI,
    model: str,
    texts: list[str],
    start_index: int,
    retries: int,
    retry_base_seconds: float,
    min_batch_size: int,
    request_timeout: float,
    skip_failed_embeddings: bool,
) -> tuple[int, list[list[float] | None]]:
    last_error = None
    for attempt in range(retries + 1):
        try:
            return await asyncio.wait_for(
                create_embedding_batch(client, model, texts, start_index),
                timeout=request_timeout,
            )
        except Exception as exc:
            last_error = exc
            print(
                f"Embedding batch failed: start={start_index}, size={len(texts)}, "
                f"attempt={attempt + 1}/{retries + 1}, error={type(exc).__name__}"
            )
            if attempt < retries:
                await asyncio.sleep(retry_base_seconds * (2**attempt))

    if len(texts) > min_batch_size:
        midpoint = len(texts) // 2
        _, left_embeddings = await create_embedding_batch_with_retry(
            client,
            model,
            texts[:midpoint],
            start_index,
            retries,
            retry_base_seconds,
            min_batch_size,
            request_timeout,
            skip_failed_embeddings,
        )
        _, right_embeddings = await create_embedding_batch_with_retry(
            client,
            model,
            texts[midpoint:],
            start_index + midpoint,
            retries,
            retry_base_seconds,
            min_batch_size,
            request_timeout,
            skip_failed_embeddings,
        )
        return start_index, left_embeddings + right_embeddings

    if skip_failed_embeddings:
        print(
            f"Skipping failed embedding text(s): start_index={start_index}, "
            f"batch_size={len(texts)}, error={type(last_error).__name__}"
        )
        return start_index, [None] * len(texts)

    raise RuntimeError(
        f"Embedding batch failed after {retries + 1} attempt(s); "
        f"start_index={start_index}, batch_size={len(texts)}"
    ) from last_error


async def compute_embeddings_async(
    texts: list[str],
    config: dict[str, Any],
    cache_path: Path,
) -> list[list[float] | None]:
    openai_config = config.get("openai", {})
    embedding_config = config.get("embeddings", {})
    model = embedding_config.get("model") or openai_config.get("model")
    if not model:
        raise ValueError("Falta embeddings.model en el YAML de embeddings.")

    cache: dict[str, list[float] | None] = {}
    if cache_path.exists():
        with cache_path.open("rb") as file:
            cache = pickle.load(file)

    keys = [f"{model}:{stable_hash(text)}" for text in texts]
    missing_pairs = [(index, text) for index, (key, text) in enumerate(zip(keys, texts)) if key not in cache]
    if not missing_pairs:
        print(f"Loaded {len(texts)} embeddings from cache: {cache_path}")
        return [cache[key] for key in keys]

    client = AsyncOpenAI(
        api_key=openai_config.get("api_key", ""),
        base_url=openai_config.get("base_url"),
        timeout=embedding_config.get("timeout", 120),
        max_retries=embedding_config.get("max_retries", 2),
    )
    batch_size = int(embedding_config.get("batch_size", 64))
    max_concurrency = max(1, int(embedding_config.get("max_concurrency", 4)))
    request_retries = int(embedding_config.get("request_retries", 4))
    retry_base_seconds = float(embedding_config.get("retry_base_seconds", 2.0))
    min_batch_size = int(embedding_config.get("min_batch_size", 1))
    request_timeout = float(embedding_config.get("request_timeout", embedding_config.get("timeout", 120)))
    skip_failed_embeddings = bool(embedding_config.get("skip_failed_embeddings", True))

    batches = [
        missing_pairs[start : start + batch_size]
        for start in range(0, len(missing_pairs), batch_size)
    ]
    queue: asyncio.Queue[list[tuple[int, str]] | None] = asyncio.Queue()
    for batch in batches:
        queue.put_nowait(batch)
    for _ in range(max_concurrency):
        queue.put_nowait(None)

    print(
        f"Embedding {len(missing_pairs)} missing prompts with {model} "
        f"in {len(batches)} batch(es), concurrency={max_concurrency}..."
    )
    progress = tqdm(total=len(batches), desc="Embedding batches", leave=False)

    async def worker() -> None:
        while True:
            batch = await queue.get()
            try:
                if batch is None:
                    return
                indexes = [index for index, _ in batch]
                batch_texts = [text for _, text in batch]
                _, embeddings = await create_embedding_batch_with_retry(
                    client,
                    model,
                    batch_texts,
                    indexes[0],
                    request_retries,
                    retry_base_seconds,
                    min_batch_size,
                    request_timeout,
                    skip_failed_embeddings,
                )
                for text_index, embedding in zip(indexes, embeddings):
                    cache[keys[text_index]] = normalize_dense_values(embedding) if embedding is not None else None
                progress.update(1)
            finally:
                queue.task_done()

    workers = [asyncio.create_task(worker()) for _ in range(max_concurrency)]
    try:
        await asyncio.gather(*workers)
    finally:
        progress.close()
        for task in workers:
            if not task.done():
                task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        await client.close()

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("wb") as file:
        pickle.dump(cache, file)
    return [cache.get(key) for key in keys]


def compute_embeddings(texts: list[str], config: dict[str, Any], cache_path: Path) -> list[list[float] | None]:
    return asyncio.run(compute_embeddings_async(texts, config, cache_path))


def build_vocabulary(tokenized_docs: list[list[str]], max_features: int, min_df: int) -> tuple[list[str], dict[str, int]]:
    document_frequency = Counter()
    term_frequency = Counter()
    for tokens in tokenized_docs:
        document_frequency.update(set(tokens))
        term_frequency.update(tokens)

    candidates = [
        term
        for term, doc_count in document_frequency.items()
        if doc_count >= min_df
    ]
    candidates.sort(key=lambda term: (term_frequency[term], document_frequency[term], term), reverse=True)
    vocabulary = sorted(candidates[:max_features])
    return vocabulary, {term: index for index, term in enumerate(vocabulary)}


def tfidf_vectors(tokenized_docs: list[list[str]], term_to_index: dict[str, int]) -> tuple[list[dict[int, float]], list[float]]:
    doc_count = len(tokenized_docs)
    document_frequency = Counter()
    for tokens in tokenized_docs:
        document_frequency.update({term for term in tokens if term in term_to_index})

    idf = {
        term_to_index[term]: math.log((1 + doc_count) / (1 + count)) + 1.0
        for term, count in document_frequency.items()
    }

    vectors = []
    norms = []
    for tokens in tokenized_docs:
        counts = Counter(term_to_index[term] for term in tokens if term in term_to_index)
        total = sum(counts.values()) or 1
        vector = {
            index: (count / total) * idf[index]
            for index, count in counts.items()
        }
        norm = math.sqrt(sum(value * value for value in vector.values()))
        if norm:
            vector = {index: value / norm for index, value in vector.items()}
        vectors.append(vector)
        norms.append(1.0 if norm else 0.0)
    return vectors, norms


def sparse_dot(left: dict[int, float], right: dict[int, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(index, 0.0) for index, value in left.items())


def normalize_sparse(vector: dict[int, float]) -> dict[int, float]:
    norm = math.sqrt(sum(value * value for value in vector.values()))
    if not norm:
        return vector
    return {index: value / norm for index, value in vector.items()}


def mean_centroid(vectors: list[dict[int, float]], indexes: list[int]) -> dict[int, float]:
    centroid: dict[int, float] = defaultdict(float)
    if not indexes:
        return centroid
    for doc_index in indexes:
        for term_index, value in vectors[doc_index].items():
            centroid[term_index] += value
    return normalize_sparse({index: value / len(indexes) for index, value in centroid.items()})


def kmeans_cosine(
    vectors: list[dict[int, float]],
    dimensions: int,
    k: int,
    max_iter: int,
    seed: int,
) -> tuple[list[int], list[dict[int, float]]]:
    rng = random.Random(seed)
    non_empty_indexes = [index for index, vector in enumerate(vectors) if vector]
    if len(non_empty_indexes) < k:
        raise ValueError(f"No hay suficientes prompts con vocabulario util para k={k}.")

    centroid_indexes = rng.sample(non_empty_indexes, k)
    centroids = [vectors[index].copy() for index in centroid_indexes]
    assignments = [-1] * len(vectors)

    for _ in range(max_iter):
        changed = False
        clusters: dict[int, list[int]] = defaultdict(list)
        for doc_index, vector in enumerate(vectors):
            if not vector:
                cluster_id = 0
            else:
                scores = [
                    sparse_dot(vector, centroid)
                    for centroid in centroids
                ]
                cluster_id = max(range(k), key=lambda index: scores[index])
            if assignments[doc_index] != cluster_id:
                changed = True
            assignments[doc_index] = cluster_id
            clusters[cluster_id].append(doc_index)

        for cluster_id in range(k):
            if clusters[cluster_id]:
                centroids[cluster_id] = mean_centroid(vectors, clusters[cluster_id])
            else:
                replacement = rng.choice(non_empty_indexes)
                centroids[cluster_id] = vectors[replacement].copy()

        if not changed:
            break

    return assignments, centroids


def kmeans_cosine_dense_python(
    vectors: list[list[float]],
    k: int,
    max_iter: int,
    seed: int,
) -> list[int]:
    rng = random.Random(seed)
    centroid_indexes = rng.sample(range(len(vectors)), k)
    centroids = [vectors[index][:] for index in centroid_indexes]
    assignments = [-1] * len(vectors)

    for _ in range(max_iter):
        changed = False
        clusters: dict[int, list[int]] = defaultdict(list)
        for doc_index, vector in enumerate(vectors):
            scores = [
                sum(value * centroid[dim] for dim, value in enumerate(vector))
                for centroid in centroids
            ]
            cluster_id = max(range(k), key=lambda index: scores[index])
            if assignments[doc_index] != cluster_id:
                changed = True
            assignments[doc_index] = cluster_id
            clusters[cluster_id].append(doc_index)

        for cluster_id in range(k):
            if not clusters[cluster_id]:
                centroids[cluster_id] = vectors[rng.randrange(len(vectors))][:]
                continue
            centroid = [0.0] * len(vectors[0])
            for doc_index in clusters[cluster_id]:
                for dim, value in enumerate(vectors[doc_index]):
                    centroid[dim] += value
            centroid = [value / len(clusters[cluster_id]) for value in centroid]
            centroids[cluster_id] = normalize_dense_values(centroid)

        if not changed:
            break
    return assignments


def kmeans_cosine_dense(
    vectors: list[list[float]],
    k: int,
    max_iter: int,
    seed: int,
) -> list[int]:
    if np is None:
        return kmeans_cosine_dense_python(vectors, k, max_iter, seed)

    rng = np.random.default_rng(seed)
    matrix = np.asarray(vectors, dtype=np.float32)
    centroid_indexes = rng.choice(matrix.shape[0], size=k, replace=False)
    centroids = matrix[centroid_indexes].copy()
    assignments = np.full(matrix.shape[0], -1, dtype=np.int32)

    for _ in range(max_iter):
        scores = matrix @ centroids.T
        new_assignments = scores.argmax(axis=1).astype(np.int32)
        if np.array_equal(assignments, new_assignments):
            break
        assignments = new_assignments

        for cluster_id in range(k):
            mask = assignments == cluster_id
            if not mask.any():
                centroids[cluster_id] = matrix[rng.integers(0, matrix.shape[0])]
                continue
            centroid = matrix[mask].mean(axis=0)
            norm = np.linalg.norm(centroid)
            centroids[cluster_id] = centroid / norm if norm else centroid

    return assignments.tolist()


def top_terms_for_cluster(
    vectors: list[dict[int, float]],
    indexes: list[int],
    vocabulary: list[str],
    limit: int,
) -> list[str]:
    totals = Counter()
    for doc_index in indexes:
        totals.update(vectors[doc_index])
    return [vocabulary[index] for index, _ in totals.most_common(limit)]


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


PALETTE = [
    "#2563eb",
    "#dc2626",
    "#16a34a",
    "#9333ea",
    "#ea580c",
    "#0891b2",
    "#be123c",
    "#65a30d",
    "#7c3aed",
    "#ca8a04",
    "#0f766e",
    "#db2777",
]


def project_embeddings_2d(vectors: list[list[float]]) -> list[tuple[float, float]]:
    if not vectors:
        return []
    if np is None:
        return [
            (vector[0] if len(vector) > 0 else 0.0, vector[1] if len(vector) > 1 else 0.0)
            for vector in vectors
        ]

    matrix = np.asarray(vectors, dtype=np.float32)
    matrix = matrix - matrix.mean(axis=0, keepdims=True)
    try:
        _, _, vt = np.linalg.svd(matrix, full_matrices=False)
        projected = matrix @ vt[:2].T
    except np.linalg.LinAlgError:
        projected = matrix[:, :2]
    if projected.shape[1] == 1:
        projected = np.column_stack([projected[:, 0], np.zeros(projected.shape[0])])
    return [(float(x), float(y)) for x, y in projected[:, :2]]


def write_assignments(
    path: Path,
    rows: list[dict[str, Any]],
    assignments: list[int],
    points: list[tuple[float, float]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["cluster", "x", "y", "line", "prompt_id", "prompt"])
        writer.writeheader()
        for row, cluster_id, point in zip(rows, assignments, points):
            writer.writerow(
                {
                    "cluster": cluster_id,
                    "x": point[0],
                    "y": point[1],
                    "line": row["line"],
                    "prompt_id": row["prompt_id"],
                    "prompt": row["prompt"],
                }
            )


def write_cluster_chart(path: Path, cluster_rows: list[dict[str, Any]]) -> None:
    width = 1000
    row_height = 46
    margin_left = 120
    margin_right = 40
    margin_top = 44
    margin_bottom = 34
    height = margin_top + margin_bottom + (row_height * len(cluster_rows))
    max_count = max(row["size"] for row in cluster_rows) if cluster_rows else 1
    chart_width = width - margin_left - margin_right

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="24" y="28" font-family="Arial, sans-serif" font-size="20" font-weight="700" fill="#111827">Prompt cluster sizes</text>',
    ]
    for row_number, row in enumerate(cluster_rows):
        y = margin_top + (row_number * row_height)
        bar_width = max(2, int((row["size"] / max_count) * chart_width))
        label = f"cluster {row['cluster']}"
        value = f"{row['size']} ({row['pct']:.1%})"
        parts.extend(
            [
                f'<text x="24" y="{y + 24}" font-family="Arial, sans-serif" font-size="14" fill="#374151">{label}</text>',
                f'<rect x="{margin_left}" y="{y + 8}" width="{bar_width}" height="24" rx="4" fill="#2563eb"/>',
                f'<text x="{margin_left + bar_width + 10}" y="{y + 25}" font-family="Arial, sans-serif" font-size="14" fill="#111827">{value}</text>',
            ]
        )
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def scale_points(
    points: list[tuple[float, float]],
    width: int,
    height: int,
    padding: int,
) -> list[tuple[float, float]]:
    if not points:
        return []
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 1e-9)
    span_y = max(max_y - min_y, 1e-9)
    plot_width = width - (padding * 2)
    plot_height = height - (padding * 2)
    return [
        (
            padding + ((x - min_x) / span_x) * plot_width,
            height - padding - ((y - min_y) / span_y) * plot_height,
        )
        for x, y in points
    ]


def write_cluster_scatter(
    path: Path,
    rows: list[dict[str, Any]],
    assignments: list[int],
    points: list[tuple[float, float]],
    cluster_rows: list[dict[str, Any]],
    max_points: int,
    seed: int,
) -> None:
    width = 1100
    height = 820
    padding = 72
    legend_x = 820
    rng = random.Random(seed)
    indexes = list(range(len(points)))
    if max_points and len(indexes) > max_points:
        indexes = sorted(rng.sample(indexes, max_points))
    scaled_points = scale_points(points, width=760, height=height, padding=padding)
    plotted = len(indexes)

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="24" y="34" font-family="Arial, sans-serif" font-size="22" font-weight="700" fill="#111827">Prompt clusters scatter</text>',
        '<text x="24" y="58" font-family="Arial, sans-serif" font-size="13" fill="#4b5563">2D PCA projection of prompt embeddings; colors are k-means clusters.</text>',
        f'<text x="24" y="{height - 20}" font-family="Arial, sans-serif" font-size="12" fill="#6b7280">Showing {plotted} of {len(points)} points.</text>',
        f'<rect x="{padding}" y="{padding}" width="{760 - (padding * 2)}" height="{height - (padding * 2)}" fill="#f9fafb" stroke="#e5e7eb"/>',
    ]
    for index in indexes:
        x, y = scaled_points[index]
        cluster_id = assignments[index]
        color = PALETTE[cluster_id % len(PALETTE)]
        row = rows[index]
        title = html.escape(f"cluster {cluster_id} | line {row['line']} | {truncate(row['prompt'], 180)}")
        parts.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="2.7" fill="{color}" fill-opacity="0.72">'
            f"<title>{title}</title></circle>"
        )

    parts.append(f'<text x="{legend_x}" y="88" font-family="Arial, sans-serif" font-size="16" font-weight="700" fill="#111827">Legend</text>')
    for row_number, row in enumerate(sorted(cluster_rows, key=lambda item: item["cluster"])):
        y = 116 + (row_number * 52)
        color = PALETTE[row["cluster"] % len(PALETTE)]
        label = html.escape(f"cluster {row['cluster']}: {row['size']} ({row['pct']:.1%})")
        terms = html.escape(", ".join(row["top_terms"][:5]))
        parts.extend(
            [
                f'<circle cx="{legend_x + 8}" cy="{y - 5}" r="6" fill="{color}"/>',
                f'<text x="{legend_x + 24}" y="{y}" font-family="Arial, sans-serif" font-size="13" font-weight="700" fill="#111827">{label}</text>',
                f'<text x="{legend_x + 24}" y="{y + 18}" font-family="Arial, sans-serif" font-size="12" fill="#4b5563">{terms}</text>',
            ]
        )
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def write_summary_files(
    output_dir: Path,
    summary: dict[str, Any],
    cluster_rows: list[dict[str, Any]],
    embedded_rows: list[dict[str, Any]],
    assignments: list[int],
    points: list[tuple[float, float]],
    max_scatter_points: int,
    seed: int,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        f"Dataset: {summary['dataset']}",
        f"Prompts: {summary['prompts_total']} total, {summary['prompts_embedded']} embedded, {summary['embeddings_failed']} failed",
        f"Embedding model: {summary['embedding_model']}",
        f"K-means: k={summary['k']}, seed={summary['seed']}",
        f"Largest cluster: {summary['largest_cluster_size']} ({summary['largest_cluster_pct']:.1%})",
        "",
        "Cluster sizes:",
    ]
    for row in cluster_rows:
        lines.append(f"- cluster {row['cluster']}: {row['size']} prompts ({row['pct']:.1%})")
        lines.append(f"  top terms: {', '.join(row['top_terms'])}")
    (output_dir / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_cluster_chart(output_dir / "cluster_sizes.svg", cluster_rows)
    write_cluster_scatter(
        output_dir / "cluster_scatter.svg",
        embedded_rows,
        assignments,
        points,
        cluster_rows,
        max_scatter_points,
        seed,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cluster prompts from a DPO JSONL dataset and inspect cluster sizes."
    )
    parser.add_argument("--input", type=Path, default=Path("dpo_data/dpo_dataset_clean_merged.jsonl"))
    parser.add_argument("--config", type=Path, default=Path("config_embeddings.yaml"))
    parser.add_argument("--output-dir", type=Path, default=Path("dpo_data/prompt_cluster_analysis"))
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--output-csv", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N prompts; useful for smoke tests.")
    parser.add_argument("--k", type=int, default=8, help="Number of clusters.")
    parser.add_argument("--max-features", type=int, default=2500, help="TF-IDF terms used only to label clusters.")
    parser.add_argument("--min-df", type=int, default=2, help="TF-IDF min document frequency used only to label clusters.")
    parser.add_argument("--max-iter", type=int, default=25)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--top-terms", type=int, default=12)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--sample-chars", type=int, default=240)
    parser.add_argument(
        "--max-scatter-points",
        type=int,
        default=12000,
        help="Maximum points to draw in cluster_scatter.svg. Use 0 to draw all points.",
    )
    parser.add_argument(
        "--dominance-threshold",
        type=float,
        default=0.40,
        help="Warn if the largest cluster is at least this fraction of the dataset.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cache_path = args.cache or (args.output_dir / "prompt_embeddings_cache.pkl")
    output_csv = args.output_csv or (args.output_dir / "prompt_clusters.csv")

    rows = load_prompts(args.input)
    if args.limit is not None:
        rows = rows[: args.limit]
    if not rows:
        raise SystemExit(f"No se encontraron prompts validos en {args.input}")
    if args.k < 2:
        raise SystemExit("--k debe ser al menos 2.")
    if args.k > len(rows):
        raise SystemExit(f"--k={args.k} es mayor que el numero de prompts ({len(rows)}).")

    embedding_config = load_embedding_config(args.config)
    embedding_model = embedding_config.get("embeddings", {}).get("model", "")
    embeddings = compute_embeddings([row["prompt"] for row in rows], embedding_config, cache_path)
    embedded_rows = []
    embedded_vectors = []
    failed_embeddings = 0
    for row, embedding in zip(rows, embeddings):
        if embedding is None:
            failed_embeddings += 1
            continue
        embedded_rows.append(row)
        embedded_vectors.append(embedding)

    if len(embedded_vectors) < args.k:
        raise SystemExit(
            f"Solo hay {len(embedded_vectors)} embeddings validos para k={args.k}; "
            f"fallaron {failed_embeddings}."
        )

    tokenized_docs = [tokenize(row["prompt"]) for row in rows]
    vocabulary, term_to_index = build_vocabulary(tokenized_docs, args.max_features, args.min_df)
    if not vocabulary:
        raise SystemExit("El vocabulario quedo vacio. Prueba con --min-df 1.")
    label_vectors, _ = tfidf_vectors(tokenized_docs, term_to_index)
    row_index_to_label_index = {id(row): index for index, row in enumerate(rows)}

    assignments = kmeans_cosine_dense(embedded_vectors, args.k, args.max_iter, args.seed)
    points = project_embeddings_2d(embedded_vectors)
    clusters: dict[int, list[int]] = defaultdict(list)
    for doc_index, cluster_id in enumerate(assignments):
        clusters[cluster_id].append(doc_index)

    write_assignments(output_csv, embedded_rows, assignments, points)

    total = len(embedded_rows)
    largest_cluster_size = max(len(indexes) for indexes in clusters.values())
    largest_cluster_pct = largest_cluster_size / total
    cluster_rows = []
    for cluster_id, indexes in sorted(clusters.items(), key=lambda item: len(item[1]), reverse=True):
        label_indexes = [row_index_to_label_index[id(embedded_rows[index])] for index in indexes]
        cluster_rows.append(
            {
                "cluster": cluster_id,
                "size": len(indexes),
                "pct": len(indexes) / total,
                "top_terms": top_terms_for_cluster(label_vectors, label_indexes, vocabulary, args.top_terms),
                "sample_lines": [embedded_rows[index]["line"] for index in indexes[: args.samples]],
            }
        )

    summary = {
        "dataset": str(args.input),
        "config": str(args.config),
        "output_dir": str(args.output_dir),
        "assignments_csv": str(output_csv),
        "embedding_cache": str(cache_path),
        "scatter_svg": str(args.output_dir / "cluster_scatter.svg"),
        "cluster_sizes_svg": str(args.output_dir / "cluster_sizes.svg"),
        "prompts_total": len(rows),
        "prompts_embedded": total,
        "embeddings_failed": failed_embeddings,
        "embedding_model": embedding_model,
        "k": args.k,
        "seed": args.seed,
        "max_iter": args.max_iter,
        "largest_cluster_size": largest_cluster_size,
        "largest_cluster_pct": largest_cluster_pct,
        "dominance_threshold": args.dominance_threshold,
        "max_scatter_points": args.max_scatter_points,
        "clusters": cluster_rows,
    }
    write_summary_files(
        args.output_dir,
        summary,
        cluster_rows,
        embedded_rows,
        assignments,
        points,
        args.max_scatter_points,
        args.seed,
    )

    print(f"Dataset: {args.input}")
    print(f"Prompts: {len(rows)} total, {total} embedded, {failed_embeddings} failed")
    print(f"Embedding model: {embedding_model}")
    print(f"Output dir: {args.output_dir}")
    print(f"Embedding cache: {cache_path}")
    print(f"Cluster labels: TF-IDF terms, features={len(vocabulary)}, min_df={args.min_df}")
    print(f"K-means: k={args.k}, seed={args.seed}")
    print(f"Assignments CSV: {output_csv}")
    print(f"Summary JSON: {args.output_dir / 'summary.json'}")
    print(f"Report TXT: {args.output_dir / 'report.txt'}")
    print(f"Chart SVG: {args.output_dir / 'cluster_sizes.svg'}")
    print(f"Scatter SVG: {args.output_dir / 'cluster_scatter.svg'}")
    print()
    print("Cluster sizes:")

    for row in cluster_rows:
        indexes = clusters[row["cluster"]]
        print(f"- cluster {row['cluster']}: {row['size']} prompts ({row['pct']:.1%})")
        print(f"  top terms: {', '.join(row['top_terms'])}")
        for sample_index in indexes[: args.samples]:
            row = embedded_rows[sample_index]
            print(f"  sample line {row['line']}: {truncate(row['prompt'], args.sample_chars)}")
        print()

    if largest_cluster_pct >= args.dominance_threshold:
        print(
            "WARNING: largest cluster dominance "
            f"{largest_cluster_pct:.1%} >= {args.dominance_threshold:.1%}. "
            "This suggests the dataset may be dominated by one prompt type."
        )
    else:
        print(
            "Largest cluster dominance "
            f"{largest_cluster_pct:.1%} < {args.dominance_threshold:.1%}."
        )


if __name__ == "__main__":
    main()
