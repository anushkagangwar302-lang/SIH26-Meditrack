#!/bin/bash
# MediKiosk-Backend Health Check Script
# Monitors all services and provides detailed health status

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
HEALTH_ENDPOINT="http://localhost:8000/healthz"
READY_ENDPOINT="http://localhost:8000/readyz"

# Functions
print_header() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

print_status() {
    local status=$1
    local message=$2
    
    if [ "$status" = "OK" ]; then
        echo -e "${GREEN}✓${NC} $message"
    elif [ "$status" = "WARN" ]; then
        echo -e "${YELLOW}⚠${NC} $message"
    else
        echo -e "${RED}✗${NC} $message"
    fi
}

check_docker_services() {
    print_header "Docker Services Status"
    
    cd "$PROJECT_ROOT"
    
    # Check if docker-compose is running
    if ! docker-compose ps &> /dev/null; then
        print_status "ERROR" "Docker Compose services not running"
        return 1
    fi
    
    # Check each service
    local services=("postgres" "redis" "nginx" "api" "celery_worker" "celery_beat")
    
    for service in "${services[@]}"; do
        local status=$(docker-compose ps -q "$service" | xargs docker inspect --format='{{.State.Status}}' 2>/dev/null || echo "not running")
        
        if [ "$status" = "running" ]; then
            print_status "OK" "$service is running"
        else
            print_status "ERROR" "$service is not running (status: $status)"
        fi
    done
}

check_database() {
    print_header "Database Health"
    
    cd "$PROJECT_ROOT"
    
    # Check PostgreSQL connection
    if docker-compose exec -T postgres pg_isready -U medikiosk &> /dev/null; then
        print_status "OK" "PostgreSQL is accepting connections"
    else
        print_status "ERROR" "PostgreSQL is not accepting connections"
        return 1
    fi
    
    # Check database size
    local db_size=$(docker-compose exec -T postgres psql -U medikiosk -d medikiosk -t -c "SELECT pg_size_pretty(pg_database_size('medikiosk'));" 2>/dev/null | xargs)
    print_status "OK" "Database size: $db_size"
    
    # Check active connections
    local connections=$(docker-compose exec -T postgres psql -U medikiosk -d medikiosk -t -c "SELECT count(*) FROM pg_stat_activity WHERE datname = 'medikiosk';" 2>/dev/null | xargs)
    print_status "OK" "Active connections: $connections"
    
    # Check connection pool
    local max_connections=$(docker-compose exec -T postgres psql -U medikiosk -d medikiosk -t -c "SHOW max_connections;" 2>/dev/null | xargs)
    local usage_percentage=$((connections * 100 / max_connections))
    
    if [ $usage_percentage -lt 80 ]; then
        print_status "OK" "Connection pool usage: $usage_percentage% ($connections/$max_connections)"
    elif [ $usage_percentage -lt 90 ]; then
        print_status "WARN" "Connection pool usage: $usage_percentage% ($connections/$max_connections)"
    else
        print_status "ERROR" "Connection pool usage: $usage_percentage% ($connections/$max_connections)"
    fi
}

check_redis() {
    print_header "Redis Health"
    
    cd "$PROJECT_ROOT"
    
    # Check Redis connection
    if docker-compose exec -T redis redis-cli ping &> /dev/null; then
        print_status "OK" "Redis is responding"
    else
        print_status "ERROR" "Redis is not responding"
        return 1
    fi
    
    # Check Redis memory usage
    local memory_info=$(docker-compose exec -T redis redis-cli INFO memory | grep used_memory_human | cut -d: -f2 | tr -d '\r')
    print_status "OK" "Redis memory usage: $memory_info"
    
    # Check Redis memory percentage
    local max_memory=$(docker-compose exec -T redis redis-cli CONFIG GET maxmemory | tail -1)
    local used_memory=$(docker-compose exec -T redis redis-cli INFO memory | grep used_memory: | cut -d: -f2 | tr -d '\r')
    
    if [ "$max_memory" = "0" ]; then
        print_status "WARN" "Redis max memory not configured"
    else
        local usage_percentage=$((used_memory * 100 / max_memory))
        if [ $usage_percentage -lt 80 ]; then
            print_status "OK" "Redis memory usage: $usage_percentage%"
        else
            print_status "WARN" "Redis memory usage: $usage_percentage%"
        fi
    fi
    
    # Check connected clients
    local clients=$(docker-compose exec -T redis redis-cli CLIENT LIST | wc -l)
    print_status "OK" "Connected clients: $clients"
}

check_application() {
    print_header "Application Health"
    
    # Check health endpoint
    if curl -f -s "$HEALTH_ENDPOINT" > /dev/null 2>&1; then
        print_status "OK" "Health endpoint responding"
    else
        print_status "ERROR" "Health endpoint not responding"
        return 1
    fi
    
    # Check ready endpoint
    if curl -f -s "$READY_ENDPOINT" > /dev/null 2>&1; then
        print_status "OK" "Ready endpoint responding"
    else
        print_status "WARN" "Ready endpoint not responding (application may be starting)"
    fi
    
    # Get detailed health info
    local health_info=$(curl -s "$HEALTH_ENDPOINT" 2>/dev/null)
    echo -e "${BLUE}Health Info:${NC}"
    echo "$health_info" | python3 -m json.tool 2>/dev/null || echo "$health_info"
}

check_celery() {
    print_header "Celery Workers Health"
    
    cd "$PROJECT_ROOT"
    
    # Check Celery workers
    if docker-compose exec -T celery_worker celery -A workers.celery_app inspect ping &> /dev/null; then
        print_status "OK" "Celery workers are responding"
    else
        print_status "ERROR" "Celery workers are not responding"
        return 1
    fi
    
    # Check active tasks
    local active_tasks=$(docker-compose exec -T celery_worker celery -A workers.celery_app inspect active | grep -c "task" || echo "0")
    print_status "OK" "Active tasks: $active_tasks"
    
    # Check registered tasks
    local registered_tasks=$(docker-compose exec -T celery_worker celery -A workers.celery_app inspect registered | grep -c "task" || echo "0")
    print_status "OK" "Registered tasks: $registered_tasks"
    
    # Check Celery beat
    if docker-compose exec -T celery_beat celery -A workers.celery_app inspect ping &> /dev/null; then
        print_status "OK" "Celery beat is responding"
    else
        print_status "ERROR" "Celery beat is not responding"
    fi
}

check_disk_space() {
    print_header "Disk Space"
    
    # Check disk usage
    local disk_usage=$(df -h / | tail -1 | awk '{print $5}' | sed 's/%//')
    
    if [ $disk_usage -lt 80 ]; then
        print_status "OK" "Disk usage: $disk_usage%"
    elif [ $disk_usage -lt 90 ]; then
        print_status "WARN" "Disk usage: $disk_usage%"
    else
        print_status "ERROR" "Disk usage: $disk_usage%"
    fi
    
    # Check upload directories
    local temp_scans_size=$(du -sh "$PROJECT_ROOT/uploads/temp_scans" 2>/dev/null | awk '{print $1}')
    local encrypted_vault_size=$(du -sh "$PROJECT_ROOT/uploads/encrypted_vault" 2>/dev/null | awk '{print $1}')
    
    print_status "OK" "Temp scans size: $temp_scans_size"
    print_status "OK" "Encrypted vault size: $encrypted_vault_size"
}

check_ssl_certificates() {
    print_header "SSL Certificates"
    
    local cert_file="$PROJECT_ROOT/nginx/ssl/cert.pem"
    
    if [ ! -f "$cert_file" ]; then
        print_status "ERROR" "SSL certificate not found"
        return 1
    fi
    
    # Check certificate expiry
    local expiry_date=$(openssl x509 -enddate -noout -in "$cert_file" | cut -d= -f2)
    local expiry_epoch=$(date -d "$expiry_date" +%s)
    local current_epoch=$(date +%s)
    local days_until_expiry=$(( (expiry_epoch - current_epoch) / 86400 ))
    
    if [ $days_until_expiry -gt 30 ]; then
        print_status "OK" "SSL certificate expires in $days_until_expiry days ($expiry_date)"
    elif [ $days_until_expiry -gt 7 ]; then
        print_status "WARN" "SSL certificate expires in $days_until_expiry days ($expiry_date)"
    else
        print_status "ERROR" "SSL certificate expires in $days_until_expiry days ($expiry_date)"
    fi
}

main() {
    print_header "MediKiosk-Backend Health Check"
    echo "Timestamp: $(date)"
    echo ""
    
    check_docker_services
    echo ""
    
    check_database
    echo ""
    
    check_redis
    echo ""
    
    check_application
    echo ""
    
    check_celery
    echo ""
    
    check_disk_space
    echo ""
    
    check_ssl_certificates
    echo ""
    
    print_header "Health Check Complete"
}

# Run main function
main
