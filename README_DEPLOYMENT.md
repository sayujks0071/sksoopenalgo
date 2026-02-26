# OpenAlgo + Dhan API Production Deployment - Complete Setup

## 📋 Index of Files

### Main Deployment Files
- **`deploy_lightsail.sh`** - Automated deployment script (execute this first)
- **`docker-compose.prod.yml`** - Production Docker configuration
- **`.env.production`** - Environment variables template

### Management Tools
- **`manage.sh`** - Daily operations and management
- **`check_production_readiness.sh`** - Pre-deployment verification
- **`nginx/`** - Nginx reverse proxy configuration

### Documentation
- **`DEPLOYMENT_GUIDE.md`** - Complete step-by-step guide
- **`QUICK_START.md`** - Quick reference for local development
- **`PRODUCTION_CHECKLIST.md`** - Security and readiness checklist
- **`README.md`** - This file (overview)

---

## 🚀 Quick Start

### Local Development (Mac/Linux/Windows)

```bash
# 1. Clone repository
git clone https://github.com/marketcalls/openalgo.git
cd openalgo

# 2. Copy environment template
cp .sample.env .env

# 3. Build and start locally
docker compose build
docker compose up -d

# 4. Access application
# Web: http://127.0.0.1:5000
# WebSocket: ws://127.0.0.1:8765

# 5. Stop services
docker compose down
```

See `QUICK_START.md` for detailed local development setup.

---

### AWS Lightsail Deployment (Production)

```bash
# 1. SSH into Lightsail instance
ssh -i your-key.pem ubuntu@YOUR_LIGHTSAIL_IP

# 2. Clone repository
git clone https://github.com/marketcalls/openalgo.git
cd openalgo

# 3. Run deployment script
chmod +x deploy_lightsail.sh
./deploy_lightsail.sh algo.endoscopicspinehyderabad.in

# 4. Update credentials
sudo nano /opt/openalgo/.env
# Edit: BROKER_API_KEY, BROKER_API_SECRET, DB_PASSWORD

# 5. Restart services
sudo systemctl restart openalgo

# 6. Verify
/opt/openalgo/monitor.sh
# Access: https://algo.endoscopicspinehyderabad.in
```

See `DEPLOYMENT_GUIDE.md` for detailed production setup.

---

## 📊 Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                 AWS Lightsail Instance              │
│                                                     │
│  ┌────────────────────────────────────────────┐   │
│  │          Docker Containers                 │   │
│  │                                            │   │
│  │  ┌──────────┐  ┌──────────────────────┐   │   │
│  │  │  Nginx   │  │  OpenAlgo Flask App  │   │   │
│  │  │  Port 80 │  │  Port 5000           │   │   │
│  │  │  443     │  │  WebSocket: 8765     │   │   │
│  │  └──────────┘  └──────────────────────┘   │   │
│  │       ↓                    ↓               │   │
│  │  ┌────────────────────────────────┐       │   │
│  │  │    PostgreSQL Database         │       │   │
│  │  │    (Trading Data Storage)      │       │   │
│  │  └────────────────────────────────┘       │   │
│  │       ↓                                    │   │
│  │  ┌────────────────────────────────┐       │   │
│  │  │  Certbot (SSL Certificate)     │       │   │
│  │  │  Auto-renewal Every 60 Days    │       │   │
│  │  └────────────────────────────────┘       │   │
│  └────────────────────────────────────────────┘   │
│                        ↓                           │
│  ┌────────────────────────────────────────────┐   │
│  │  Persistent Volumes (Data Storage)        │   │
│  │  • Database files                         │   │
│  │  • Strategy codes                         │   │
│  │  • Application logs                       │   │
│  │  • API keys & certificates                │   │
│  └────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
                        ↑
                   Custom Domain
              algo.endoscopicspinehyderabad.in
                   (HTTPS/SSL)
                        ↓
              ┌──────────────────┐
              │  Dhan API        │
              │  (Live Trading)  │
              └──────────────────┘
```

---

## 🔐 Security Features

✅ **HTTPS/SSL/TLS**
- Let's Encrypt certificates (free, auto-renewing)
- HTTP automatically redirects to HTTPS
- TLS 1.2 and 1.3 only

✅ **Application Security**
- CSRF protection enabled
- Content Security Policy headers
- Secure session cookies
- API rate limiting
- Input validation

✅ **Infrastructure Security**
- Firewall rules (SSH restricted to your IP)
- Container isolation (no direct DB access)
- Environment variables encrypted
- Systemd service with auto-restart

✅ **Data Protection**
- PostgreSQL with strong passwords
- Automated backups
- Persistent volumes for data retention
- Log rotation and retention policies

---

## 📈 Performance Features

✅ **Caching**
- Nginx reverse proxy caching (5-min API, 1-day static)
- Browser caching for static assets
- Database connection pooling

✅ **WebSocket Support**
- Real-time trading updates
- Connection pooling for multiple symbols
- Automatic reconnection handling

✅ **Resource Optimization**
- NumPy/SciPy thread limits (prevents exhaustion)
- Memory limits per strategy
- Shared memory for numerical operations
- Automatic log rotation

---

## 🛠 Operational Tools

### Daily Management

```bash
# Status check
/opt/openalgo/manage.sh status

# View logs
/opt/openalgo/manage.sh logs openalgo
/opt/openalgo/manage.sh logs nginx

# Restart services
/opt/openalgo/manage.sh restart

# Health check
/opt/openalgo/monitor.sh

# Create backup
/opt/openalgo/manage.sh backup

# Restore from backup
/opt/openalgo/manage.sh restore /path/to/backup
```

### Monitoring

```bash
# Check production readiness
./check_production_readiness.sh

# Monitor running processes
docker stats

# Check certificate expiration
echo | openssl s_client -connect algo.endoscopicspinehyderabad.in:443 2>/dev/null | \
    openssl x509 -noout -dates
```

---

## 📋 Pre-Deployment Checklist

Before running the deployment script:

- [ ] AWS Lightsail instance is running (Ubuntu 20.04 or 22.04)
- [ ] SSH access verified (`ssh -i key.pem ubuntu@IP` works)
- [ ] Domain registered and DNS A record created
- [ ] DNS propagation verified (`nslookup algo.endoscopicspinehyderabad.in`)
- [ ] Lightsail instance has 2GB+ RAM and 20GB+ storage
- [ ] Dhan API credentials obtained (API Key + Secret)
- [ ] Port 80 and 443 allowed in Lightsail firewall

---

## 📝 Post-Deployment Checklist

After deployment:

- [ ] SSL certificate obtained (check: `https://algo.endoscopicspinehyderabad.in`)
- [ ] `.env` file updated with Dhan credentials
- [ ] Services restarted (`sudo systemctl restart openalgo`)
- [ ] Health check passed (`/opt/openalgo/monitor.sh`)
- [ ] Application accessible (`https://algo.endoscopicspinehyderabad.in`)
- [ ] Dhan broker configured in settings
- [ ] First trading strategy created and tested
- [ ] Backup system verified (`/opt/openalgo/manage.sh backup`)

---

## 🐛 Troubleshooting

### Common Issues

**Site not accessible**
```bash
# Check DNS
nslookup algo.endoscopicspinehyderabad.in

# Check containers
docker compose ps

# View logs
/opt/openalgo/manage.sh logs
```

**Certificate errors**
```bash
# View certificate
echo | openssl s_client -connect algo.endoscopicspinehyderabad.in:443 2>/dev/null | \
    openssl x509 -noout -dates

# Manual renewal
cd /opt/openalgo && docker compose run --rm certbot \
    certbot certonly --webroot -w /var/www/certbot \
    -d algo.endoscopicspinehyderabad.in
```

**Database issues**
```bash
# Test connection
/opt/openalgo/manage.sh psql
SELECT 1;

# Restart database
/opt/openalgo/manage.sh restart postgres
```

See `DEPLOYMENT_GUIDE.md` for more troubleshooting.

---

## 📚 Documentation Map

| Document | Purpose |
|----------|---------|
| `DEPLOYMENT_GUIDE.md` | Complete deployment & operations guide |
| `QUICK_START.md` | Quick reference for local setup |
| `PRODUCTION_CHECKLIST.md` | Security & readiness checklist |
| `README.md` | This file (overview) |

---

## 🎯 Key URLs

After deployment:

| Service | URL |
|---------|-----|
| Web App | https://algo.endoscopicspinehyderabad.in |
| WebSocket | wss://algo.endoscopicspinehyderabad.in/ws |
| Dhan API | https://dhan.co/docs |
| OpenAlgo Docs | https://docs.openalgo.in |

---

## 💡 Tips & Best Practices

### Security
- Keep `.env` file permissions at 600
- Use strong passwords (25+ characters, mixed case)
- Rotate secrets every 90 days
- Monitor logs regularly
- Backup data weekly

### Performance
- Monitor memory usage: `docker stats`
- Check database performance weekly
- Review and archive old logs
- Monitor WebSocket connections
- Test during low-traffic hours

### Operations
- Check health daily: `/opt/openalgo/monitor.sh`
- Backup before updates
- Test backups monthly
- Keep Docker images updated
- Monitor certificate expiration

---

## 🚨 Emergency Procedures

### Service Down
```bash
# 1. Check status
/opt/openalgo/manage.sh status

# 2. Restart services
/opt/openalgo/manage.sh restart

# 3. Check logs
/opt/openalgo/manage.sh logs

# 4. Restore from backup if needed
/opt/openalgo/manage.sh restore /opt/openalgo/backups/LATEST
```

### Data Loss
```bash
# 1. Stop services
docker compose down

# 2. Restore from backup
/opt/openalgo/manage.sh restore /opt/openalgo/backups/YYYY-MM-DD

# 3. Restart services
docker compose up -d
```

### Certificate Expired
```bash
# 1. Stop services
docker compose down

# 2. Renew certificate manually
docker compose run --rm certbot certbot certonly \
    --webroot -w /var/www/certbot --force-renewal \
    -d algo.endoscopicspinehyderabad.in

# 3. Restart services
docker compose up -d
```

---

## 📞 Support Resources

- **GitHub Issues**: https://github.com/marketcalls/openalgo/issues
- **OpenAlgo Docs**: https://docs.openalgo.in
- **Dhan API Support**: https://dhan.co/support
- **Docker Support**: https://docs.docker.com
- **Let's Encrypt Help**: https://letsencrypt.org/docs/

---

## 📦 Technology Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Application | Python Flask | 3.12 |
| Database | PostgreSQL | 15 |
| Web Server | Nginx | Latest Alpine |
| SSL/TLS | Let's Encrypt | Automatic |
| Container | Docker | Latest |
| Orchestration | Docker Compose | Latest |

---

## 📊 System Requirements

### AWS Lightsail Instance
- **Minimum**: 2GB RAM, 20GB Storage
- **Recommended**: 4GB RAM, 50GB Storage
- **Optimal**: 8GB RAM, 100GB Storage

### Network
- Port 80 (HTTP) - for cert renewal
- Port 443 (HTTPS) - for web access
- Port 22 (SSH) - for management

### Domain
- Custom domain registered
- DNS A record pointing to Lightsail IP
- DNS propagation complete

---

## 🎓 Learning Resources

- **Docker**: https://docker.com/products/docker-desktop
- **OpenAlgo**: https://github.com/marketcalls/openalgo
- **Dhan**: https://dhan.co
- **Trading**: https://docs.openalgo.in/strategies

---

## ✅ Success Criteria

Your deployment is successful when:
1. ✅ Application accessible at `https://algo.endoscopicspinehyderabad.in`
2. ✅ SSL certificate valid (browser shows 🔒)
3. ✅ All containers running (`docker compose ps`)
4. ✅ Database healthy (`/opt/openalgo/manage.sh psql`)
5. ✅ Dhan broker configured and authenticated
6. ✅ First strategy created and running
7. ✅ Backup system operational (`/opt/openalgo/manage.sh backup`)

---

## 📝 Notes

- Keep this directory and `.env` file secure
- Backup `.env` file separately from application
- Never share API keys or passwords
- Monitor system resources regularly
- Test backup/restore procedures monthly
- Keep documentation updated

---

**Your production-ready OpenAlgo trading platform is configured and ready to deploy! 🚀**

Start with: `./deploy_lightsail.sh algo.endoscopicspinehyderabad.in`

For questions, refer to the guide files or check the resources above.
