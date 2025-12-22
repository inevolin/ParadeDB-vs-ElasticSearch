# ParadeDB vs Elasticsearch: Performance Benchmark Analysis

This project benchmarks the full-text search performance of **ParadeDB** (PostgreSQL-based) against **Elasticsearch**. The goal is to understand the performance characteristics, trade-offs, and scalability of each solution under controlled conditions.

## 📊 Executive Summary

Based on the latest benchmark runs, we observed distinct performance profiles for each system:

*   **Small Datasets (1k documents)**: **ParadeDB** demonstrated significantly higher throughput (TPS) and lower latency compared to Elasticsearch. It excelled in raw query speed for smaller data volumes.
*   **Medium Datasets (100k documents)**: **Elasticsearch** took the lead, showing better scaling for indexing speed and query throughput. ParadeDB's indexing time increased more noticeably at this scale.
*   **Operational Overhead**: Elasticsearch consistently showed faster startup times, while ParadeDB (running as a PG extension) required slightly more time to become ready.

## 📈 Detailed Results

### 1. Small Dataset Performance (1,000 Documents)

At a small scale, ParadeDB outperforms Elasticsearch by a wide margin in query throughput.

| Metric | ParadeDB | Elasticsearch | Winner |
| :--- | :--- | :--- | :--- |
| **Avg Throughput (TPS)** | **1,947.99** | 257.25 | 🏆 ParadeDB (~7.5x) |
| **Data Loading & Indexing** | **0.17s** | 0.30s | 🏆 ParadeDB |
| **Simple Term Query** | **0.0005s** | 0.0043s | 🏆 ParadeDB |
| **Phrase Query** | **0.0005s** | 0.0036s | 🏆 ParadeDB |
| **Complex Query** | **0.0006s** | 0.0038s | 🏆 ParadeDB |
| **Startup Time** | 17.83s | **12.97s** | 🏆 Elasticsearch |

> **Analysis**: For small datasets, ParadeDB's lightweight nature and tight integration with PostgreSQL provide near-instantaneous query responses, avoiding the overhead of HTTP/JSON serialization often associated with Elasticsearch.

### 2. Medium Dataset Performance (100,000 Documents)

As data volume grows, Elasticsearch's mature indexing engine begins to show its strength.

| Metric | ParadeDB | Elasticsearch | Winner |
| :--- | :--- | :--- | :--- |
| **Avg Throughput (TPS)** | 133.23 | **198.10** | 🏆 Elasticsearch (~1.5x) |
| **Data Loading & Indexing** | 18.72s | **5.37s** | 🏆 Elasticsearch |
| **Simple Term Query** | 0.0056s | **0.0053s** | 🏆 Elasticsearch |
| **Phrase Query** | 0.0067s | **0.0044s** | 🏆 Elasticsearch |
| **Complex Query** | 0.0136s | **0.0056s** | 🏆 Elasticsearch |
| **Startup Time** | 19.90s | **12.92s** | 🏆 Elasticsearch |

> **Analysis**: At 100k documents, Elasticsearch's specialized inverted index structures and optimized JVM caching allow it to handle higher concurrency and ingestion rates more efficiently. ParadeDB's indexing time was notably higher (18.72s vs 5.37s), suggesting that bulk ingestion optimization is a key differentiator for Elasticsearch at this scale.

---

## 🔬 Methodology

The benchmarks were conducted using a containerized environment to ensure isolation and reproducibility.

*   **Environment**: Docker containers for both databases.
*   **Resources**: Both systems were restricted to identical CPU and Memory limits (configurable in `config/benchmark_config.json`) to ensure a fair fight.
*   **Workload**:
    *   **Ingestion**: Bulk loading of JSON documents.
    *   **Queries**: A mix of Simple Term, Exact Phrase, and Complex Boolean queries.
    *   **Concurrency**: 4 concurrent workers executing 100 transactions each.

## 🛠️ How to Reproduce

To run these benchmarks yourself and verify the results:

1.  **Prerequisites**: Docker and Python 3.
2.  **Install Dependencies**: `pip install -r requirements.txt`
3.  **Run Benchmark**:
    ```bash
    # Run default benchmark (Small scale)
    ./run_tests.sh

    # Run Medium scale benchmark
    ./run_tests.sh -s medium
    ```
4.  **View Results**:
    *   Summaries are generated in `plots/`.
    *   Raw timing logs are in `results/`.
    *   Configuration can be tweaked in `config/benchmark_config.json`.

