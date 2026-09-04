#!/bin/bash
# MediKiosk-Backend Restore Script
# Restores system from backup with validation and safety checks

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

# Confirmation prompt
confirm() {
    local message=$1
    echo -n "${YELLOW}$message${NC} (yes/no): "
    read response
    if [ "$response" != "yes" ]; then
        log_info "Operation cancelled by user"
        exit 0
    fi
}

# List available backups
list_backups() {
    log_info "Available backups:"
    
    echo ""
    echo "Database Backups:"
    ls -lh "$BACKUP_DIR/database/" 2>/dev/null || echo "No database backups found"
    
    echo ""
    echo "Redis Backups:"
    ls -lh "$BACKUP_DIR/redis/" 2>/dev/null || echo "No Redis backups found"
    
    echo ""
    echo "Configuration Backups:"
    ls -lh "$BACKUP_DIR/config/" 2>/dev/null || echo "No configuration backups found"
    
    echo ""
    echo "Upload Backups:"
    ls -lh "$BACKUP_DIR/uploads/" 2>/dev/null || echo "No upload backups found"
}

# Restore PostgreSQL database
restore_database() {
    local backup_file=$1
    
    log_info "Restoring PostgreSQL database from: $backup_file"
    
    confirm "This will replace the current database. Are you sure?"
    
    cd "$PROJECT_ROOT"
    
    # Stop API services to prevent conflicts
    log_info "Stopping API services..."
    docker-compose stop api celery_worker celery_beat
    
    # Verify backup file
    if [ ! -f "$backup_file" ]; then
        log_error "Backup file not found: $backup_file"
        return 1
    fi
    
    # Verify backup integrity
    if ! gzip -t "$backup_file" 2>/dev/null; then
        log_error "Backup file is corrupted"
        return 1
    fi
    
    # Create current database backup before restore
    log_info "Creating safety backup of current database..."
    docker-compose exec -T postgres pg_dump -U medikiosk medikiosk | gzip > "$BACKUP_DIR/database/medikiosk_pre_restore_$(date +%Y%m%d_%H%M%S).sql.gz"
    
    # Restore database
    log_info "Restoring database..."
    gunzip < "$backup_file" | docker-compose exec -T postgres psql -U medikiosk medikiosk
    
    if [ $? -eq 0 ]; then
        log_info "Database restore completed successfully"
        
        # Restart API services
        log_info "Restarting API services..."
        docker-compose start api celery_worker celery_beat
        
        return 0
    else
        log_error "Database restore failed"
        
        # Attempt to restore from safety backup
        log_warn "Attempting to restore from safety backup..."
        local safety_backup=$(ls -t "$BACKUP_DIR/database/medikiosk_pre_restore_*.sql.gz" | head -1)
        if [ -n "$safety_backup" ]; then
            gunzip < "$safety_backup" | docker-compose exec -T postgres psql -U medikiosk medikiosk
            log_info "Database restored from safety backup"
        fi
        
        return 1
    fi
}

# Restore Redis data
restore_redis() {
    local backup_file=$1
    
    log_info "Restoring Redis data from: $backup_file"
    
    confirm "This will replace the current Redis data. Are you sure?"
    
    cd "$PROJECT_ROOT"
    
    # Verify backup file
    if [ ! -f "$backup_file" ]; then
        log_error "Backup file not found: $backup_file"
        return 1
    fi
    
    # Create current Redis backup before restore
    log_info "Creating safety backup of current Redis data..."
    docker-compose exec -T redis redis-cli SAVE
    docker cp $(docker-compose ps -q redis):/data/dump.rdb "$BACKUP_DIR/redis/redis_pre_restore_$(date +%Y%m%d_%H%M%S).rdb"
    
    # Stop Redis
    log_info "Stopping Redis..."
    docker-compose stop redis
    
    # Copy backup file to Redis container
    docker cp "$backup_file" $(docker-compose ps -q redis):/data/dump.rdb
    
    # Start Redis
    log_info "Starting Redis..."
    docker-compose start redis
    
    if [ $? -eq 0 ]; then
        log_info "Redis restore completed successfully"
        return 0
    else
        log_error "Redis restore failed"
        
        # Attempt to restore from safety backup
        log_warn "Attempting to restore from safety backup..."
        local safety_backup=$(ls -t "$BACKUP_DIR/redis/redis_pre_restore_*.rdb" | head -1)
        if [ -n "$safety_backup" ]; then
            docker-compose stop redis
            docker cp "$safety_backup" $(docker-compose ps -q redis):/data/dump.rdb
            docker-compose start redis
            log_info "Redis restored from safety backup"
        fi
        
        return 1
    fi
}

# Restore configuration
restore_config() {
    local backup_file=$1
    
    log_info "Restoring configuration from: $backup_file"
    
    confirm "This will replace the current configuration. Are you sure?"
    
    # Verify backup file
    if [ ! -f "$backup_file" ]; then
        log_error "Backup file not found: $backup_file"
        return 1
    fi
    
    # Create current configuration backup
    log_info "Creating safety backup of current configuration..."
    if [ -f "$PROJECT_ROOT/.env" ]; then
        cp "$PROJECT_ROOT/.env" "$BACKUP_DIR/config/env_pre_restore_$(date +%Y%m%d_%H%M%S).bak"
    fi
    
    # Restore configuration
    cp "$backup_file" "$PROJECT_ROOT/.env"
    
    if [ $? -eq 0 ]; then
        log_info "Configuration restore completed successfully"
        log_warn "Please review the restored .env file and update any secrets if needed"
        return 0
    else
        log_error "Configuration restore failed"
        return 1
    fi
}

# Restore encrypted vault
restore_encrypted_vault() {
    local backup_file=$1
    
    log_info "Restoring encrypted vault from: $backup_file"
    
    confirm "This will replace the current encrypted vault. Are you sure?"
    
    # Verify backup file
    if [ ! -f "$backup_file" ]; then
        log_error "Backup file not found: $backup_file"
        return 1
    fi
    
    # Create current vault backup
    log_info "Creating safety backup of current encrypted vault..."
    if [ -d "$PROJECT_ROOT/uploads/encrypted_vault" ]; then
        tar -czf "$BACKUP_DIR/uploads/encrypted_vault_pre_restore_$(date +%Y%m%d_%H%M%S).tar.gz" -C "$PROJECT_ROOT/uploads" encrypted_vault/
    fi
    
    # Remove current vault
    rm -rf "$PROJECT_ROOT/uploads/encrypted_vault"/*
    
    # Restore vault
    tar -xzf "$backup_file" -C "$PROJECT_ROOT/uploads/"
    
    if [ $? -eq 0 ]; then
        log_info "Encrypted vault restore completed successfully"
        return 0
    else
        log_error "Encrypted vault restore failed"
        return 1
    fi
}

# Full system restore
full_restore() {
    local timestamp=$1
    
    log_info "Starting full system restore from timestamp: $timestamp"
    
    confirm "This will restore the entire system. Are you sure?"
    
    # Restore database
    local db_backup="$BACKUP_DIR/database/medikiosk_${timestamp}.sql.gz"
    if [ -f "$db_backup" ]; then
        restore_database "$db_backup"
    else
        log_error "Database backup not found for timestamp: $timestamp"
        return 1
    fi
    
    # Restore Redis
    local redis_backup="$BACKUP_DIR/redis/redis_${timestamp}.rdb"
    if [ -f "$redis_backup" ]; then
        restore_redis "$redis_backup"
    else
        log_warn "Redis backup not found for timestamp: $timestamp, skipping"
    fi
    
    # Restore configuration
    local config_backup="$BACKUP_DIR/config/env_${timestamp}.bak"
    if [ -f "$config_backup" ]; then
        restore_config "$config_backup"
    else
        log_warn "Configuration backup not found for timestamp: $timestamp, skipping"
    fi
    
    # Restore encrypted vault
    local vault_backup="$BACKUP_DIR/uploads/encrypted_vault_${timestamp}.tar.gz"
    if [ -f "$vault_backup" ]; then
        restore_encrypted_vault "$vault_backup"
    else
        log_warn "Encrypted vault backup not found for timestamp: $timestamp, skipping"
    fi
    
    log_info "Full system restore completed"
    log_warn "Please restart all services: docker-compose restart"
}

# Main function
main() {
    case "${1:-list}" in
        list)
            list_backups
            ;;
        database)
            if [ -z "$2" ]; then
                log_error "Please specify backup file"
                exit 1
            fi
            restore_database "$2"
            ;;
        redis)
            if [ -z "$2" ]; then
                log_error "Please specify backup file"
                exit 1
            fi
            restore_redis "$2"
            ;;
        config)
            if [ -z "$2" ]; then
                log_error "Please specify backup file"
                exit 1
            fi
            restore_config "$2"
            ;;
        vault)
            if [ -z "$2" ]; then
                log_error "Please specify backup file"
                exit 1
            fi
            restore_encrypted_vault "$2"
            ;;
        full)
            if [ -z "$2" ]; then
                log_error "Please specify timestamp (e.g., 20240904_120000)"
                exit 1
            fi
            full_restore "$2"
            ;;
        *)
            echo "Usage: $0 {list|database|redis|config|vault|full}"
            echo ""
            echo "Examples:"
            echo "  $0 list                                    # List available backups"
            echo "  $0 database /var/backups/medikiosk/database/medikiosk_20240904_120000.sql.gz"
            echo "  $0 redis /var/backups/medikiosk/redis/redis_20240904_120000.rdb"
            echo "  $0 full 20240904_120000                    # Full system restore"
            exit 1
            ;;
    esac
}

# Run main function
main "$@"
