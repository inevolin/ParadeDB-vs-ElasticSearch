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
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse

def install_python_if_needed(quiet=False):
    """Install Python3 and required packages if not available"""
    try:
        import psycopg2
        import requests
        return True
    except ImportError:
        if not quiet:
            print("Installing Python dependencies...")

        # Install Python3 if not present
        try:
            subprocess.run([sys.executable, "--version"], check=True, capture_output=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            if not quiet:
                print("Python3 not found, installing...")
            # Download and install Python3 static binary for ARM64
            arch = subprocess.run(["uname", "-m"], capture_output=True, text=True).stdout.strip()
            if arch in ["aarch64", "arm64"]:
                python_url = "https://github.com/indygreg/python-build-standalone/releases/download/20240107/cpython-3.11.7+20240107-aarch64-unknown-linux-gnu-install_only.tar.gz"
            else:
                python_url = "https://github.com/indygreg/python-build-standalone/releases/download/20240107/cpython-3.11.7+20240107-x86_64-unknown-linux-gnu-install_only.tar.gz"

            subprocess.run(["curl", "-L", "-o", "/tmp/python.tar.gz", python_url], check=True)
            subprocess.run(["tar", "-xzf", "/tmp/python.tar.gz", "-C", "/tmp"], check=True)
            python_dir = "/tmp/python"
            os.environ["PATH"] = f"{python_dir}/bin:{os.environ.get('PATH', '')}"
            sys.executable = f"{python_dir}/bin/python3"

        # Install pip packages
        subprocess.run([sys.executable, "-m", "pip", "install", "--user", "psycopg2-binary", "requests"], check=True)

        if not quiet:
            print("Python dependencies installed")
        return True

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

def wait_for_database(host, port, user, password, quiet=False):
    """Wait for database to be ready"""
    if not quiet:
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
            if not quiet:
                print("Database is ready!")
            return True
        except psycopg2.OperationalError:
            if not quiet:
                print(f"Waiting for database... (attempt {attempt + 1}/{max_attempts})")
            time.sleep(2)
            attempt += 1

    print("Database failed to become ready", file=sys.stderr)
    return False

def setup_database(host, port, user, password, db_name, quiet=False):
    """Create database and table"""
    if not quiet:
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

def create_table(host, port, user, password, db_name, quiet=False):
    """Create the documents table"""
    if not quiet:
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

def load_data(host, port, user, password, db_name, scale, data_dir="/data", quiet=False):
    """Load synthetic data into the database"""
    if not quiet:
        print("Loading data...")

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
    
    # Read pre-generated data from host
    if not quiet:
        print(f"Loading {dataset['name']} synthetic dataset...")
    
    data_file = f'/data/documents_{scale}.json'
    
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
                        cursor.executemany(
                            "INSERT INTO documents (title, content) VALUES (%s, %s)",
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
            cursor.executemany(
                "INSERT INTO documents (title, content) VALUES (%s, %s)",
                values
            )
        
        conn.commit()
        if not quiet:
            print(f"Loaded {count} documents")
            
    except Exception as e:
        print(f"Error during data loading: {e}", file=sys.stderr)
        raise
    finally:
        if conn:
            conn.close()

def create_index(host, port, user, password, db_name, quiet=False):
    """Create the BM25 search index"""
    if not quiet:
        print("Creating search index...")

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
        if not quiet:
            print("Search index created")
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
            'query_template': lambda phrase: f"SELECT id, title FROM documents WHERE documents @@@ 'content:\"{phrase}\"' LIMIT 10;"
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

    total_time = 0
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

    # Run workers concurrently
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(worker_task, worker_id) for worker_id in range(1, concurrency + 1)]

        for future in as_completed(futures):
            worker_time, worker_transactions = future.result()
            total_time += worker_time
            completed_transactions += worker_transactions

    avg_time = total_time / transactions if transactions > 0 else 0

    if not quiet:
        print(f"Average time for Query {query_type}: {avg_time:.6f}s")
        print(f"Total time for Query {query_type}: {total_time:.6f}s")

    return avg_time, total_time

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

    # Install Python dependencies if needed
    install_python_if_needed(args.quiet)

    # Wait for database
    if not wait_for_database(args.host, args.port, args.user, args.password, args.quiet):
        sys.exit(1)

    # Setup operations using direct connections
    setup_database(args.host, args.port, args.user, args.password, args.dbname, args.quiet)
    create_table(args.host, args.port, args.user, args.password, args.dbname, args.quiet)
    load_data(args.host, args.port, args.user, args.password, args.dbname, args.scale, args.data_dir, args.quiet)
    create_index(args.host, args.port, args.user, args.password, args.dbname, args.quiet)

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
            print("Running benchmark queries...")

        # Run all three query types
        for query_type in [1, 2, 3]:
            avg_time, total_time = run_concurrent_queries(
                benchmark_pool, args.dbname, query_type,
                args.transactions, args.concurrency, args.quiet
            )

            # Write results to files (matching the shell script output format)
            with open(f'/tmp/query{query_type}_time.txt', 'w') as f:
                f.write(f"Average time for Query {query_type}: {avg_time:.6f}s\n")
                f.write(f"Total time for Query {query_type}: {total_time:.6f}s\n")

        if not args.quiet:
            print("Benchmark completed. Results saved to /tmp/")

    finally:
        benchmark_pool.closeall()

if __name__ == "__main__":
    main()