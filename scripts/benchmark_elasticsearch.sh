#!/bin/bash

# Elasticsearch Benchmark Script (Optimized with connection reuse)
# This script runs inside the Elasticsearch pod

set -e

# Parse command line arguments first
QUIET=false
while [[ $# -gt 0 ]]; do
    case $1 in
        -q|--quiet)
            QUIET=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Elasticsearch connection details
ES_HOST=${ES_HOST:-localhost}
ES_PORT=${ES_PORT:-9200}
INDEX_NAME=${INDEX_NAME:-documents}

# Wait for Elasticsearch to be ready
echo "Waiting for Elasticsearch to be ready..."
until curl -s --max-time 5 "$ES_HOST:$ES_PORT/_cluster/health" | grep -q '"status":"green"\|"status":"yellow"'; do
    if [[ "$QUIET" != "true" ]]; then
        echo "Waiting for Elasticsearch..."
    fi
    sleep 2
done

echo "Starting Elasticsearch benchmark..."

# Install Python if not present
if ! command -v python3 &> /dev/null; then
    echo "Installing Python3..."
    cd /tmp
    ARCH=$(uname -m)
    if [[ "$ARCH" == "aarch64" ]] || [[ "$ARCH" == "arm64" ]]; then
        PYTHON_URL="https://github.com/indygreg/python-build-standalone/releases/download/20240107/cpython-3.11.7+20240107-aarch64-unknown-linux-gnu-install_only.tar.gz"
    else
        PYTHON_URL="https://github.com/indygreg/python-build-standalone/releases/download/20240107/cpython-3.11.7+20240107-x86_64-unknown-linux-gnu-install_only.tar.gz"
    fi
    curl -L "$PYTHON_URL" | tar -xz
    export PATH="/tmp/python/bin:$PATH"
    /tmp/python/bin/python3 -m pip install requests
fi

# Delete index if exists
curl -s -X DELETE "$ES_HOST:$ES_PORT/$INDEX_NAME" > /dev/null 2>&1 || true

# Create index with mapping
echo "Creating index..."
CURL_CMD="curl -s -X PUT \"$ES_HOST:$ES_PORT/$INDEX_NAME\" -H 'Content-Type: application/json' --data-binary '{
  \"mappings\": {
    \"properties\": {
      \"title\": { \"type\": \"text\" },
      \"content\": { \"type\": \"text\" }
    }
  }
}'"
if [[ "$QUIET" == "true" ]]; then
    eval "$CURL_CMD > /dev/null"
else
    eval "$CURL_CMD"
fi

# Prepare data
echo "Preparing data..."

# Load config
CONFIG_FILE="/config/benchmark_config.json"
SCALE_SIZE=$(python3 -c "
import json
with open('$CONFIG_FILE') as f:
    config = json.load(f)
scale_size_map = {
    'small': 'small_scale',
    'medium': 'medium_scale',
    'large': 'large_scale'
}
print(config['data'][scale_size_map['$SCALE']])
")

# Use pre-generated NDJSON data
echo "Loading synthetic data..."

# Load data using bulk API with pre-generated NDJSON
BULK_CMD="curl -s -X POST \"$ES_HOST:$ES_PORT/_bulk\" -H 'Content-Type: application/x-ndjson' --data-binary @/data/documents_${SCALE}.ndjson"
if [[ "$QUIET" == "true" ]]; then
    eval "$BULK_CMD > /dev/null"
else
    eval "$BULK_CMD"
fi

# Wait for indexing to complete
curl -s -X POST "$ES_HOST:$ES_PORT/$INDEX_NAME/_refresh" > /dev/null

# Count total documents in index
echo "Counting documents in index..."
COUNT=$(curl -s "$ES_HOST:$ES_PORT/$INDEX_NAME/_count" | grep -o '"count":[0-9]*' | cut -d: -f2)
echo "Total documents in index: $COUNT"

# Run benchmark queries
echo "Running benchmark queries..."

# Number of transactions (iterations) per query type
TRANSACTIONS=${TRANSACTIONS:-10}
CONCURRENCY=${CONCURRENCY:-1}

# Query terms for different iterations
# Query 1: Simple term searches
QUERY1_TERMS=("movie" "film" "story" "drama" "comedy" "action" "thriller" "romance" "horror" "adventure")

# Query 2: Phrase searches
QUERY2_TERMS=("science fiction" "romantic comedy" "action adventure" "crime drama" "horror film" "documentary" "animation" "musical" "western" "biography")

# Query 3: Complex boolean searches (term1 OR term2)
QUERY3_TERM1=("action" "comedy" "drama" "thriller" "horror" "romance" "adventure" "crime" "mystery" "fantasy")
QUERY3_TERM2=("comedy" "drama" "thriller" "horror" "romance" "adventure" "crime" "mystery" "fantasy" "animation")

echo "Running $TRANSACTIONS transactions per query type with concurrency $CONCURRENCY..."

# Function to run queries concurrently
run_concurrent_queries() {
    local query_type=$1
    local query_description=$2
    
    if [[ "$QUIET" != "true" ]]; then
        echo "Query $query_type: $query_description ($TRANSACTIONS iterations, concurrency: $CONCURRENCY)"
    fi
    
    # Run the Python script with connection pooling and capture output
    /tmp/python/bin/python3 /scripts/elasticsearch_benchmark.py "$ES_HOST" "$ES_PORT" "$INDEX_NAME" "$query_type" "$TRANSACTIONS" "$CONCURRENCY" > /tmp/query${query_type}_output.txt 2>&1
    
    # Extract average and total times from output
    AVG_TIME=$(grep "Average time for Query $query_type:" /tmp/query${query_type}_output.txt | sed 's/.*: \([0-9.]*\)s/\1/')
    TOTAL_TIME=$(grep "Total time for Query $query_type:" /tmp/query${query_type}_output.txt | sed 's/.*: \([0-9.]*\)s/\1/')
    
    echo "Average time for Query $query_type: ${AVG_TIME}s" > /tmp/query${query_type}_time.txt
    echo "Total time for Query $query_type: ${TOTAL_TIME}s" >> /tmp/query${query_type}_time.txt
}

# Query 1 execution
run_concurrent_queries 1 "Simple term search"

# Query 2 execution
run_concurrent_queries 2 "Phrase search"

# Query 3 execution
run_concurrent_queries 3 "Complex query"

echo "Benchmark completed. Results saved to /tmp/"