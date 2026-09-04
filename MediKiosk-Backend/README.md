# MediKiosk-Backend — Complete Healthcare Intake System

FastAPI backend for SIH26 MediTrack with ABHA/ABDM integration, Bhashini/AI4Bharat voice, AYUSH clinical intake, and DPDP Act 2023 compliance.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Quick Start](#quick-start)
- [Phase-by-Phase Setup](#phase-by-phase-setup)
- [Production Deployment](#production-deployment)
- [Scaling Guidelines](#scaling-guidelines)
- [Go-Live Checklist](#go-live-checklist)
- [Monitoring & Operations](#monitoring--operations)
- [Security & Compliance](#security--compliance)
- [Troubleshooting](#troubleshooting)

## Architecture Overview

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Kiosk Clients │────▶│   Nginx LB/SSL  │────▶│  FastAPI Replicas│
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                                       │
                       ┌─────────────────┐             │
                       │  Celery Workers │◀────────────┘
                       └─────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
┌───────▼──────┐    ┌────────▼────────┐    ┌───────▼──────┐
│   Postgres   │    │      Redis      │    │ External APIs│
│  (Primary)   │    │ (Sessions/Locks)│    │ (ABDM/Bhashini)│
└──────────────┘    └─────────────────┘    └──────────────┘
```

### Key Components

- **FastAPI Replicas**: Stateless API servers (horizontal scaling)
- **Nginx**: Load balancer, SSL termination, rate limiting
- **PostgreSQL**: Persistent data storage with connection pooling
- **Redis**: Session state, distributed locks, Celery broker, rate limiting
- **Celery Workers**: Background tasks (OCR, ABDM sync, PDF generation)
- **Celery Beat**: Periodic tasks (temp file cleanup, health checks)

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.12+ (for local development)
- PostgreSQL 16+ (if not using Docker)
- Redis 7+ (if not using Docker)

### Initial Setup

```bash
# Clone repository
git clone https://github.com/rahull-techh/SIH26-Meditrack.git
cd SIH26-Meditrack/MediKiosk-Backend

# Copy environment template
cp .env.example .env

# Generate cryptographic keys
python3 -c "import os,base64,secrets; print('JWT_SECRET_KEY=' + secrets.token_urlsafe(64)); print('JWT_REFRESH_SECRET_KEY=' + secrets.token_urlsafe(64)); print('FIELD_ENCRYPTION_KEY=' + base64.urlsafe_b64encode(os.urandom(32)).decode()); print('WEBHOOK_HMAC_KEY=' + base64.urlsafe_b64encode(os.urandom(32)).decode())"

# Edit .env and replace all CHANGE_ME values
# Configure database passwords, API keys, and secrets

# Build and start services
docker compose up --build -d

# Check health
curl -s http://127.0.0.1:8000/healthz
curl -s http://127.0.0.1:8000/readyz
```

## Phase-by-Phase Setup

### Phase 1: Foundations (Core Infrastructure)

**Status**: ✅ Complete

**Components**:
- `core/config.py` - Pydantic Settings for environment configuration
- `core/database.py` - Async SQLAlchemy + Redis clients with connection pooling
- `core/security.py` - Encryption helpers, JWT, password/OTP hashing
- `core/exceptions.py` - Global exception handlers
- `utils/logger.py` - Structured JSON logging with request IDs

**Verification**:
```bash
# Test database connectivity
docker compose exec api python -c "from app.core.database import engine; import asyncio; asyncio.run(engine.connect())"

# Test Redis connectivity
docker compose exec api python -c "from app.core.database import redis_client; redis_client.ping()"
```

### Phase 2: Data Layer (Models & Schemas)

**Status**: ✅ Complete

**Components**:
- `models/user.py` - User and clinic models
- `models/clinical.py` - Clinical data models
- `models/ayush.py` - AYUSH-specific models
- `models/documents.py` - Document storage models
- `models/consent.py` - Consent tracking models
- `schemas/*` - Pydantic schemas for all domains

**Migration Setup**:
```bash
# Run Alembic migrations (NEVER use create_all in production)
alembic upgrade head

# Verify migration status
alembic current
alembic history
```

**PII Field Flags**: All Aadhaar/ABHA fields are explicitly marked with `# PII` comments for encryption.

### Phase 3: Auth & Consent

**Status**: ✅ Complete

**Components**:
- `api/v1/auth_routes.py` - ABHA login, consent management
- Consent enforcement via `Depends(require_intake_session)` dependency

**Setup**:
```bash
# 1. Run migrations
alembic upgrade head

# 2. Insert clinic and staff user (via database script or admin panel)
# Example SQL:
# INSERT INTO clinics (name, license_number, address) VALUES ('Test Clinic', 'LIC123', '123 Main St');
# INSERT INTO users (clinic_id, login_handle, password_hash, role) VALUES (1, 'kiosk_user', '$argon2id$v=19$m=65536,t=3,p=2$...', 'kiosk');

# 3. Test patient flow
curl -X POST http://127.0.0.1:8000/api/v1/auth/abha/otp/request \
  -H "Content-Type: application/json" \
  -d '{"abha_id": "123456789012"}' \
  -H "Idempotency-Key: unique-request-id"

curl -X POST http://127.0.0.1:8000/api/v1/auth/abha/otp/verify \
  -H "Content-Type: application/json" \
  -d '{"abha_id": "123456789012", "otp": "246810"}' \
  -H "Idempotency-Key: unique-request-id"

curl -X POST http://127.0.0.1:8000/api/v1/auth/consent \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <access_token>" \
  -d '{"purpose": "treatment", "data_categories": ["clinical", "documents"]}'

curl -X GET http://127.0.0.1:8000/api/v1/auth/intake-check \
  -H "Authorization: Bearer <access_token>"
```

### Phase 4: AI Modules

**Status**: ✅ Complete

**Components**:
- `ai_modules/asr_tts.py` - Bhashini voice interface with circuit breaker
- `ai_modules/nlp_clinical.py` - Clinical NLP processing
- `ai_modules/ocr_vision.py` - Document OCR with fallback

**Configuration**:
```bash
# Set Bhashini credentials in .env
BHASHINI_API_KEY=your_api_key
BHASHINI_USER_ID=your_user_id
BHASHINI_ASR_PIPELINE_ID=asr_pipeline_id
BHASHINI_TTS_PIPELINE_ID=tts_pipeline_id

# Configure OCR provider
OCR_SERVICE_PROVIDER=tesseract  # or google_vision, aws_textract
OCR_API_KEY=your_ocr_key  # if using cloud provider
```

### Phase 5: Services

**Status**: ✅ Complete

**Components**:
- `services/dialogue_manager.py` - SOCRATES/AYUSH branching logic
- `services/triage_service.py` - Red-flag triage rules
- `services/summary_engine.py` - Clinical summary generation
- `services/fhir_service.py` - FHIR resource conversion

**Business Logic**: All clinical business logic isolated in services, not route handlers.

### Phase 6: Routes & Realtime

**Status**: ✅ Complete

**Components**:
- `api/v1/interview.py` - WebSocket with Redis fan-out for multi-replica support
- `api/v1/documents.py` - Async upload with polling
- `api/v1/summary.py` - Summary endpoints
- `api/v1/abdm_webhooks.py` - ABDM webhook handlers with signature verification

**WebSocket Testing**:
```bash
# Test WebSocket connection
wscat -c ws://127.0.0.1:8000/api/v1/interview/session_id \
  -H "Authorization: Bearer <access_token>"
```

### Phase 7: Workers

**Status**: ✅ Complete

**Components**:
- `workers/celery_app.py` - Celery configuration
- `workers/tasks.py` - OCR processing, ABDM sync, PDF generation, temp file cleanup

**Task Execution**:
```bash
# Monitor Celery workers
docker compose exec celery_worker celery -A workers.celery_app inspect active

# Trigger manual task (for testing)
docker compose exec api python -c "from workers.tasks import process_ocr; process_ocr.delay('doc_id')"
```

### Phase 8: Tests

**Status**: ✅ Complete

**Components**:
- `tests/test_dialogue_flow.py` - Dialogue flow tests
- `tests/test_ocr_extraction.py` - OCR extraction tests
- `tests/test_abdm_fhir.py` - ABDM/FHIR integration tests
- `tests/test_concurrency.py` - Concurrency safety tests
- `tests/load_test.py` - Load testing script (Locust/k6)

**Test Execution**:
```bash
# Run unit tests
docker compose exec api pytest tests/

# Run concurrency tests
docker compose exec api pytest tests/test_concurrency.py -v

# Run load tests
docker compose exec api locust -f tests/load_test.py --host=http://api:8000
```

### Phase 9: Operations

**Status**: 🚧 In Progress

**Components**:
- Production docker-compose.yml with reverse proxy
- Complete .env.example with all required variables
- Comprehensive README with go-live checklist
- Production-ready Dockerfile
- Complete .gitignore

## Production Deployment

### Prerequisites Checklist

- [ ] SSL certificates obtained and placed in `nginx/ssl/`
- [ ] All environment variables configured in `.env`
- [ ] Database passwords changed from defaults
- [ ] API keys obtained from ABDM, Bhashini, OCR provider
- [ ] Server resources provisioned (CPU, RAM, storage)
- [ ] Backup strategy configured
- [ ] Monitoring and alerting set up
- [ ] Security audit completed

### Deployment Steps

#### 1. Environment Preparation

```bash
# Set production environment
export ENVIRONMENT=production

# Generate production keys
python3 -c "import os,base64,secrets; print('JWT_SECRET_KEY=' + secrets.token_urlsafe(64)); print('JWT_REFRESH_SECRET_KEY=' + secrets.token_urlsafe(64)); print('FIELD_ENCRYPTION_KEY=' + base64.urlsafe_b64encode(os.urandom(32)).decode()); print('WEBHOOK_HMAC_KEY=' + base64.urlsafe_b64encode(os.urandom(32)).decode())"

# Configure production .env
cp .env.example .env
# Edit .env with production values
```

#### 2. SSL Certificate Setup

```bash
# Place SSL certificates
mkdir -p nginx/ssl
cp /path/to/your/cert.pem nginx/ssl/cert.pem
cp /path/to/your/key.pem nginx/ssl/key.pem
chmod 644 nginx/ssl/cert.pem
chmod 600 nginx/ssl/key.pem
```

#### 3. Database Migration

```bash
# Backup existing database (if upgrading)
docker compose exec postgres pg_dump -U medikiosk medikiosk > backup.sql

# Run migrations
docker compose exec api alembic upgrade head

# Verify migration
docker compose exec api alembic current
```

#### 4. Service Deployment

```bash
# Build and start production services
docker compose -f docker-compose.yml up -d --build

# Scale API replicas based on load
docker compose up -d --scale api=3

# Verify all services are healthy
docker compose ps
curl -s https://your-domain.com/healthz
curl -s https://your-domain.com/readyz
```

#### 5. Post-Deployment Verification

```bash
# Test authentication flow
curl -X POST https://your-domain.com/api/v1/auth/abha/otp/request \
  -H "Content-Type: application/json" \
  -d '{"abha_id": "test_abha_id"}'

# Test WebSocket connection
wscat -c wss://your-domain.com/api/v1/interview/test_session

# Check Celery workers
docker compose exec celery_worker celery -A workers.celery_app inspect active

# Monitor logs
docker compose logs -f api
docker compose logs -f celery_worker
```

## Scaling Guidelines

### Horizontal Scaling

#### API Replicas

**Formula**: `api_replicas = (expected_concurrent_users / users_per_replica) + buffer`

- **Development**: 1 replica
- **Staging**: 2 replicas
- **Production**: 3-10 replicas (based on load)

**Configuration**:
```yaml
# In docker-compose.yml
deploy:
  replicas: 3  # Adjust based on load
```

**Monitoring**:
- CPU utilization > 70% → Add replicas
- Memory utilization > 80% → Add replicas or increase memory limits
- Response time > 2s → Add replicas

#### Celery Workers

**Formula**: `worker_replicas = (ocr_tasks_per_hour / tasks_per_worker) + buffer`

- **Development**: 1 worker
- **Staging**: 2 workers
- **Production**: 2-5 workers (based on OCR volume)

**Configuration**:
```yaml
# In docker-compose.yml
deploy:
  replicas: 2  # Adjust based on task volume
```

### Vertical Scaling

#### Database Connection Pooling

**Formula**: `pool_size = (postgres_max_connections / api_replicas) - buffer`

**Example**: Postgres max_connections=100, api_replicas=3
- `pool_size = 30` per replica
- `max_overflow = 10` per replica

**Configuration**:
```bash
# In .env
DB_POOL_SIZE=30
DB_MAX_OVERFLOW=10
```

#### Redis Connection Pooling

**Configuration**:
```bash
# In .env
REDIS_POOL_SIZE=50
```

### Resource Limits

#### Minimum Resources per Service

| Service | CPU | RAM | Storage |
|---------|-----|-----|---------|
| API (per replica) | 0.5-1 core | 512MB-1GB | - |
| Celery Worker | 1-2 cores | 1GB-2GB | - |
| Postgres | 2-4 cores | 2GB-4GB | 50GB+ |
| Redis | 1 core | 512MB | 10GB+ |
| Nginx | 0.5 core | 256MB | - |

#### Scaling Recommendations

**Small Clinic** (1-5 kiosks):
- API: 2 replicas
- Celery: 1 worker
- Postgres: 2 cores, 2GB RAM
- Redis: 1 core, 512MB RAM

**Medium Clinic** (5-20 kiosks):
- API: 3-4 replicas
- Celery: 2 workers
- Postgres: 4 cores, 4GB RAM
- Redis: 1 core, 1GB RAM

**Large Hospital** (20+ kiosks):
- API: 5-10 replicas
- Celery: 3-5 workers
- Postgres: 8+ cores, 8GB+ RAM
- Redis: 2 cores, 2GB RAM

## Go-Live Checklist

### Pre-Deployment

#### Security & Compliance
- [ ] All passwords changed from defaults
- [ ] JWT secrets generated (minimum 64 characters)
- [ ] Field encryption key generated (32 bytes)
- [ ] Webhook HMAC key generated (32 bytes)
- [ ] SSL certificates installed and valid
- [ ] HTTPS enforced via nginx
- [ ] Security headers configured (CSP, HSTS, X-Frame-Options)
- [ ] Rate limiting configured and tested
- [ ] Input validation tested
- [ ] SQL injection prevention verified
- [ ] XSS prevention verified
- [ ] CSRF protection enabled
- [ ] DPDP Act 2023 compliance audit completed

#### Data Protection
- [ ] Database encryption at rest enabled
- [ ] Field-level encryption for PII verified
- [ ] Backup strategy implemented and tested
- [ ] Disaster recovery plan documented
- [ ] Data retention policy configured
- [ ] Audit logging enabled and tested
- [ ] PII not logged in error messages
- [ ] Consent management verified

#### External Integrations
- [ ] ABDM credentials obtained and configured
- [ ] ABDM sandbox testing completed
- [ ] Bhashini API keys obtained
- [ ] Bhashini voice testing completed
- [ ] OCR service configured and tested
- [ ] Webhook endpoints configured
- [ ] Callback URLs registered with ABDM

#### Performance & Reliability
- [ ] Load testing completed (target: 1000 concurrent users)
- [ ] Database query optimization verified
- [ ] Connection pooling configured
- [ ] Redis caching configured
- [ ] Celery task queue tested
- [ ] Circuit breakers tested
- [ ] Retry logic tested
- [ ] Health check endpoints verified
- [ ] Graceful shutdown tested

#### Monitoring & Alerting
- [ ] Application monitoring configured (Prometheus/Grafana)
- [ ] Log aggregation configured (ELK/Loki)
- [ ] Error tracking configured (Sentry)
- [ ] Uptime monitoring configured
- [ ] Alert thresholds defined
- [ ] On-call rotation established
- [ ] Runbook documentation completed

### Deployment Day

#### Database
- [ ] Pre-production database backup created
- [ ] Alembic migrations tested on staging
- [ ] Database indexes verified
- [ ] Connection pool settings verified
- [ ] Redis data persistence verified

#### Application
- [ ] Docker images built and pushed to registry
- [ ] Environment variables configured
- [ ] SSL certificates installed
- [ ] nginx configuration verified
- [ ] Health checks passing
- [ ] Rolling deployment executed
- [ ] Smoke tests passed

#### Post-Deployment
- [ ] All services healthy
- [ ] Authentication flow tested
- [ ] ABHA integration tested
- [ ] Voice interface tested
- [ ] Document upload tested
- [ ] OCR processing tested
- [ ] WebSocket connections tested
- [ ] Celery tasks processing
- [ ] Logs flowing correctly
- [ ] Metrics collecting correctly

### Post-Launch Monitoring

#### First 24 Hours
- [ ] Monitor error rates (target: < 0.1%)
- [ ] Monitor response times (target: < 500ms p95)
- [ ] Monitor database connections
- [ ] Monitor Redis memory usage
- [ ] Monitor Celery queue depth
- [ ] Monitor SSL certificate expiry
- [ ] Monitor backup completion

#### First Week
- [ ] Daily health checks
- [ ] Review security logs
- [ ] Monitor user feedback
- [ ] Optimize based on real traffic patterns
- [ ] Update documentation
- [ ] Schedule security review

## Monitoring & Operations

### Health Check Endpoints

```bash
# Application health
GET /healthz  # Returns 200 if all dependencies are healthy

# Readiness check
GET /readyz   # Returns 200 if application can accept traffic

# Metrics endpoint (if enabled)
GET /metrics  # Prometheus metrics
```

### Log Management

#### Log Levels

- **DEBUG**: Detailed development information
- **INFO**: General operational information
- **WARNING**: Warning messages (potential issues)
- **ERROR**: Error messages (service degradation)
- **CRITICAL**: Critical errors (service failure)

#### Log Streams

- **Application Logs**: `/var/log/medikiosk/app.log`
- **Audit Logs**: `/var/log/medikiosk/audit.log` (compliance)
- **Access Logs**: `/var/log/nginx/access.log`
- **Error Logs**: `/var/log/nginx/error.log`

#### Log Analysis

```bash
# View application logs
docker compose logs -f api

# View Celery worker logs
docker compose logs -f celery_worker

# View nginx logs
docker compose logs -f nginx

# Search for errors
docker compose logs api | grep ERROR

# Search for specific request ID
docker compose logs api | grep "request_id=abc123"
```

### Performance Monitoring

#### Key Metrics

- **Request Rate**: Requests per second
- **Response Time**: p50, p95, p99 latency
- **Error Rate**: Percentage of failed requests
- **Database Connections**: Active/idle connections
- **Redis Memory**: Memory usage and eviction rate
- **Celery Queue**: Task queue depth
- **Celery Workers**: Active/processing tasks

#### Monitoring Tools

- **Prometheus**: Metrics collection
- **Grafana**: Visualization and dashboards
- **Sentry**: Error tracking
- **ELK Stack**: Log aggregation and analysis

### Backup Strategy

#### Database Backups

```bash
# Daily automated backup
docker compose exec postgres pg_dump -U medikiosk medikiosk | gzip > backup_$(date +%Y%m%d).sql.gz

# Restore from backup
gunzip < backup_20240904.sql.gz | docker compose exec -T postgres psql -U medikiosk medikiosk
```

#### Backup Schedule

- **Database**: Daily full backups, hourly WAL archives
- **Redis**: Daily RDB snapshots
- **Uploads**: Daily encrypted_vault backups
- **Configuration**: Version controlled (.env.example)

#### Retention Policy

- **Daily backups**: 7 days
- **Weekly backups**: 4 weeks
- **Monthly backups**: 12 months
- **Annual backups**: 7 years (compliance)

## Security & Compliance

### DPDP Act 2023 Compliance

#### Data Protection Requirements

- **Consent Management**: Explicit consent before PII access
- **Data Minimization**: Collect only necessary data
- **Purpose Limitation**: Use data only for stated purpose
- **Storage Limitation**: Retain data only as long as necessary
- **Data Security**: Encryption at rest and in transit
- **Access Control**: Role-based access control
- **Audit Trail**: Complete audit logging
- **Breach Notification**: Incident response procedures

#### Implementation Checklist

- [ ] Field-level encryption for Aadhaar/ABHA data
- [ ] Consent enforcement in code
- [ ] Audit logging for all PII access
- [ ] Data retention policies configured
- [ ] Right to erasure implemented
- [ ] Data portability implemented
- [ ] Breach detection and notification
- [ ] Regular security audits

### Security Best Practices

#### Authentication

- JWT with short-lived access tokens (30 minutes)
- Refresh tokens with 7-day expiry
- Multi-factor authentication for admin access
- Password requirements (minimum 12 characters)
- Account lockout after failed attempts

#### Authorization

- Role-based access control (patient, kiosk, physician, admin)
- Least privilege principle
- Regular access reviews
- Session timeout after inactivity

#### Network Security

- HTTPS enforced for all endpoints
- TLS 1.2+ with strong ciphers
- Web Application Firewall (WAF)
- DDoS protection
- Network segmentation

#### Application Security

- Input validation and sanitization
- SQL injection prevention
- XSS protection
- CSRF protection
- Security headers (CSP, HSTS, X-Frame-Options)
- Dependency vulnerability scanning

## Troubleshooting

### Common Issues

#### Database Connection Issues

**Symptoms**: `Database connection error`, `Connection pool exhausted`

**Solutions**:
```bash
# Check database health
docker compose exec postgres pg_isready -U medikiosk

# Check connection pool settings
# In .env: DB_POOL_SIZE=20, DB_MAX_OVERFLOW=10

# Restart API service
docker compose restart api
```

#### Redis Connection Issues

**Symptoms**: `Redis connection error`, `Session not found`

**Solutions**:
```bash
# Check Redis health
docker compose exec redis redis-cli ping

# Check Redis memory usage
docker compose exec redis redis-cli INFO memory

# Restart Redis service
docker compose restart redis
```

#### Celery Task Failures

**Symptoms**: `Task execution failed`, `OCR processing timeout`

**Solutions**:
```bash
# Check Celery worker status
docker compose exec celery_worker celery -A workers.celery_app inspect active

# Check Celery logs
docker compose logs celery_worker

# Restart Celery worker
docker compose restart celery_worker
```

#### SSL Certificate Issues

**Symptoms**: `SSL certificate error`, `HTTPS not working`

**Solutions**:
```bash
# Check certificate validity
openssl x509 -in nginx/ssl/cert.pem -text -noout

# Check certificate permissions
ls -la nginx/ssl/

# Restart nginx
docker compose restart nginx
```

#### Performance Issues

**Symptoms**: Slow response times, high CPU/memory usage

**Solutions**:
```bash
# Check resource usage
docker stats

# Scale API replicas
docker compose up -d --scale api=5

# Check database query performance
docker compose exec postgres psql -U medikiosk -c "SELECT * FROM pg_stat_statements ORDER BY total_time DESC LIMIT 10;"
```

### Emergency Procedures

#### Service Outage

1. **Identify affected service**: Check health endpoints
2. **Check logs**: Review error logs for root cause
3. **Restart service**: `docker compose restart <service>`
4. **Scale up**: Add replicas if under load
5. **Rollback**: Revert to previous version if needed

#### Data Breach

1. **Isolate systems**: Disable affected services
2. **Preserve evidence**: Capture logs and system state
3. **Assess impact**: Identify compromised data
4. **Notify stakeholders**: Follow breach notification procedures
5. **Remediate**: Patch vulnerabilities, change credentials
6. **Document**: Complete incident report

#### Database Corruption

1. **Stop writes**: Put application in maintenance mode
2. **Assess damage**: Check database integrity
3. **Restore backup**: Restore from most recent clean backup
4. **Verify data**: Validate data integrity
5. **Resume operations**: Gradually restore service

## Support & Resources

### Documentation

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Celery Documentation](https://docs.celeryproject.org/)
- [ABDM Documentation](https://abdm.gov.in/)
- [Bhashini Documentation](https://bhashini.gov.in/)

### Community

- GitHub Issues: https://github.com/rahull-techh/SIH26-Meditrack/issues
- SIH26 Support: [Contact information]

### Emergency Contacts

- **Technical Lead**: [Contact information]
- **Security Team**: [Contact information]
- **ABDM Support**: [Contact information]
- **Bhashini Support**: [Contact information]

---

**Version**: 1.0.0  
**Last Updated**: 2026-09-04  
**Maintained By**: SIH26 MediTrack Team
