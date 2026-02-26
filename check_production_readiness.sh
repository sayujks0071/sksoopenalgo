#!/bin/bash

# OpenAlgo Production Readiness Checklist
# Run this script to verify your production setup is ready

set -e

INSTALL_DIR=${1:-.}
DOMAIN=${2:-}
ISSUES=0
WARNINGS=0
COMPOSE_FILE=""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_header() {
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}\n"
}

check_pass() {
    echo -e "${GREEN}✓ PASS${NC}: $1"
}

check_fail() {
    echo -e "${RED}✗ FAIL${NC}: $1"
    ((ISSUES++))
}

check_warn() {
    echo -e "${YELLOW}⚠ WARN${NC}: $1"
    ((WARNINGS++))
}

read_env_value() {
    local file="$1"
    local key="$2"
    grep -E "^[[:space:]]*${key}[[:space:]]*=" "$file" 2>/dev/null | tail -1 | \
        sed -E "s/^[^=]*=[[:space:]]*//; s/^['\"]//; s/['\"]$//"
}

if [ -f "$INSTALL_DIR/docker-compose.yml" ]; then
    COMPOSE_FILE="$INSTALL_DIR/docker-compose.yml"
elif [ -f "$INSTALL_DIR/docker-compose.prod.yml" ]; then
    COMPOSE_FILE="$INSTALL_DIR/docker-compose.prod.yml"
fi

if [ -z "$DOMAIN" ]; then
    for ENV_FILE in "$INSTALL_DIR/.env" "$INSTALL_DIR/.env.production"; do
        if [ -f "$ENV_FILE" ]; then
            DOMAIN=$(read_env_value "$ENV_FILE" "CUSTOM_DOMAIN")
            if [ -n "$DOMAIN" ]; then
                break
            fi
            HOST_SERVER=$(read_env_value "$ENV_FILE" "HOST_SERVER")
            if [ -n "$HOST_SERVER" ]; then
                DOMAIN=$(echo "$HOST_SERVER" | sed -E 's#^https?://##; s#/.*$##')
                break
            fi
        fi
    done
fi

if [ -z "$DOMAIN" ]; then
    DOMAIN="algo.endoscopicspinehyderabad.in"
fi

compose() {
    docker compose -f "$COMPOSE_FILE" "$@"
}

# ============================================================================
# DOCKER SETUP CHECKS
# ============================================================================
print_header "Docker Setup"

# Check Docker installation
if command -v docker &> /dev/null; then
    check_pass "Docker is installed"
else
    check_fail "Docker is not installed"
fi

# Check Docker Compose
if docker compose version &> /dev/null; then
    check_pass "Docker Compose is installed"
else
    check_fail "Docker Compose is not installed"
fi

# Check Docker daemon
if docker ps &> /dev/null; then
    check_pass "Docker daemon is running"
else
    check_fail "Docker daemon is not running"
fi

# ============================================================================
# APPLICATION FILES
# ============================================================================
print_header "Application Files"

# Check docker compose file
if [ -n "$COMPOSE_FILE" ]; then
    check_pass "Compose file exists: $(basename "$COMPOSE_FILE")"
else
    check_fail "No compose file found (expected docker-compose.yml or docker-compose.prod.yml)"
fi

# Check Dockerfile
if [ -f "$INSTALL_DIR/openalgo/Dockerfile" ]; then
    check_pass "Dockerfile exists"
else
    check_fail "Dockerfile not found"
fi

# Check .env file
if [ -f "$INSTALL_DIR/.env" ]; then
    check_pass ".env configuration file exists"
    
    # Check critical .env variables
    if grep -q "BROKER_API_KEY" "$INSTALL_DIR/.env"; then
        if grep -q "BROKER_API_KEY=CHANGE_ME" "$INSTALL_DIR/.env" || \
           grep -q "BROKER_API_KEY=YOUR" "$INSTALL_DIR/.env"; then
            check_warn ".env has default BROKER_API_KEY - update with real credentials"
        else
            check_pass ".env has BROKER_API_KEY set"
        fi
    else
        check_warn ".env missing BROKER_API_KEY"
    fi
    
    if grep -q "DB_PASSWORD" "$INSTALL_DIR/.env"; then
        if grep -q "DB_PASSWORD=CHANGE" "$INSTALL_DIR/.env" || \
           grep -q "DB_PASSWORD=change_me" "$INSTALL_DIR/.env"; then
            check_warn ".env has default DB_PASSWORD - change to strong password"
        else
            check_pass ".env has DB_PASSWORD set"
        fi
    fi
else
    check_fail ".env file not found - copy from .env.production or .sample.env"
fi

# ============================================================================
# NGINX CONFIGURATION
# ============================================================================
print_header "Nginx Configuration"

if [ -f "$INSTALL_DIR/nginx/nginx.conf" ]; then
    check_pass "nginx.conf exists"
else
    check_warn "nginx.conf not found"
fi

if [ -f "$INSTALL_DIR/nginx/conf.d/openalgo.conf" ]; then
    check_pass "OpenAlgo Nginx config exists"
    
    # Check if domain is in config
    if grep -q "server_name.*$DOMAIN" "$INSTALL_DIR/nginx/conf.d/openalgo.conf"; then
        check_pass "Domain $DOMAIN configured in Nginx"
    else
        check_warn "Domain $DOMAIN not found in Nginx config - update conf.d/openalgo.conf"
    fi
else
    check_warn "conf.d/openalgo.conf not found"
fi

# ============================================================================
# SSL CERTIFICATE
# ============================================================================
print_header "SSL/TLS Configuration"

CERT_PATH="$INSTALL_DIR/ssl/certbot/conf/live/$DOMAIN"

if [ -f "$CERT_PATH/fullchain.pem" ] && [ -f "$CERT_PATH/privkey.pem" ]; then
    check_pass "SSL certificates found for $DOMAIN"
    
    # Check certificate expiration
    EXPIRY=$(openssl x509 -enddate -noout -in "$CERT_PATH/fullchain.pem" 2>/dev/null | cut -d= -f2)
    EXPIRY_EPOCH=$(date -d "$EXPIRY" +%s 2>/dev/null || date -jf "%b %d %T %Z %Y" "$EXPIRY" +%s 2>/dev/null)
    NOW_EPOCH=$(date +%s)
    DAYS_UNTIL=$((($EXPIRY_EPOCH - $NOW_EPOCH) / 86400))
    
    if [ "$DAYS_UNTIL" -lt 0 ]; then
        check_fail "SSL certificate expired!"
    elif [ "$DAYS_UNTIL" -lt 7 ]; then
        check_warn "SSL certificate expires in $DAYS_UNTIL days - renewal needed soon"
    else
        check_pass "SSL certificate valid for $DAYS_UNTIL days"
    fi
else
    check_fail "SSL certificates not found - run Let's Encrypt setup"
fi

# ============================================================================
# CONTAINER STATUS
# ============================================================================
print_header "Container Status"

if [ -n "$COMPOSE_FILE" ] && cd "$INSTALL_DIR" 2>/dev/null; then
    # Check if containers exist
    CONTAINERS=$(compose ps --quiet 2>/dev/null | wc -l)
    
    if [ "$CONTAINERS" -gt 0 ]; then
        check_pass "$CONTAINERS containers found"
        
        # Check specific containers
        for SERVICE in openalgo postgres nginx; do
            if compose ps --services --filter "status=running" 2>/dev/null | grep -q "$SERVICE"; then
                check_pass "Container '$SERVICE' is running"
            elif compose ps --services 2>/dev/null | grep -q "$SERVICE"; then
                check_warn "Container '$SERVICE' is not running"
            fi
        done
    else
        check_warn "No containers running - start with: docker compose -f $(basename "$COMPOSE_FILE") up -d"
    fi
else
    check_warn "Cannot access compose file directory"
fi

# ============================================================================
# DATABASE CHECK
# ============================================================================
print_header "Database"

if [ -n "$COMPOSE_FILE" ] && cd "$INSTALL_DIR" 2>/dev/null && compose ps | grep -q "postgres"; then
    if compose exec -T postgres pg_isready -U openalgo &>/dev/null; then
        check_pass "PostgreSQL database is healthy"
        
        # Check if openalgo_trading database exists
        if compose exec -T postgres psql -U openalgo -d openalgo_trading -c "SELECT 1" &>/dev/null; then
            check_pass "Database 'openalgo_trading' exists"
        else
            check_warn "Database 'openalgo_trading' not initialized"
        fi
    else
        check_warn "PostgreSQL is not responding"
    fi
else
    check_warn "PostgreSQL container not running"
fi

# ============================================================================
# VOLUME SETUP
# ============================================================================
print_header "Data Volumes"

VOLUMES_NEEDED=(
    "openalgo_db"
    "openalgo_log"
    "openalgo_strategies"
    "openalgo_keys"
    "openalgo_tmp"
    "postgres_data"
)

for VOL in "${VOLUMES_NEEDED[@]}"; do
    if docker volume ls -q | grep -q "^${VOL}$"; then
        check_pass "Volume '$VOL' exists"
    else
        check_warn "Volume '$VOL' not found - will be created on container start"
    fi
done

# ============================================================================
# NETWORK CONNECTIVITY
# ============================================================================
print_header "Network Connectivity"

# Check DNS resolution
if command -v nslookup &> /dev/null; then
    if nslookup "$DOMAIN" &>/dev/null; then
        check_pass "Domain '$DOMAIN' resolves via DNS"
        IP=$(nslookup "$DOMAIN" 2>/dev/null | grep -A1 "Name:" | grep "Address:" | head -1 | awk '{print $NF}')
        check_pass "  Resolves to: $IP"
    else
        check_warn "Domain '$DOMAIN' does not resolve - check DNS settings"
    fi
fi

# Check HTTPS connectivity
if command -v curl &> /dev/null; then
    if curl -s -I "https://$DOMAIN" &>/dev/null; then
        check_pass "HTTPS is accessible at https://$DOMAIN"
    else
        check_warn "HTTPS connection to $DOMAIN failed - may still be starting up"
    fi
fi

# ============================================================================
# FILE PERMISSIONS
# ============================================================================
print_header "File Permissions"

if [ -f "$INSTALL_DIR/.env" ]; then
    PERMS=$(stat -c %a "$INSTALL_DIR/.env" 2>/dev/null || stat -f %OLp "$INSTALL_DIR/.env" 2>/dev/null)
    if [ "$PERMS" = "600" ] || [ "$PERMS" = "-rw-------" ]; then
        check_pass ".env file has secure permissions (600)"
    else
        check_warn ".env file permissions are $PERMS - should be 600"
    fi
fi

# Check ownership
if [ -d "$INSTALL_DIR" ]; then
    OWNER=$(ls -ld "$INSTALL_DIR" | awk '{print $3}')
    if [ "$OWNER" = "openalgo" ] || [ "$OWNER" = "ubuntu" ] || [ "$OWNER" = "root" ]; then
        check_pass "Directory owned by appropriate user: $OWNER"
    else
        check_warn "Directory ownership: $OWNER"
    fi
fi

# ============================================================================
# SYSTEMD SERVICE
# ============================================================================
print_header "System Integration"

if [ -f "/etc/systemd/system/openalgo.service" ]; then
    check_pass "Systemd service file exists"
    
    if systemctl is-enabled openalgo &>/dev/null; then
        check_pass "Systemd service is enabled (auto-start)"
    else
        check_warn "Systemd service is not enabled - services won't auto-start on reboot"
    fi
    
    if systemctl is-active openalgo &>/dev/null; then
        check_pass "Systemd service is active"
    else
        check_warn "Systemd service is not active - start with: sudo systemctl start openalgo"
    fi
else
    check_warn "Systemd service not installed - services won't auto-start"
fi

# ============================================================================
# MANAGEMENT TOOLS
# ============================================================================
print_header "Management Tools"

if [ -f "$INSTALL_DIR/manage.sh" ] && [ -x "$INSTALL_DIR/manage.sh" ]; then
    check_pass "manage.sh script is available and executable"
else
    check_warn "manage.sh script not found or not executable"
fi

if [ -f "$INSTALL_DIR/monitor.sh" ] && [ -x "$INSTALL_DIR/monitor.sh" ]; then
    check_pass "monitor.sh script is available and executable"
else
    check_warn "monitor.sh script not found or not executable"
fi

# ============================================================================
# LOG DIRECTORY
# ============================================================================
print_header "Logging Setup"

if [ -d "$INSTALL_DIR/logs" ]; then
    check_pass "Logs directory exists"
    
    if [ -d "$INSTALL_DIR/logs/nginx" ]; then
        check_pass "Nginx logs directory exists"
    fi
else
    check_warn "Logs directory not found"
fi

# ============================================================================
# SECURITY CHECKLIST
# ============================================================================
print_header "Security"

check_pass "SSL/TLS enabled (HTTPS)"

# Check CSRF
if grep -q "CSRF_ENABLED.*TRUE" "$INSTALL_DIR/.env" 2>/dev/null; then
    check_pass "CSRF protection enabled"
else
    check_warn "CSRF protection may not be enabled"
fi

# Check CSP
if grep -q "CSP_ENABLED.*TRUE" "$INSTALL_DIR/.env" 2>/dev/null; then
    check_pass "Content Security Policy enabled"
else
    check_warn "Content Security Policy may not be enabled"
fi

# Check secure cookies
if grep -q "SESSION_COOKIE_SECURE" "$INSTALL_DIR/openalgo/app.py" 2>/dev/null; then
    check_pass "Secure cookie settings configured"
fi

# ============================================================================
# SUMMARY
# ============================================================================
print_header "Readiness Summary"

echo ""
echo "Issues found: ${RED}$ISSUES${NC}"
echo "Warnings:     ${YELLOW}$WARNINGS${NC}"
echo ""

if [ "$ISSUES" -eq 0 ]; then
    echo -e "${GREEN}✓ PRODUCTION READY!${NC}"
    echo ""
    echo "Your OpenAlgo setup is ready for production use."
    echo ""
    echo "Next steps:"
    echo "1. Verify DNS is pointing to your server"
    echo "2. Test: https://$DOMAIN"
    echo "3. Configure Dhan broker in settings"
    echo "4. Set up monitoring alerts"
    echo "5. Create your first trading strategy"
    echo ""
    exit 0
else
    echo -e "${RED}✗ ISSUES FOUND - NOT READY${NC}"
    echo ""
    echo "Please fix the issues above before deploying to production."
    echo ""
    if [ "$WARNINGS" -gt 0 ]; then
        echo "Also consider the $WARNINGS warnings above."
    fi
    echo ""
    exit 1
fi
