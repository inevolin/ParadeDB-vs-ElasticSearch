# ParadeDB vs Elasticsearch: Performance Benchmark Analysis

This project benchmarks the full-text search performance of **ParadeDB** (PostgreSQL-based) against **Elasticsearch**. The goal is to understand the performance characteristics, trade-offs, and scalability of each solution under controlled conditions.

## 📊 Executive Summary

Based on the latest benchmark runs, we observed distinct performance profiles for each system:

*   **Large Datasets (1M parent + 1M child documents)**: Elasticsearch generally leads on average TPS for full-text queries, while ParadeDB is competitive and can outperform on the JOIN workload depending on concurrency.
*   **JOIN Workload (Query 6)**: ParadeDB uses a SQL join against `child_documents`; Elasticsearch uses a `join` field with `has_child`. In the checked runs, ParadeDB was faster for JOINs at 1 and 50 clients, and Elasticsearch was slightly faster at 10 clients.
*   **Ingest & Indexing**: ParadeDB is materially faster end-to-end for loading + indexing in the included large runs.

## 📈 Detailed Results

### 1. Large Dataset Performance (1,000,000 Parent Documents + Child Documents) & Concurrency Analysis

For the large dataset, we tested performance across multiple concurrency levels (1, 10, and 50 clients) to understand how each system scales under load.

#### Performance Comparison by Concurrency

*Note: These results are based on 1,000 transactions per query type (Query 1–6).*

| Metrics (ParadeDB vs ES) | 1 Client | 10 Clients | 50 Clients |
| :--- | :--- | :--- | :--- |
| **Avg TPS (across Query 1–6)** | 150.96 vs **360.28** | 190.01 vs **843.97** | 444.32 vs **837.35** |
| **Startup Time** | 16.51s vs **12.76s** | 32.28s vs **12.78s** | **14.15s** vs 18.03s |
| **Load + Index Time** | **136.01s** vs 351.68s | **127.96s** vs 298.47s | **123.28s** vs 380.48s |

#### Key Findings

*   **Load + Index**: ParadeDB is faster than Elasticsearch in the included large runs.
*   **Throughput (Avg TPS across Query 1–6)**: Elasticsearch leads at 1/10 clients; at 50 clients ParadeDB closes the gap while still trailing overall average.
*   **JOIN Query (Query 6)**: JOIN performance differs from pure search queries; see the per-query breakdown in the summary files.

#### Visualizations

*(See "Workload" section for details on Query 1–6)*

**1 Client Summary**
![1 Client Summary](plots/large_1_1000_combined_summary.png)

---

**10 Clients Summary**
![10 Clients Summary](plots/large_10_1000_combined_summary.png)

---

**50 Clients Summary**
![50 Clients Summary](plots/large_50_1000_combined_summary.png)


## 🔬 Methodology

The benchmarks were conducted using a containerized environment to ensure isolation and reproducibility.

*   **Hardware**: MacBook Pro M1.
*   **Environment**: Local Kubernetes cluster running in Docker (configured with 8 CPUs and 12GB RAM).
*   **Software Versions**:
    *   Docker: 29.1.3
    *   Kubernetes Client: v1.34.1
    *   Python: 3.10.15
    *   Elasticsearch: 8.11.0
    *   ParadeDB: latest
*   **Resources**: Both systems were restricted to identical CPU and Memory limits (4 CPU, 8GB RAM, configurable in `config/benchmark_config.json`) to ensure a fair fight.
*   **Data Storage Differences**: 
    *   **ParadeDB**: Stores full raw text data in PostgreSQL tables (title and content columns) plus creates BM25 search indexes, resulting in larger storage footprint.
    *   **Elasticsearch**: Only maintains compressed inverted indexes and tokenized data optimized for search, resulting in more efficient storage.
    *   **Why ParadeDB often looks larger in this benchmark**: ParadeDB is a PostgreSQL database, so the measured size includes table heap storage (raw `title`/`content`), MVCC/page overhead, and secondary indexes (the BM25 index on `documents`, plus the btree/GIN indexes on `child_documents`). Elasticsearch’s reported store size is optimized for search workloads and uses compression/segment structures; it does not map 1:1 to Postgres heap+index accounting.
*   **Workload**:
    *   **Ingestion**: Bulk loading of JSON documents.
    *   **Queries**: The benchmark executes a mix of 6 distinct query types to simulate real-world usage patterns:
        1.  **Query 1 (Simple Search)**: Single-term full-text search (e.g., "strategy", "innovation"). Tests basic inverted index lookup speed.
        2.  **Query 2 (Phrase Search)**: Exact phrase matching (e.g., "project management"). Tests position-aware index performance.
        3.  **Query 3 (Complex Query)**: Two-term *OR* query (ParadeDB uses `... content:term1 OR content:term2 ...`; Elasticsearch uses a `bool.should`). Tests disjunction performance.
        4.  **Query 4 (Top-N Query)**: Single-term search with a limit on results (N=50). Tests ranking and retrieval optimization for paginated views.
        5.  **Query 5 (Boolean Query)**: A three-clause boolean query over `content` with positive and negative terms. (Implementation note: the current ParadeDB query requires both the “must” and “should” terms; Elasticsearch includes the “should” as a `should` clause alongside `must`/`must_not`.)
        6.  **Query 6 (JOIN Query)**: Join parents to children.
            *   **ParadeDB**: `documents` JOIN `child_documents` on `(child_documents.data->>'parent_id')::uuid = documents.id`, filtered by a full-text predicate on the parent.
            *   **Elasticsearch**: Parent/child join using a `join_field` mapping and `has_child` query (includes `inner_hits`).
    *   **Concurrency**: Tests are run at a configurable concurrency (e.g., 1, 10, 50) to evaluate scalability.

### Data Model / Schema (UML ASCII)

The benchmark uses a parent/child model so Query 6 can exercise a JOIN-style workload.

```
                 +---------------------------+
                 |         documents         |
                 +---------------------------+
                 | id: UUID (PK)             |
                 | title: TEXT               |
                 | content: TEXT             |
                 +---------------------------+
                              1
                              |
                              | (logical relationship via data->>'parent_id'
                              |  in child JSON; not a SQL FK)
                              |
                              *
                 +---------------------------+
                 |      child_documents      |
                 +---------------------------+
                 | id: UUID (PK)             |
                 | data: JSONB               |
                 |  - parent_id: UUID        |
                 |  - data: {...}            |
                 +---------------------------+


Elasticsearch index: documents
  - join_field: join { parent -> child }
  - parent docs: join_field = "parent"
  - child docs:  join_field = { name: "child", parent: <parent_id> }, routed by parent_id
```

### Metric Definitions and Calculations

The benchmark measures several key performance metrics:

*   **Iterations (Transactions)**: The total number of queries executed for each query type. This represents the workload volume.
*   **Concurrency**: The number of simultaneous client threads executing queries in parallel. Higher concurrency simulates more users.
*   **Average Query Latency**: The average time taken per individual query, calculated as the total execution time across all workers divided by the total number of transactions. This metric represents the response time experienced by clients.
*   **TPS (Transactions Per Second)**: The throughput metric, calculated as total transactions divided by the wall time. This shows how many queries the system can process per second under the given concurrency.
*   **Wall Time**: The total elapsed time from the start to the end of the benchmark run for a specific query type and concurrency level.

**Relationships and Computations**:
- TPS = Total Transactions / Wall Time
- Average Latency = (Sum of individual worker execution times) / Total Transactions
- Wall Time is measured across concurrent execution, so it represents the time until the last worker completes
- Higher concurrency typically reduces wall time but may increase average latency due to resource contention
- Iterations determine the statistical significance; more iterations provide more reliable average latency measurements

*   **Data Generation**:
    *   Synthetic data is generated using real English words (sourced from `dwyl/english-words`) to ensure realistic term frequency and distribution, rather than random character strings.
    *   Documents simulate business reports with fields like `title`, `description`, `category`, etc.

*   **Client Implementation**:
    *   **ParadeDB**: Uses `psycopg2` with `ThreadedConnectionPool` to efficiently manage database connections across concurrent threads.
    *   **Elasticsearch**: Uses Python `requests` with `HTTPAdapter` to enable connection pooling and automatic retries, ensuring optimal HTTP performance.
    *   **Concurrency Model**: Both benchmarks utilize Python's `ThreadPoolExecutor` to spawn concurrent worker threads, simulating real-world parallel user requests.

*   **Resource Monitoring**:
    *   Real-time resource usage (CPU & Memory) is captured using `docker stats` (since `kubectl top` was not available in the local environment) to ensure accurate measurement of container overhead.

## 📂 Project Structure

```
├── config/                 # Benchmark configuration
├── data/                   # Generated synthetic data
├── k8s/                    # Kubernetes deployment manifests
├── plots/                  # Generated performance plots and summaries
├── results/                # Raw benchmark results (JSON, CSV)
├── scripts/                # Python scripts for benchmarking and monitoring
├── generate_plots.py       # Plot generation script
├── run_tests.sh            # Main benchmark runner script
└── requirements.txt        # Python dependencies
```

## 🛠️ How to Reproduce

To run these benchmarks yourself and verify the results:

1.  **Prerequisites**: Docker and Python 3.
2.  **Install Dependencies**: `pip install -r requirements.txt`
3.  **Run Benchmark**:
    ```bash
    # Run Large scale benchmark using defaults from config/benchmark_config.json
    ./run_tests.sh -s large

    # Reproduce the committed large runs (1k transactions/query)
    ./run_tests.sh -s large -c 1  -t 1000
    ./run_tests.sh -s large -c 10 -t 1000
    ./run_tests.sh -s large -c 50 -t 1000
    ```
4.  **View Results**:
    *   Summaries and plots are generated in the `plots/` directory.
    *   Raw timing logs and resource usage data are in the `results/` directory.
    *   **Query Plans**: For ParadeDB, `EXPLAIN ANALYZE` output for each query type is saved to `results/explain_analyze_query_X.txt` (X = 1..6) to assist with performance debugging.
    *   Configuration can be tweaked in `config/benchmark_config.json`.

### Advanced Usage

The `run_tests.sh` script supports several flags to customize the benchmark run:

| Flag | Description | Default |
| :--- | :--- | :--- |
| `-s, --scale` | Data scale (`small`, `medium`, `large`) | `small` |
| `-c, --concurrency` | Number of concurrent clients | From config |
| `-t, --transactions` | Number of transactions per query type | From config |
| `--cpu` | CPU limit for databases (e.g., `4`, `1000m`) | From config |
| `--mem` | Memory limit for databases (e.g., `8Gi`, `4GB`) | From config |
| `-d, --databases` | Specific databases to run (`paradedb`, `elasticsearch`) | Both |

**Examples:**

```bash
# Run with custom concurrency and transaction count
./run_tests.sh -s medium -c 50 -t 500

# Benchmark only ParadeDB with specific resource limits
./run_tests.sh -d paradedb --cpu 2 --mem 4Gi
```

## ⚙️ Configuration

The benchmark is highly configurable via `config/benchmark_config.json`. Key sections include:

*   **`benchmark`**: Global defaults for concurrency and transaction counts.
*   **`data`**: Defines the number of documents for `small`, `medium`, and `large` scales.
*   **`resources`**: (Used by the runner) Defines default CPU/Memory requests and limits for the Kubernetes deployments.
*   **`queries`**: Defines the specific terms used for each query type. You can modify the lists of terms (e.g., `simple.terms`, `complex.term1s`) to change the search corpus.

## 📦 Data & Output Artifacts

### Data files

The runner generates and/or consumes two datasets per scale:

*   Parent documents: `data/documents_{scale}.json`
*   Child documents: `data/documents_child_{scale}.json`

Child documents contain a `parent_id` that references a parent document `id`. Both ParadeDB and Elasticsearch load child documents when the file exists.

### Results files

The benchmark runner and plot generator use a scale+concurrency+transactions naming convention:

*   `results/{scale}_{concurrency}_{transactions}_{db}_results.json`
*   `results/{scale}_{concurrency}_{transactions}_{db}_resources.csv`
*   `results/{scale}_{concurrency}_{transactions}_{db}_startup_time.txt`
*   ParadeDB-only query plans: `results/explain_analyze_query_{1..6}.txt`

The committed example artifacts include:

*   `results/large_1_1000_*`, `results/large_10_1000_*`, `results/large_50_1000_*`
*   `plots/large_1_1000_*`, `plots/large_10_1000_*`, `plots/large_50_1000_*`

## ⚠️ Limitations & Future Work

*   **Read-Heavy Focus**: This benchmark primarily focuses on search performance (read latency and throughput). While ingestion time is measured, high-throughput ingestion scenarios (updates, deletes) are not currently covered.
*   **Single Node**: The current setup deploys single-node instances of both ParadeDB and Elasticsearch. Distributed cluster performance and high-availability scenarios are not tested.
*   **Cold vs. Warm Cache**: The benchmark runs queries in sequence. While multiple iterations are performed, explicit controls for cold vs. warm cache testing are not strictly enforced, though the "warm-up" effect is naturally captured in the average latency over many transactions.

