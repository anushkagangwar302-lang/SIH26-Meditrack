# Production-Ready Deployment Guide for MediKiosk-Backend

## Overview

This guide provides step-by-step instructions to deploy MediKiosk-Backend to production with full security, compliance (DPDP Act 2023), and high availability.

## Pre-Deployment Requirements

### 1. Infrastructure
- [ ] Linux server (Ubuntu 20.04+ or similar)
- [ ] Docker Engine 24.0+
- [ ] Docker Compose 2.20+
- [ ] SSL certificate (from Let's Encrypt or trusted CA)
- [ ] Production domain name
- [ ] Firewall configured (ports 80, 443 open)

### 2. Credentials & Secrets
- [ ] ABDM Client ID & Secret (https://abdm.gov.in/)
- [ ] Bhashini API Key & User ID (https://bhashini.gov.in/)
- [ ] OCR API credentials (if using cloud provider)
- [ ] DPDP Act 2023 notice & privacy policy ready

## Deployment Steps

### Step 1: Generate Production Secrets

```bash
cd MediKiosk-Backend
bash scripts/generate-production-secrets.sh > /tmp/production-secrets.txt
echo "Save these secrets securely in AWS Secrets Manager or Vault!"
cat /tmp/production-secrets.txt
```

### Step 2: Setup SSL Certificates

```bash
# Let's Encrypt (Recommended)
bash scripts/setup-ssl-certificates.sh letsencrypt your-production-domain.com

# Or Self-signed (Development only)
bash scripts/setup-ssl-certificates.sh selfsigned
```

### Step 3: Configure Environment

```bash
cp .env.production .env
vim .env  # Edit with production values
```

### Step 4: Deploy Services

```bash
bash scripts/production-deploy.sh
```

### Step 5: Verify Deployment

```bash
curl -k https://your-domain.com/healthz
curl -k https://your-domain.com/readyz
```

## Key Files for Production

- `docker-compose.production.yml` - Production-ready multi-replica deployment
- `nginx/nginx.production.conf` - Production nginx with security headers
- `.env.production` - Production environment template (update before deployment)
- `scripts/generate-production-secrets.sh` - Generate secure random secrets
- `scripts/setup-ssl-certificates.sh` - Setup SSL/TLS certificates
- `scripts/production-deploy.sh` - Automated production deployment

---

**See PRODUCTION_DEPLOYMENT.md for complete documentation**
