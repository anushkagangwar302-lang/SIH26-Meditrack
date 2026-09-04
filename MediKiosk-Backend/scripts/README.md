# MediKiosk-Backend Operational Scripts

This directory contains production-ready scripts for deploying, monitoring, and maintaining the MediKiosk-Backend system.

## Script Overview

### Deployment & Operations

#### `deploy.sh`
**Purpose**: Automated deployment with safety checks and rollback capability

**Usage**:
```bash
./scripts/deploy.sh deploy    # Full deployment process
./scripts/deploy.sh rollback  # Rollback to previous version
./scripts/deploy.sh health    # Check deployment health
./scripts/deploy.sh backup    # Create backup only
```

**Features**:
- Pre-deployment validation checks
- Automatic backup creation
- Database migration execution
- Health check verification
- Automatic rollback on failure
- Old backup cleanup

### Health Monitoring

#### `health_check.sh`
**Purpose**: Comprehensive health monitoring of all system components

**Usage**:
```bash
./scripts/health_check.sh
```

**Features**:
- Docker services status
- Database health and connection pool
- Redis health and memory usage
- Application health endpoints
- Celery workers status
- Disk space monitoring
- SSL certificate expiry check

### Backup & Restore

#### `backup.sh`
**Purpose**: Automated backup of database, Redis, configuration, and encrypted vault

**Usage**:
```bash
./scripts/backup.sh full     # Full backup (all components)
./scripts/backup.sh database # Database only
./scripts/backup.sh redis    # Redis only
./scripts/backup.sh config   # Configuration only
./scripts/backup.sh vault    # Encrypted vault only
./scripts/backup.sh cleanup  # Clean old backups
```

**Features**:
- Compressed database backups
- Redis RDB snapshots
- Configuration backup with masked secrets
- Encrypted vault backup (patient opt-in data)
- Automatic backup integrity verification
- Configurable retention policy (default: 30 days)

#### `restore.sh`
**Purpose**: System restore from backup with validation

**Usage**:
```bash
./scripts/restore.sh list                                    # List available backups
./scripts/restore.sh database <backup_file>                 # Restore database
./scripts/restore.sh redis <backup_file>                    # Restore Redis
./scripts/restore.sh config <backup_file>                   # Restore configuration
./scripts/restore.sh vault <backup_file>                    # Restore encrypted vault
./scripts/restore.sh full <timestamp>                       # Full system restore
```

**Features**:
- Interactive confirmation prompts
- Safety backup before restore
- Backup integrity verification
- Automatic service restart
- Rollback capability

### Log Management

#### `logrotate.conf`
**Purpose**: Log rotation configuration for production logs

**Installation**:
```bash
sudo ./scripts/setup_logrotate.sh
```

**Features**:
- Daily log rotation
- Compressed log files
- Configurable retention periods
- Automatic log file reopening
- Separate retention for audit logs (365 days for compliance)

#### `setup_logrotate.sh`
**Purpose**: Install and configure log rotation

**Usage**:
```bash
sudo ./scripts/setup_logrotate.sh
```

**Features**:
- Automatic logrotate installation
- Log directory creation
- User/group setup
- Configuration file installation
- Cron job setup
- Initial log file creation

### Utility Scripts

#### `generate_keys.sh`
**Purpose**: Generate cryptographic keys for JWT, encryption, and webhook signatures

**Usage**:
```bash
./scripts/generate_keys.sh generate      # Generate all keys and display
./scripts/generate_keys.sh update        # Generate and update .env file
./scripts/generate_keys.sh jwt           # Generate JWT secret only
./scripts/generate_keys.sh encryption    # Generate encryption key only
./scripts/generate_keys.sh hmac          # Generate HMAC key only
./scripts/generate_keys.sh postgres      # Generate PostgreSQL password
```

**Features**:
- Cryptographically secure key generation
- JWT secret keys (64 bytes)
- Field encryption keys (32 bytes)
- Webhook HMAC keys (32 bytes)
- Automatic .env file update
- Backup of existing .env file

#### `cleanup.sh`
**Purpose**: Clean up temporary files, old logs, and Docker resources

**Usage**:
```bash
./scripts/cleanup.sh temp     # Clean temporary scan files
./scripts/cleanup.sh vault    # Clean old encrypted vault files
./scripts/cleanup.sh docker   # Clean Docker resources
./scripts/cleanup.sh logs     # Clean old log files
./scripts/cleanup.sh celery   # Clean Celery task results
./scripts/cleanup.sh system   # Run system cleanup
./scripts/cleanup.sh all      # Run all cleanup operations
./scripts/cleanup.sh status   # Show disk usage
```

**Features**:
- Temporary file cleanup (24-hour retention)
- Encrypted vault cleanup (365-day retention)
- Docker resource cleanup
- Log file cleanup (30-day retention)
- System package cache cleanup
- Disk usage reporting

#### `monitor.sh`
**Purpose**: Real-time monitoring and diagnostics

**Usage**:
```bash
./scripts/monitor.sh docker    # Monitor Docker containers
./scripts/monitor.sh resources # Monitor system resources
./scripts/monitor.sh app       # Monitor application metrics
./scripts/monitor.sh db        # Monitor database metrics
./scripts/monitor.sh redis     # Monitor Redis metrics
./scripts/monitor.sh celery    # Monitor Celery metrics
./scripts/monitor.sh errors    # Monitor recent errors
./scripts/monitor.sh network   # Monitor network metrics
./scripts/monitor.sh all       # Monitor all components

# Add --watch for continuous monitoring
./scripts/monitor.sh all --watch
```

**Features**:
- Real-time component monitoring
- System resource tracking
- Application health checks
- Database statistics
- Redis metrics
- Celery task monitoring
- Error log aggregation
- Continuous monitoring mode

## Script Permissions

All scripts should be made executable before use:

```bash
# Option 1: Make all scripts executable
chmod +x scripts/*.sh

# Option 2: Use the setup script
./scripts/setup_permissions.sh
```

## Environment Setup

Before running these scripts, ensure:

1. **Docker and Docker Compose are installed**
   ```bash
   docker --version
   docker-compose --version
   ```

2. **.env file is configured**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

3. **Cryptographic keys are generated**
   ```bash
   ./scripts/generate_keys.sh update
   ```

4. **SSL certificates are in place**
   ```bash
   # Place certificates in nginx/ssl/
   nginx/ssl/cert.pem
   nginx/ssl/key.pem
   ```

## Scheduled Tasks

### Daily Backup (Recommended)
Add to crontab for automated daily backups:
```bash
0 2 * * * /path/to/MediKiosk-Backend/scripts/backup.sh full
```

### Hourly Health Check
```bash
0 * * * * /path/to/MediKiosk-Backend/scripts/health_check.sh
```

### Weekly Cleanup
```bash
0 3 * * 0 /path/to/MediKiosk-Backend/scripts/cleanup.sh all
```

## Security Considerations

1. **Script Permissions**: Ensure scripts are owned by appropriate users and have correct permissions
2. **Environment Variables**: Never commit .env files or scripts containing secrets
3. **Backup Security**: Encrypt backups if storing in cloud storage
4. **Root Access**: Some scripts require root access - use sudo carefully
5. **Audit Logging**: All script executions should be logged for compliance

## Troubleshooting

### Script Permission Denied
```bash
chmod +x scripts/<script_name>.sh
```

### Docker Compose Not Found
```bash
# Install Docker Compose
sudo apt-get install docker-compose
```

### Python Not Available
```bash
# Install Python 3
sudo apt-get install python3 python3-pip
```

### Redis Connection Failed
```bash
# Check Redis status
docker-compose ps redis
docker-compose logs redis
```

## Maintenance

### Regular Updates
- Review and update scripts quarterly
- Test backup/restore procedures monthly
- Verify log rotation configuration
- Update retention policies as needed

### Documentation
- Keep this README updated with script changes
- Document any custom modifications
- Maintain change logs for critical updates

## Support

For issues or questions about these scripts:
1. Check the main README.md for system documentation
2. Review script-specific comments
3. Check system logs for error details
4. Contact the technical team for assistance

---

**Last Updated**: 2026-09-04  
**Version**: 1.0.0  
**Maintained By**: SIH26 MediTrack Team
