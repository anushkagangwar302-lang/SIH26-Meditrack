#!/bin/bash
# MediKiosk-Backend Script Permissions Setup
# Makes all operational scripts executable

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Setting executable permissions for operational scripts..."

chmod +x "$SCRIPT_DIR/deploy.sh"
chmod +x "$SCRIPT_DIR/health_check.sh"
chmod +x "$SCRIPT_DIR/backup.sh"
chmod +x "$SCRIPT_DIR/restore.sh"
chmod +x "$SCRIPT_DIR/setup_logrotate.sh"
chmod +x "$SCRIPT_DIR/generate_keys.sh"
chmod +x "$SCRIPT_DIR/cleanup.sh"
chmod +x "$SCRIPT_DIR/monitor.sh"
# chmod +x "$SCRIPT_DIR/setup_permissions.sh"  # Already executable

echo "Script permissions set successfully!"
echo ""
echo "Executable scripts:"
ls -l "$SCRIPT_DIR"/*.sh
