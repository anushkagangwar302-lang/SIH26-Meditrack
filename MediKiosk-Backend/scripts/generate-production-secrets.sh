#!/bin/bash
# =============================================================================
# Production Secrets Generation Script
# =============================================================================
# This script generates cryptographically secure production secrets.
# Run ONCE before initial deployment and store outputs in secure vault.
#
# Usage:
#   bash scripts/generate-production-secrets.sh > secrets.txt
#   Keep secrets.txt in a secure secret manager (Vault, AWS Secrets Manager, etc.)
#
# WARNING: Never commit generated secrets to version control
# =============================================================================

set -e

echo "========================================"
echo "MediKiosk Production Secrets Generator"
echo "========================================"
echo ""
echo "Generating cryptographically secure secrets..."
echo ""

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to generate random string
generate_secret() {
    local length=$1
    python3 -c "import secrets; print(secrets.token_urlsafe($length))"
}

# Function to generate random bytes (base64 encoded)
generate_bytes() {
    local length=$1
    python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom($length)).decode())"
}

echo -e "${GREEN}✓ JWT Access Token Secret (64 chars)${NC}"
JWT_SECRET=$(generate_secret 64)
echo "JWT_SECRET_KEY=$JWT_SECRET"
echo ""

echo -e "${GREEN}✓ JWT Refresh Token Secret (64 chars)${NC}"
JWT_REFRESH_SECRET=$(generate_secret 64)
echo "JWT_REFRESH_SECRET_KEY=$JWT_REFRESH_SECRET"
echo ""

echo -e "${GREEN}✓ Field Encryption Key (32 bytes, base64)${NC}"
FIELD_ENCRYPTION_KEY=$(generate_bytes 32)
echo "FIELD_ENCRYPTION_KEY=$FIELD_ENCRYPTION_KEY"
echo ""

echo -e "${GREEN}✓ Webhook HMAC Key (32 bytes, base64)${NC}"
WEBHOOK_HMAC_KEY=$(generate_bytes 32)
echo "WEBHOOK_HMAC_KEY=$WEBHOOK_HMAC_KEY"
echo ""

echo -e "${GREEN}✓ Database Password (24 chars)${NC}"
DATABASE_PASSWORD=$(python3 -c "import secrets, string; chars = string.ascii_letters + string.digits + '!@#$%^&*'; print(''.join(secrets.choice(chars) for _ in range(24)))")
echo "POSTGRES_PASSWORD=$DATABASE_PASSWORD"
echo ""

echo -e "${GREEN}✓ Redis Password (24 chars)${NC}"
REDIS_PASSWORD=$(python3 -c "import secrets, string; chars = string.ascii_letters + string.digits + '!@#$%^&*'; print(''.join(secrets.choice(chars) for _ in range(24)))")
echo "REDIS_PASSWORD=$REDIS_PASSWORD"
echo ""

echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}SAVE THESE SECRETS IMMEDIATELY!${NC}"
echo -e "${YELLOW}Store in: AWS Secrets Manager, HashiCorp Vault, or similar${NC}"
echo -e "${YELLOW}DO NOT commit to version control${NC}"
echo -e "${YELLOW}========================================${NC}"
echo ""
echo -e "${RED}Steps:${NC}"
echo "1. Copy all secrets above"
echo "2. Store in your secret management system"
echo "3. Update docker-compose.yml with actual values"
echo "4. Run: docker compose up --build -d"
echo ""
