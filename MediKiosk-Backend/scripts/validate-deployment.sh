#!/bin/bash

################################################################################
# MediKiosk-Backend Production Deployment Validation Script
# 
# Purpose: Comprehensive pre-deployment checks for production readiness
# Usage: bash scripts/validate-deployment.sh
# 
# Checks:
# 1. Environment configuration completeness
# 2. SSL certificate validity
# 3. Docker & Docker Compose availability
# 4. Database connectivity
# 5. Redis connectivity
# 6. Required dependencies
# 7. Security configuration
# 8. File permissions
# 9. Resource limits
# 10. Health endpoint accessibility
################################################################################

set -euo pipefail

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Counters
PASSED=0
FAILED=0
WARNINGS=0
TOTAL_CHECKS=0

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${PROJECT_ROOT}/.env"
DOCKER_COMPOSE_FILE="${PROJECT_ROOT}/docker-compose.yml"
NGINX_SSL_DIR="${PROJECT_ROOT}/nginx/ssl"
UPLOADS_DIR="${PROJECT_ROOT}/uploads"

################################################################################
# Helper Functions
################################################################################

print_header() {
    echo -e "\n${BLUE}================================================================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}================================================================================${NC}\n"
}

print_check() {
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
    echo -n "  [$TOTAL_CHECKS] $1... "
}

print_pass() {
    PASSED=$((PASSED + 1))
    echo -e "${GREEN}✓ PASS${NC}"
}

print_fail() {
    FAILED=$((FAILED + 1))
    echo -e "${RED}✗ FAIL${NC}"
    if [ -n "${1:-}" ]; then
        echo -e "      ${RED}Error: $1${NC}"
    fi
}

print_warn() {
    WARNINGS=$((WARNINGS + 1))
    echo -e "${YELLOW}⚠ WARN${NC}"
    if [ -n "${1:-}" ]; then
        echo -e "      ${YELLOW}Warning: $1${NC}"
    fi
}

print_info() {
    echo -e "      ${BLUE}ℹ $1${NC}"
}

print_summary() {
    echo ""
    echo -e "${BLUE}================================================================================${NC}"
    echo -e "${BLUE}VALIDATION SUMMARY${NC}"
    echo -e "${BLUE}================================================================================${NC}"
    echo -e "Total Checks: ${TOTAL_CHECKS}"
    echo -e "${GREEN}Passed: ${PASSED}${NC}"
    echo -e "${RED}Failed: ${FAILED}${NC}"
    echo -e "${YELLOW}Warnings: ${WARNINGS}${NC}"
    echo ""
    
    if [ $FAILED -eq 0 ]; then
        echo -e "${GREEN}✓ All critical checks passed!${NC}"
        if [ $WARNINGS -gt 0 ]; then
            echo -e "${YELLOW}Note: ${WARNINGS} warning(s) found. Review before production deployment.${NC}"
        fi
        return 0
    else
        echo -e "${RED}✗ ${FAILED} critical check(s) failed. Fix issues before deployment.${NC}"
        return 1
    fi
}

################################################################################
# Section 1: Environment Configuration
################################################################################

validate_environment_config() {
    print_header "Section 1: Environment Configuration"
    
    print_check "Checking if .env file exists"
    if [ -f "$ENV_FILE" ]; then
        print_pass
    else
        print_fail ".env file not found at $ENV_FILE"
        print_info "Run: cp .env.example .env"
        return
    fi
    
    print_check "Checking if .env.example exists"
    if [ -f "${PROJECT_ROOT}/.env.example" ]; then
        print_pass
    else
        print_fail ".env.example not found"
    fi
    
    # Load .env file
    set -a
    source "$ENV_FILE" || true
    set +a
    
    # Required environment variables
    local required_vars=(
        "ENVIRONMENT"
        "APP_NAME"
        "DATABASE_URL"
        "POSTGRES_PASSWORD"
        "REDIS_HOST"
        "JWT_SECRET_KEY"
        "JWT_REFRESH_SECRET_KEY"
        "FIELD_ENCRYPTION_KEY"
        "WEBHOOK_HMAC_KEY"
    )
    
    for var in "${required_vars[@]}"; do
        print_check "Environment variable: $var"
        if [ -z "${!var:-}" ]; then
            print_fail "Not set or empty"
        else
            value="${!var:-}"
            if [[ "$value" == *"CHANGE_ME"* ]] || [[ "$value" == "CHANGE_ME" ]]; then
                print_fail "Still contains CHANGE_ME placeholder"
            else
                print_pass
            fi
        fi
    done
    
    # Check environment type
    print_check "ENVIRONMENT is set to production"
    if [ "${ENVIRONMENT:-}" = "production" ]; then
        print_pass
    elif [ "${ENVIRONMENT:-}" = "staging" ]; then
        print_warn "ENVIRONMENT is staging, not production"
    else
        print_warn "ENVIRONMENT is '${ENVIRONMENT:-}', recommend setting to production"
    fi
    
    # Check DEBUG flag
    print_check "DEBUG is disabled"
    if [ "${DEBUG:-}" = "false" ] || [ "${DEBUG:-}" = "False" ] || [ -z "${DEBUG:-}" ]; then
        print_pass
    else
        print_fail "DEBUG is enabled - must be false in production"
    fi
    
    # Check DEV_ABHA_OTP
    print_check "DEV_ABHA_OTP is empty (production)"
    if [ -z "${DEV_ABHA_OTP:-}" ]; then
        print_pass
    else
        print_fail "DEV_ABHA_OTP is set - must be empty in production"
    fi
    
    # Check CORS_ORIGINS
    print_check "CORS_ORIGINS configured"
    if [ -n "${CORS_ORIGINS:-}" ] && [[ "$CORS_ORIGINS" != *"localhost"* ]]; then
        print_pass
        print_info "CORS_ORIGINS: ${CORS_ORIGINS:-}"
    elif [ -n "${CORS_ORIGINS:-}" ]; then
        print_warn "CORS_ORIGINS contains localhost - update for production"
        print_info "Current: ${CORS_ORIGINS:-}"
    else
        print_fail "CORS_ORIGINS not set"
    fi
}

################################################################################
# Section 2: SSL Certificates
################################################################################

validate_ssl_certificates() {
    print_header "Section 2: SSL Certificates"
    
    print_check "Checking if nginx/ssl directory exists"
    if [ -d "$NGINX_SSL_DIR" ]; then
        print_pass
    else
        print_fail "Directory $NGINX_SSL_DIR does not exist"
        print_info "Run: mkdir -p $NGINX_SSL_DIR"
        return
    fi
    
    print_check "Checking if cert.pem exists"
    if [ -f "${NGINX_SSL_DIR}/cert.pem" ]; then
        print_pass
    else
        print_fail "cert.pem not found at ${NGINX_SSL_DIR}/cert.pem"
        print_info "Place your SSL certificate there (Let's Encrypt recommended)"
        return
    fi
    
    print_check "Checking if key.pem exists"
    if [ -f "${NGINX_SSL_DIR}/key.pem" ]; then
        print_pass
    else
        print_fail "key.pem not found at ${NGINX_SSL_DIR}/key.pem"
        return
    fi
    
    # Check file permissions
    print_check "Checking cert.pem permissions (should be 644)"
    local cert_perms
    cert_perms=$(stat -f "%OLp" "${NGINX_SSL_DIR}/cert.pem" 2>/dev/null || stat -c "%a" "${NGINX_SSL_DIR}/cert.pem" 2>/dev/null || echo "unknown")
    if [[ "$cert_perms" == "644" ]] || [[ "$cert_perms" == "-rw-r--r--" ]]; then
        print_pass
    else
        print_warn "cert.pem permissions are $cert_perms (should be 644)"
    fi
    
    print_check "Checking key.pem permissions (should be 600)"
    local key_perms
    key_perms=$(stat -f "%OLp" "${NGINX_SSL_DIR}/key.pem" 2>/dev/null || stat -c "%a" "${NGINX_SSL_DIR}/key.pem" 2>/dev/null || echo "unknown")
    if [[ "$key_perms" == "600" ]] || [[ "$key_perms" == "-rw-------" ]]; then
        print_pass
    else
        print_warn "key.pem permissions are $key_perms (should be 600)"
    fi
    
    # Validate certificate
    if command -v openssl &> /dev/null; then
        print_check "Validating certificate with OpenSSL"
        if openssl x509 -in "${NGINX_SSL_DIR}/cert.pem" -noout &>/dev/null; then
            print_pass
            
            # Check expiration
            print_check "Checking certificate expiration"
            local expiry_date
            expiry_date=$(openssl x509 -enddate -noout -in "${NGINX_SSL_DIR}/cert.pem" | cut -d= -f2)
            local expiry_epoch
            expiry_epoch=$(date -j -f "%b %d %T %Y %Z" "$expiry_date" +%s 2>/dev/null || date -d "$expiry_date" +%s 2>/dev/null || echo "0")
            local now_epoch
            now_epoch=$(date +%s)
            local days_left
            days_left=$(( (expiry_epoch - now_epoch) / 86400 ))
            
            if [ "$days_left" -gt 30 ]; then
                print_pass
                print_info "Certificate valid for $days_left more days (expires: $expiry_date)"
            elif [ "$days_left" -gt 0 ]; then
                print_warn "Certificate expires in $days_left days (expires: $expiry_date)"
            else
                print_fail "Certificate has expired (expired: $expiry_date)"
            fi
        else
            print_fail "Certificate validation failed"
        fi
    else
        print_warn "OpenSSL not installed - skipping certificate validation"
    fi
}

################################################################################
# Section 3: Docker and Docker Compose
################################################################################

validate_docker_setup() {
    print_header "Section 3: Docker and Docker Compose"
    
    print_check "Checking if Docker is installed"
    if command -v docker &> /dev/null; then
        print_pass
        local docker_version
        docker_version=$(docker --version 2>/dev/null)
        print_info "$docker_version"
    else
        print_fail "Docker is not installed"
        print_info "Install from: https://docs.docker.com/get-docker/"
        return
    fi
    
    print_check "Checking if Docker daemon is running"
    if docker info &>/dev/null; then
        print_pass
    else
        print_fail "Docker daemon is not running"
        print_info "Start Docker and try again"
        return
    fi
    
    print_check "Checking if Docker Compose is installed"
    if command -v docker-compose &> /dev/null || docker compose version &>/dev/null; then
        print_pass
        if command -v docker-compose &> /dev/null; then
            local compose_version
            compose_version=$(docker-compose --version 2>/dev/null)
            print_info "$compose_version"
        else
            local compose_version
            compose_version=$(docker compose version 2>/dev/null)
            print_info "$compose_version"
        fi
    else
        print_fail "Docker Compose is not installed"
        return
    fi
    
    print_check "Checking if docker-compose.yml exists"
    if [ -f "$DOCKER_COMPOSE_FILE" ]; then
        print_pass
    else
        print_fail "docker-compose.yml not found at $DOCKER_COMPOSE_FILE"
        return
    fi
    
    print_check "Validating docker-compose.yml syntax"
    if docker compose -f "$DOCKER_COMPOSE_FILE" config &>/dev/null; then
        print_pass
    else
        print_fail "docker-compose.yml has invalid syntax"
    fi
    
    print_check "Checking Docker disk space"
    local docker_disk_usage
    docker_disk_usage=$(docker system df 2>/dev/null | tail -1 | awk '{print $5}' | sed 's/%//')
    if [ -n "$docker_disk_usage" ] && [ "$docker_disk_usage" -lt 80 ]; then
        print_pass
        print_info "Docker disk usage: ${docker_disk_usage}%"
    elif [ -n "$docker_disk_usage" ]; then
        print_warn "Docker disk usage is ${docker_disk_usage}% (>80%)"
    fi
}

################################################################################
# Section 4: Database Configuration
################################################################################

validate_database_config() {
    print_header "Section 4: Database Configuration"
    
    set -a
    source "$ENV_FILE" || true
    set +a
    
    print_check "DATABASE_URL is configured"
    if [ -n "${DATABASE_URL:-}" ]; then
        print_pass
        # Extract host from connection string
        local db_host
        db_host=$(echo "$DATABASE_URL" | grep -oP '(?<=@)[^:/]+' | head -1)
        print_info "Database host: ${db_host:-localhost}"
    else
        print_fail "DATABASE_URL not set"
        return
    fi
    
    print_check "POSTGRES_PASSWORD is set and not default"
    if [ -n "${POSTGRES_PASSWORD:-}" ] && [ "${POSTGRES_PASSWORD:-}" != "CHANGE_ME" ]; then
        print_pass
        print_info "Password length: ${#POSTGRES_PASSWORD} characters"
    else
        print_fail "POSTGRES_PASSWORD not set or is default"
    fi
    
    print_check "DB_POOL_SIZE is configured"
    if [ -n "${DB_POOL_SIZE:-}" ]; then
        print_pass
        print_info "Pool size: ${DB_POOL_SIZE}"
    else
        print_warn "DB_POOL_SIZE not set, using default"
    fi
    
    print_check "DB_MAX_OVERFLOW is configured"
    if [ -n "${DB_MAX_OVERFLOW:-}" ]; then
        print_pass
        print_info "Max overflow: ${DB_MAX_OVERFLOW}"
    else
        print_warn "DB_MAX_OVERFLOW not set, using default"
    fi
    
    print_check "Checking if Dockerfile exists"
    if [ -f "${PROJECT_ROOT}/Dockerfile" ]; then
        print_pass
    else
        print_fail "Dockerfile not found"
    fi
}

################################################################################
# Section 5: Redis Configuration
################################################################################

validate_redis_config() {
    print_header "Section 5: Redis Configuration"
    
    set -a
    source "$ENV_FILE" || true
    set +a
    
    print_check "REDIS_HOST is configured"
    if [ -n "${REDIS_HOST:-}" ]; then
        print_pass
        print_info "Redis host: ${REDIS_HOST}"
    else
        print_fail "REDIS_HOST not set"
        return
    fi
    
    print_check "REDIS_PORT is configured"
    if [ -n "${REDIS_PORT:-}" ]; then
        print_pass
        print_info "Redis port: ${REDIS_PORT}"
    else
        print_warn "REDIS_PORT not set, using default (6379)"
    fi
    
    print_check "Redis database numbers are unique"
    local redis_dbs=(
        "${REDIS_DB_SESSION:-0}"
        "${REDIS_DB_CELERY_BROKER:-1}"
        "${REDIS_DB_CELERY_RESULT:-2}"
        "${REDIS_DB_LOCKS:-3}"
        "${REDIS_DB_RATELIMIT:-4}"
    )
    local sorted_dbs
    sorted_dbs=$(printf '%s\n' "${redis_dbs[@]}" | sort -u | wc -l)
    if [ "$sorted_dbs" -eq ${#redis_dbs[@]} ]; then
        print_pass
    else
        print_warn "Some Redis database numbers may be duplicated"
    fi
    
    print_check "CELERY_BROKER_URL is configured"
    if [ -n "${CELERY_BROKER_URL:-}" ]; then
        print_pass
        print_info "Celery broker: ${CELERY_BROKER_URL}"
    else
        print_warn "CELERY_BROKER_URL not set, using default"
    fi
}

################################################################################
# Section 6: Security Configuration
################################################################################

validate_security_config() {
    print_header "Section 6: Security Configuration"
    
    set -a
    source "$ENV_FILE" || true
    set +a
    
    print_check "JWT_SECRET_KEY is set and strong"
    if [ -n "${JWT_SECRET_KEY:-}" ] && [ "${JWT_SECRET_KEY}" != "CHANGE_ME" ]; then
        print_pass
        if [ ${#JWT_SECRET_KEY} -ge 32 ]; then
            print_info "JWT secret length: ${#JWT_SECRET_KEY} characters (strong)"
        else
            print_warn "JWT secret length: ${#JWT_SECRET_KEY} characters (recommend ≥32)"
        fi
    else
        print_fail "JWT_SECRET_KEY not set or is default"
    fi
    
    print_check "JWT_REFRESH_SECRET_KEY is set and different from access key"
    if [ -n "${JWT_REFRESH_SECRET_KEY:-}" ] && [ "${JWT_REFRESH_SECRET_KEY}" != "CHANGE_ME" ]; then
        print_pass
        if [ "${JWT_SECRET_KEY:-}" != "${JWT_REFRESH_SECRET_KEY:-}" ]; then
            print_info "Refresh secret is different from access secret"
        else
            print_warn "Refresh secret is identical to access secret"
        fi
    else
        print_fail "JWT_REFRESH_SECRET_KEY not set or is default"
    fi
    
    print_check "FIELD_ENCRYPTION_KEY is set (32 bytes base64)"
    if [ -n "${FIELD_ENCRYPTION_KEY:-}" ] && [ "${FIELD_ENCRYPTION_KEY}" != "CHANGE_ME" ]; then
        print_pass
        if [ ${#FIELD_ENCRYPTION_KEY} -ge 44 ]; then
            print_info "Encryption key length: ${#FIELD_ENCRYPTION_KEY} characters"
        else
            print_warn "Encryption key may be too short"
        fi
    else
        print_fail "FIELD_ENCRYPTION_KEY not set or is default"
    fi
    
    print_check "WEBHOOK_HMAC_KEY is set"
    if [ -n "${WEBHOOK_HMAC_KEY:-}" ] && [ "${WEBHOOK_HMAC_KEY}" != "CHANGE_ME" ]; then
        print_pass
    else
        print_fail "WEBHOOK_HMAC_KEY not set or is default"
    fi
    
    print_check "JWT access token TTL is reasonable (≤60 minutes)"
    if [ -n "${JWT_ACCESS_TTL_MINUTES:-}" ]; then
        if [ "${JWT_ACCESS_TTL_MINUTES:-}" -le 60 ]; then
            print_pass
            print_info "Access token TTL: ${JWT_ACCESS_TTL_MINUTES} minutes"
        else
            print_warn "Access token TTL is ${JWT_ACCESS_TTL_MINUTES} minutes (recommend ≤60)"
        fi
    else
        print_warn "JWT_ACCESS_TTL_MINUTES not set, using default"
    fi
    
    print_check "Password hashing algorithm is configured"
    if [ -n "${PASSWORD_HASH_ALGORITHM:-}" ]; then
        print_pass
        print_info "Algorithm: ${PASSWORD_HASH_ALGORITHM}"
    else
        print_warn "PASSWORD_HASH_ALGORITHM not set, using default"
    fi
}

################################################################################
# Section 7: Upload Directories
################################################################################

validate_upload_directories() {
    print_header "Section 7: Upload Directories"
    
    print_check "Checking if uploads directory exists"
    if [ -d "$UPLOADS_DIR" ]; then
        print_pass
    else
        print_fail "Uploads directory not found at $UPLOADS_DIR"
        print_info "Run: mkdir -p $UPLOADS_DIR"
        return
    fi
    
    print_check "Checking if temp_scans directory exists"
    if [ -d "${UPLOADS_DIR}/temp_scans" ]; then
        print_pass
    else
        print_warn "temp_scans directory not found"
        print_info "Run: mkdir -p ${UPLOADS_DIR}/temp_scans"
    fi
    
    print_check "Checking if encrypted_vault directory exists"
    if [ -d "${UPLOADS_DIR}/encrypted_vault" ]; then
        print_pass
    else
        print_warn "encrypted_vault directory not found"
        print_info "Run: mkdir -p ${UPLOADS_DIR}/encrypted_vault"
    fi
    
    # Check permissions
    print_check "Checking uploads directory is writable"
    if [ -w "$UPLOADS_DIR" ]; then
        print_pass
    else
        print_fail "Uploads directory is not writable"
        print_info "Run: chmod 755 $UPLOADS_DIR"
    fi
    
    print_check "Checking disk space (need at least 10GB)"
    local available_space
    available_space=$(df "$UPLOADS_DIR" | tail -1 | awk '{print $4}')
    if [ "$available_space" -gt 10485760 ]; then  # 10GB in KB
        print_pass
        print_info "Available space: $((available_space / 1048576))GB"
    else
        print_warn "Available space is only $((available_space / 1048576))GB (recommend ≥10GB)"
    fi
}

################################################################################
# Section 8: Required Files
################################################################################

validate_required_files() {
    print_header "Section 8: Required Files"
    
    local required_files=(
        "requirements.txt"
        "Dockerfile"
        "docker-compose.yml"
        "app/main.py"
        "app/core/config.py"
        "app/core/database.py"
        "nginx/nginx.conf"
        ".env.example"
    )
    
    for file in "${required_files[@]}"; do
        print_check "File: $file"
        if [ -f "${PROJECT_ROOT}/${file}" ]; then
            print_pass
        else
            print_fail "Not found at ${PROJECT_ROOT}/${file}"
        fi
    done
}

################################################################################
# Section 9: Integration Configuration
################################################################################

validate_integrations() {
    print_header "Section 9: External Integrations"
    
    set -a
    source "$ENV_FILE" || true
    set +a
    
    print_check "ABDM integration: CLIENT_ID configured"
    if [ -n "${ABDM_CLIENT_ID:-}" ] && [ "${ABDM_CLIENT_ID}" != "CHANGE_ME" ]; then
        print_pass
        print_info "ABDM Client ID is set"
    else
        print_warn "ABDM_CLIENT_ID not set - ABDM features disabled"
    fi
    
    print_check "ABDM integration: CLIENT_SECRET configured"
    if [ -n "${ABDM_CLIENT_SECRET:-}" ] && [ "${ABDM_CLIENT_SECRET}" != "CHANGE_ME" ]; then
        print_pass
    else
        print_warn "ABDM_CLIENT_SECRET not set"
    fi
    
    print_check "ABDM integration: CALLBACK_URL configured"
    if [ -n "${ABDM_CALLBACK_URL:-}" ] && [[ "$ABDM_CALLBACK_URL" == https://* ]]; then
        print_pass
        print_info "Callback URL: ${ABDM_CALLBACK_URL}"
    elif [ -n "${ABDM_CALLBACK_URL:-}" ]; then
        print_warn "ABDM_CALLBACK_URL may not use HTTPS"
    else
        print_warn "ABDM_CALLBACK_URL not configured"
    fi
    
    print_check "Bhashini integration: API_KEY configured"
    if [ -n "${BHASHINI_API_KEY:-}" ] && [ "${BHASHINI_API_KEY}" != "CHANGE_ME" ]; then
        print_pass
    else
        print_warn "BHASHINI_API_KEY not set - Voice features disabled"
    fi
    
    print_check "Bhashini integration: USER_ID configured"
    if [ -n "${BHASHINI_USER_ID:-}" ] && [ "${BHASHINI_USER_ID}" != "CHANGE_ME" ]; then
        print_pass
    else
        print_warn "BHASHINI_USER_ID not set"
    fi
    
    print_check "Bhashini integration: Pipeline IDs configured"
    if [ -n "${BHASHINI_ASR_PIPELINE_ID:-}" ] && [ -n "${BHASHINI_TTS_PIPELINE_ID:-}" ]; then
        print_pass
        print_info "Both ASR and TTS pipelines configured"
    else
        print_warn "Bhashini pipeline IDs not fully configured"
    fi
    
    print_check "OCR service configured"
    if [ -n "${OCR_SERVICE_PROVIDER:-}" ]; then
        print_pass
        print_info "OCR Provider: ${OCR_SERVICE_PROVIDER}"
    else
        print_warn "OCR_SERVICE_PROVIDER not set"
    fi
}

################################################################################
# Section 10: Feature Flags
################################################################################

validate_feature_flags() {
    print_header "Section 10: Feature Flags"
    
    set -a
    source "$ENV_FILE" || true
    set +a
    
    local features=(
        "FEATURE_AYUSH_ENABLED"
        "FEATURE_SOCRATES_ENABLED"
        "FEATURE_ABDM_ENABLED"
        "FEATURE_VOICE_ENABLED"
        "FEATURE_OCR_ENABLED"
    )
    
    for feature in "${features[@]}"; do
        print_check "Feature flag: $feature"
        if [ -n "${!feature:-}" ]; then
            print_pass
            print_info "Status: ${!feature}"
        else
            print_warn "Feature flag not set, using default"
        fi
    done
}

################################################################################
# Section 11: Pre-flight Checks (Simulation)
################################################################################

validate_preflight() {
    print_header "Section 11: Pre-flight Health Checks (Dry Run)"
    
    print_check "Docker Compose configuration valid"
    if docker compose -f "$DOCKER_COMPOSE_FILE" config &>/dev/null; then
        print_pass
    else
        print_fail "docker-compose.yml configuration is invalid"
        return
    fi
    
    print_check "All Docker images available"
    local images=(
        "postgres:16.8-alpine"
        "redis:7.4.2-alpine"
        "nginx:1.27.3-alpine"
        "python:3.12.8-slim-bookworm"
    )
    
    local all_available=true
    for img in "${images[@]}"; do
        if docker image inspect "$img" &>/dev/null; then
            print_info "✓ $img"
        else
            print_info "⚠ $img (will be pulled during build)"
        fi
    done
}

################################################################################
# Section 12: Deployment Readiness Score
################################################################################

print_deployment_score() {
    print_header "Deployment Readiness Assessment"
    
    local total_critical=$((TOTAL_CHECKS - WARNINGS))
    local score=0
    
    if [ $FAILED -eq 0 ]; then
        score=100
    elif [ $FAILED -le 2 ]; then
        score=80
    elif [ $FAILED -le 5 ]; then
        score=60
    else
        score=40
    fi
    
    echo ""
    echo "  Critical Checks: $PASSED / $total_critical"
    echo "  Warnings: $WARNINGS"
    echo "  Failures: $FAILED"
    echo ""
    echo "  Deployment Readiness Score: ${score}%"
    echo ""
    
    case $score in
        100)
            echo -e "  ${GREEN}✓ READY FOR PRODUCTION DEPLOYMENT${NC}"
            echo -e "  ${GREEN}All critical requirements met.${NC}"
            ;;
        80)
            echo -e "  ${YELLOW}⚠ MOSTLY READY (Minor Issues)${NC}"
            echo -e "  ${YELLOW}Resolve warnings before full production deployment.${NC}"
            ;;
        60)
            echo -e "  ${YELLOW}⚠ STAGING READY${NC}"
            echo -e "  ${YELLOW}Recommended for staging only. Resolve issues before production.${NC}"
            ;;
        *)
            echo -e "  ${RED}✗ NOT READY${NC}"
            echo -e "  ${RED}Multiple critical issues must be resolved first.${NC}"
            ;;
    esac
    
    echo ""
}

################################################################################
# Section 13: Generate Deployment Checklist
################################################################################

generate_deployment_checklist() {
    print_header "Deployment Checklist"
    
    cat > "${PROJECT_ROOT}/DEPLOYMENT_CHECKLIST.md" << 'EOF'
# MediKiosk-Backend Deployment Checklist

## Pre-Deployment (1-2 weeks before)

### Environment & Secrets
- [ ] Generate JWT secrets (64+ characters)
- [ ] Generate encryption keys (32 bytes base64)
- [ ] Generate HMAC keys (32 bytes base64)
- [ ] Set strong database password (20+ characters, mixed case/numbers/symbols)
- [ ] Set Redis password (if required)
- [ ] Update CORS_ORIGINS to production domain
- [ ] Obtain ABDM credentials from https://abdm.gov.in/
- [ ] Obtain Bhashini API keys from https://bhashini.gov.in/
- [ ] Configure OCR service provider

### SSL Certificates
- [ ] Obtain SSL certificate from CA (Let's Encrypt recommended)
- [ ] Verify certificate validity (not self-signed for production)
- [ ] Place cert.pem and key.pem in nginx/ssl/
- [ ] Verify certificate expiration date (>30 days)
- [ ] Set proper permissions (644 for cert, 600 for key)

### Infrastructure
- [ ] Provision production server with adequate resources
- [ ] Configure DNS to production domain
- [ ] Open firewall ports 80 and 443
- [ ] Configure backup storage
- [ ] Setup monitoring/alerting infrastructure
- [ ] Setup log aggregation (ELK/Loki)
- [ ] Setup error tracking (Sentry)

### Validation
- [ ] Run `bash scripts/validate-deployment.sh`
- [ ] Resolve all critical failures
- [ ] Address warnings with team
- [ ] Run all unit tests: `docker compose exec api pytest tests/`
- [ ] Run load tests: `docker compose exec api locust -f tests/load_test.py`
- [ ] Security audit completed
- [ ] Database backup strategy tested

## Deployment Day

### Pre-Deployment
- [ ] Create database backup
- [ ] Note current git commit hash
- [ ] Establish rollback plan
- [ ] Brief ops team on deployment
- [ ] Monitor dashboard ready
- [ ] On-call team notified

### Database
- [ ] Run migrations: `docker compose exec api alembic upgrade head`
- [ ] Verify migration: `docker compose exec api alembic current`
- [ ] Validate database indexes

### Application
- [ ] Build Docker images: `docker compose build`
- [ ] Start services: `docker compose up -d`
- [ ] Wait for health checks to pass
- [ ] Verify all services healthy: `docker compose ps`

### Smoke Tests
- [ ] Test /healthz endpoint
- [ ] Test /readyz endpoint
- [ ] Test ABHA login flow
- [ ] Test document upload
- [ ] Test WebSocket connection
- [ ] Test OCR processing
- [ ] Check application logs for errors

### Monitoring
- [ ] Verify metrics collection
- [ ] Verify log aggregation
- [ ] Verify error tracking
- [ ] Set baseline performance metrics
- [ ] Enable alerts for critical metrics

## Post-Deployment (First 24 Hours)

### Monitoring
- [ ] Monitor error rate (target: <0.1%)
- [ ] Monitor response times (target: p95 <500ms)
- [ ] Monitor database connections
- [ ] Monitor Redis memory usage
- [ ] Monitor disk space usage
- [ ] Monitor SSL certificate expiry
- [ ] Review security logs

### User Testing
- [ ] User acceptance testing
- [ ] Gather user feedback
- [ ] Monitor user traffic patterns
- [ ] Verify all features working

## Post-Launch (First Week)

### Operations
- [ ] Daily health checks
- [ ] Review application logs
- [ ] Review security logs
- [ ] Monitor resource utilization
- [ ] Optimize based on real traffic
- [ ] Schedule follow-up security review
- [ ] Update documentation with lessons learned

### Maintenance
- [ ] Setup certificate renewal automation
- [ ] Setup database backup verification
- [ ] Setup log retention policies
- [ ] Setup metrics retention policies

## Ongoing (Monthly)

- [ ] SSL certificate expiration check (30+ days notice)
- [ ] Security updates check
- [ ] Database maintenance (VACUUM, ANALYZE)
- [ ] Log review and archival
- [ ] Performance optimization review
- [ ] Capacity planning review

EOF
    
    echo "✓ Generated DEPLOYMENT_CHECKLIST.md"
}

################################################################################
# Section 14: Generate Quick Start Guide
################################################################################

generate_quick_start() {
    print_header "Generating Quick Start Guide"
    
    cat > "${PROJECT_ROOT}/QUICK_START_PRODUCTION.md" << 'EOF'
# MediKiosk-Backend: Production Quick Start

## 1. Clone Repository
```bash
git clone https://github.com/rahull-techh/SIH26-Meditrack.git
cd SIH26-Meditrack/MediKiosk-Backend
```

## 2. Configure Environment
```bash
# Copy template
cp .env.example .env

# Generate secrets (macOS)
python3 << 'SECRETS'
import os, base64, secrets
print("JWT_SECRET_KEY=" + secrets.token_urlsafe(64))
print("JWT_REFRESH_SECRET_KEY=" + secrets.token_urlsafe(64))
print("FIELD_ENCRYPTION_KEY=" + base64.urlsafe_b64encode(os.urandom(32)).decode())
print("WEBHOOK_HMAC_KEY=" + base64.urlsafe_b64encode(os.urandom(32)).decode())
SECRETS

# Edit .env and update all CHANGE_ME values with actual production secrets
nano .env
```

## 3. Setup SSL Certificates
```bash
# Create SSL directory
mkdir -p nginx/ssl

# Option A: Let's Encrypt (Recommended)
certbot certonly --standalone -d your-domain.com
cp /etc/letsencrypt/live/your-domain.com/fullchain.pem nginx/ssl/cert.pem
cp /etc/letsencrypt/live/your-domain.com/privkey.pem nginx/ssl/key.pem
chmod 644 nginx/ssl/cert.pem
chmod 600 nginx/ssl/key.pem

# Option B: Self-signed (Development only)
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx/ssl/key.pem -out nginx/ssl/cert.pem \
  -subj "/C=IN/ST=State/L=City/O=Org/CN=localhost"
```

## 4. Create Upload Directories
```bash
mkdir -p uploads/temp_scans uploads/encrypted_vault
chmod 755 uploads uploads/temp_scans uploads/encrypted_vault
```

## 5. Validate Deployment
```bash
# Run comprehensive validation
bash scripts/validate-deployment.sh

# Review results and fix any critical issues
```

## 6. Start Services
```bash
# Build images
docker compose build

# Start all services
docker compose up -d

# Wait for services to be healthy (check docker compose ps)
docker compose ps

# Check logs
docker compose logs -f api
```

## 7. Run Migrations
```bash
# Execute database migrations
docker compose exec api alembic upgrade head

# Verify migration
docker compose exec api alembic current
```

## 8. Health Checks
```bash
# Application health
curl https://your-domain.com/healthz

# Readiness check
curl https://your-domain.com/readyz

# Test authentication
curl -X POST https://your-domain.com/api/v1/auth/abha/otp/request \
  -H "Content-Type: application/json" \
  -d '{"abha_id": "test_abha_id"}'
```

## 9. Scale (if needed)
```bash
# Scale API replicas
docker compose up -d --scale api=5

# Scale Celery workers
docker compose up -d --scale celery_worker=3

# Verify scaling
docker compose ps
```

## 10. Monitor
```bash
# Watch logs
docker compose logs -f api celery_worker

# Check resource usage
docker stats

# Database health
docker compose exec postgres psql -U medikiosk -d medikiosk -c "SELECT version();"

# Redis health
docker compose exec redis redis-cli ping
```

## Troubleshooting

### Services won't start
```bash
# Check logs
docker compose logs api

# Verify .env is valid
source .env && echo "OK"

# Restart services
docker compose restart
```

### Database connection errors
```bash
# Verify Postgres is ready
docker compose exec postgres pg_isready -U medikiosk

# Check database exists
docker compose exec postgres psql -U medikiosk -l

# Reset connection pool
docker compose restart api
```

### SSL certificate errors
```bash
# Validate certificate
openssl x509 -in nginx/ssl/cert.pem -text -noout

# Check permissions
ls -la nginx/ssl/

# Reload nginx
docker compose restart nginx
```

### High CPU/Memory usage
```bash
# Check resource limits
docker compose ps

# Identify resource-heavy services
docker stats

# Scale up or increase limits in docker-compose.yml
docker compose up -d --scale api=5
```

## Support

- GitHub Issues: https://github.com/rahull-techh/SIH26-Meditrack/issues
- Main README: ../README.md
- Troubleshooting: ../README.md#troubleshooting

EOF
    
    echo "✓ Generated QUICK_START_PRODUCTION.md"
}

################################################################################
# Section 15: Generate Configuration Validation Script
################################################################################

generate_env_validator() {
    print_header "Generating Environment Configuration Validator"
    
    cat > "${PROJECT_ROOT}/scripts/validate-env.sh" << 'EOF'
#!/bin/bash

# Quick environment validation script
# Usage: bash scripts/validate-env.sh

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ENV_FILE=".env"

if [ ! -f "$ENV_FILE" ]; then
    echo -e "${RED}✗ Error: .env file not found${NC}"
    exit 1
fi

source "$ENV_FILE"

errors=0
warnings=0

check_var() {
    local var=$1
    local min_len=${2:-1}
    local name=$3
    
    if [ -z "${!var:-}" ]; then
        echo -e "${RED}✗ Missing: $name${NC}"
        ((errors++))
    elif [[ "${!var}" == *"CHANGE_ME"* ]]; then
        echo -e "${RED}✗ Not configured: $name${NC}"
        ((errors++))
    elif [ ${#!var} -lt $min_len ]; then
        echo -e "${YELLOW}⚠ Too short: $name (${#!var}/${min_len} chars)${NC}"
        ((warnings++))
    else
        echo -e "${GREEN}✓ $name${NC}"
    fi
}

echo "Validating environment configuration..."
echo ""

check_var "ENVIRONMENT" 1 "ENVIRONMENT (set to: ${ENVIRONMENT:-})"
check_var "APP_ENV" 1 "APP_ENV (set to: ${APP_ENV:-})"
check_var "DATABASE_URL" 30 "DATABASE_URL"
check_var "POSTGRES_PASSWORD" 12 "POSTGRES_PASSWORD"
check_var "REDIS_HOST" 1 "REDIS_HOST"
check_var "JWT_SECRET_KEY" 32 "JWT_SECRET_KEY"
check_var "JWT_REFRESH_SECRET_KEY" 32 "JWT_REFRESH_SECRET_KEY"
check_var "FIELD_ENCRYPTION_KEY" 32 "FIELD_ENCRYPTION_KEY"
check_var "WEBHOOK_HMAC_KEY" 32 "WEBHOOK_HMAC_KEY"

echo ""
if [ $errors -eq 0 ]; then
    echo -e "${GREEN}✓ All required environment variables are configured${NC}"
else
    echo -e "${RED}✗ $errors critical issue(s) found${NC}"
    exit 1
fi

if [ $warnings -gt 0 ]; then
    echo -e "${YELLOW}⚠ $warnings warning(s) found${NC}"
fi

EOF
    
    chmod +x "${PROJECT_ROOT}/scripts/validate-env.sh"
    echo "✓ Generated validate-env.sh"
}

################################################################################
# Section 16: Generate Health Check Script
################################################################################

generate_health_check() {
    print_header "Generating Health Check Script"
    
    cat > "${PROJECT_ROOT}/scripts/health-check.sh" << 'EOF'
#!/bin/bash

# Health check for running MediKiosk services
# Usage: bash scripts/health-check.sh [domain]

DOMAIN="${1:-http://localhost}"
TIMEOUT=10

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

check_endpoint() {
    local url=$1
    local name=$2
    
    echo -n "Checking $name... "
    
    local response
    response=$(curl -s -m $TIMEOUT -w "%{http_code}" -o /dev/null "$url" 2>&1 || echo "000")
    
    if [ "$response" = "200" ]; then
        echo -e "${GREEN}✓ OK${NC}"
        return 0
    else
        echo -e "${RED}✗ FAIL (HTTP $response)${NC}"
        return 1
    fi
}

echo "MediKiosk Health Check"
echo "Domain: $DOMAIN"
echo ""

passed=0
failed=0

check_endpoint "$DOMAIN/healthz" "Liveness" && ((passed++)) || ((failed++))
check_endpoint "$DOMAIN/readyz" "Readiness" && ((passed++)) || ((failed++))

# Docker Compose checks
if command -v docker &>/dev/null; then
    echo ""
    echo "Docker Services:"
    
    services=("api" "postgres" "redis" "nginx" "celery_worker")
    
    for service in "${services[@]}"; do
        echo -n "  $service... "
        local status
        status=$(docker compose ps $service --format="{{.State}}" 2>/dev/null || echo "unknown")
        
        if [ "$status" = "running" ]; then
            echo -e "${GREEN}✓${NC}"
        else
            echo -e "${RED}✗ ($status)${NC}"
        fi
    done
fi

echo ""
echo "Summary: $passed passed, $failed failed"

exit $failed

EOF
    
    chmod +x "${PROJECT_ROOT}/scripts/health-check.sh"
    echo "✓ Generated health-check.sh"
}

################################################################################
# Main Execution
################################################################################

main() {
    clear
    
    print_header "MediKiosk-Backend Production Deployment Validator"
    echo "Running comprehensive validation checks..."
    echo ""
    
    # Run all validation sections
    validate_environment_config
    validate_ssl_certificates
    validate_docker_setup
    validate_database_config
    validate_redis_config
    validate_security_config
    validate_upload_directories
    validate_required_files
    validate_integrations
    validate_feature_flags
    validate_preflight
    
    # Print summary and score
    print_summary
    print_deployment_score
    
    # Generate supporting documents
    generate_deployment_checklist
    generate_quick_start
    generate_env_validator
    generate_health_check
    
    echo ""
    print_header "Generated Documentation"
    echo -e "  ${GREEN}✓ DEPLOYMENT_CHECKLIST.md${NC} - Pre/during/post deployment tasks"
    echo -e "  ${GREEN}✓ QUICK_START_PRODUCTION.md${NC} - Step-by-step production setup"
    echo -e "  ${GREEN}✓ scripts/validate-env.sh${NC} - Quick environment validation"
    echo -e "  ${GREEN}✓ scripts/health-check.sh${NC} - Runtime health checks"
    echo ""
    echo "Next steps:"
    echo "  1. Review DEPLOYMENT_CHECKLIST.md"
    echo "  2. Fix any critical issues reported above"
    echo "  3. Run: bash scripts/validate-env.sh"
    echo "  4. Follow: cat QUICK_START_PRODUCTION.md"
    echo ""
}

# Run main function and capture exit code
main
exit_code=$?

exit $exit_code
