#!/bin/bash
# MediKiosk-Backend Cryptographic Keys Generator
# Generates secure keys for JWT, encryption, and webhook signatures

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
ENV_FILE="$PROJECT_ROOT/.env"

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

# Generate JWT secret key
generate_jwt_secret() {
    log_info "Generating JWT secret key..."
    local jwt_secret=$(python3 -c "import secrets; print(secrets.token_urlsafe(64))")
    echo "JWT_SECRET_KEY=$jwt_secret"
}

# Generate JWT refresh secret key
generate_jwt_refresh_secret() {
    log_info "Generating JWT refresh secret key..."
    local jwt_refresh_secret=$(python3 -c "import secrets; print(secrets.token_urlsafe(64))")
    echo "JWT_REFRESH_SECRET_KEY=$jwt_refresh_secret"
}

# Generate field encryption key
generate_encryption_key() {
    log_info "Generating field encryption key..."
    local encryption_key=$(python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())")
    echo "FIELD_ENCRYPTION_KEY=$encryption_key"
}

# Generate webhook HMAC key
generate_hmac_key() {
    log_info "Generating webhook HMAC key..."
    local hmac_key=$(python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())")
    echo "WEBHOOK_HMAC_KEY=$hmac_key"
}

# Generate PostgreSQL password
generate_postgres_password() {
    log_info "Generating PostgreSQL password..."
    local postgres_password=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    echo "POSTGRES_PASSWORD=$postgres_password"
}

# Generate all keys
generate_all_keys() {
    log_info "Generating all cryptographic keys..."
    
    local jwt_secret=$(generate_jwt_secret | cut -d= -f2)
    local jwt_refresh_secret=$(generate_jwt_refresh_secret | cut -d= -f2)
    local encryption_key=$(generate_encryption_key | cut -d= -f2)
    local hmac_key=$(generate_hmac_key | cut -d= -f2)
    local postgres_password=$(generate_postgres_password | cut -d= -f2)
    
    echo ""
    echo "${BLUE}========================================${NC}"
    echo "${BLUE}Generated Cryptographic Keys${NC}"
    echo "${BLUE}========================================${NC}"
    echo ""
    echo "JWT_SECRET_KEY=$jwt_secret"
    echo "JWT_REFRESH_SECRET_KEY=$jwt_refresh_secret"
    echo "FIELD_ENCRYPTION_KEY=$encryption_key"
    echo "WEBHOOK_HMAC_KEY=$hmac_key"
    echo "POSTGRES_PASSWORD=$postgres_password"
    echo ""
    echo "${YELLOW}IMPORTANT: Store these keys securely and never commit them to version control${NC}"
    echo ""
}

# Update .env file
update_env_file() {
    log_info "Updating .env file..."
    
    if [ ! -f "$ENV_FILE" ]; then
        log_error ".env file not found. Please create it from .env.example first"
        return 1
    fi
    
    # Backup existing .env
    cp "$ENV_FILE" "$ENV_FILE.backup"
    log_info "Backup created: $ENV_FILE.backup"
    
    # Generate keys
    local jwt_secret=$(generate_jwt_secret | cut -d= -f2)
    local jwt_refresh_secret=$(generate_jwt_refresh_secret | cut -d= -f2)
    local encryption_key=$(generate_encryption_key | cut -d= -f2)
    local hmac_key=$(generate_hmac_key | cut -d= -f2)
    local postgres_password=$(generate_postgres_password | cut -d= -f2)
    
    # Update .env file
    sed -i "s/JWT_SECRET_KEY=.*/JWT_SECRET_KEY=$jwt_secret/" "$ENV_FILE"
    sed -i "s/JWT_REFRESH_SECRET_KEY=.*/JWT_REFRESH_SECRET_KEY=$jwt_refresh_secret/" "$ENV_FILE"
    sed -i "s/FIELD_ENCRYPTION_KEY=.*/FIELD_ENCRYPTION_KEY=$encryption_key/" "$ENV_FILE"
    sed -i "s/WEBHOOK_HMAC_KEY=.*/WEBHOOK_HMAC_KEY=$hmac_key/" "$ENV_FILE"
    sed -i "s/POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$postgres_password/" "$ENV_FILE"
    
    log_info ".env file updated successfully"
    log_warn "Please review the updated .env file and restart services"
}

# Main function
main() {
    case "${1:-generate}" in
        generate)
            generate_all_keys
            ;;
        update)
            update_env_file
            ;;
        jwt)
            generate_jwt_secret
            ;;
        jwt-refresh)
            generate_jwt_refresh_secret
            ;;
        encryption)
            generate_encryption_key
            ;;
        hmac)
            generate_hmac_key
            ;;
        postgres)
            generate_postgres_password
            ;;
        *)
            echo "Usage: $0 {generate|update|jwt|jwt-refresh|encryption|hmac|postgres}"
            echo ""
            echo "Commands:"
            echo "  generate      - Generate all keys and display them"
            echo "  update        - Generate all keys and update .env file"
            echo "  jwt           - Generate JWT secret key only"
            echo "  jwt-refresh   - Generate JWT refresh secret key only"
            echo "  encryption    - Generate field encryption key only"
            echo "  hmac          - Generate webhook HMAC key only"
            echo "  postgres      - Generate PostgreSQL password only"
            exit 1
            ;;
    esac
}

# Run main function
main "$@"
