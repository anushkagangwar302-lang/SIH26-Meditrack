#!/bin/bash
# =============================================================================
# SSL Certificate Setup for Production
# =============================================================================
# This script helps setup SSL certificates for production deployment.
#
# Usage (Let's Encrypt - Recommended):
#   bash scripts/setup-ssl-certificates.sh letsencrypt your-domain.com
#
# Usage (Self-signed - Development Only):
#   bash scripts/setup-ssl-certificates.sh selfsigned
#
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

SSL_DIR="$(dirname "$0")/../nginx/ssl"

echo "========================================"
echo "SSL Certificate Setup"
echo "========================================"
echo ""

if [ "$1" = "letsencrypt" ] && [ -n "$2" ]; then
    DOMAIN=$2
    echo -e "${GREEN}Setting up Let's Encrypt certificate for: $DOMAIN${NC}"
    echo ""
    
    # Check if certbot is installed
    if ! command -v certbot &> /dev/null; then
        echo -e "${RED}✗ certbot not found. Install with: sudo apt-get install certbot${NC}"
        exit 1
    fi
    
    echo "Step 1: Obtain certificate from Let's Encrypt..."
    sudo certbot certonly --standalone -d "$DOMAIN" --agree-tos --register-unsafely-without-email
    
    echo ""
    echo "Step 2: Create SSL directory..."
    mkdir -p "$SSL_DIR"
    
    echo "Step 3: Copy certificates..."
    sudo cp "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" "$SSL_DIR/cert.pem"
    sudo cp "/etc/letsencrypt/live/$DOMAIN/privkey.pem" "$SSL_DIR/key.pem"
    
    echo "Step 4: Fix permissions..."
    sudo chown $(id -u):$(id -g) "$SSL_DIR/cert.pem" "$SSL_DIR/key.pem"
    chmod 644 "$SSL_DIR/cert.pem"
    chmod 600 "$SSL_DIR/key.pem"
    
    echo ""
    echo -e "${GREEN}✓ SSL certificates installed successfully${NC}"
    echo ""
    echo "Certificate info:"
    openssl x509 -in "$SSL_DIR/cert.pem" -text -noout | grep -E "Subject:|Issuer:|Not Before|Not After"
    echo ""
    echo "Auto-renewal setup:"
    echo "Add to crontab: 0 0 1 * * /usr/bin/certbot renew --quiet && docker compose -f /path/to/docker-compose.yml restart nginx"
    
elif [ "$1" = "selfsigned" ]; then
    echo -e "${YELLOW}⚠ Creating self-signed certificate (DEVELOPMENT ONLY)${NC}"
    echo ""
    
    mkdir -p "$SSL_DIR"
    
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout "$SSL_DIR/key.pem" -out "$SSL_DIR/cert.pem" \
        -subj "/C=IN/ST=State/L=City/O=MediKiosk/CN=localhost"
    
    chmod 644 "$SSL_DIR/cert.pem"
    chmod 600 "$SSL_DIR/key.pem"
    
    echo -e "${GREEN}✓ Self-signed certificate created${NC}"
    echo "Certificate: $SSL_DIR/cert.pem"
    echo "Key: $SSL_DIR/key.pem"
    echo ""
    echo -e "${RED}WARNING: This is for development only. Use Let's Encrypt for production.${NC}"
    
else
    echo -e "${RED}Invalid arguments${NC}"
    echo ""
    echo "Usage:"
    echo "  bash scripts/setup-ssl-certificates.sh letsencrypt your-domain.com"
    echo "  bash scripts/setup-ssl-certificates.sh selfsigned"
    exit 1
fi
