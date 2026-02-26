# Quick Start - Local Development Setup

## For Local Testing Before Production Deployment

### Prerequisites
- Docker and Docker Compose installed locally
- Git installed
- 4GB+ RAM available

### Local Development Setup

```bash
# Clone the repository
git clone https://github.com/marketcalls/openalgo.git
cd openalgo

# Copy sample environment
cp .sample.env .env

# Edit .env for local development
nano .env

# Set these for local testing:
HOST_SERVER=http://127.0.0.1:5000
FLASK_HOST_IP=127.0.0.1
FLASK_ENV=development
FLASK_DEBUG=True
BROKER_API_KEY=YOUR_DHAN_KEY
BROKER_API_SECRET=YOUR_DHAN_SECRET
```

### Build and Run Locally

```bash
# Build the image
docker compose build

# Start services
docker compose up -d

# Wait for startup (30-40 seconds)
sleep 40

# Check containers
docker compose ps

# View logs
docker compose logs -f openalgo
```

### Access Application

- **Web App**: http://127.0.0.1:5000
- **WebSocket**: ws://127.0.0.1:8765

### Stop Services

```bash
docker compose down
```

### Clean Up

```bash
# Remove all containers and volumes
docker compose down -v

# Clear Docker cache
docker system prune -a
```

---

## Testing Dhan API Connection

Before deploying to production, test your Dhan API credentials:

```bash
# Enter OpenAlgo container
docker compose exec openalgo bash

# Run test script
python -c "
import os
from dotenv import load_dotenv
load_dotenv()

broker_key = os.getenv('BROKER_API_KEY')
broker_secret = os.getenv('BROKER_API_SECRET')

if broker_key and broker_secret:
    print('✓ Credentials loaded successfully')
    print(f'  API Key: {broker_key[:10]}...')
else:
    print('✗ Credentials not found in .env')
"

exit
```

---

## Production Deployment on AWS Lightsail

### Step 1: Set Up AWS Lightsail Instance

1. Go to AWS Lightsail console
2. Create new instance:
   - OS: Ubuntu 20.04 LTS
   - Instance: Medium (2GB RAM, 50GB SSD)
   - Region: Closest to your location
   - Name: openalgo-prod

3. Note the Public IP address

### Step 2: Configure DNS

1. Go to your domain registrar
2. Create/Update A record:
   - Hostname: algo
   - Points to: Your Lightsail Public IP
   - TTL: 3600

3. Verify DNS: `nslookup algo.endoscopicspinehyderabad.in`

### Step 3: Deploy to Lightsail

```bash
# From your local machine, SSH into Lightsail
ssh -i path/to/lightsail.pem ubuntu@YOUR_LIGHTSAIL_IP

# Clone repository
git clone https://github.com/marketcalls/openalgo.git
cd openalgo

# Run deployment script
chmod +x deploy_lightsail.sh
./deploy_lightsail.sh algo.endoscopicspinehyderabad.in

# Wait 5-15 minutes for setup
```

### Step 4: Post-Deployment

```bash
# Connect via SSH to Lightsail
ssh -i path/to/lightsail.pem ubuntu@YOUR_LIGHTSAIL_IP

# Edit .env with real credentials
sudo nano /opt/openalgo/.env

# Update:
BROKER_API_KEY=YOUR_REAL_DHAN_KEY
BROKER_API_SECRET=YOUR_REAL_DHAN_SECRET
DB_PASSWORD=YOUR_SECURE_PASSWORD

# Restart services
sudo systemctl restart openalgo

# Verify
sudo /opt/openalgo/manage.sh status
```

### Step 5: Access Production

```bash
# Visit your domain
https://algo.endoscopicspinehyderabad.in
```

---

## Managing Production Deployment

### Daily Operations

```bash
# SSH into Lightsail
ssh -i lightsail.pem ubuntu@YOUR_IP

# Check status
/opt/openalgo/manage.sh status

# View logs
/opt/openalgo/manage.sh logs openalgo

# Create backup
/opt/openalgo/manage.sh backup

# Restart if needed
/opt/openalgo/manage.sh restart openalgo
```

### Updating OpenAlgo

```bash
# On Lightsail instance
cd /opt/openalgo

# Update code and containers
/opt/openalgo/manage.sh update

# Verify
/opt/openalgo/manage.sh status
```

### Monitoring

```bash
# Run health check
/opt/openalgo/monitor.sh

# Check SSL certificate expiration
echo | openssl s_client -connect algo.endoscopicspinehyderabad.in:443 2>/dev/null | \
    openssl x509 -noout -dates
```

---

## Troubleshooting

### "Certificate not found" Error

```bash
# Manually request certificate
cd /opt/openalgo
docker compose run --rm certbot certbot certonly \
    --webroot -w /var/www/certbot \
    --email your-email@example.com \
    --agree-tos \
    -d algo.endoscopicspinehyderabad.in

# Restart nginx
docker compose restart nginx
```

### "Connection refused" to Dhan API

```bash
# Verify credentials in .env
grep "BROKER_API" /opt/openalgo/.env

# Check OpenAlgo logs
docker compose logs openalgo | grep -i "dhan\|broker\|auth"
```

### "Database connection failed"

```bash
# Check PostgreSQL
/opt/openalgo/manage.sh psql

# Type: SELECT 1;  (should return 1)

# Verify credentials
grep "^DB_" /opt/openalgo/.env

# Restart database
docker compose restart postgres
```

### "Port 443 already in use"

```bash
# Find process using port 443
lsof -i :443

# Kill process or stop Nginx
docker compose stop nginx
docker compose up -d
```

---

## Environment Variables Reference

### Required for Trading
- `BROKER_API_KEY` - Dhan API key
- `BROKER_API_SECRET` - Dhan API secret
- `VALID_BROKERS` - Set to: dhan,dhan_sandbox

### Database
- `DB_USER` - PostgreSQL user
- `DB_PASSWORD` - PostgreSQL password (25+ chars, mixed case, numbers, symbols)
- `DB_NAME` - Database name

### Security
- `APP_KEY` - Application encryption key (generate with: python -c "import secrets; print(secrets.token_hex(32))")
- `API_KEY_PEPPER` - API key pepper (generate with: python -c "import secrets; print(secrets.token_hex(32))")

### Domain
- `CUSTOM_DOMAIN` - Your domain
- `HOST_SERVER` - https://your-domain.com
- `WEBSOCKET_URL` - wss://your-domain.com/ws

### Feature Flags
- `ENABLE_STRATEGY_WATCHDOG` - TRUE/FALSE (auto-restart failed strategies)
- `CORS_ENABLED` - TRUE/FALSE (allow cross-origin requests)
- `CSRF_ENABLED` - TRUE/FALSE (CSRF protection)

---

## Support

For issues or questions:

1. Check logs: `/opt/openalgo/manage.sh logs`
2. Review guide: See DEPLOYMENT_GUIDE.md
3. Check Dhan docs: https://dhan.co/docs
4. OpenAlgo docs: https://docs.openalgo.in

---

**Happy trading! 📊**
