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

**Output contains:**
- JWT_SECRET_KEY (64 chars)
- JWT_REFRESH_SECRET_KEY (64 chars)
- FIELD_ENCRYPTION_KEY (32 bytes, base64)
- WEBHOOK_HMAC_KEY (32 bytes, base64)
- POSTGRES_PASSWORD (24 chars)
- REDIS_PASSWORD (24 chars)

### Step 2: Setup SSL Certificates

```bash
# Option A: Let's Encrypt (Recommended for production)
bash scripts/setup-ssl-certificates.sh letsencrypt your-production-domain.com

# Option B: Self-signed (Development only)
bash scripts/setup-ssl-certificates.sh selfsigned
```

Verify certificates:
```bash
ls -la nginx/ssl/
# Output should show:
# -rw-r--r-- cert.pem
# -rw------- key.pem
```

### Step 3: Configure Environment

```bash
# Copy production template
cp .env.production .env

# Edit with actual production values
vim .env

# Required replacements:
# - DATABASE_URL: Update with production DB credentials
# - POSTGRES_PASSWORD: Use generated secret
# - REDIS_HOST: Update with production Redis host
# - REDIS_PASSWORD: Use generated secret
# - JWT_SECRET_KEY: Use generated secret
# - JWT_REFRESH_SECRET_KEY: Use generated secret
# - FIELD_ENCRYPTION_KEY: Use generated secret
# - WEBHOOK_HMAC_KEY: Use generated secret
# - ABDM_CLIENT_ID: Your ABDM credentials
# - ABDM_CLIENT_SECRET: Your ABDM credentials
# - ABDM_CALLBACK_URL: https://your-domain.com/api/v1/abdm/webhooks
# - BHASHINI_API_KEY: Your Bhashini credentials
# - BHASHINI_USER_ID: Your Bhashini credentials
# - CORS_ORIGINS: https://your-frontend-domain.com
# - DEV_ABHA_OTP: (leave empty for production)
```

### Step 4: Validate Configuration

```bash
# Run comprehensive validation
bash scripts/validate-deployment.sh

# Output should show:
# ✓ All environment variables configured
# ✓ SSL certificates valid
# ✓ Docker installed
# ✓ Database credentials set
# ✓ All secrets generated
```

### Step 5: Deploy Services

```bash
# Make scripts executable
chmod +x scripts/*.sh

# Run automated deployment
bash scripts/production-deploy.sh

# This will:
# 1. Verify all prerequisites
# 2. Backup existing database
# 3. Build Docker images
# 4. Start all services (Postgres, Redis, API, Celery, Nginx)
# 5. Run database migrations
# 6. Verify health checks
```

### Step 6: Post-Deployment Verification

```bash
# Check service status
docker compose ps

# Expected output: All services in "running" state

# Test health endpoints
curl -k https://your-domain.com/healthz
# Response: {"status": "ok"}

curl -k https://your-domain.com/readyz
# Response: {"status": "ready"}

# Check logs
docker compose logs -f api
docker compose logs -f celery_worker

# Monitor resource usage
docker stats
```

## Production Operations

### Database Backups

```bash
# Manual backup
docker compose exec postgres pg_dump -U medikiosk medikiosk | gzip > backup_$(date +%Y%m%d).sql.gz

# Automated backup (add to crontab)
# Daily at 2 AM
0 2 * * * cd /path/to/MediKiosk-Backend && docker compose exec -T postgres pg_dump -U medikiosk medikiosk | gzip > backup_$(date +\%Y\%m\%d).sql.gz
```

### SSL Certificate Renewal

```bash
# Automated renewal with Let's Encrypt (add to crontab)
# Monthly renewal attempt
0 0 1 * * /usr/bin/certbot renew --quiet && docker compose -f /path/to/docker-compose.yml restart nginx

# Verify renewal
openssl x509 -in nginx/ssl/cert.pem -text -noout | grep "Not After"
```

### Scaling

```bash
# Scale API replicas (for 1000+ concurrent users)
docker compose up -d --scale api=5

# Scale Celery workers (for high OCR/ABDM volume)
docker compose up -d --scale celery_worker=4

# Monitor load
docker stats
```

### Health Monitoring

```bash
# Setup Prometheus (optional)
# Metrics available at: https://your-domain.com/metrics

# Monitor error rates
docker compose logs api | grep "ERROR"

# Monitor database connections
docker compose exec postgres psql -U medikiosk -c "SELECT datname, count(*) FROM pg_stat_activity GROUP BY datname;"

# Monitor Redis memory
docker compose exec redis redis-cli INFO memory
```

## Troubleshooting

### Services won't start

```bash
# Check logs
docker compose logs

# Verify .env configuration
source .env && echo "Config loaded"

# Check database connectivity
docker compose exec api python -c "from app.core.database import engine; import asyncio; asyncio.run(engine.connect())"

# Restart services
docker compose restart
```

### SSL certificate errors

```bash
# Verify certificate
openssl x509 -in nginx/ssl/cert.pem -text -noout

# Check expiration
openssl x509 -enddate -noout -in nginx/ssl/cert.pem

# Restart nginx
docker compose restart nginx
```

### Database connection issues

```bash
# Check Postgres status
docker compose exec postgres pg_isready -U medikiosk

# Increase connection pool
# Edit .env: DB_POOL_SIZE=40, DB_MAX_OVERFLOW=20

# Restart API
docker compose restart api
```

### High CPU/Memory usage

```bash
# Check resource usage
docker stats

# Scale up services
docker compose up -d --scale api=5

# Increase resource limits in docker-compose.yml
```

## Security Checklist (DPDP Act 2023)

- [ ] All secrets configured and not in version control
- [ ] SSL/TLS enforced (HTTP → HTTPS redirect)
- [ ] Database passwords changed from defaults
- [ ] JWT secrets generated (minimum 64 characters)
- [ ] Field encryption enabled for PII (Aadhaar, ABHA)
- [ ] Audit logging configured
- [ ] Rate limiting enabled
- [ ] CORS configured for specific domain
- [ ] Security headers present in HTTP responses
- [ ] Webhook HMAC verification enabled
- [ ] DEV_ABHA_OTP unset in production
- [ ] Regular security audits scheduled

## Maintenance Schedule

### Daily
- [ ] Monitor error rates (target: < 0.1%)
- [ ] Check service health
- [ ] Review security logs

### Weekly
- [ ] Review resource utilization
- [ ] Check backup completion
- [ ] Update application logs

### Monthly
- [ ] SSL certificate expiration check
- [ ] Security patch updates
- [ ] Database optimization
- [ ] Security audit

### Quarterly
- [ ] Full security assessment
- [ ] Disaster recovery testing
- [ ] Capacity planning review

## Support & Documentation

- **Main README**: [../README.md](../README.md)
- **Technical Setup**: [README.md](./README.md)
- **ABDM Integration**: [https://abdm.gov.in/](https://abdm.gov.in/)
- **Bhashini Documentation**: [https://bhashini.gov.in/](https://bhashini.gov.in/)
- **DPDP Act 2023**: [https://www.meity.gov.in/](https://www.meity.gov.in/)

## Emergency Contacts

- **Technical Support**: [Your contact]
- **Security Issues**: security@your-org.com
- **ABDM Support**: support@abdm.gov.in
- **Bhashini Support**: support@bhashini.gov.in

---

**Last Updated**: 2026-09-04  
**Version**: 1.0.0  
**Maintained By**: SIH26 MediTrack Team
