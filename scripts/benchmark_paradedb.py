#!/usr/bin/env python3
"""
ParadeDB Benchmark Script
Python version with connection pooling and concurrent query execution
"""

import sys
import time
import json
import os
import subprocess
import psycopg2
from psycopg2 import pool
from psycopg2.extras import execute_values

try:
    from concurrent.futures import ThreadPoolExecutor, as_completed
except ImportError:
    # concurrent.futures is built-in in Python 3
    pass

import argparse

def create_connection_pool(host, port, dbname, user, password, min_conn=1, max_conn=10):
    """Create a PostgreSQL connection pool"""
    try:
        connection_pool = psycopg2.pool.ThreadedConnectionPool(
            min_conn, max_conn,
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
            connect_timeout=10
        )
        # Store connection parameters for later use
        connection_pool._host = host
        connection_pool._port = port
        connection_pool._user = user
        connection_pool._password = password
        return connection_pool
    except Exception as e:
        print(f"Failed to create connection pool: {e}", file=sys.stderr)
        sys.exit(1)

def wait_for_database(host, port, user, password):
    """Wait for database to be ready"""
    print("Waiting for ParadeDB to be ready...")

    max_attempts = 30
    attempt = 0

    while attempt < max_attempts:
        try:
            conn = psycopg2.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                dbname='postgres',
                connect_timeout=5
            )
            conn.close()
            print("Database is ready!")
            return True
        except psycopg2.OperationalError:
            print(f"Waiting for database... (attempt {attempt + 1}/{max_attempts})")
            time.sleep(2)
            attempt += 1

    print("Database failed to become ready", file=sys.stderr)
    return False

def setup_database(host, port, user, password, db_name):
    """Create database and table"""
    print("Setting up database...")

    conn = None
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname='postgres'
        )
        conn.autocommit = True
        cursor = conn.cursor()

        # Drop and create database
        cursor.execute(f"DROP DATABASE IF EXISTS {db_name}")
        cursor.execute(f"CREATE DATABASE {db_name}")

        conn.commit()
    finally:
        if conn:
            conn.close()

def create_table(host, port, user, password, db_name):
    """Create the documents table"""
    print("Creating table...")

    conn = None
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=db_name
        )
        conn.autocommit = True
        cursor = conn.cursor()

        # Create table
        cursor.execute("""
            DROP TABLE IF EXISTS documents;
            CREATE TABLE documents (
                id SERIAL PRIMARY KEY,
                title TEXT,
                content TEXT
            );
        """)

        conn.commit()
    finally:
        if conn:
            conn.close()

def load_data(host, port, user, password, db_name, scale, data_dir="/data"):
    """Load synthetic data into the database"""
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
    
    data_file = f'/data/documents_{scale}.json'
    
    print(f"Loading data from {data_file}...")
    
    # Parse the pre-generated JSON data in batches
    batch_size = 10000
    documents = []
    count = 0
    
    conn = None
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=db_name
        )
        conn.autocommit = True
        cursor = conn.cursor()

        with open(data_file, 'r') as f:
            for line in f:
                try:
                    doc = json.loads(line.strip())
                    documents.append(doc)
                    count += 1
                    
                    if len(documents) >= batch_size:
                        values = [(d.get('title', ''), d.get('content', '')) for d in documents]
                        execute_values(
                            cursor,
                            "INSERT INTO documents (title, content) VALUES %s",
                            values
                        )
                        documents = []
                        
                    if count >= expected_size:
                        break
                        
                except json.JSONDecodeError as e:
                    print(f"Error parsing line: {e}", file=sys.stderr)
                    continue
        
        # Insert remaining documents
        if documents:
            values = [(d.get('title', ''), d.get('content', '')) for d in documents]
            execute_values(
                cursor,
                "INSERT INTO documents (title, content) VALUES %s",
                values
            )
        
        conn.commit()
        end_time = time.perf_counter()
        loading_time = end_time - start_time
        print(f"Loaded {count} documents")
        
        # Save data loading time
        with open('/tmp/data_loading_time.txt', 'w') as f:
            f.write(f"Data loading time: {loading_time:.6f}s\n")
            
    except Exception as e:
        print(f"Error during data loading: {e}", file=sys.stderr)
        raise
    finally:
        if conn:
            conn.close()

def create_index(host, port, user, password, db_name):
    """Create the BM25 search index"""
    print("Creating search index...")

    start_time = time.perf_counter()

    conn = None
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=db_name
        )
        conn.autocommit = True
        cursor = conn.cursor()

        # Create BM25 index
        cursor.execute("""
            CREATE INDEX documents_search_idx ON documents
            USING bm25 (id, title, content)
            WITH (key_field='id');
        """)

        conn.commit()
        
        # Optimize table statistics
        print("Running VACUUM ANALYZE...")
        old_isolation_level = conn.isolation_level
        conn.set_isolation_level(0) # ISOLATION_LEVEL_AUTOCOMMIT
        cursor.execute("VACUUM ANALYZE documents;")
        conn.set_isolation_level(old_isolation_level)
        
        end_time = time.perf_counter()
        index_time = end_time - start_time
        print("Search index created")
        
        # Save index creation time
        with open('/tmp/index_creation_time.txt', 'w') as f:
            f.write(f"Index creation time: {index_time:.6f}s\n")
            
    finally:
        if conn:
            conn.close()

def run_single_query(conn_pool, db_name, query_sql):
    """Run a single query and return execution time"""
    conn = conn_pool.getconn()
    try:
        cursor = conn.cursor()

        start_time = time.perf_counter()
        cursor.execute(query_sql)
        results = cursor.fetchall()
        end_time = time.perf_counter()

        return end_time - start_time, len(results)
    finally:
        conn_pool.putconn(conn)

def run_concurrent_queries(conn_pool, db_name, query_type, transactions, concurrency, quiet=False):
    """Run queries concurrently"""

    # Query configurations
    query_configs = {
        1: {
            'name': 'Simple Term Search',
            'terms': ["data", "information", "system", "service", "request", "report", "analysis", "record"],
            'query_template': lambda term: f"SELECT id, title FROM documents WHERE documents @@@ 'content:{term}' ORDER BY paradedb.score(documents) DESC LIMIT 10;"
        },
        2: {
            'name': 'Phrase Search',
            'terms': ["public data", "service request", "data analysis", "information system", "record management", "data processing", "service delivery", "information access"],
            'query_template': lambda phrase: f"SELECT id, title FROM documents WHERE documents @@@ 'content:\"{phrase}\"' ORDER BY paradedb.score(documents) DESC LIMIT 10;"
        },
        3: {
            'name': 'Complex Query',
            'term1s': ["data", "information", "system", "service", "request", "report", "analysis", "record"],
            'term2s': ["public", "management", "processing", "delivery", "access", "collection", "storage", "retrieval"],
            'query_template': lambda term1, term2: f"SELECT id, title FROM documents WHERE documents @@@ 'content:{term1} OR content:{term2}' ORDER BY paradedb.score(documents) DESC LIMIT 20;"
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
                query_sql = config['query_template'](term1, term2)
            else:
                term_idx = (i - 1) % len(config['terms'])
                term = config['terms'][term_idx]
                query_sql = config['query_template'](term)

            query_time, result_count = run_single_query(conn_pool, db_name, query_sql)
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
    parser = argparse.ArgumentParser(description='ParadeDB Benchmark Script')
    parser.add_argument('-q', '--quiet', action='store_true', help='Run in quiet mode')
    parser.add_argument('--host', default=os.environ.get('DB_HOST', 'localhost'), help='Database host')
    parser.add_argument('--port', type=int, default=int(os.environ.get('DB_PORT', '5432')), help='Database port')
    parser.add_argument('--dbname', default=os.environ.get('POSTGRES_DB', 'benchmark_db'), help='Database name')
    parser.add_argument('--user', default=os.environ.get('POSTGRES_USER', 'benchmark_user'), help='Database user')
    parser.add_argument('--password', default=os.environ.get('POSTGRES_PASSWORD', 'benchmark_password_123'), help='Database password')
    parser.add_argument('--scale', default=os.environ.get('SCALE', 'small'), help='Data scale (small, medium, large)')
    parser.add_argument('--transactions', type=int, default=int(os.environ.get('TRANSACTIONS', '10')), help='Number of transactions per query type')
    parser.add_argument('--concurrency', type=int, default=int(os.environ.get('CONCURRENCY', '1')), help='Concurrency level')
    parser.add_argument('--data-dir', default='/data', help='Data directory path')

    args = parser.parse_args()

    # Wait for database
    if not wait_for_database(args.host, args.port, args.user, args.password):
        sys.exit(1)

    # Setup operations using direct connections
    setup_database(args.host, args.port, args.user, args.password, args.dbname)
    create_table(args.host, args.port, args.user, args.password, args.dbname)
    load_data(args.host, args.port, args.user, args.password, args.dbname, args.scale, args.data_dir)
    create_index(args.host, args.port, args.user, args.password, args.dbname)

    # Create connection pool for benchmark operations
    benchmark_pool = create_connection_pool(
        args.host, args.port, args.dbname, args.user, args.password,
        min_conn=args.concurrency, max_conn=args.concurrency * 2
    )

    # Count total documents
    conn = benchmark_pool.getconn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM documents;")
        count = cursor.fetchone()[0]
        print(f"Total documents in database: {count}")
    finally:
        cursor.close()
        benchmark_pool.putconn(conn)

    try:
        if not args.quiet:
            print("Warming up...")
            
        # Warmup
        for query_type in [1, 2, 3]:
            run_concurrent_queries(
                benchmark_pool, args.dbname, query_type,
                transactions=max(1, args.transactions // 10),
                concurrency=args.concurrency,
                quiet=True
            )

        if not args.quiet:
            print("Running benchmark queries...")

        # Run all three query types
        for query_type in [1, 2, 3]:
            avg_latency, total_time = run_concurrent_queries(
                benchmark_pool, args.dbname, query_type,
                args.transactions, args.concurrency, args.quiet
            )

            # Write results to files (matching the shell script output format)
            with open(f'/tmp/query{query_type}_time.txt', 'w') as f:
                f.write(f"Average Latency for Query {query_type}: {avg_latency:.6f}s\n")
                f.write(f"Wall time for Query {query_type}: {total_time:.6f}s\n")

        if not args.quiet:
            print("Benchmark completed. Results saved to /tmp/")

    finally:
        benchmark_pool.closeall()

if __name__ == "__main__":
    main()