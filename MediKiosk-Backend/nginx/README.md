# SSL Certificates for Production

This directory contains SSL configuration for HTTPS termination.

## SSL Certificate Setup

Place your SSL certificates in the `ssl/` subdirectory:

- `ssl/cert.pem` - SSL certificate file
- `ssl/key.pem` - SSL private key file

## Certificate Setup

For production, use certificates from a trusted Certificate Authority (CA):

1. **Let's Encrypt (recommended for production):**
   ```bash
   certbot certonly --standalone -d your-domain.com
   # Copy certificates to this directory
   cp /etc/letsencrypt/live/your-domain.com/fullchain.pem ssl/cert.pem
   cp /etc/letsencrypt/live/your-domain.com/privkey.pem ssl/key.pem
   ```

2. **Self-signed certificates (development only):**
   ```bash
   openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
     -keyout ssl/key.pem -out ssl/cert.pem \
     -subj "/C=IN/ST=State/L=City/O=Organization/CN=localhost"
   ```

## Security Notes

- **Never commit real certificates** to version control
- **Never share private keys** (`ssl/key.pem`)
- Ensure certificates are properly permissioned (644 for cert.pem, 600 for key.pem)
- Use strong ciphers and TLS 1.2+ as configured in nginx.conf
- Certificate rotation should be part of your maintenance schedule

## DPDP Act 2023 Compliance

- All data in transit must be encrypted (HTTPS enforced)
- Certificates must be from trusted CAs for production
- Regular certificate rotation is required for compliance
