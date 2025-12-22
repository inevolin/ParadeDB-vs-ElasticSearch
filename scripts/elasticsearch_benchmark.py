#!/usr/bin/env python3
"""
Elasticsearch Benchmark Script with Connection Pooling
"""

import sys
import time
import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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

def run_concurrent_queries(es_host, es_port, index_name, query_type, transactions, concurrency):
    """Run queries concurrently with connection pooling"""
    
    # Create a shared session for all workers
    session = create_session()
    
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
    print(f"Query {query_type}: {config['name']} ({transactions} iterations, concurrency: {concurrency})")
    
    # Calculate transactions per worker
    transactions_per_worker = (transactions + concurrency - 1) // concurrency
    
    total_time = 0
    completed_transactions = 0
    
    def worker_task(worker_id):
        nonlocal completed_transactions
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
    
    # Run workers concurrently
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(worker_task, worker_id) for worker_id in range(1, concurrency + 1)]
        
        for future in as_completed(futures):
            worker_time, worker_transactions = future.result()
            total_time += worker_time
            completed_transactions += worker_transactions
    
    avg_time = total_time / transactions if transactions > 0 else 0
    
    print(f"Average time for Query {query_type}: {avg_time:.6f}s")
    print(f"Total time for Query {query_type}: {total_time:.6f}s")
    
    return avg_time, total_time

def main():
    if len(sys.argv) != 7:
        print("Usage: python elasticsearch_benchmark.py <host> <port> <index> <query_type> <transactions> <concurrency>")
        sys.exit(1)
    
    es_host = sys.argv[1]
    es_port = int(sys.argv[2])
    index_name = sys.argv[3]
    query_type = int(sys.argv[4])
    transactions = int(sys.argv[5])
    concurrency = int(sys.argv[6])
    
    run_concurrent_queries(es_host, es_port, index_name, query_type, transactions, concurrency)

if __name__ == "__main__":
    main()