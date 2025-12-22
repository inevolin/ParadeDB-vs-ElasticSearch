#!/usr/bin/env python3
"""
Elasticsearch Benchmark Script (Complete workflow)
Handles setup, data loading, and benchmarking
"""

import sys
import time
import json
import os
import subprocess
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from concurrent.futures import ThreadPoolExecutor, as_completed
except ImportError:
    # concurrent.futures is built-in in Python 3
    pass

def create_session():
    """Create a requests session with connection pooling"""
    session = requests.Session()
    
    # Configure retry strategy
    retry_strategy = Retry(
        total=3,
        status_forcelist=[429, 500, 502, 503, 504],
        backoff_factor=1
    )
    
    # Configure adapter with connection pooling
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,
        pool_maxsize=10,
        pool_block=False
    )
    
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    return session

def wait_for_elasticsearch(session, es_host, es_port, quiet=False):
    """Wait for Elasticsearch to be ready"""
    if not quiet:
        print("Waiting for Elasticsearch to be ready...")
    
    url = f"http://{es_host}:{es_port}/_cluster/health"
    max_attempts = 30
    attempt = 0
    
    while attempt < max_attempts:
        try:
            response = session.get(url, timeout=5)
            if response.status_code == 200:
                health = response.json()
                if health.get('status') in ['green', 'yellow']:
                    if not quiet:
                        print("Elasticsearch is ready!")
                    return True
        except requests.RequestException:
            pass
        
        if not quiet:
            print(f"Waiting for Elasticsearch... (attempt {attempt + 1}/{max_attempts})")
        time.sleep(2)
        attempt += 1
    
    print("Elasticsearch failed to become ready", file=sys.stderr)
    return False

def setup_index(session, es_host, es_port, index_name, quiet=False):
    """Delete and recreate the index"""
    if not quiet:
        print("Setting up index...")
    
    start_time = time.perf_counter()
    
    # Delete index if exists
    delete_url = f"http://{es_host}:{es_port}/{index_name}"
    try:
        session.delete(delete_url, timeout=10)
    except requests.RequestException:
        pass  # Index might not exist
    
    # Create index with mapping
    create_url = f"http://{es_host}:{es_port}/{index_name}"
    mapping = {
        "mappings": {
            "properties": {
                "title": {"type": "text"},
                "content": {"type": "text"}
            }
        }
    }
    
    response = session.put(create_url, json=mapping, timeout=10)
    if response.status_code not in [200, 201]:
        print(f"Failed to create index: {response.text}", file=sys.stderr)
        return False
    
    end_time = time.perf_counter()
    index_creation_time = end_time - start_time
    
    if not quiet:
        print("Index created")
    
    # Save index creation time
    with open('/tmp/index_creation_time.txt', 'w') as f:
        f.write(f"Index creation time: {index_creation_time:.6f}s\n")
    
    return True

def load_data(session, es_host, es_port, index_name, scale, quiet=False):
    """Load data using bulk API"""
    if not quiet:
        print("Loading data...")
    
    start_time = time.perf_counter()
    
    # Load config
    config_file = '/config/benchmark_config.json'
    with open(config_file, 'r') as f:
        config = json.load(f)
    
    # Get expected size from scale-specific config
    scale_size_map = {
        'small': 'small_scale',
        'medium': 'medium_scale', 
        'large': 'large_scale'
    }
    expected_size = config['data'][scale_size_map[scale]]
    
    data_file = f'/data/documents_{scale}.ndjson'
    
    if not quiet:
        print(f"Loading data from {data_file}...")
    
    # Send bulk requests in batches
    batch_size = 5000
    bulk_data = ""
    batch_count = 0
    total_count = 0
    
    bulk_url = f"http://{es_host}:{es_port}/_bulk"
    headers = {'Content-Type': 'application/x-ndjson'}
    
    with open(data_file, 'r') as f:
        for line in f:
            bulk_data += line
            batch_count += 1
            total_count += 1
            
            if batch_count >= batch_size:
                response = session.post(bulk_url, data=bulk_data, headers=headers, timeout=60)
                if response.status_code not in [200, 201]:
                    print(f"Bulk load failed: {response.text}", file=sys.stderr)
                    return False
                bulk_data = ""
                batch_count = 0
                
            if total_count >= expected_size:
                break
    
    # Send remaining data
    if bulk_data:
        response = session.post(bulk_url, data=bulk_data, headers=headers, timeout=60)
        if response.status_code not in [200, 201]:
            print(f"Bulk load failed: {response.text}", file=sys.stderr)
            return False
    
    # Refresh index
    refresh_url = f"http://{es_host}:{es_port}/{index_name}/_refresh"
    session.post(refresh_url, timeout=10)
    
    end_time = time.perf_counter()
    loading_time = end_time - start_time
    
    if not quiet:
        print(f"Loaded {total_count} documents")
    
    # Save data loading time
    with open('/tmp/data_loading_time.txt', 'w') as f:
        f.write(f"Data loading time: {loading_time:.6f}s\n")
    
    return True

def count_documents(session, es_host, es_port, index_name, quiet=False):
    """Count documents in index"""
    if not quiet:
        print("Counting documents in index...")
    
    count_url = f"http://{es_host}:{es_port}/{index_name}/_count"
    response = session.get(count_url, timeout=10)
    
    if response.status_code == 200:
        count = response.json().get('count', 0)
        if not quiet:
            print(f"Total documents in index: {count}")
        return count
    else:
        print(f"Failed to count documents: {response.text}", file=sys.stderr)
        return 0

def run_query(session, es_host, es_port, index_name, query_body):
    """Run a single Elasticsearch query"""
    url = f"http://{es_host}:{es_port}/{index_name}/_search"
    
    start_time = time.perf_counter()
    
    try:
        response = session.get(
            url,
            headers={'Content-Type': 'application/json'},
            json=query_body,
            timeout=10
        )
        response.raise_for_status()
        
        end_time = time.perf_counter()
        return end_time - start_time
        
    except Exception as e:
        print(f"Query failed: {e}", file=sys.stderr)
        end_time = time.perf_counter()
        return end_time - start_time

def run_concurrent_queries(session, es_host, es_port, index_name, query_type, transactions, concurrency, quiet=False):
    """Run queries concurrently with connection pooling"""
    
    # Query configurations
    query_configs = {
        1: {
            'name': 'Simple Term Search',
            'terms': ["data", "information", "system", "service", "request", "report", "analysis", "record"],
            'query_template': lambda term: {
                "query": {"match": {"content": term}},
                "size": 10,
                "_source": ["title"],
                "sort": [{"_score": "desc"}]
            }
        },
        2: {
            'name': 'Phrase Search', 
            'terms': ["public data", "service request", "data analysis", "information system", "record management", "data processing", "service delivery", "information access"],
            'query_template': lambda phrase: {
                "query": {"match_phrase": {"content": phrase}},
                "size": 10,
                "_source": ["title"],
                "sort": [{"_score": "desc"}]
            }
        },
        3: {
            'name': 'Complex Query',
            'term1s': ["data", "information", "system", "service", "request", "report", "analysis", "record"],
            'term2s': ["public", "management", "processing", "delivery", "access", "collection", "storage", "retrieval"],
            'query_template': lambda term1, term2: {
                "query": {"bool": {"should": [
                    {"match": {"content": term1}},
                    {"match": {"content": term2}}
                ]}},
                "size": 20,
                "_source": ["title"],
                "sort": [{"_score": "desc"}]
            }
        }
    }
    
    config = query_configs[query_type]
    if not quiet:
        print(f"Query {query_type}: {config['name']} ({transactions} iterations, concurrency: {concurrency})")
    
    # Calculate transactions per worker
    transactions_per_worker = (transactions + concurrency - 1) // concurrency
    
    completed_transactions = 0
    
    def worker_task(worker_id):
        worker_time = 0
        worker_transactions = 0
        
        start_idx = (worker_id - 1) * transactions_per_worker + 1
        end_idx = min(worker_id * transactions_per_worker, transactions)
        
        for i in range(start_idx, end_idx + 1):
            if query_type == 3:
                term1_idx = (i - 1) % len(config['term1s'])
                term2_idx = (i - 1) % len(config['term2s'])
                term1 = config['term1s'][term1_idx]
                term2 = config['term2s'][term2_idx]
                query_body = config['query_template'](term1, term2)
            else:
                term_idx = (i - 1) % len(config['terms'])
                term = config['terms'][term_idx]
                query_body = config['query_template'](term)
            
            query_time = run_query(session, es_host, es_port, index_name, query_body)
            worker_time += query_time
            worker_transactions += 1
            
        return worker_time, worker_transactions
    
    # Run workers concurrently and measure wall time
    start_time = time.perf_counter()
    total_latency = 0
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(worker_task, worker_id) for worker_id in range(1, concurrency + 1)]
        
        for future in as_completed(futures):
            worker_time, worker_transactions = future.result()
            completed_transactions += worker_transactions
            total_latency += worker_time
    end_time = time.perf_counter()
    wall_time = end_time - start_time
    
    avg_latency = total_latency / transactions if transactions > 0 else 0
    
    if not quiet:
        print(f"Average Latency for Query {query_type}: {avg_latency:.6f}s")
        print(f"Wall time for Query {query_type}: {wall_time:.6f}s")
        print(f"TPS for Query {query_type}: {transactions / wall_time:.2f}")
    
    return avg_latency, wall_time

def main():
    # Parse arguments
    quiet = '--quiet' in sys.argv or '-q' in sys.argv
    
    # Elasticsearch connection details
    es_host = os.environ.get('ES_HOST', 'localhost')
    es_port = int(os.environ.get('ES_PORT', '9200'))
    index_name = os.environ.get('INDEX_NAME', 'documents')
    scale = os.environ.get('SCALE', 'small')
    transactions = int(os.environ.get('TRANSACTIONS', '10'))
    concurrency = int(os.environ.get('CONCURRENCY', '1'))
    
    # Create session
    session = create_session()
    
    # Wait for Elasticsearch
    if not wait_for_elasticsearch(session, es_host, es_port, quiet):
        sys.exit(1)
    
    # Setup index
    if not setup_index(session, es_host, es_port, index_name, quiet):
        sys.exit(1)
    
    # Load data
    if not load_data(session, es_host, es_port, index_name, scale, quiet):
        sys.exit(1)
    
    # Count documents
    count_documents(session, es_host, es_port, index_name, quiet)
    
    # Warmup
    if not quiet:
        print("Warming up...")
        
    for query_type in [1, 2, 3]:
        run_concurrent_queries(
            session, es_host, es_port, index_name, query_type,
            transactions=max(1, transactions // 10),
            concurrency=concurrency,
            quiet=True
        )
    
    # Run benchmark queries
    if not quiet:
        print("Running benchmark queries...")
    
    for query_type in [1, 2, 3]:
        avg_latency, total_time = run_concurrent_queries(
            session, es_host, es_port, index_name, query_type,
            transactions, concurrency, quiet
        )
        
        # Write results to files (matching the shell script output format)
        with open(f'/tmp/query{query_type}_time.txt', 'w') as f:
            f.write(f"Average Latency for Query {query_type}: {avg_latency:.6f}s\n")
            f.write(f"Wall time for Query {query_type}: {total_time:.6f}s\n")
    
    if not quiet:
        print("Benchmark completed. Results saved to /tmp/")

if __name__ == "__main__":
    main()