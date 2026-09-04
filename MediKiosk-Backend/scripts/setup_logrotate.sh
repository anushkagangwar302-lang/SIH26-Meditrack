#!/bin/bash
# MediKiosk-Backend Log Rotation Setup Script
# Installs and configures log rotation for production logs

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
LOGROTATE_CONF="/etc/logrotate.d/medikiosk"
LOG_DIR="/var/log/medikiosk"

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

# Check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_error "This script must be run as root"
        exit 1
    fi
}

# Install logrotate if not present
install_logrotate() {
    if ! command -v logrotate &> /dev/null; then
        log_info "Installing logrotate..."
        
        if command -v apt-get &> /dev/null; then
            apt-get update && apt-get install -y logrotate
        elif command -v yum &> /dev/null; then
            yum install -y logrotate
        else
            log_error "Unable to install logrotate. Please install manually."
            exit 1
        fi
        
        log_info "logrotate installed successfully"
    else
        log_info "logrotate is already installed"
    fi
}

# Create log directories
create_log_dirs() {
    log_info "Creating log directories..."
    
    mkdir -p "$LOG_DIR"
    mkdir -p "/var/log/nginx"
    
    # Set permissions
    chmod 755 "$LOG_DIR"
    chmod 755 "/var/log/nginx"
    
    # Create medikiosk user if not exists
    if ! id medikiosk &>/dev/null; then
        useradd --system --home-dir /var/log/medikiosk --shell /usr/sbin/nologin medikiosk
        log_info "Created medikiosk user"
    fi
    
    # Set ownership
    chown -R medikiosk:medikiosk "$LOG_DIR"
    chown -R nginx:nginx "/var/log/nginx" 2>/dev/null || chown -R www-data:www-data "/var/log/nginx"
    
    log_info "Log directories created"
}

# Install logrotate configuration
install_logrotate_conf() {
    log_info "Installing logrotate configuration..."
    
    if [ -f "$SCRIPT_DIR/logrotate.conf" ]; then
        cp "$SCRIPT_DIR/logrotate.conf" "$LOGROTATE_CONF"
        chmod 644 "$LOGROTATE_CONF"
        log_info "Logrotate configuration installed: $LOGROTATE_CONF"
    else
        log_error "logrotate.conf not found in scripts directory"
        exit 1
    fi
}

# Test logrotate configuration
test_logrotate() {
    log_info "Testing logrotate configuration..."
    
    if logrotate -d "$LOGROTATE_CONF" 2>&1; then
        log_info "Logrotate configuration test passed"
    else
        log_warn "Logrotate configuration test failed (this may be normal if logs don't exist yet)"
    fi
}

# Setup cron job for logrotate (if not using system default)
setup_cron() {
    log_info "Setting up cron job for logrotate..."
    
    # Check if logrotate is already configured in cron
    if crontab -l 2>/dev/null | grep -q "logrotate"; then
        log_info "Logrotate cron job already exists"
        return
    fi
    
    # Add cron job to run logrotate hourly
    (crontab -l 2>/dev/null; echo "0 * * * * /usr/sbin/logrotate $LOGROTATE_CONF >/dev/null 2>&1") | crontab -
    
    log_info "Cron job added for hourly log rotation"
}

# Create initial log files
create_initial_logs() {
    log_info "Creating initial log files..."
    
    touch "$LOG_DIR/app.log"
    touch "$LOG_DIR/audit.log"
    touch "$LOG_DIR/celery_worker.log"
    touch "$LOG_DIR/celery_beat.log"
    
    chown medikiosk:medikiosk "$LOG_DIR"/*.log
    chmod 640 "$LOG_DIR"/*.log
    
    log_info "Initial log files created"
}

# Main setup function
main() {
    log_info "Starting log rotation setup..."
    
    check_root
    install_logrotate
    create_log_dirs
    install_logrotate_conf
    test_logrotate
    setup_cron
    create_initial_logs
    
    log_info "Log rotation setup completed successfully!"
    log_info "Configuration file: $LOGROTATE_CONF"
    log_info "Log directory: $LOG_DIR"
    log_info ""
    log_info "To manually test log rotation, run:"
    log_info "  sudo logrotate -f $LOGROTATE_CONF"
}

# Run main function
main
