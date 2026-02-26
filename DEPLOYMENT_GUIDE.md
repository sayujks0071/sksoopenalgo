# OpenAlgo + Dhan API Production Deployment Guide
# AWS Lightsail with Custom Domain & SSL

## Overview

This guide sets up a production-ready OpenAlgo trading platform on AWS Lightsail with:
- **Custom Domain**: algo.endoscopicspinehyderabad.in
- **SSL/TLS**: Let's Encrypt (automatic renewal)
- **Dhan API Integration**: Live trading with Dhan broker
- **Database**: PostgreSQL for persistent data
- **Reverse Proxy**: Nginx with caching
- **WebSocket**: Real-time trading updates
- **Auto-restart**: Systemd integration for reliability

---

## Prerequisites

1. **AWS Lightsail Instance**
   - OS: Ubuntu 20.04 or 22.04
   - RAM: Minimum 2GB (4GB+ recommended)
   - Storage: Minimum 20GB
   - Network: Port 80, 443 open

2. **Domain Setup**
   - Custom domain already registered
   - DNS A record pointing to Lightsail IP address
   - Verify DNS is working: `nslookup algo.endoscopicspinehyderabad.in`

3. **Dhan API Credentials**
   - Dhan API Key
   - Dhan API Secret
   - Available at: https://dhan.co/developers

4. **Local Machine**
   - SSH client (for connecting to Lightsail)
   - Git (for cloning repository)

---

## Deployment Steps

### Step 1: Connect to AWS Lightsail Instance

```bash
# Download your SSH key from AWS Console
chmod 400 path/to/your/key.pem

# SSH into instance (replace IP with your Lightsail IP)
ssh -i path/to/your/key.pem ubuntu@YOUR_LIGHTSAIL_IP

# Switch to root for easier setup (optional)
sudo -i
```

### Step 2: Clone Repository

```bash
# On your Lightsail instance:
cd /home/ubuntu
git clone https://github.com/marketcalls/openalgo.git
cd openalgo
```

### Step 3: Run Deployment Script

```bash
# Make script executable
chmod +x deploy_lightsail.sh

# Run deployment (replace with your actual domain)
./deploy_lightsail.sh algo.endoscopicspinehyderabad.in
```

This script will:
- Install Docker and Docker Compose
- Create application user and directories
- Set up Nginx configuration
- Request SSL certificate from Let's Encrypt
- Start all containers
- Create systemd service for auto-start

**Deployment takes 5-15 minutes depending on your internet speed.**

### Step 4: Update Environment Variables

The script creates a `.env` file with default values. **You MUST update it with your credentials:**

```bash
# Edit .env file
nano /opt/openalgo/.env

# Update these critical values:
BROKER_API_KEY=YOUR_ACTUAL_DHAN_API_KEY
BROKER_API_SECRET=YOUR_ACTUAL_DHAN_API_SECRET
DB_PASSWORD=CHANGE_TO_STRONG_PASSWORD
```

**⚠️ IMPORTANT**: These credentials should be kept secret. Never commit `.env` to git.

### Step 5: Restart Services

```bash
# Restart OpenAlgo with new configuration
sudo systemctl restart openalgo

# Wait 30 seconds for services to start
sleep 30

# Check status
sudo systemctl status openalgo
```

### Step 6: Verify SSL Certificate

```bash
# Check if certificate was issued successfully
sudo ls -la /opt/openalgo/ssl/certbot/conf/live/algo.endoscopicspinehyderabad.in/

# You should see: fullchain.pem, privkey.pem, etc.
```

### Step 7: Test the Application

```bash
# From local machine:
curl -I https://algo.endoscopicspinehyderabad.in

# You should see: HTTP/2 200 or HTTP/1.1 200
# Check headers include: Strict-Transport-Security
```

---

## Accessing the Application

1. **Web Application**
   - URL: `https://algo.endoscopicspinehyderabad.in`
   - Login with your credentials

2. **Configure Dhan Broker**
   - Settings → Broker Configuration
   - Select "Dhan" broker
   - Complete authentication flow

3. **Start Trading**
   - Create/upload strategies
   - Configure symbols and parameters
   - Start strategy execution

---

## Daily Management

### Check Status

```bash
# Simple status check
/opt/openalgo/manage.sh status

# Detailed health check
/opt/openalgo/manage.sh health

# Or use the monitor script
/opt/openalgo/monitor.sh
```

### View Logs

```bash
# Application logs
/opt/openalgo/manage.sh logs openalgo

# Nginx logs
/opt/openalgo/manage.sh logs nginx

# Database logs
/opt/openalgo/manage.sh logs postgres

# Combined logs (last 100 lines)
/opt/openalgo/manage.sh logs
```

### Restart Services

```bash
# Restart all services
/opt/openalgo/manage.sh restart

# Restart specific service
/opt/openalgo/manage.sh restart openalgo
/opt/openalgo/manage.sh restart nginx
/opt/openalgo/manage.sh restart postgres
```

### Backup Data

```bash
# Create backup
/opt/openalgo/manage.sh backup

# Backup location: /opt/openalgo/backups/YYYYMMDD_HHMMSS/

# Includes:
# - Database dump
# - Strategies
# - Configuration
```

### Restore from Backup

```bash
# List available backups
ls -la /opt/openalgo/backups/

# Restore specific backup
/opt/openalgo/manage.sh restore /opt/openalgo/backups/20240115_143022
```

---

## Firewall Configuration (AWS Lightsail)

Important: Configure your Lightsail firewall for security.

1. **Go to AWS Lightsail Console**
2. **Select your instance**
3. **Click "Networking" tab**
4. **Configure Firewall Rules:**

| Rule | Protocol | Port | Source | Action |
|------|----------|------|--------|--------|
| HTTP | TCP | 80 | Anywhere | Allow |
| HTTPS | TCP | 443 | Anywhere | Allow |
| SSH | TCP | 22 | Your IP only | Allow |
| All Others | - | - | - | Deny |

**Note:** Keep port 80 open for Let's Encrypt certificate renewal.

---

## SSL Certificate Management

### Automatic Renewal

The Certbot container automatically renews certificates 30 days before expiration.

```bash
# Check certificate expiration
echo | openssl s_client -connect algo.endoscopicspinehyderabad.in:443 2>/dev/null | \
    openssl x509 -noout -dates
```

### Manual Certificate Renewal

```bash
cd /opt/openalgo

# Trigger certificate renewal
docker compose run --rm certbot certbot renew --force-renewal

# Restart Nginx to load new certificate
docker compose restart nginx
```

---

## Troubleshooting

### Application Not Accessible

```bash
# 1. Check containers are running
/opt/openalgo/manage.sh status

# 2. Check logs for errors
/opt/openalgo/manage.sh logs openalgo

# 3. Test DNS resolution
nslookup algo.endoscopicspinehyderabad.in

# 4. Check certificate
curl -vI https://algo.endoscopicspinehyderabad.in
```

### Certificate Issues

```bash
# Check certificate status
sudo certbot certificates --config-dir /opt/openalgo/ssl/certbot/conf

# View Let's Encrypt logs
cat /var/log/letsencrypt/letsencrypt.log | tail -50

# Manually request new certificate
cd /opt/openalgo
docker compose down
docker compose run --rm certbot certbot certonly \
    --webroot -w /var/www/certbot \
    --email admin@algo.endoscopicspinehyderabad.in \
    --agree-tos \
    --force-renewal \
    -d algo.endoscopicspinehyderabad.in
docker compose up -d
```

### Database Connection Errors

```bash
# Check PostgreSQL health
/opt/openalgo/manage.sh psql

# Run: SELECT 1;  (if you see "1", database is working)

# If not working, restart database
/opt/openalgo/manage.sh restart postgres

# Check database credentials in .env
cat /opt/openalgo/.env | grep "^DB_"
```

### High Memory Usage

```bash
# Check memory usage per container
docker stats

# If OpenAlgo using too much memory:
# 1. Edit .env: STRATEGY_MEMORY_LIMIT_MB=512 (reduce from 1024)
# 2. Restart: /opt/openalgo/manage.sh restart openalgo
```

### WebSocket Not Connecting

```bash
# Check WebSocket logs
/opt/openalgo/manage.sh logs openalgo | grep -i websocket

# Test WebSocket endpoint
wscat -c wss://algo.endoscopicspinehyderabad.in/socket.io
```

---

## Performance Optimization

### Increase Container Resources

Edit `/opt/openalgo/docker-compose.yml`:

```yaml
services:
  openalgo:
    # Add resource limits:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
        reservations:
          cpus: '1'
          memory: 2G
```

Restart: `systemctl restart openalgo`

### Enable Nginx Caching

Already enabled! Caches API responses for 5 minutes:
- View cache stats: `docker compose exec nginx redis-cli info`

### Database Optimization

```bash
# Connect to database
/opt/openalgo/manage.sh psql

# Run optimization (inside psql):
VACUUM ANALYZE;
```

---

## Security Checklist

- ✅ SSL/TLS enabled (HTTPS)
- ✅ Firewall configured (ports 80, 443 only)
- ✅ SSH key-based authentication only
- ✅ `.env` file protected (600 permissions)
- ✅ Database password strong (25+ chars)
- ✅ CSRF protection enabled
- ✅ Security headers configured
- ✅ Rate limiting active
- ✅ Logs rotated (14-day retention)

**Additional recommendations:**
- Enable MFA on AWS account
- Monitor logs regularly
- Keep system packages updated: `apt-get update && apt-get upgrade`
- Backup regularly: `weekly with /opt/openalgo/manage.sh backup`

---

## Useful Commands Reference

```bash
# Container Management
docker compose ps                    # List containers
docker compose logs -f openalgo      # Follow app logs
docker compose restart openalgo      # Restart app
docker compose down                  # Stop all services

# Using management script
/opt/openalgo/manage.sh status       # Show status
/opt/openalgo/manage.sh health       # Health check
/opt/openalgo/manage.sh backup       # Create backup
/opt/openalgo/manage.sh logs         # View logs

# System Management
sudo systemctl status openalgo       # Systemd status
sudo systemctl restart openalgo      # Systemd restart
sudo systemctl stop openalgo         # Stop systemd service
journalctl -u openalgo -f            # Follow systemd logs

# Database
/opt/openalgo/manage.sh psql         # Connect to database
psql -U openalgo -d openalgo_trading # Direct connection

# File Management
tail -f /opt/openalgo/logs/nginx/openalgo_access.log     # Nginx access logs
tail -f /opt/openalgo/logs/nginx/openalgo_error.log      # Nginx errors
tail -f /opt/openalgo/logs/app.log                       # App logs
```

---

## Support and Resources

- **OpenAlgo Docs**: https://docs.openalgo.in
- **Dhan API Docs**: https://dhan.co/docs
- **GitHub Repository**: https://github.com/marketcalls/openalgo
- **Docker Documentation**: https://docs.docker.com

---

## Next Steps

1. ✅ Deploy OpenAlgo on Lightsail
2. ✅ Configure Dhan broker integration
3. ✅ Create and test trading strategies
4. ✅ Set up alerts and monitoring
5. ✅ Monitor performance and optimize

**Enjoy hassle-free algorithmic trading! 📈**
