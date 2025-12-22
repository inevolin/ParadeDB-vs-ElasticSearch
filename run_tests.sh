#!/bin/bash

# ParadeDB vs Elasticsearch Full-Text Search Benchmark Runner
# This script provides a unified interface to run benchmarks with different configurations

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
DATABASES=("paradedb" "elasticsearch")
CONFIG_FILE="config/benchmark_config.json"
SCALE=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['benchmark'].get('scale', 'small'))")

# Define scale-prefixed directories
DATA_DIR="data"
RESULTS_DIR="results"
PLOTS_DIR="plots"

# Load resource defaults from config
CPU=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['resources']['paradedb']['cpu_request'])")
MEMORY=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['resources']['paradedb']['memory_request'])")
JVM_OPTS=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['resources']['elasticsearch']['jvm_opts'])")
TRANSACTIONS=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['benchmark']['transactions'])")
CONCURRENCY=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['benchmark']['concurrency'])")


# Function to print usage
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Run full-text search benchmarks for ParadeDB and Elasticsearch"
    echo ""
    echo "OPTIONS:"
    echo "  -d, --databases DB1 DB2    Databases to benchmark (paradedb, elasticsearch)"
    echo "                             Default: paradedb elasticsearch"
    echo "  -s, --scale SCALE          Data scale (small, medium, large)"
    echo "                             Default: small"
    echo "  --cpu CPU                  CPU resources for databases (e.g., 4, 1000m)"
    echo "                             Default: from config"
    echo "  --mem MEM                  Memory resources for databases (e.g., 2Gi, 4GB)"
    echo "                             Default: from config"
    echo "  --jvm-opts OPTS            JVM options for Elasticsearch (e.g., '-Xms2g -Xmx4g')"
    echo "                             Default: from config"
    echo "  -h, --help                 Show this help message"
    echo ""
    echo "EXAMPLES:"
    echo "  $0 --scale medium"
    echo "  $0 --databases paradedb --scale large"
    echo "  $0 --databases elasticsearch --scale small"
    echo "  $0 --cpu 2 --mem 8Gi"
}

# Function to print colored output
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check prerequisites
check_prerequisites() {
    print_info "Checking prerequisites..."

    # Check if kubectl is available (for k8s deployments)
    if command -v kubectl &> /dev/null; then
        print_info "kubectl found - Kubernetes deployments available"
    else
        print_warning "kubectl not found - manual database setup required"
    fi

    print_success "Prerequisites check passed"
}

# Function to clean database data
cleanup_database_data() {
    print_info "Cleaning up database data..."
    # (delete the PV/PVC if used, or local data directories)
}

# Function to generate data on host
generate_data_on_host() {
    print_info "Generating data on host for scale: $SCALE"
    
    mkdir -p "$DATA_DIR"
    
    if [[ ! -f "$DATA_DIR/documents_${SCALE}.json" ]]; then
        python3 scripts/generate_synthetic_data.py "$SCALE" > "$DATA_DIR/documents_${SCALE}.json"
        print_success "Data generated and saved to $DATA_DIR/documents_${SCALE}.json"
    else
        print_info "Data file $DATA_DIR/documents_${SCALE}.json already exists"
    fi
    
    if [[ ! -f "$DATA_DIR/documents_${SCALE}.ndjson" ]]; then
        cat "$DATA_DIR/documents_${SCALE}.json" | while read -r line; do
            echo "{\"index\":{\"_index\":\"documents\"}}"
            echo "$line"
        done > "$DATA_DIR/documents_${SCALE}.ndjson"
        print_success "NDJSON file generated and saved to $DATA_DIR/documents_${SCALE}.ndjson"
    else
        print_info "NDJSON file $DATA_DIR/documents_${SCALE}.ndjson already exists"
    fi
}

# Function to update Kubernetes YAML files with resource specifications
update_k8s_resources() {
    print_info "Updating Kubernetes resource specifications..."

    # Copy templates to deployment files
    cp k8s/paradedb-deployment-template.yaml k8s/paradedb-deployment.yaml
    cp k8s/elasticsearch-deployment-template.yaml k8s/elasticsearch-deployment.yaml

    # Compute absolute paths relative to current directory
    DATA_PATH="$(pwd)/$DATA_DIR"
    SCRIPT_PATH="$(pwd)/scripts"
    CONFIG_PATH="$(pwd)/config"

    # Replace path placeholders in both deployments
    sed -i '' "s|DATA_PATH_PLACEHOLDER|$DATA_PATH|g" k8s/paradedb-deployment.yaml
    sed -i '' "s|SCRIPT_PATH_PLACEHOLDER|$SCRIPT_PATH|g" k8s/paradedb-deployment.yaml
    sed -i '' "s|CONFIG_PATH_PLACEHOLDER|$CONFIG_PATH|g" k8s/paradedb-deployment.yaml
    sed -i '' "s|DATA_PATH_PLACEHOLDER|$DATA_PATH|g" k8s/elasticsearch-deployment.yaml
    sed -i '' "s|SCRIPT_PATH_PLACEHOLDER|$SCRIPT_PATH|g" k8s/elasticsearch-deployment.yaml
    sed -i '' "s|CONFIG_PATH_PLACEHOLDER|$CONFIG_PATH|g" k8s/elasticsearch-deployment.yaml

    # Replace placeholders in ParadeDB deployment
    sed -i '' "s/CPU_REQUEST_PLACEHOLDER/$CPU/g" k8s/paradedb-deployment.yaml
    sed -i '' "s/CPU_LIMIT_PLACEHOLDER/$CPU/g" k8s/paradedb-deployment.yaml
    sed -i '' "s/MEMORY_REQUEST_PLACEHOLDER/$MEMORY/g" k8s/paradedb-deployment.yaml
    sed -i '' "s/MEMORY_LIMIT_PLACEHOLDER/$MEMORY/g" k8s/paradedb-deployment.yaml

    # Replace placeholders in Elasticsearch deployment
    sed -i '' "s/CPU_REQUEST_PLACEHOLDER/$CPU/g" k8s/elasticsearch-deployment.yaml
    sed -i '' "s/CPU_LIMIT_PLACEHOLDER/$CPU/g" k8s/elasticsearch-deployment.yaml
    sed -i '' "s/MEMORY_REQUEST_PLACEHOLDER/$MEMORY/g" k8s/elasticsearch-deployment.yaml
    sed -i '' "s/MEMORY_LIMIT_PLACEHOLDER/$MEMORY/g" k8s/elasticsearch-deployment.yaml
    sed -i '' "s/JVM_OPTS_PLACEHOLDER/$JVM_OPTS/g" k8s/elasticsearch-deployment.yaml

    print_success "Kubernetes resource specifications updated"
}

# Function to delete existing deployments
delete_deployments() {
    print_info "Deleting existing deployments..."
    kubectl delete deployments --all
    kubectl wait --for=delete pod --all --timeout=60s || true
    print_success "Existing deployments deleted"
}

# Function to teardown a specific database
teardown_database() {
    local db=$1
    print_info "Tearing down $db deployment..."

    if command -v kubectl &> /dev/null; then
        # Check for errors in pod logs before teardown
        local pod_name
        if [[ "$db" == "paradedb" ]]; then
            pod_name=$(kubectl get pods -l app=paradedb --field-selector=status.phase=Running -o name --sort-by=.metadata.creationTimestamp | tail -1 | cut -d/ -f2)
        elif [[ "$db" == "elasticsearch" ]]; then
            pod_name=$(kubectl get pods -l app=elasticsearch --field-selector=status.phase=Running -o name --sort-by=.metadata.creationTimestamp | tail -1 | cut -d/ -f2)
        fi
        
        if [[ -n "$pod_name" ]]; then
            # Check pod status
            local pod_phase=$(kubectl get pod $pod_name -o jsonpath='{.status.phase}')
            if [[ "$pod_phase" != "Running" && "$pod_phase" != "Succeeded" ]]; then
                echo "Pod $pod_name is in $pod_phase state, aborting teardown"
                exit 1
            fi
            
            # Check for errors in logs
            local errors=$(kubectl logs $pod_name 2>&1 | grep -E "(ERROR|Exception|Failed|FATAL)" | grep -v "JVM arguments" | grep -v "PrematureChannelClosureException" || true)
            local has_errors=false
            if [[ -n "$errors" ]]; then
                echo "Errors found in $db pod logs:"
                echo "$errors"
                echo "Continuing with teardown, but aborting further testing"
                has_errors=true
            fi
        fi
        
        if [[ "$db" == "paradedb" ]]; then
            kubectl delete -f k8s/paradedb-deployment.yaml --ignore-not-found=true || true
            kubectl wait --for=delete pod -l app=paradedb --timeout=60s || true
        elif [[ "$db" == "elasticsearch" ]]; then
            kubectl delete -f k8s/elasticsearch-deployment.yaml --ignore-not-found=true || true
            kubectl wait --for=delete pod -l app=elasticsearch --timeout=60s || true
        fi
        print_success "$db deployment torn down"
        if [[ "$has_errors" == "true" ]]; then
            exit 1
        fi
    else
        print_warning "kubectl not available - skipping $db teardown"
    fi
}

# Function to setup a specific database
setup_database() {
    local db=$1
    print_info "Setting up $db database..."

    if command -v kubectl &> /dev/null; then
        # Create namespace if it doesn't exist
        kubectl apply -f k8s/namespace.yaml

        if [[ "$db" == "paradedb" ]]; then
            print_info "Deploying ParadeDB..."
            kubectl apply -f k8s/paradedb-deployment.yaml
            kubectl wait --for=condition=ready pod -l app=paradedb --timeout=300s
        elif [[ "$db" == "elasticsearch" ]]; then
            print_info "Deploying Elasticsearch..."
            kubectl apply -f k8s/elasticsearch-deployment.yaml
            kubectl wait --for=condition=ready pod -l app=elasticsearch --timeout=300s
        fi
        print_success "$db deployment completed"
    else
        print_warning "kubectl not available. Please ensure $db is running manually."
        if [[ "$db" == "paradedb" ]]; then
            print_warning "Expected: ParadeDB on localhost:5432"
        elif [[ "$db" == "elasticsearch" ]]; then
            print_warning "Expected: Elasticsearch on localhost:9200"
        fi
    fi
}

# Function to run benchmarks for a specific database
run_benchmark() {
    local db=$1
    print_info "Running benchmark for $db (scale: $SCALE)"

    if [[ ! -d "$RESULTS_DIR" ]]; then
        mkdir -p "$RESULTS_DIR"
    fi

    if command -v kubectl &> /dev/null; then
        # Copy benchmark script to pod and run it
        local pod_name
        if [[ "$db" == "paradedb" ]]; then
            pod_name=$(kubectl get pods -l app=paradedb --field-selector=status.phase=Running -o name --sort-by=.metadata.creationTimestamp | tail -1 | cut -d/ -f2)
            kubectl exec $pod_name -- python3 /scripts/benchmark_paradedb.py --scale $SCALE --transactions $TRANSACTIONS --concurrency $CONCURRENCY --quiet
            # Copy results back
            kubectl cp $pod_name:/tmp/query1_time.txt "$RESULTS_DIR/${SCALE}_${db}_query1_time.txt" || true
            kubectl cp $pod_name:/tmp/query2_time.txt "$RESULTS_DIR/${SCALE}_${db}_query2_time.txt" || true
            kubectl cp $pod_name:/tmp/query3_time.txt "$RESULTS_DIR/${SCALE}_${db}_query3_time.txt" || true
        elif [[ "$db" == "elasticsearch" ]]; then
            pod_name=$(kubectl get pods -l app=elasticsearch --field-selector=status.phase=Running -o name --sort-by=.metadata.creationTimestamp | tail -1 | cut -d/ -f2)
            kubectl exec $pod_name -- chmod +x /scripts/benchmark_elasticsearch.sh
            kubectl exec $pod_name -- env SCALE=$SCALE TRANSACTIONS=$TRANSACTIONS CONCURRENCY=$CONCURRENCY /scripts/benchmark_elasticsearch.sh --quiet
            # Copy results back
            kubectl cp $pod_name:/tmp/query1_time.txt "$RESULTS_DIR/${SCALE}_${db}_query1_time.txt" || true
            kubectl cp $pod_name:/tmp/query2_time.txt "$RESULTS_DIR/${SCALE}_${db}_query2_time.txt" || true
            kubectl cp $pod_name:/tmp/query3_time.txt "$RESULTS_DIR/${SCALE}_${db}_query3_time.txt" || true
        fi
        print_success "$db benchmark completed"
    else
        print_warning "kubectl not available - skipping $db benchmark"
    fi
}

# Function to generate plots
generate_plots() {
    print_info "Generating performance plots..."

    if [[ ! -d "$PLOTS_DIR" ]]; then
        mkdir -p "$PLOTS_DIR"
    fi

    # Call Python script to generate plots
    python3 generate_plots.py "${DATABASES[@]}" "$SCALE"

    print_success "Plot generation completed"
}


# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -d|--databases)
            shift
            DATABASES=()
            while [[ $# -gt 0 && ! $1 =~ ^- ]]; do
                DATABASES+=("$1")
                shift
            done
            ;;
        -s|--scale)
            SCALE="$2"
            shift 2
            ;;
        --cpu)
            CPU="$2"
            shift 2
            ;;
        --mem)
            MEMORY="$2"
            shift 2
            ;;
        --jvm-opts)
            JVM_OPTS="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

# Validate arguments
if [[ ! " small medium large " =~ " $SCALE " ]]; then
    print_error "Invalid scale: $SCALE. Must be one of: small, medium, large"
    exit 1
fi

for db in "${DATABASES[@]}"; do
    if [[ ! " paradedb elasticsearch " =~ " $db " ]]; then
        print_error "Invalid database: $db. Must be one of: paradedb, elasticsearch"
        exit 1
    fi
done

if [[ ! -f "$CONFIG_FILE" ]]; then
    print_error "Configuration file not found: $CONFIG_FILE"
    exit 1
fi

# Validate resource formats
validate_resource() {
    local value=$1
    local type=$2
    if [[ "$type" == "CPU" ]]; then
        if [[ ! $value =~ ^[0-9]+(m)?$ ]]; then
            print_error "Invalid $type resource format: $value. Use formats like 4, 1000m"
            exit 1
        fi
    else
        if [[ ! $value =~ ^[0-9]+(m|Mi|Gi|G)?$ ]]; then
            print_error "Invalid $type resource format: $value. Use formats like 1000m, 2Gi, 512Mi"
            exit 1
        fi
    fi
}

validate_resource "$CPU" "CPU"
validate_resource "$MEMORY" "Memory"

# Main execution
print_info "Starting ParadeDB vs Elasticsearch Benchmark Suite"
print_info "Configuration:"
print_info "  Databases: ${DATABASES[*]}"
print_info "  Scale: $SCALE"
print_info "  Transactions: $TRANSACTIONS"
print_info "  Config: $CONFIG_FILE"
print_info "  Resources: CPU=${CPU}, Memory=${MEMORY}, JVM_OPTS=${JVM_OPTS}"
echo

cleanup_database_data
check_prerequisites
generate_data_on_host
update_k8s_resources
delete_deployments
# download_data  # Data is now downloaded by benchmark scripts

# Run benchmarks for each database separately
for db in "${DATABASES[@]}"; do
    setup_database "$db"
    run_benchmark "$db"
    teardown_database "$db"
done

generate_plots

print_success "Benchmark suite completed successfully!"
print_info "Results are available in the '$RESULTS_DIR/' directory"
print_info "Plots are available in the '$PLOTS_DIR/' directory"
print_info "Check README.md for detailed analysis instructions"
