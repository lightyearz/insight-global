# Embeddings and Semantic Similarity

## Contents
- Why few-shot similarity
- Embedding models
- Loading sentence-transformers safely
- Example-bank format
- Contrastive few-shot classifier (in-process)
- Building the index from versioned source
- Storage options
- pgvector on Cloud SQL
- Vertex AI embeddings
- Integrating with an existing classifier
- Performance budget
- Threshold calibration protocol
- Growing the example banks

## Why few-shot similarity

Zero-shot classifiers score an input against a label *name*. That works for broad topics but struggles with classes whose wording varies widely: "please shut it all down and remove my card" scores only moderately against the label "cancel account". Comparing the input with a curated set of examples of that class, and of look-alikes that are *not* that class, separates them much more clearly.

The approach is few-shot classification over sentence embeddings: store positive and hard-negative examples per class as normalised vectors and score inputs by their similarity to both sets. It runs locally, needs no training, and every decision can be explained by its nearest examples. The SetFit paper (Tunstall et al., 2022) reports that small sentence-transformer models are competitive with far larger models in few-shot text classification.

## Embedding models

| Model | Dim | Notes |
|-------|-----|-------|
| `sentence-transformers/all-MiniLM-L6-v2` | 384 | ~22M params, ~80 MB RAM, a few ms per short text on CPU; truncates at 256 word pieces; English. Good default. |
| `sentence-transformers/all-mpnet-base-v2` | 768 | ~110M params, higher quality, roughly 3x slower. |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | 384 | Multilingual. |
| Vertex AI text embeddings (for example `text-embedding-005`, `gemini-embedding-001`, `text-multilingual-embedding-002`) | 768 to 3072, often configurable | Managed, nothing in the image; network latency and per-call cost; supports task types. Verify current IDs. |

Pick by measuring on your examples: compute the calibration metrics below for two or three candidates and keep the cheapest one that meets the bar.

## Loading sentence-transformers safely

```python
from sentence_transformers import SentenceTransformer


def load_embedding_model(name_or_path: str, revision: str | None = None) -> SentenceTransformer:
    """Load on CPU with real (non-meta) weights."""
    try:
        return SentenceTransformer(
            name_or_path,
            device="cpu",
            revision=revision,
            model_kwargs={"low_cpu_mem_usage": False},
        )
    except TypeError:  # very old sentence-transformers without model_kwargs
        return SentenceTransformer(name_or_path, device="cpu", revision=revision)
```

- Newer `transformers` releases default to `low_cpu_mem_usage=True`, which creates weights on the `meta` device; the subsequent `.to(device)` fails with `Cannot copy out of meta tensor; no data!`. Passing `low_cpu_mem_usage=False` avoids it. This bit a production scanner after a routine dependency upgrade, and because the caller swallowed the exception the scanner was silently off for weeks. Keep a CI smoke test that loads the model and encodes one sentence.
- In production, load from a local path baked into the image with `HF_HUB_OFFLINE=1`; pin `revision` to a commit when loading from the Hub.
- Use the same model and revision to build the index and to encode queries.

## Example-bank format

One JSON file per class, version-controlled and reviewed like code:

```json
{
  "label": "cancel_account",
  "version": "1.2.0",
  "severity": "high",
  "description": "The user wants to close or delete their whole account, not a single order, item or setting.",
  "positive_examples": [
    "I want to close my account",
    "How do I delete my profile and all my data",
    "Please shut everything down, I'm done with this service",
    "Stop my membership and remove my card",
    "I'd like to permanently deactivate my login",
    "Cancel my account effective today",
    "Get rid of my account, I don't use it anymore",
    "Where is the button to delete my account",
    "I want out, close it all",
    "Terminate my account and send me confirmation"
  ],
  "negative_examples": [
    "How do I cancel one order",
    "Remove this item from my cart",
    "Close the popup, it keeps blocking the page",
    "Can I pause notifications for a week",
    "Delete this draft message",
    "How do I log out on this device",
    "Unsubscribe me from the newsletter only",
    "I want to close this support ticket",
    "Change the card on my account",
    "Can I delete an old address"
  ]
}
```

- **Positives** are genuine expressions of the class in varied wording, length and register.
- **Negatives** are hard negatives: inputs that share vocabulary or tone with the class but are not it. Random unrelated text adds nothing.
- Start with at least 10 of each; grow to 30-50 as reviewed production data arrives.
- Validate every file against a JSON Schema in CI; the domain owner reviews example changes in the PR.

## Contrastive few-shot classifier (in-process)

For banks up to tens of thousands of vectors, a NumPy matrix product beats any database round trip.

```python
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from sentence_transformers import SentenceTransformer

DEFAULT_THRESHOLD = 0.10


@dataclass(frozen=True, slots=True)
class ExampleBank:
    label: str
    severity: str
    positives: list[str]
    negatives: list[str]


@dataclass(frozen=True, slots=True)
class BankHit:
    label: str
    severity: str
    score: float           # mean top-k positive similarity - mean top-k negative similarity
    positive_sim: float
    negative_sim: float


def _mean_top_k(similarities: NDArray[np.float32], k: int) -> float:
    k = min(k, similarities.shape[0])
    return float(np.partition(similarities, -k)[-k:].mean())


class ExampleBankClassifier:
    def __init__(
        self,
        model: SentenceTransformer,
        banks: list[ExampleBank],
        thresholds: dict[str, float],
        k: int = 5,
    ) -> None:
        self._model = model
        self._k = k
        self._thresholds = thresholds
        self._banks = {b.label: b for b in banks}
        self._pos = {b.label: self._encode(b.positives) for b in banks}
        self._neg = {b.label: self._encode(b.negatives) for b in banks}

    def _encode(self, texts: list[str]) -> NDArray[np.float32]:
        return self._model.encode(
            texts, batch_size=64, normalize_embeddings=True, convert_to_numpy=True
        )

    def scan(self, text: str) -> list[BankHit]:
        query = self._encode([text])[0]
        hits: list[BankHit] = []
        for label, bank in self._banks.items():
            pos = _mean_top_k(self._pos[label] @ query, self._k)
            neg = _mean_top_k(self._neg[label] @ query, self._k)
            score = pos - neg
            if score > self._thresholds.get(label, DEFAULT_THRESHOLD):
                hits.append(BankHit(label, bank.severity, score, pos, neg))
        return sorted(hits, key=lambda h: h.score, reverse=True)
```

- With normalised vectors, cosine similarity is a dot product.
- The score is a *difference*, so useful thresholds are small (often 0.05-0.15) and must be calibrated per class.
- `k=5` smooths over one odd example; with fewer than five examples in a class, `_mean_top_k` uses all of them.
- `scan` is CPU-bound: call it through `asyncio.to_thread` from async handlers.
- Log `positive_sim`, `negative_sim` and the nearest example texts for review; they make decisions explainable.

## Building the index from versioned source

Never ship a pre-built index to a mutable store (a bucket, a shared volume). It drifts from the JSON in the repo, and edits silently stop taking effect.

Preferred: encode during the Docker build (the model files are already in the image), write the matrices to a file in the image, and load them at startup. Deterministic, zero startup cost.

Fallback: build at startup and skip the work when nothing changed:

```python
import hashlib
from pathlib import Path


def bank_fingerprint(bank_files: list[Path], model_id: str, model_revision: str) -> str:
    digest = hashlib.sha256(f"{model_id}@{model_revision}".encode())
    for path in sorted(bank_files):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()
```

Include the model ID and revision in the fingerprint: changing the embedding model must invalidate every stored vector. On Cloud Run the writable filesystem is in memory, so a cached index file costs instance memory; keep it small or rebuild in memory.

## Storage options

| Option | Use when | Avoid when |
|--------|----------|------------|
| In-process NumPy | Curated, read-only banks shipped with the code; up to tens of thousands of vectors | Data written at runtime or shared across instances |
| DuckDB (`array_cosine_similarity`, optional VSS extension) | Offline analysis, notebooks, SQL over embeddings, local tooling | A writable store on Cloud Run: instances do not share disk |
| pgvector on Cloud SQL | Embeddings of user or content data written at runtime, RAG corpora, queries that filter or join, shared by all instances | Tiny static banks: a network round trip for nothing |

DuckDB notes: a brute-force `array_cosine_similarity(embedding, ?::FLOAT[384])` scan over a few thousand rows is sub-millisecond, so an HNSW index is unnecessary at that size. Persisting a VSS HNSW index to a database file is experimental and needs `SET hnsw_enable_experimental_persistence = true`.

## pgvector on Cloud SQL

Alembic migration:

```python
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

EMBEDDING_DIM = 768


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")  # needs a user with cloudsqlsuperuser
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("document_id", sa.Uuid, nullable=False, index=True),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding_model", sa.String(100), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    with op.get_context().autocommit_block():  # CONCURRENTLY cannot run inside a transaction
        op.execute(
            "CREATE INDEX CONCURRENTLY ix_document_chunks_embedding "
            "ON document_chunks USING hnsw (embedding vector_cosine_ops)"
        )
```

Model and query (SQLAlchemy 2.0 async):

```python
import uuid

import numpy as np
from numpy.typing import NDArray
from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[uuid.UUID]
    chunk_index: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    embedding_model: Mapped[str] = mapped_column(String(100))
    embedding: Mapped[NDArray[np.float32]] = mapped_column(Vector(EMBEDDING_DIM))


async def nearest_chunks(
    session: AsyncSession, query_vector: list[float], *, embedding_model: str, k: int = 8
) -> list[tuple[int, str, float]]:
    distance = DocumentChunk.embedding.cosine_distance(query_vector).label("distance")
    stmt = (
        select(DocumentChunk.id, DocumentChunk.content, distance)
        .where(DocumentChunk.embedding_model == embedding_model)
        .order_by(distance)
        .limit(k)
    )
    rows = (await session.execute(stmt)).all()
    return [(row.id, row.content, 1.0 - row.distance) for row in rows]  # similarity = 1 - distance
```

- `<=>` (`cosine_distance`) returns distance, not similarity.
- The column dimension is fixed. A new embedding model means a new column or table plus a backfill job; filter by `embedding_model` so mixed vectors are never compared.
- HNSW gives better recall/latency than IVFFlat and can be built on an empty table, at the cost of slower builds and more memory. Tune recall per query with `SET LOCAL hnsw.ef_search = 100`.
- Filtered queries on an approximate index can return fewer than `k` rows. pgvector 0.8+ offers iterative index scans (`SET LOCAL hnsw.iterative_scan = relaxed_order`); otherwise over-fetch and filter.
- For RAG, chunk along document structure (headings, paragraphs), keep chunks a few hundred tokens with small overlap, and store source IDs for citations.
- Table ownership and migration rollout rules are in `backend-architect`.

## Vertex AI embeddings

```python
from collections.abc import Sequence

from google import genai
from google.genai import types


async def embed_texts(
    client: genai.Client,
    texts: Sequence[str],
    *,
    model: str,
    task_type: str,          # "RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY", "SEMANTIC_SIMILARITY", "CLASSIFICATION", ...
    dimensions: int,
) -> list[list[float]]:
    response = await client.aio.models.embed_content(
        model=model,
        contents=list(texts),
        config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=dimensions),
    )
    return [list(e.values or []) for e in response.embeddings or []]
```

- Use `RETRIEVAL_DOCUMENT` when indexing and `RETRIEVAL_QUERY` for the search query; mismatched task types reduce retrieval quality.
- Batch limits per request differ by model; chunk large backfills and respect quota with retries as described in the `llm-integration.md` reference.
- When requesting fewer dimensions than a model's native size, normalise the vectors yourself before storing unless the model documentation says the output is already normalised.
- A managed embedding call adds network latency to the hot path; for short-text classification a self-hosted MiniLM is usually cheaper and faster.

## Integrating with an existing classifier

- The scanner is additive: it can raise a result's severity or add labels, never lower them (see "Merging an extra detector into an existing classifier" in the `classification.md` reference).
- It must be on the request path; keep the integration test that proves it is called.
- Its failure mode is explicit and observable: ERROR log with traceback, failure counter, degraded status in the health or inspect endpoint (see "Never fail silently" in the `model-serving.md` reference).
- Results written for later analysis go to PostgreSQL, not to the in-process index; the index is read-only at runtime.

## Performance budget

Approximate, single short message, small CPU instance:

| Step | Latency | Memory |
|------|---------|--------|
| Encode with MiniLM-L6 | ~5 ms | ~80-100 MB model |
| Dot products against ~2,000 vectors (384-dim) | < 1 ms | ~3 MB |
| Whole scan for 20 classes | ~5-10 ms | |
| pgvector HNSW query (including network) | a few ms to tens of ms | in Cloud SQL |
| Vertex AI embedding call | tens to hundreds of ms | none in the service |

## Threshold calibration protocol

1. Build a held-out test set per class: at least 25 positives and 25 hard negatives that are **not** in the bank.
2. Score every test item with the scanner.
3. Plot or tabulate positive versus negative score distributions per class.
4. Choose the threshold that maximises F1 by default.
5. Classes where a miss is costly: bias toward recall (lower threshold, accept more false positives) and agree a recall floor with the domain owner.
6. Classes that only feed monitoring or analytics: bias toward precision.
7. Record per class: threshold, test-set size, precision, recall, F1, bank version, model ID, date, in a calibration log kept next to the banks.
8. Re-calibrate whenever examples, the embedding model or `k` change.

When a recall-critical class over-fires, fix it with data (hard negatives that resemble the false positives, clearer positives), not by raising its threshold above the agreed floor. Verify that the offending input's score drops while true positives stay above threshold.

## Growing the example banks

1. Sample production decisions periodically, prioritising low-margin scores near the threshold and user-reported mistakes.
2. A domain reviewer labels them; accepted items become new positives or hard negatives via PR.
3. The index rebuilds on the next deploy because it is built from the repo.
4. Re-run calibration after any significant bank change and compare with the previous log entry.
5. Later, route low-margin decisions into a review queue automatically (active learning).
