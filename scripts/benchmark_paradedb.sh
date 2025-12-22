#!/bin/bash

# ParadeDB Benchmark Script
# This script runs inside the ParadeDB pod

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

# Database connection details (passed as env vars or defaults)
DB_HOST=${DB_HOST:-localhost}
DB_PORT=${DB_PORT:-5432}
DB_NAME=${POSTGRES_DB:-benchmark_db}
DB_USER=${POSTGRES_USER:-benchmark_user}
DB_PASSWORD=${POSTGRES_PASSWORD:-benchmark_password_123}

# Wait for database to be ready
if [[ "$QUIET" != "true" ]]; then
    echo "Waiting for ParadeDB to be ready..."
fi
until pg_isready -h $DB_HOST -p $DB_PORT -U $DB_USER -d postgres; do
    if [[ "$QUIET" != "true" ]]; then
        echo "Waiting for database..."
    fi
    sleep 2
done

# Set password for psql
export PGPASSWORD=$DB_PASSWORD

if [[ "$QUIET" != "true" ]]; then
    echo "Starting ParadeDB benchmark..."
fi

# Create database and user if not exists
psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d postgres -c "DROP DATABASE IF EXISTS $DB_NAME;" 2>/dev/null || true
psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d postgres -c "CREATE DATABASE $DB_NAME;" 2>/dev/null || true
# Note: User should already exist via POSTGRES_USER env var in container

# Create table
if [[ "$QUIET" != "true" ]]; then
    echo "Creating table..."
fi
psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME << 'EOF' 2>/dev/null
DROP TABLE IF EXISTS documents;
CREATE TABLE documents (
    id SERIAL PRIMARY KEY,
    title TEXT,
    content TEXT
);
EOF

# Load data
if [[ "$QUIET" != "true" ]]; then
    echo "Loading data..."
fi
# Load JSON data using PostgreSQL JSON functions
psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME << EOF 2>/dev/null
CREATE TEMP TABLE temp_docs (data jsonb);
INSERT INTO temp_docs(data) SELECT * FROM json_array_elements(pg_read_file('/data/${SCALE}_documents.json')::json);
INSERT INTO documents (title, content)
SELECT 
    data->>'title', 
    data->>'content'
FROM temp_docs;
EOF

# Create search index
if [[ "$QUIET" != "true" ]]; then
    echo "Creating search index..."
fi
psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME << 'EOF' 2>/dev/null
CREATE INDEX documents_search_idx ON documents 
USING bm25 (id, title, content)
WITH (key_field='id');
EOF

# Run benchmark queries
if [[ "$QUIET" != "true" ]]; then
    echo "Running benchmark queries..."
fi

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
    local total_time=0
    
    if [[ "$QUIET" != "true" ]]; then
        echo "Query $query_type: $query_description ($TRANSACTIONS iterations, concurrency: $CONCURRENCY)"
    fi
    
    # Calculate transactions per worker
    local transactions_per_worker=$(( ($TRANSACTIONS + $CONCURRENCY - 1) / $CONCURRENCY ))
    
    # Run concurrent workers
    for worker in $(seq 1 $CONCURRENCY); do
        (
            local worker_start=$(( ($worker - 1) * $transactions_per_worker + 1 ))
            local worker_end=$(( $worker * $transactions_per_worker ))
            if [[ $worker_end -gt $TRANSACTIONS ]]; then
                worker_end=$TRANSACTIONS
            fi
            
            # Create SQL script for this worker
            local sql_file="/tmp/worker${worker}_query${query_type}.sql"
            echo "" > $sql_file
            
            local worker_time=0
            for i in $(seq $worker_start $worker_end); do
                if [[ "$QUIET" != "true" ]]; then
                    echo "  Worker $worker, Iteration $i"
                fi
                
                # Generate the query SQL
                case $query_type in
                    1) 
                        local term_index=$(( (i-1) % ${#QUERY1_TERMS[@]} ))
                        local term=${QUERY1_TERMS[$term_index]}
                        echo "\\timing on" >> $sql_file
                        echo "SELECT id, title FROM documents WHERE documents @@@ 'title:$term OR content:$term' ORDER BY paradedb.score(documents) DESC LIMIT 10;" >> $sql_file
                        ;;
                    2) 
                        local term_index=$(( (i-1) % ${#QUERY2_TERMS[@]} ))
                        local phrase=${QUERY2_TERMS[$term_index]}
                        echo "\\timing on" >> $sql_file
                        echo "SELECT id, title FROM documents WHERE documents @@@ 'title:\"${phrase//\'/''}\" OR content:\"${phrase//\'/''}\"' LIMIT 10;" >> $sql_file
                        ;;
                    3) 
                        local term1_index=$(( (i-1) % ${#QUERY3_TERM1[@]} ))
                        local term2_index=$(( (i-1) % ${#QUERY3_TERM2[@]} ))
                        local term1=${QUERY3_TERM1[$term1_index]}
                        local term2=${QUERY3_TERM2[$term2_index]}
                        echo "\\timing on" >> $sql_file
                        echo "SELECT id, title FROM documents WHERE documents @@@ 'title:$term1 OR content:$term1 OR title:$term2 OR content:$term2' ORDER BY paradedb.score(documents) DESC LIMIT 20;" >> $sql_file
                        ;;
                esac
            done
            
            # Run the SQL script once
            psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -f $sql_file > /tmp/worker${worker}_query${query_type}_output.txt 2>&1
            
            # Parse timing from output
            worker_time=0
            while IFS= read -r line; do
                if [[ $line =~ Time:\ ([0-9]+\.[0-9]+)\ ms ]]; then
                    time_ms=${BASH_REMATCH[1]}
                    time_sec=$(awk "BEGIN {printf \"%.6f\", $time_ms / 1000}")
                    worker_time=$(awk "BEGIN {printf \"%.6f\", $worker_time + $time_sec}")
                fi
            done < /tmp/worker${worker}_query${query_type}_output.txt
            
            # Clean up
            rm $sql_file /tmp/worker${worker}_query${query_type}_output.txt
            
            # Write worker results to temp file
            echo "$worker_time" > /tmp/query${query_type}_worker${worker}_time.txt
        ) &
    done
    
    # Wait for all workers to complete
    wait
    
    # Aggregate results from all workers
    total_time=0
    for worker in $(seq 1 $CONCURRENCY); do
        if [[ -f /tmp/query${query_type}_worker${worker}_time.txt ]]; then
            worker_time=$(cat /tmp/query${query_type}_worker${worker}_time.txt)
            total_time=$(awk "BEGIN {printf \"%.6f\", $total_time + $worker_time}")
            rm /tmp/query${query_type}_worker${worker}_time.txt
        fi
    done
    
    avg_time=$(awk "BEGIN {printf \"%.6f\", $total_time / $TRANSACTIONS}")
    echo "Average time for Query $query_type: ${avg_time}s" > /tmp/query${query_type}_time.txt
    echo "Total time for Query $query_type: ${total_time}s" >> /tmp/query${query_type}_time.txt
}

# Query 1 execution
run_concurrent_queries 1 "Simple term search"

# Query 2 execution
run_concurrent_queries 2 "Phrase search"

# Query 3 execution
run_concurrent_queries 3 "Complex query"

echo "Benchmark completed. Results saved to /tmp/"