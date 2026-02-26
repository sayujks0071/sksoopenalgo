#!/bin/bash

################################################################################
# OpenAlgo Production Deployment Script
# For AWS Lightsail with Custom Domain + Dhan API Trading
#
# Usage: ./deploy_lightsail.sh <your-domain.com>
# Example: ./deploy_lightsail.sh algo.endoscopicspinehyderabad.in
#
# Prerequisites:
# - Ubuntu 20.04 or 22.04 on AWS Lightsail
# - SSH access to the instance
# - Domain DNS already pointing to Lightsail IP
#
################################################################################

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
DOMAIN=${1:-algo.endoscopicspinehyderabad.in}
INSTALL_DIR="/opt/openalgo"
APP_USER="openalgo"
APP_GROUP="openalgo"
EMAIL="admin@${DOMAIN}"

# Functions
print_header() {
    echo -e "\n${BLUE}===============================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}===============================================${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
    exit 1
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# Check if domain argument provided
if [ -z "$1" ]; then
    print_error "Domain required. Usage: ./deploy_lightsail.sh <domain.com>"
fi

# ============================================================================
# STEP 1: System Updates and Prerequisites
# ============================================================================
print_header "Step 1: System Updates and Prerequisites"

echo "Updating package manager..."
apt-get update -qq
apt-get upgrade -y -qq

echo "Installing dependencies..."
apt-get install -y -qq \
    curl \
    wget \
    git \
    build-essential \
    python3-pip \
    python3-venv \
    certbot \
    openssl \
    jq \
    htop \
    lsof \
    net-tools

print_success "System dependencies installed"

# ============================================================================
# STEP 2: Install Docker and Docker Compose
# ============================================================================
print_header "Step 2: Installing Docker and Docker Compose"

if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    
    # Add Docker repository
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo bash get-docker.sh
    rm get-docker.sh
    
    # Start Docker daemon
    systemctl start docker
    systemctl enable docker
    
    print_success "Docker installed and enabled"
else
    print_success "Docker already installed"
fi

# Install Docker Compose plugin
if ! docker compose version &> /dev/null; then
    echo "Installing Docker Compose plugin..."
    apt-get install -y -qq docker-compose-plugin
    print_success "Docker Compose installed"
else
    print_success "Docker Compose already installed"
fi

# ============================================================================
# STEP 3: Create Application User and Directory Structure
# ============================================================================
print_header "Step 3: Setting Up Application User and Directories"

# Create application user if not exists
if ! id "$APP_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$APP_USER"
    print_success "Created user: $APP_USER"
else
    print_success "User $APP_USER already exists"
fi

# Add current user to docker group
usermod -aG docker "$APP_USER" || true

# Create installation directory
mkdir -p "$INSTALL_DIR"
chown -R "$APP_USER:$APP_GROUP" "$INSTALL_DIR"
print_success "Installation directory: $INSTALL_DIR"

# ============================================================================
# STEP 4: Clone or Update OpenAlgo Repository
# ============================================================================
print_header "Step 4: Cloning/Updating OpenAlgo Repository"

if [ -d "$INSTALL_DIR/.git" ]; then
    echo "Repository exists, pulling latest changes..."
    cd "$INSTALL_DIR"
    sudo -u "$APP_USER" git pull origin main || true
    print_success "Repository updated"
else
    echo "Cloning OpenAlgo repository..."
    cd /opt
    sudo -u "$APP_USER" git clone https://github.com/marketcalls/openalgo.git "$INSTALL_DIR"
    cd "$INSTALL_DIR"
    print_success "Repository cloned"
fi

# ============================================================================
# STEP 5: Create Directory Structure
# ============================================================================
print_header "Step 5: Creating Directory Structure"

sudo -u "$APP_USER" mkdir -p \
    "$INSTALL_DIR/nginx/conf.d" \
    "$INSTALL_DIR/ssl/certbot/conf" \
    "$INSTALL_DIR/ssl/certbot/www" \
    "$INSTALL_DIR/logs/nginx" \
    "$INSTALL_DIR/data/postgres" \
    "$INSTALL_DIR/strategies"

print_success "Directory structure created"

# ============================================================================
# STEP 6: Copy Configuration Files
# ============================================================================
print_header "Step 6: Setting Up Configuration Files"

# Copy docker-compose file
if [ ! -f "$INSTALL_DIR/docker-compose.yml" ]; then
    if [ -f "$INSTALL_DIR/docker-compose.prod.yml" ]; then
        sudo -u "$APP_USER" cp "$INSTALL_DIR/docker-compose.prod.yml" "$INSTALL_DIR/docker-compose.yml"
        print_success "Docker Compose configuration ready"
    else
        print_warning "docker-compose.prod.yml not found, will need to copy manually"
    fi
fi

# Create .env file from template
print_warning "Configuring environment variables..."

# Generate secure passwords
DB_PASSWORD=$(openssl rand -base64 32 | head -c 24)
APP_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
API_KEY_PEPPER=$(python3 -c "import secrets; print(secrets.token_hex(32))")

# Create .env file with configuration
cat > "$INSTALL_DIR/.env" <<EOF
# OpenAlgo Production Configuration
ENV_CONFIG_VERSION='1.0.6'

# Custom Domain
CUSTOM_DOMAIN=$DOMAIN
HOST_SERVER=https://$DOMAIN
WEBSOCKET_URL=wss://$DOMAIN/ws

# Dhan API (IMPORTANT: Update these with your actual credentials)
BROKER_API_KEY=CHANGE_ME_DHAN_API_KEY
BROKER_API_SECRET=CHANGE_ME_DHAN_API_SECRET
VALID_BROKERS=dhan,dhan_sandbox
REDIRECT_URL=https://$DOMAIN/dhan/callback

# Database
DB_NAME=openalgo_trading
DB_USER=openalgo
DB_PASSWORD=$DB_PASSWORD
DATABASE_URL=postgresql://openalgo:$DB_PASSWORD@postgres:5432/openalgo_trading
LATENCY_DATABASE_URL=sqlite:///db/latency.db
LOGS_DATABASE_URL=sqlite:///db/logs.db
SANDBOX_DATABASE_URL=sqlite:///db/sandbox.db
HISTORIFY_DATABASE_URL=db/historify.duckdb

# Security
APP_KEY=$APP_KEY
API_KEY_PEPPER=$API_KEY_PEPPER
CSRF_ENABLED=TRUE
CSP_ENABLED=TRUE

# Flask
FLASK_ENV=production
FLASK_DEBUG=False
FLASK_HOST_IP=0.0.0.0
FLASK_PORT=5000

# WebSocket
WEBSOCKET_HOST=0.0.0.0
WEBSOCKET_PORT=8765

# ZeroMQ
ZMQ_HOST=0.0.0.0
ZMQ_PORT=5555

# CORS
CORS_ENABLED=TRUE
CORS_ALLOWED_ORIGINS=https://$DOMAIN
CORS_ALLOWED_METHODS=GET,POST,DELETE,PUT,PATCH
CORS_ALLOWED_HEADERS=Content-Type,Authorization,X-Requested-With
CORS_ALLOW_CREDENTIALS=FALSE
CORS_MAX_AGE=86400

# Rate Limiting
LOGIN_RATE_LIMIT_MIN=5 per minute
LOGIN_RATE_LIMIT_HOUR=25 per hour
API_RATE_LIMIT=50 per second
ORDER_RATE_LIMIT=10 per second
SMART_ORDER_RATE_LIMIT=2 per second
WEBHOOK_RATE_LIMIT=100 per minute
STRATEGY_RATE_LIMIT=200 per minute
SMART_ORDER_DELAY=0.5

# Logging
LOG_TO_FILE=True
LOG_LEVEL=INFO
LOG_DIR=log
LOG_RETENTION=14

# Docker & Resources
APP_MODE=standalone
STRATEGY_MEMORY_LIMIT_MB=1024
OPENBLAS_NUM_THREADS=2
OMP_NUM_THREADS=2
MKL_NUM_THREADS=2
NUMEXPR_NUM_THREADS=2
NUMBA_NUM_THREADS=2

# Strategy
ENABLE_STRATEGY_WATCHDOG=TRUE
SESSION_EXPIRY_TIME=03:00
MASTER_CONTRACT_CUTOFF_TIME=08:00

# Timezone
TZ=Asia/Kolkata

# Ngrok (disabled in production)
NGROK_ALLOW=FALSE
EOF

chown "$APP_USER:$APP_GROUP" "$INSTALL_DIR/.env"
chmod 600 "$INSTALL_DIR/.env"

print_success ".env file created with secure passwords"
print_warning "IMPORTANT: Update these values in $INSTALL_DIR/.env:"
echo "  - BROKER_API_KEY (Dhan API key)"
echo "  - BROKER_API_SECRET (Dhan API secret)"

# ============================================================================
# STEP 7: Setup Nginx Configuration
# ============================================================================
print_header "Step 7: Configuring Nginx"

# Create nginx.conf
cat > "$INSTALL_DIR/nginx/nginx.conf" <<'NGINX_CONF'
user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log warn;
pid /var/run/nginx.pid;

events {
    worker_connections 2048;
    use epoll;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" "$http_x_forwarded_for"';

    access_log /var/log/nginx/access.log main;
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;
    client_max_body_size 100m;

    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_types text/plain text/css text/xml text/javascript 
               application/x-javascript application/xml+rss 
               application/rss+xml application/json;

    proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=openalgo_cache:10m max_size=100m inactive=60m;

    include /etc/nginx/conf.d/*.conf;
}
NGINX_CONF

chown -R "$APP_USER:$APP_GROUP" "$INSTALL_DIR/nginx"
print_success "Nginx base configuration created"

# ============================================================================
# STEP 8: Setup Nginx OpenAlgo Configuration
# ============================================================================
print_header "Step 8: Configuring Nginx for ${DOMAIN}"

cat > "$INSTALL_DIR/nginx/conf.d/openalgo.conf" <<NGINX_OPENALGO
# HTTP and Let's Encrypt validation
server {
    listen 80;
    server_name _;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location /health {
        access_log off;
        return 200 "healthy\n";
        add_header Content-Type text/plain;
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}

# HTTPS Configuration
server {
    listen 443 ssl http2;
    server_name $DOMAIN;

    ssl_certificate /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    access_log /var/log/nginx/openalgo_access.log main;
    error_log /var/log/nginx/openalgo_error.log warn;

    location / {
        proxy_pass http://openalgo:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
    }

    location /socket.io {
        proxy_pass http://openalgo:5000/socket.io;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "Upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 7d;
        proxy_send_timeout 7d;
        proxy_read_timeout 7d;
    }

    location /ws {
        proxy_pass ws://openalgo:8765;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "Upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 7d;
        proxy_send_timeout 7d;
        proxy_read_timeout 7d;
    }

    location /api/ {
        proxy_pass http://openalgo:5000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_cache openalgo_cache;
        proxy_cache_valid 200 5m;
        proxy_connect_timeout 30s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    location /static/ {
        proxy_pass http://openalgo:5000;
        proxy_cache openalgo_cache;
        proxy_cache_valid 200 1d;
        expires 1d;
    }

    location /assets/ {
        proxy_pass http://openalgo:5000;
        proxy_cache openalgo_cache;
        proxy_cache_valid 200 1d;
        expires 1d;
    }
}
NGINX_OPENALGO

chown "$APP_USER:$APP_GROUP" "$INSTALL_DIR/nginx/conf.d/openalgo.conf"
print_success "Nginx OpenAlgo configuration created for $DOMAIN"

# ============================================================================
# STEP 9: Request SSL Certificate with Let's Encrypt
# ============================================================================
print_header "Step 9: Setting Up SSL Certificate (Let's Encrypt)"

echo "Starting Docker services temporarily to setup SSL..."
cd "$INSTALL_DIR"

# Start only nginx temporarily for cert request
docker compose up -d nginx 2>/dev/null || {
    print_warning "Initial nginx startup may fail - that's OK, continuing with cert setup"
}

sleep 5

# Request certificate
echo "Requesting SSL certificate for $DOMAIN..."
docker compose run --rm certbot certbot certonly \
    --webroot -w /var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    --force-renewal \
    -d "$DOMAIN" || print_warning "Cert request completed (check status separately)"

sleep 3

# Kill temporary services
docker compose down 2>/dev/null || true

print_success "SSL certificate setup initiated for $DOMAIN"

# ============================================================================
# STEP 10: Start Full Docker Stack
# ============================================================================
print_header "Step 10: Starting OpenAlgo Docker Stack"

cd "$INSTALL_DIR"

echo "Building and starting all containers..."
docker compose build --no-cache openalgo 2>&1 | tail -20 || print_warning "Build may have warnings"

docker compose up -d --pull missing

sleep 10

# Check container status
if docker compose ps | grep -q "openalgo.*Up"; then
    print_success "OpenAlgo application started"
else
    print_warning "Checking container logs for errors..."
    docker compose logs openalgo | tail -50
fi

if docker compose ps | grep -q "nginx.*Up"; then
    print_success "Nginx reverse proxy started"
else
    print_error "Nginx failed to start - check logs: docker compose logs nginx"
fi

if docker compose ps | grep -q "postgres.*Up"; then
    print_success "PostgreSQL database started"
else
    print_error "PostgreSQL failed to start"
fi

# ============================================================================
# STEP 11: Create Systemd Service
# ============================================================================
print_header "Step 11: Setting Up Systemd Service for Auto-Start"

cat > /etc/systemd/system/openalgo.service <<SYSTEMD_SERVICE
[Unit]
Description=OpenAlgo Trading Platform
After=docker.service
Requires=docker.service

[Service]
Type=exec
WorkingDirectory=$INSTALL_DIR
User=$APP_USER
Group=docker

# Start command
ExecStart=/usr/bin/docker compose -f docker-compose.yml up --remove-orphans

# Stop command
ExecStop=/usr/bin/docker compose -f docker-compose.yml down

# Restart policy
Restart=unless-stopped
RestartSec=10

# Resource limits
LimitNOFILE=infinity
LimitNPROC=infinity

[Install]
WantedBy=multi-user.target
SYSTEMD_SERVICE

# Reload systemd daemon and enable service
systemctl daemon-reload
systemctl enable openalgo
print_success "Systemd service created and enabled"

# ============================================================================
# STEP 12: Setup Log Rotation
# ============================================================================
print_header "Step 12: Setting Up Log Rotation"

cat > /etc/logrotate.d/openalgo <<LOGROTATE_CONFIG
$INSTALL_DIR/logs/nginx/*.log {
    daily
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 nobody adm
    sharedscripts
    postrotate
        docker compose -f $INSTALL_DIR/docker-compose.yml exec -T nginx nginx -s reload > /dev/null 2>&1 || true
    endscript
}
LOGROTATE_CONFIG

print_success "Log rotation configured"

# ============================================================================
# STEP 13: Setup Monitoring and Alerts
# ============================================================================
print_header "Step 13: Creating Monitoring Script"

cat > "$INSTALL_DIR/monitor.sh" <<'MONITOR_SCRIPT'
#!/bin/bash

# OpenAlgo Health Monitor
DOMAIN=$1
DOMAIN=${DOMAIN:-algo.endoscopicspinehyderabad.in}
INSTALL_DIR="/opt/openalgo"

check_services() {
    cd "$INSTALL_DIR"
    
    echo "=== OpenAlgo Service Status ==="
    echo "Domain: $DOMAIN"
    echo "Timestamp: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""
    
    # Docker containers
    echo "Container Status:"
    docker compose ps | grep -E "openalgo|postgres|nginx|certbot"
    
    echo ""
    echo "Recent Errors (last 50 lines):"
    docker compose logs --tail=50 2>&1 | grep -i "error" | tail -5 || echo "No recent errors"
    
    echo ""
    echo "Web Service Health:"
    curl -s -I https://$DOMAIN 2>&1 | head -1 || echo "Unable to reach $DOMAIN"
    
    echo ""
    echo "Database Status:"
    docker compose exec -T postgres pg_isready -U openalgo 2>&1 || echo "Database unreachable"
}

check_services
MONITOR_SCRIPT

chmod +x "$INSTALL_DIR/monitor.sh"
chown "$APP_USER:$APP_GROUP" "$INSTALL_DIR/monitor.sh"
print_success "Monitoring script created: $INSTALL_DIR/monitor.sh"

# ============================================================================
# STEP 14: Firewall Configuration (AWS Lightsail)
# ============================================================================
print_header "Step 14: Firewall Configuration (Important!)"

print_warning "Configure AWS Lightsail Firewall:"
echo ""
echo "  ✓ Inbound Rules needed:"
echo "    - HTTP (80): Allow from Anywhere (for cert renewal)"
echo "    - HTTPS (443): Allow from Anywhere (for access)"
echo "    - SSH (22): Allow from your IP only"
echo ""
echo "  ✓ Outbound Rules:"
echo "    - Allow all"
echo ""
echo "  To update: Go to AWS Lightsail Console > Networking > Firewall"

# ============================================================================
# FINAL SUMMARY
# ============================================================================
print_header "DEPLOYMENT COMPLETE! 🎉"

echo "OpenAlgo Production Setup Summary:"
echo "=================================="
echo "Domain: https://$DOMAIN"
echo "Installation Directory: $INSTALL_DIR"
echo "Configuration File: $INSTALL_DIR/.env"
echo ""
echo "Important Next Steps:"
echo "1. Update API Credentials:"
echo "   nano $INSTALL_DIR/.env"
echo "   Set your Dhan API credentials:"
echo "     BROKER_API_KEY=YOUR_DHAN_KEY"
echo "     BROKER_API_SECRET=YOUR_DHAN_SECRET"
echo ""
echo "2. Restart OpenAlgo:"
echo "   sudo systemctl restart openalgo"
echo ""
echo "3. Monitor the application:"
echo "   sudo $INSTALL_DIR/monitor.sh"
echo ""
echo "4. View logs:"
echo "   cd $INSTALL_DIR"
echo "   docker compose logs -f openalgo    # App logs"
echo "   docker compose logs -f nginx       # Web server logs"
echo "   docker compose logs -f postgres    # Database logs"
echo ""
echo "5. Access the application:"
echo "   https://$DOMAIN"
echo ""
echo "Useful Commands:"
echo "=================="
echo "  docker compose ps                  # Check container status"
echo "  docker compose restart openalgo    # Restart app"
echo "  docker compose logs -f             # View all logs"
echo "  systemctl status openalgo          # Check systemd service"
echo "  $INSTALL_DIR/monitor.sh            # Run health check"
echo ""
print_success "Deployment script completed successfully!"
print_warning "Don't forget to update Dhan API credentials in .env file!"
