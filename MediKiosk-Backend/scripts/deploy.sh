#!/bin/bash
# MediKiosk-Backend Production Deployment Script
# This script automates the deployment process with safety checks and rollbacks

set -e  # Exit on error
set -o pipefail  # Catch errors in pipes

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DEPLOYMENT_LOG="/var/log/medikiosk/deployment.log"
BACKUP_DIR="/var/backups/medikiosk"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Logging function
log() {
    local level=$1
    shift
    local message="$@"
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} ${level}: ${message}" | tee -a "$DEPLOYMENT_LOG"
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

# Pre-deployment checks
pre_deployment_checks() {
    log_info "Running pre-deployment checks..."
    
    # Check if .env exists
    if [ ! -f "$PROJECT_ROOT/.env" ]; then
        log_error ".env file not found. Please create it from .env.example"
        exit 1
    fi
    
    # Check if running as root (not recommended)
    if [ "$EUID" -eq 0 ]; then
        log_warn "Running as root is not recommended. Consider using a non-root user."
    fi
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed"
        exit 1
    fi
    
    # Check Docker Compose
    if ! command -v docker-compose &> /dev/null; then
        log_error "Docker Compose is not installed"
        exit 1
    fi
    
    # Check if Docker is running
    if ! docker info &> /dev/null; then
        log_error "Docker daemon is not running"
        exit 1
    fi
    
    # Check SSL certificates
    if [ ! -f "$PROJECT_ROOT/nginx/ssl/cert.pem" ] || [ ! -f "$PROJECT_ROOT/nginx/ssl/key.pem" ]; then
        log_error "SSL certificates not found in nginx/ssl/"
        exit 1
    fi
    
    # Check environment variables
    source "$PROJECT_ROOT/.env"
    if [ "$POSTGRES_PASSWORD" = "CHANGE_ME" ]; then
        log_error "POSTGRES_PASSWORD is still set to CHANGE_ME"
        exit 1
    fi
    
    if [ "$JWT_SECRET_KEY" = "CHANGE_ME" ]; then
        log_error "JWT_SECRET_KEY is still set to CHANGE_ME"
        exit 1
    fi
    
    log_info "Pre-deployment checks passed"
}

# Create backup
create_backup() {
    log_info "Creating backup..."
    
    mkdir -p "$BACKUP_DIR"
    
    # Backup database
    log_info "Backing up database..."
    docker-compose -f "$PROJECT_ROOT/docker-compose.yml" exec -T postgres pg_dump -U medikiosk medikiosk | gzip > "$BACKUP_DIR/database_$TIMESTAMP.sql.gz"
    
    # Backup Redis
    log_info "Backing up Redis..."
    docker-compose -f "$PROJECT_ROOT/docker-compose.yml" exec -T redis redis-cli SAVE
    docker cp $(docker-compose -f "$PROJECT_ROOT/docker-compose.yml" ps -q redis):/data/dump.rdb "$BACKUP_DIR/redis_$TIMESTAMP.rdb"
    
    # Backup .env (without secrets)
    log_info "Backing up configuration..."
    cp "$PROJECT_ROOT/.env" "$BACKUP_DIR/env_$TIMESTAMP.bak"
    
    log_info "Backup completed: $BACKUP_DIR/*_$TIMESTAMP.*"
}

# Run database migrations
run_migrations() {
    log_info "Running database migrations..."
    
    docker-compose -f "$PROJECT_ROOT/docker-compose.yml" exec api alembic upgrade head
    
    if [ $? -eq 0 ]; then
        log_info "Database migrations completed successfully"
    else
        log_error "Database migrations failed"
        rollback
        exit 1
    fi
}

# Deploy application
deploy_application() {
    log_info "Deploying application..."
    
    cd "$PROJECT_ROOT"
    
    # Pull latest images
    log_info "Pulling latest Docker images..."
    docker-compose -f docker-compose.yml pull
    
    # Build images
    log_info "Building Docker images..."
    docker-compose -f docker-compose.yml build --no-cache
    
    # Stop existing services
    log_info "Stopping existing services..."
    docker-compose -f docker-compose.yml down
    
    # Start services
    log_info "Starting services..."
    docker-compose -f docker-compose.yml up -d
    
    # Wait for services to be healthy
    log_info "Waiting for services to be healthy..."
    sleep 30
    
    # Check service health
    check_health
}

# Health check
check_health() {
    log_info "Checking service health..."
    
    local max_attempts=30
    local attempt=0
    
    while [ $attempt -lt $max_attempts ]; do
        if curl -f -s http://localhost:8000/healthz > /dev/null 2>&1; then
            log_info "Application is healthy"
            return 0
        fi
        
        attempt=$((attempt + 1))
        log_warn "Health check attempt $attempt failed, retrying..."
        sleep 10
    done
    
    log_error "Health check failed after $max_attempts attempts"
    rollback
    exit 1
}

# Rollback function
rollback() {
    log_error "Initiating rollback..."
    
    cd "$PROJECT_ROOT"
    
    # Stop current deployment
    docker-compose -f docker-compose.yml down
    
    # Restore from backup
    if [ -f "$BACKUP_DIR/database_$TIMESTAMP.sql.gz" ]; then
        log_info "Restoring database from backup..."
        gunzip < "$BACKUP_DIR/database_$TIMESTAMP.sql.gz" | docker-compose -f docker-compose.yml exec -T postgres psql -U medikiosk medikiosk
    fi
    
    log_info "Rollback completed"
}

# Post-deployment verification
post_deployment_verification() {
    log_info "Running post-deployment verification..."
    
    # Test authentication endpoint
    log_info "Testing authentication endpoint..."
    if curl -f -s http://localhost:8000/healthz > /dev/null 2>&1; then
        log_info "Health endpoint responding"
    else
        log_error "Health endpoint not responding"
        exit 1
    fi
    
    # Check database connection
    log_info "Checking database connection..."
    docker-compose -f "$PROJECT_ROOT/docker-compose.yml" exec api python -c "from app.core.database import engine; import asyncio; asyncio.run(engine.connect())"
    
    # Check Redis connection
    log_info "Checking Redis connection..."
    docker-compose -f "$PROJECT_ROOT/docker-compose.yml" exec api python -c "from app.core.database import redis_client; redis_client.ping()"
    
    # Check Celery workers
    log_info "Checking Celery workers..."
    docker-compose -f "$PROJECT_ROOT/docker-compose.yml" exec celery_worker celery -A workers.celery_app inspect ping
    
    log_info "Post-deployment verification completed"
}

# Main deployment function
main() {
    log_info "Starting deployment process..."
    log_info "Timestamp: $TIMESTAMP"
    
    pre_deployment_checks
    create_backup
    deploy_application
    run_migrations
    post_deployment_verification
    
    log_info "Deployment completed successfully!"
    log_info "Backup location: $BACKUP_DIR/*_$TIMESTAMP.*"
    
    # Cleanup old backups (keep last 7 days)
    log_info "Cleaning up old backups..."
    find "$BACKUP_DIR" -name "database_*.sql.gz" -mtime +7 -delete
    find "$BACKUP_DIR" -name "redis_*.rdb" -mtime +7 -delete
    find "$BACKUP_DIR" -name "env_*.bak" -mtime +7 -delete
}

# Handle script arguments
case "${1:-deploy}" in
    deploy)
        main
        ;;
    rollback)
        rollback
        ;;
    health)
        check_health
        ;;
    backup)
        create_backup
        ;;
    *)
        echo "Usage: $0 {deploy|rollback|health|backup}"
        exit 1
        ;;
esac
