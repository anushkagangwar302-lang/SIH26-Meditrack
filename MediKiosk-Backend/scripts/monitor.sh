#!/bin/bash
# MediKiosk-Backend Monitoring Script
# Provides real-time monitoring and diagnostics for the system

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
REFRESH_INTERVAL=5

# Functions
print_header() {
    clear
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo "Timestamp: $(date +'%Y-%m-%d %H:%M:%S')"
    echo ""
}

monitor_docker() {
    print_header "Docker Containers Status"
    
    cd "$PROJECT_ROOT"
    docker-compose ps
}

monitor_resources() {
    print_header "System Resources"
    
    echo "CPU Usage:"
    top -bn1 | grep "Cpu(s)" | sed "s/.*, *\([0-9.]*\)%id.*/\1/" | awk '{print 100 - $1"%"}'
    
    echo ""
    echo "Memory Usage:"
    free -h
    
    echo ""
    echo "Disk Usage:"
    df -h /
    
    echo ""
    echo "Docker Stats:"
    docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}"
}

monitor_application() {
    print_header "Application Metrics"
    
    # Check if application is responding
    if curl -f -s http://localhost:8000/healthz > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} Application is healthy"
    else
        echo -e "${RED}✗${NC} Application is not responding"
    fi
    
    echo ""
    
    # Get request count (if metrics are enabled)
    echo "Recent application logs:"
    docker-compose logs --tail=10 api 2>/dev/null | grep -E "INFO|ERROR|WARNING" || echo "No recent logs"
}

monitor_database() {
    print_header "Database Metrics"
    
    cd "$PROJECT_ROOT"
    
    # Check database connection
    if docker-compose exec -T postgres pg_isready -U medikiosk &> /dev/null; then
        echo -e "${GREEN}✓${NC} Database is accepting connections"
    else
        echo -e "${RED}✗${NC} Database is not accepting connections"
    fi
    
    echo ""
    
    # Get database statistics
    echo "Database Statistics:"
    docker-compose exec -T postgres psql -U medikiosk -d medikiosk -c "
        SELECT 
            schemaname,
            tablename,
            n_live_tup as row_count,
            n_dead_tup as dead_rows,
            last_vacuum,
            last_autovacuum
        FROM pg_stat_user_tables 
        ORDER BY n_live_tup DESC;
    " 2>/dev/null || echo "Unable to fetch database statistics"
}

monitor_redis() {
    print_header "Redis Metrics"
    
    cd "$PROJECT_ROOT"
    
    # Check Redis connection
    if docker-compose exec -T redis redis-cli ping &> /dev/null; then
        echo -e "${GREEN}✓${NC} Redis is responding"
    else
        echo -e "${RED}✗${NC} Redis is not responding"
    fi
    
    echo ""
    
    # Get Redis info
    echo "Redis Statistics:"
    docker-compose exec -T redis redis-cli INFO memory | grep -E "used_memory_human|used_memory_peak_human|mem_fragmentation_ratio"
    
    echo ""
    echo "Connected Clients:"
    docker-compose exec -T redis redis-cli CLIENT LIST | wc -l
}

monitor_celery() {
    print_header "Celery Metrics"
    
    cd "$PROJECT_ROOT"
    
    # Check Celery workers
    if docker-compose exec -T celery_worker celery -A workers.celery_app inspect ping &> /dev/null; then
        echo -e "${GREEN}✓${NC} Celery workers are responding"
    else
        echo -e "${RED}✗${NC} Celery workers are not responding"
    fi
    
    echo ""
    
    # Get active tasks
    echo "Active Tasks:"
    docker-compose exec -T celery_worker celery -A workers.celery_app inspect active 2>/dev/null || echo "No active tasks"
    
    echo ""
    
    # Get queue length
    echo "Queue Length:"
    docker-compose exec -T redis redis-cli LLEN celery 2>/dev/null || echo "Unable to fetch queue length"
}

monitor_errors() {
    print_header "Recent Errors"
    
    cd "$PROJECT_ROOT"
    
    echo "Application Errors (last 20):"
    docker-compose logs --tail=20 api 2>/dev/null | grep -i error || echo "No recent errors"
    
    echo ""
    echo "Celery Errors (last 20):"
    docker-compose logs --tail=20 celery_worker 2>/dev/null | grep -i error || echo "No recent errors"
    
    echo ""
    echo "Nginx Errors (last 20):"
    docker-compose logs --tail=20 nginx 2>/dev/null | grep -i error || echo "No recent errors"
}

monitor_network() {
    print_header "Network Metrics"
    
    echo "Network Connections:"
    netstat -an | grep ESTABLISHED | wc -l
    
    echo ""
    echo "Docker Network Stats:"
    docker stats --no-stream --format "table {{.Name}}\t{{.NetIO}}" 2>/dev/null || echo "Unable to fetch network stats"
}

continuous_monitor() {
    local mode=$1
    
    while true; do
        case $mode in
            docker)
                monitor_docker
                ;;
            resources)
                monitor_resources
                ;;
            app)
                monitor_application
                ;;
            db)
                monitor_database
                ;;
            redis)
                monitor_redis
                ;;
            celery)
                monitor_celery
                ;;
            errors)
                monitor_errors
                ;;
            network)
                monitor_network
                ;;
            all)
                monitor_docker
                echo ""
                monitor_resources
                echo ""
                monitor_application
                echo ""
                monitor_database
                echo ""
                monitor_redis
                echo ""
                monitor_celery
                echo ""
                monitor_errors
                ;;
        esac
        
        echo ""
        echo -e "${CYAN}Press Ctrl+C to exit. Refreshing in ${REFRESH_INTERVAL} seconds...${NC}"
        sleep $REFRESH_INTERVAL
    done
}

# Main function
main() {
    case "${1:-all}" in
        docker)
            if [ "$2" = "--watch" ]; then
                continuous_monitor docker
            else
                monitor_docker
            fi
            ;;
        resources)
            if [ "$2" = "--watch" ]; then
                continuous_monitor resources
            else
                monitor_resources
            fi
            ;;
        app)
            if [ "$2" = "--watch" ]; then
                continuous_monitor app
            else
                monitor_application
            fi
            ;;
        db)
            if [ "$2" = "--watch" ]; then
                continuous_monitor db
            else
                monitor_database
            fi
            ;;
        redis)
            if [ "$2" = "--watch" ]; then
                continuous_monitor redis
            else
                monitor_redis
            fi
            ;;
        celery)
            if [ "$2" = "--watch" ]; then
                continuous_monitor celery
            else
                monitor_celery
            fi
            ;;
        errors)
            if [ "$2" = "--watch" ]; then
                continuous_monitor errors
            else
                monitor_errors
            fi
            ;;
        network)
            if [ "$2" = "--watch" ]; then
                continuous_monitor network
            else
                monitor_network
            fi
            ;;
        all)
            if [ "$2" = "--watch" ]; then
                continuous_monitor all
            else
                monitor_docker
                echo ""
                monitor_resources
                echo ""
                monitor_application
                echo ""
                monitor_database
                echo ""
                monitor_redis
                echo ""
                monitor_celery
                echo ""
                monitor_errors
            fi
            ;;
        *)
            echo "Usage: $0 {docker|resources|app|db|redis|celery|errors|network|all} [--watch]"
            echo ""
            echo "Commands:"
            echo "  docker    - Monitor Docker containers"
            echo "  resources - Monitor system resources"
            echo "  app       - Monitor application metrics"
            echo "  db        - Monitor database metrics"
            echo "  redis     - Monitor Redis metrics"
            echo "  celery    - Monitor Celery metrics"
            echo "  errors    - Monitor recent errors"
            echo "  network   - Monitor network metrics"
            echo "  all       - Monitor all components"
            echo ""
            echo "Options:"
            echo "  --watch   - Continuous monitoring with auto-refresh"
            exit 1
            ;;
    esac
}

# Run main function
main "$@"
