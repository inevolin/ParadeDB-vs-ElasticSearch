# Query Breakdown: Elasticsearch vs ParadeDB (Postgres)

This document explains how each benchmark query (1–6) is implemented in this repo for:

- **Elasticsearch**: JSON DSL executed via `/_search`.
- **ParadeDB**: SQL executed in Postgres, where `@@@` triggers a ParadeDB **BM25** full-text index scan (implemented via Tantivy).

It focuses on (a) **what each system is actually asked to do** and (b) **why performance/behavior differs**.

Source of truth for query templates:
- Elasticsearch: `scripts/elasticsearch_benchmark.py`
- ParadeDB: `scripts/benchmark_paradedb.py`

> Important: Queries are *not always semantically identical* between systems. Where the benchmark differs (notably Query 5 and Query 6), this doc calls it out explicitly because it can materially affect both results and performance.

---

## Common execution model differences (applies to all queries)

### Elasticsearch
- Uses a **Lucene inverted index** with segment-level execution.
- Typically ranks results with **BM25** and returns top-K by score.
- Query execution cost is heavily influenced by:
  - shard/segment count, merge state, caches
  - whether scoring is needed
  - whether it can terminate early (top-K optimizations)

### ParadeDB (Postgres + Tantivy)
- Uses Postgres for SQL planning/execution and concurrency, and ParadeDB/Tantivy for **BM25** full-text retrieval.
- Full-text filtering is done via a **Custom Scan** (ParadeDB scan) over the Tantivy index; results are then joined/limited/sorted by Postgres.
- Query execution cost is influenced by:
  - Postgres plan shape (nested loop vs hash join, etc.)
  - whether an `ORDER BY paradedb.score(...)` is required
  - whether downstream joins are index-backed

---

## Query 1 — Simple Search

### Intent
Single-term full-text query (e.g., `content:strategy`), return top 10 results.

### Elasticsearch implementation
```json
{
  "query": {"match": {"content": "<term>"}},
  "size": 10,
  "_source": ["title"],
  "sort": [{"_score": "desc"}]
}
```

**How ES executes**
- Analyze `<term>` for the `content` field.
- Lookup postings lists, compute BM25 scores.
- Maintain a top-10 heap per segment/shard, then merge to global top-10.

### ParadeDB implementation
```sql
SELECT id, title
FROM documents
WHERE documents @@@ 'content:<term>'
ORDER BY paradedb.score(documents) DESC
LIMIT 10;
```

**How ParadeDB executes**
- ParadeDB scan pulls matching doc IDs from Tantivy and computes a **BM25** score.
- Postgres sorts by score (or uses a top-N sort strategy) and applies `LIMIT 10`.

### Comparison / why behavior differs
- Both are “classic” inverted-index search with scoring.
- Differences mostly come from:
  - analyzers/tokenization details
  - scoring implementation details (both are BM25-like, but not necessarily identical)
  - overhead differences: HTTP+JSON boundary (ES) vs SQL+extension boundary (Postgres)

---

## Query 2 — Phrase Search

### Intent
Exact phrase match (e.g., `"project management"`), return top 10.

### Elasticsearch implementation
```json
{
  "query": {"match_phrase": {"content": "<phrase>"}},
  "size": 10,
  "_source": ["title"],
  "sort": [{"_score": "desc"}]
}
```

**How ES executes**
- Uses positional information (term positions) to verify the phrase constraint.
- Phrase queries are usually more expensive than term queries, especially for frequent terms.

### ParadeDB implementation
```sql
SELECT id, title
FROM documents
WHERE documents @@@ 'content:"<phrase>"'
ORDER BY paradedb.score(documents) DESC
LIMIT 10;
```

**How ParadeDB executes**
- Tantivy evaluates a phrase query (also position-aware).
- Postgres orders by score and limits to 10.

### Comparison / why behavior differs
- Both rely on positional indexes; performance depends heavily on how common the phrase terms are.
- If analyzers differ (stopwords/stemming), the phrase semantics can diverge.

---

## Query 3 — Complex Query (OR / Disjunction)

### Intent
Two-term OR query, return top 20.

### Elasticsearch implementation
```json
{
  "query": {
    "bool": {
      "should": [
        {"match": {"content": "<term1>"}},
        {"match": {"content": "<term2>"}}
      ]
    }
  },
  "size": 20,
  "_source": ["title"],
  "sort": [{"_score": "desc"}]
}
```

**How ES executes**
- Evaluates a disjunction across the two match queries.
- Scoring is influenced by which clause matched and how strongly.

### ParadeDB implementation
```sql
SELECT id, title
FROM documents
WHERE documents @@@ 'content:<term1> OR content:<term2>'
ORDER BY paradedb.score(documents) DESC
LIMIT 20;
```

**How ParadeDB executes**
- Tantivy executes the OR query.
- Postgres orders by score, returns top 20.

### Comparison / why behavior differs
- Disjunctions can get expensive when either term is frequent (large candidate set).
- Both engines can apply optimization strategies, but details differ by implementation.

---

## Query 4 — Top-N Query (larger LIMIT)

### Intent
Single-term search with a higher `LIMIT` (N comes from config; README mentions N=50).

### Elasticsearch implementation
```json
{
  "query": {"match": {"content": "<term>"}},
  "size": <N>,
  "_source": ["title"],
  "sort": [{"_score": "desc"}]
}
```

### ParadeDB implementation
```sql
SELECT id, title
FROM documents
WHERE documents @@@ 'content:<term>'
ORDER BY paradedb.score(documents) DESC
LIMIT <N>;
```

### Comparison / why behavior differs
- Raising `N` increases the amount of scoring and result materialization.
- Engines often have “top-K” optimizations; how well they work depends on:
  - whether scoring is required
  - how selective the term is
  - internal heap/priority-queue implementation and per-segment merging

---

## Query 5 — Boolean Query (AND + NOT + (optional?) SHOULD)

### Intent (conceptually)
A multi-clause boolean query that mixes required terms and prohibited terms.

### Elasticsearch implementation (as benchmarked)
```json
{
  "query": {
    "bool": {
      "must": [{"match": {"content": "<must>"}}],
      "should": [{"match": {"content": "<should>"}}],
      "must_not": [{"match": {"content": "<not>"}}]
    }
  },
  "size": 10,
  "_source": ["title"],
  "sort": [{"_score": "desc"}]
}
```

**Key semantic note (very important)**
- In Elasticsearch, when a `bool` query has at least one `must` clause, `should` clauses are **optional by default** (unless `minimum_should_match` is set).
- That means: ES is effectively doing `must AND NOT not`, and using `should` primarily as a **scoring boost**, not as a required filter.

### ParadeDB implementation (as benchmarked)
```sql
SELECT id, title
FROM documents
WHERE documents @@@ 'content:<must> AND (content:<should>) AND NOT content:<not>'
ORDER BY paradedb.score(documents) DESC
LIMIT 10;
```

**Key semantic note (very important)**
- This SQL query makes `<should>` **required** (it is inside an `AND (...)`).

### Comparison / why behavior differs
- Because the semantics differ, the two engines may:
  - return different result sets
  - process very different candidate set sizes

Typical performance impact of this mismatch:
- If `<should>` is selective, ParadeDB may do less work (smaller candidate set).
- If `<should>` is common, ParadeDB may do more work than ES.

If you want semantic parity:
- Either make Elasticsearch require the `should` term with `"minimum_should_match": 1`.
- Or change the ParadeDB query to make `<should>` optional (e.g., treat it as a boosting signal rather than a filter).

---

## Query 6 — JOIN Query (parents + children)

### Intent
Return parent documents matching a full-text filter and also return related child data.

### Elasticsearch implementation (as benchmarked)
```json
{
  "query": {
    "bool": {
      "must": [
        {"match": {"content": "<term>"}},
        {
          "has_child": {
            "type": "child",
            "query": {"match_all": {}},
            "inner_hits": {}
          }
        }
      ]
    }
  },
  "size": 10,
  "_source": ["title"],
  "sort": [{"_score": "desc"}]
}
```

**What this actually asks ES to do**
- Find *parent* documents matching the full-text query.
- Filter those parents to only those that have **at least one child** (`has_child` + `match_all`).
- Additionally, because `inner_hits` is enabled, ES must also **collect and return the child documents** that match the child query.

**Why ES parent/child joins are expensive**
- ES parent/child is *not* a relational join; it’s a specialized join mechanism implemented on top of Lucene.
- It typically requires additional join bookkeeping structures (often described as “bitset joins” / “global ordinals-like” overhead depending on the join strategy and version).
- Under concurrency, that extra CPU/memory work tends to amplify contention.

### ParadeDB implementation (as benchmarked)
```sql
SELECT d.id, d.title, c.data
FROM documents d
JOIN child_documents c
  ON (c.data->>'parent_id')::uuid = d.id
WHERE d @@@ 'content:<term>'
LIMIT 10;
```

**How ParadeDB executes (typical plan shape)**
From the included `EXPLAIN ANALYZE` output for Query 6:
- First, a selective **ParadeDB Scan** on `documents` using the search index.
- Then a **Nested Loop** into `child_documents` using an index on the extracted parent_id (`child_documents_parent_id_idx`).

This is a classic relational pattern:
- small set of parent hits
- fast indexed lookups for child rows
- early termination due to `LIMIT 10`

### Critical benchmark difference: sorting / top-K requirements
- Elasticsearch Query 6 explicitly sorts by `_score` (top-10 by score).
- ParadeDB Query 6 does **not** include `ORDER BY paradedb.score(...)`.

That matters because:
- Without `ORDER BY`, Postgres can often stop as soon as it has produced 10 joined rows.
- With score sorting, ES needs to be confident it has the top 10 by score (across segments/shards) *and* do join/inner_hits work.

### Why ParadeDB can look “much better” for Query 6
- ParadeDB gets an **index-assisted join** (btree-style lookup) after a selective text filter.
- ES is doing a **join field query** (parent/child) plus **inner hits materialization**, which is comparatively heavy.
- The difference often becomes more pronounced under higher concurrency, where join bookkeeping and inner-hit fetching become contention hotspots.

---

## Notes on interpreting performance results

- **Different semantics != apples-to-apples**: Query 5 and Query 6 have meaningful semantic differences that can change both result sets and work done.
- **“Index creation time” fields differ**: Elasticsearch `index_creation_time` in results reflects mapping/index setup, while most heavy work happens during bulk indexing/merge; ParadeDB reports explicit index build time.
- **Concurrency interacts differently**:
  - ES concurrency stresses search threadpools, segment caches, and join structures.
  - Postgres concurrency stresses connection pooling, executor parallelism, buffer cache, and btree index contention.

If you want, we can add a “semantic parity mode” to the benchmark (small changes to query templates) so Query 5 and Query 6 are more directly comparable.
