#!/bin/bash
# MediKiosk-Backend Cleanup Script
# Cleans up temporary files, old logs, and Docker resources

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
TEMP_SCAN_RETENTION_HOURS=24
ENCRYPTED_VAULT_RETENTION_DAYS=365

# Logging
log() {
    local level=$1
    shift
    local message="$@"
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} ${level}: ${message}"
}

log_info() {
    log "${GREEN}INFO${NC}" "$@"
}

log_warn() {
    log "${YELLOW}WARN${NC}" "$@"
}

log_error() {
    log "${RED}ERROR${NC}" "$@"
}

# Cleanup temporary scan files
cleanup_temp_scans() {
    log_info "Cleaning up temporary scan files older than $TEMP_SCAN_RETENTION_HOURS hours..."
    
    local temp_dir="$PROJECT_ROOT/uploads/temp_scans"
    
    if [ -d "$temp_dir" ]; then
        local file_count=$(find "$temp_dir" -type f -mtime +$(echo "$TEMP_SCAN_RETENTION_HOURS/24" | bc) 2>/dev/null | wc -l)
        
        if [ $file_count -gt 0 ]; then
            find "$temp_dir" -type f -mtime +$(echo "$TEMP_SCAN_RETENTION_HOURS/24" | bc) -delete
            log_info "Removed $file_count temporary scan files"
        else
            log_info "No temporary scan files to clean up"
        fi
    else
        log_warn "Temporary scan directory not found: $temp_dir"
    fi
}

# Cleanup old encrypted vault files
cleanup_encrypted_vault() {
    log_info "Cleaning up encrypted vault files older than $ENCRYPTED_VAULT_RETENTION_DAYS days..."
    
    local vault_dir="$PROJECT_ROOT/uploads/encrypted_vault"
    
    if [ -d "$vault_dir" ]; then
        local file_count=$(find "$vault_dir" -type f -mtime +$ENCRYPTED_VAULT_RETENTION_DAYS 2>/dev/null | wc -l)
        
        if [ $file_count -gt 0 ]; then
            find "$vault_dir" -type f -mtime +$ENCRYPTED_VAULT_RETENTION_DAYS -delete
            log_info "Removed $file_count encrypted vault files"
        else
            log_info "No encrypted vault files to clean up"
        fi
    else
        log_warn "Encrypted vault directory not found: $vault_dir"
    fi
}

# Cleanup Docker resources
cleanup_docker() {
    log_info "Cleaning up Docker resources..."
    
    cd "$PROJECT_ROOT"
    
    # Remove stopped containers
    local stopped_containers=$(docker ps -aq -f status=exited)
    if [ -n "$stopped_containers" ]; then
        docker rm $stopped_containers
        log_info "Removed stopped containers"
    fi
    
    # Remove unused images
    local unused_images=$(docker images -f "dangling=true" -q)
    if [ -n "$unused_images" ]; then
        docker rmi $unused_images
        log_info "Removed unused Docker images"
    fi
    
    # Remove unused volumes
    local unused_volumes=$(docker volume ls -f "dangling=true" -q)
    if [ -n "$unused_volumes" ]; then
        docker volume rm $unused_volumes
        log_info "Removed unused Docker volumes"
    fi
    
    # Clean up build cache
    docker builder prune -f
    log_info "Cleaned up Docker build cache"
}

# Cleanup old logs
cleanup_logs() {
    log_info "Cleaning up old log files..."
    
    local log_dir="/var/log/medikiosk"
    
    if [ -d "$log_dir" ]; then
        # Remove compressed logs older than 30 days
        local old_logs=$(find "$log_dir" -name "*.gz" -mtime +30 2>/dev/null | wc -l)
        
        if [ $old_logs -gt 0 ]; then
            find "$log_dir" -name "*.gz" -mtime +30 -delete
            log_info "Removed $old_logs old log files"
        else
            log_info "No old log files to clean up"
        fi
    else
        log_warn "Log directory not found: $log_dir"
    fi
}

# Cleanup Celery task results
cleanup_celery_results() {
    log_info "Cleaning up old Celery task results..."
    
    cd "$PROJECT_ROOT"
    
    # This requires Redis CLI access
    if docker-compose exec -T redis redis-cli ping &> /dev/null; then
        # Clear old task results (optional - adjust based on your needs)
        # docker-compose exec -T redis redis-cli --scan --pattern 'celery-task-meta-*' | xargs docker-compose exec -T redis redis-cli DEL
        log_info "Celery task results cleanup (manual intervention required)"
    else
        log_warn "Redis is not available"
    fi
}

# System cleanup
cleanup_system() {
    log_info "Running system cleanup..."
    
    # Clean package cache (Debian/Ubuntu)
    if command -v apt-get &> /dev/null; then
        apt-get clean
        apt-get autoremove -y
        log_info "Cleaned package cache"
    fi
    
    # Clean package cache (RHEL/CentOS)
    if command -v yum &> /dev/null; then
        yum clean all
        log_info "Cleaned package cache"
    fi
}

# Show disk usage
show_disk_usage() {
    log_info "Current disk usage:"
    
    df -h /
    
    if [ -d "$PROJECT_ROOT/uploads" ]; then
        echo ""
        echo "Upload directories:"
        du -sh "$PROJECT_ROOT/uploads/"* 2>/dev/null
    fi
}

# Main cleanup function
main() {
    case "${1:-all}" in
        temp)
            cleanup_temp_scans
            ;;
        vault)
            cleanup_encrypted_vault
            ;;
        docker)
            cleanup_docker
            ;;
        logs)
            cleanup_logs
            ;;
        celery)
            cleanup_celery_results
            ;;
        system)
            cleanup_system
            ;;
        all)
            cleanup_temp_scans
            cleanup_encrypted_vault
            cleanup_docker
            cleanup_logs
            cleanup_celery_results
            ;;
        status)
            show_disk_usage
            ;;
        *)
            echo "Usage: $0 {temp|vault|docker|logs|celery|system|all|status}"
            echo ""
            echo "Commands:"
            echo "  temp    - Clean up temporary scan files"
            echo "  vault   - Clean up old encrypted vault files"
            echo "  docker  - Clean up Docker resources"
            echo "  logs    - Clean up old log files"
            echo "  celery  - Clean up old Celery task results"
            echo "  system  - Run system cleanup"
            echo "  all     - Run all cleanup operations"
            echo "  status  - Show current disk usage"
            exit 1
            ;;
    esac
    
    log_info "Cleanup completed"
}

# Run main function
main "$@"
