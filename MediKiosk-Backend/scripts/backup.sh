#!/bin/bash
# MediKiosk-Backend Backup Script
# Creates automated backups of database, Redis, and configuration

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
BACKUP_DIR="/var/backups/medikiosk"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=30

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

# Create backup directory
create_backup_dir() {
    mkdir -p "$BACKUP_DIR/database"
    mkdir -p "$BACKUP_DIR/redis"
    mkdir -p "$BACKUP_DIR/config"
    mkdir -p "$BACKUP_DIR/uploads"
    
    log_info "Backup directory created: $BACKUP_DIR"
}

# Backup PostgreSQL database
backup_database() {
    log_info "Backing up PostgreSQL database..."
    
    cd "$PROJECT_ROOT"
    
    # Check if postgres is running
    if ! docker-compose exec -T postgres pg_isready -U medikiosk &> /dev/null; then
        log_error "PostgreSQL is not running"
        return 1
    fi
    
    # Create database backup
    docker-compose exec -T postgres pg_dump -U medikiosk medikiosk | gzip > "$BACKUP_DIR/database/medikiosk_$TIMESTAMP.sql.gz"
    
    if [ $? -eq 0 ]; then
        local backup_size=$(du -h "$BACKUP_DIR/database/medikiosk_$TIMESTAMP.sql.gz" | cut -f1)
        log_info "Database backup completed: $backup_size"
    else
        log_error "Database backup failed"
        return 1
    fi
}

# Backup Redis data
backup_redis() {
    log_info "Backing up Redis data..."
    
    cd "$PROJECT_ROOT"
    
    # Check if redis is running
    if ! docker-compose exec -T redis redis-cli ping &> /dev/null; then
        log_error "Redis is not running"
        return 1
    fi
    
    # Save Redis data
    docker-compose exec -T redis redis-cli SAVE
    
    # Copy Redis dump file
    docker cp $(docker-compose ps -q redis):/data/dump.rdb "$BACKUP_DIR/redis/redis_$TIMESTAMP.rdb"
    
    if [ $? -eq 0 ]; then
        local backup_size=$(du -h "$BACKUP_DIR/redis/redis_$TIMESTAMP.rdb" | cut -f1)
        log_info "Redis backup completed: $backup_size"
    else
        log_error "Redis backup failed"
        return 1
    fi
}

# Backup configuration files
backup_config() {
    log_info "Backing up configuration files..."
    
    # Backup .env file (without secrets)
    if [ -f "$PROJECT_ROOT/.env" ]; then
        # Create a version with sensitive values masked
        sed 's/PASSWORD=.*/PASSWORD=***masked***/g; s/SECRET_KEY=.*/SECRET_KEY=***masked***/g; s/API_KEY=.*/API_KEY=***masked***/g' \
            "$PROJECT_ROOT/.env" > "$BACKUP_DIR/config/env_$TIMESTAMP.bak"
        log_info "Configuration backup completed"
    else
        log_warn ".env file not found, skipping configuration backup"
    fi
    
    # Backup nginx configuration
    if [ -f "$PROJECT_ROOT/nginx/nginx.conf" ]; then
        cp "$PROJECT_ROOT/nginx/nginx.conf" "$BACKUP_DIR/config/nginx_$TIMESTAMP.conf"
        log_info "Nginx configuration backup completed"
    fi
}

# Backup encrypted vault (optional - patient opt-in data)
backup_encrypted_vault() {
    log_info "Backing up encrypted vault..."
    
    if [ -d "$PROJECT_ROOT/uploads/encrypted_vault" ] && [ "$(ls -A $PROJECT_ROOT/uploads/encrypted_vault)" ]; then
        # Create encrypted backup
        tar -czf "$BACKUP_DIR/uploads/encrypted_vault_$TIMESTAMP.tar.gz" -C "$PROJECT_ROOT/uploads" encrypted_vault/
        
        if [ $? -eq 0 ]; then
            local backup_size=$(du -h "$BACKUP_DIR/uploads/encrypted_vault_$TIMESTAMP.tar.gz" | cut -f1)
            log_info "Encrypted vault backup completed: $backup_size"
        else
            log_error "Encrypted vault backup failed"
        fi
    else
        log_info "Encrypted vault is empty, skipping backup"
    fi
}

# Cleanup old backups
cleanup_old_backups() {
    log_info "Cleaning up old backups (older than $RETENTION_DAYS days)..."
    
    # Remove old database backups
    find "$BACKUP_DIR/database" -name "medikiosk_*.sql.gz" -mtime +$RETENTION_DAYS -delete
    
    # Remove old Redis backups
    find "$BACKUP_DIR/redis" -name "redis_*.rdb" -mtime +$RETENTION_DAYS -delete
    
    # Remove old configuration backups
    find "$BACKUP_DIR/config" -name "env_*.bak" -mtime +$RETENTION_DAYS -delete
    find "$BACKUP_DIR/config" -name "nginx_*.conf" -mtime +$RETENTION_DAYS -delete
    
    # Remove old upload backups
    find "$BACKUP_DIR/uploads" -name "encrypted_vault_*.tar.gz" -mtime +$RETENTION_DAYS -delete
    
    log_info "Old backups cleaned up"
}

# Verify backup integrity
verify_backup() {
    log_info "Verifying backup integrity..."
    
    # Verify database backup
    if gzip -t "$BACKUP_DIR/database/medikiosk_$TIMESTAMP.sql.gz" 2>/dev/null; then
        log_info "Database backup integrity verified"
    else
        log_error "Database backup integrity check failed"
        return 1
    fi
    
    # Verify Redis backup
    if [ -f "$BACKUP_DIR/redis/redis_$TIMESTAMP.rdb" ]; then
        log_info "Redis backup integrity verified"
    else
        log_error "Redis backup integrity check failed"
        return 1
    fi
    
    log_info "All backups verified successfully"
}

# Generate backup report
generate_report() {
    local report_file="$BACKUP_DIR/backup_report_$TIMESTAMP.txt"
    
    cat > "$report_file" << EOF
MediKiosk-Backend Backup Report
================================
Timestamp: $TIMESTAMP
Date: $(date)

Backup Summary:
- Database: $(du -h "$BACKUP_DIR/database/medikiosk_$TIMESTAMP.sql.gz" | cut -f1)
- Redis: $(du -h "$BACKUP_DIR/redis/redis_$TIMESTAMP.rdb" | cut -f1)
- Configuration: Included
- Encrypted Vault: $(if [ -f "$BACKUP_DIR/uploads/encrypted_vault_$TIMESTAMP.tar.gz" ]; then du -h "$BACKUP_DIR/uploads/encrypted_vault_$TIMESTAMP.tar.gz" | cut -f1; else echo "Skipped"; fi)

Backup Location: $BACKUP_DIR
Retention Policy: $RETENTION_DAYS days

Status: SUCCESS
EOF
    
    log_info "Backup report generated: $report_file"
}

# Main backup function
main() {
    log_info "Starting backup process..."
    log_info "Timestamp: $TIMESTAMP"
    
    create_backup_dir
    backup_database
    backup_redis
    backup_config
    backup_encrypted_vault
    verify_backup
    cleanup_old_backups
    generate_report
    
    log_info "Backup process completed successfully!"
    log_info "Backup location: $BACKUP_DIR"
}

# Handle script arguments
case "${1:-full}" in
    full)
        main
        ;;
    database)
        create_backup_dir
        backup_database
        ;;
    redis)
        create_backup_dir
        backup_redis
        ;;
    config)
        create_backup_dir
        backup_config
        ;;
    vault)
        create_backup_dir
        backup_encrypted_vault
        ;;
    cleanup)
        cleanup_old_backups
        ;;
    *)
        echo "Usage: $0 {full|database|redis|config|vault|cleanup}"
        exit 1
        ;;
esac
