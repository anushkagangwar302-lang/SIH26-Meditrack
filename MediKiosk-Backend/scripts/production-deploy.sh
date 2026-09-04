#!/bin/bash
# =============================================================================
# Production Deployment Script
# =============================================================================
# This script automates the production deployment process.
#
# Prerequisites:
#   1. Run generate-production-secrets.sh and store secrets in .env
#   2. Run setup-ssl-certificates.sh
#   3. Configure all CHANGE_ME values in .env
#   4. Run validate-deployment.sh to verify readiness
#
# Usage:
#   bash scripts/production-deploy.sh
#
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║      MediKiosk Production Deployment Script            ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check prerequisites
echo -e "${BLUE}[1/7] Checking prerequisites...${NC}"
echo ""

if [ ! -f ".env" ]; then
    echo -e "${RED}✗ .env file not found${NC}"
    echo "   Run: cp .env.production .env"
    exit 1
fi
echo -e "${GREEN}✓ .env file exists${NC}"

if [ ! -f "nginx/ssl/cert.pem" ] || [ ! -f "nginx/ssl/key.pem" ]; then
    echo -e "${RED}✗ SSL certificates not found${NC}"
    echo "   Run: bash scripts/setup-ssl-certificates.sh letsencrypt your-domain.com"
    exit 1
fi
echo -e "${GREEN}✓ SSL certificates installed${NC}"

if ! command -v docker &> /dev/null; then
    echo -e "${RED}✗ Docker not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Docker installed${NC}"

if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}✗ Docker Compose not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Docker Compose installed${NC}"
echo ""

# Validate environment
echo -e "${BLUE}[2/7] Validating environment configuration...${NC}"
echo ""

if bash scripts/validate-deployment.sh > /tmp/deployment-validation.log 2>&1; then
    echo -e "${GREEN}✓ All validation checks passed${NC}"
else
    echo -e "${RED}✗ Validation failed. See details:${NC}"
    tail -50 /tmp/deployment-validation.log
    exit 1
fi
echo ""

# Backup existing database
echo -e "${BLUE}[3/7] Creating database backup...${NC}"
echo ""

if docker compose ps postgres | grep -q "postgres"; then
    BACKUP_FILE="backup_$(date +%Y%m%d_%H%M%S).sql.gz"
    echo "Backing up to: $BACKUP_FILE"
    docker compose exec postgres pg_dump -U medikiosk medikiosk | gzip > "$BACKUP_FILE"
    echo -e "${GREEN}✓ Backup created: $BACKUP_FILE${NC}"
else
    echo -e "${YELLOW}⚠ Postgres not running. Skipping backup.${NC}"
fi
echo ""

# Build and start services
echo -e "${BLUE}[4/7] Building and starting services...${NC}"
echo ""

docker compose up --build -d
echo -e "${GREEN}✓ Services started${NC}"
echo ""

# Wait for services to be healthy
echo -e "${BLUE}[5/7] Waiting for services to be healthy...${NC}"
echo ""

max_attempts=30
attempt=0

while [ $attempt -lt $max_attempts ]; do
    if docker compose ps | grep -q "healthy"; then
        echo -e "${GREEN}✓ Services are healthy${NC}"
        break
    fi
    echo "Waiting for services... ($attempt/$max_attempts)"
    sleep 5
    attempt=$((attempt + 1))
done

if [ $attempt -eq $max_attempts ]; then
    echo -e "${YELLOW}⚠ Services took longer than expected to become healthy${NC}"
    echo "Check logs with: docker compose logs"
fi
echo ""

# Run database migrations
echo -e "${BLUE}[6/7] Running database migrations...${NC}"
echo ""

docker compose exec api alembic upgrade head
echo -e "${GREEN}✓ Migrations completed${NC}"
echo ""

# Verify deployment
echo -e "${BLUE}[7/7] Verifying deployment...${NC}"
echo ""

echo "Testing health endpoints..."
if curl -s http://localhost:8000/healthz | grep -q "ok"; then
    echo -e "${GREEN}✓ Health check passed${NC}"
else
    echo -e "${RED}✗ Health check failed${NC}"
    exit 1
fi

if curl -s http://localhost:8000/readyz | grep -q "ready"; then
    echo -e "${GREEN}✓ Readiness check passed${NC}"
else
    echo -e "${RED}✗ Readiness check failed${NC}"
    exit 1
fi
echo ""

echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     ✓ Production Deployment Successful!                ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "Next steps:"
echo "1. Monitor logs: docker compose logs -f api"
echo "2. Check status: docker compose ps"
echo "3. Test API: curl -k https://your-domain.com/healthz"
echo "4. Review dashboard: https://your-domain.com/docs (disabled in production)"
echo ""
