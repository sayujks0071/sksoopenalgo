#!/bin/bash

# OpenAlgo Container Management Script
# Simple CLI for managing the trading platform

set -e

INSTALL_DIR="${INSTALL_DIR:-.}"
COMPOSE_FILE="$INSTALL_DIR/docker-compose.yml"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Helper functions
print_header() {
    echo -e "${BLUE}=== $1 ===${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${YELLOW}ℹ $1${NC}"
}

# Check if docker-compose.yml exists
if [ ! -f "$COMPOSE_FILE" ]; then
    print_error "docker-compose.yml not found in $INSTALL_DIR"
    exit 1
fi

# Commands
case "$1" in
    start)
        print_header "Starting OpenAlgo Services"
        cd "$INSTALL_DIR"
        docker compose up -d --pull missing
        print_success "Services started"
        docker compose ps
        ;;
    
    stop)
        print_header "Stopping OpenAlgo Services"
        cd "$INSTALL_DIR"
        docker compose down
        print_success "Services stopped"
        ;;
    
    restart)
        print_header "Restarting OpenAlgo Services"
        cd "$INSTALL_DIR"
        docker compose restart "$2" 2>/dev/null || docker compose restart
        print_success "Services restarted"
        docker compose ps
        ;;
    
    status)
        print_header "Service Status"
        cd "$INSTALL_DIR"
        docker compose ps
        ;;
    
    logs)
        print_header "Service Logs"
        cd "$INSTALL_DIR"
        docker compose logs -f "${2:-openalgo}"
        ;;
    
    app-logs)
        print_header "OpenAlgo Application Logs"
        cd "$INSTALL_DIR"
        docker compose exec -T openalgo tail -f log/app.log 2>/dev/null || docker compose exec -T openalgo ls -la log/
        ;;
    
    health)
        print_header "Health Check"
        cd "$INSTALL_DIR"
        
        echo "Container Status:"
        docker compose ps | tail -n +2 | while read line; do
            if echo "$line" | grep -q "Up"; then
                echo -e "  ${GREEN}✓${NC} $line"
            else
                echo -e "  ${RED}✗${NC} $line"
            fi
        done
        
        echo ""
        echo "Database Health:"
        docker compose exec -T postgres pg_isready -U openalgo &>/dev/null && \
            echo -e "  ${GREEN}✓${NC} PostgreSQL is healthy" || \
            echo -e "  ${RED}✗${NC} PostgreSQL is down"
        
        echo ""
        echo "Web Service Health:"
        if curl -s https://localhost/health &>/dev/null; then
            echo -e "  ${GREEN}✓${NC} Web service is responding"
        else
            echo -e "  ${YELLOW}ℹ${NC} Web service not accessible locally (check from browser)"
        fi
        ;;
    
    rebuild)
        print_header "Rebuilding OpenAlgo Image"
        cd "$INSTALL_DIR"
        docker compose build --no-cache openalgo
        print_success "Build complete"
        ;;
    
    clean)
        print_header "Cleaning Up Docker Resources"
        read -p "This will remove stopped containers and unused volumes. Continue? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            docker compose down
            docker system prune -f
            print_success "Cleanup complete"
        else
            print_info "Cleanup cancelled"
        fi
        ;;
    
    update)
        print_header "Updating OpenAlgo"
        cd "$INSTALL_DIR"
        
        print_info "Pulling latest code..."
        git pull origin main || print_info "Already on latest version"
        
        print_info "Pulling latest images..."
        docker compose pull
        
        print_info "Rebuilding..."
        docker compose build openalgo
        
        print_info "Restarting services..."
        docker compose up -d --remove-orphans
        
        print_success "Update complete"
        docker compose ps
        ;;
    
    shell)
        print_header "Entering OpenAlgo Container Shell"
        cd "$INSTALL_DIR"
        docker compose exec openalgo bash
        ;;
    
    psql)
        print_header "Entering PostgreSQL Shell"
        cd "$INSTALL_DIR"
        docker compose exec postgres psql -U openalgo -d openalgo_trading
        ;;
    
    backup)
        print_header "Backing Up Data"
        cd "$INSTALL_DIR"
        
        BACKUP_DIR="./backups/$(date +%Y%m%d_%H%M%S)"
        mkdir -p "$BACKUP_DIR"
        
        print_info "Backing up database..."
        docker compose exec -T postgres pg_dump -U openalgo openalgo_trading > "$BACKUP_DIR/openalgo_trading.sql"
        
        print_info "Backing up strategies..."
        docker cp openalgo-app:/app/strategies "$BACKUP_DIR/strategies" 2>/dev/null || true
        
        print_info "Backing up configuration..."
        cp .env "$BACKUP_DIR/.env" 2>/dev/null || true
        
        print_success "Backup created at: $BACKUP_DIR"
        ;;
    
    restore)
        if [ -z "$2" ]; then
            print_error "Usage: ./manage.sh restore <backup_directory>"
            echo "Example: ./manage.sh restore ./backups/20240101_120000"
            exit 1
        fi
        
        BACKUP_DIR="$2"
        if [ ! -d "$BACKUP_DIR" ]; then
            print_error "Backup directory not found: $BACKUP_DIR"
            exit 1
        fi
        
        print_header "Restoring from Backup"
        cd "$INSTALL_DIR"
        
        read -p "This will overwrite current data. Continue? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_info "Restore cancelled"
            exit 0
        fi
        
        print_info "Restoring database..."
        docker compose exec -T postgres psql -U openalgo openalgo_trading < "$BACKUP_DIR/openalgo_trading.sql"
        
        if [ -d "$BACKUP_DIR/strategies" ]; then
            print_info "Restoring strategies..."
            docker cp "$BACKUP_DIR/strategies" openalgo-app:/app/ 2>/dev/null || true
        fi
        
        print_success "Restore complete"
        ;;
    
    config)
        print_header "Configuration"
        
        if [ "$2" == "edit" ]; then
            nano "$INSTALL_DIR/.env"
            print_info "Restart services for changes to take effect: ./manage.sh restart"
        elif [ "$2" == "view" ]; then
            print_info "Configuration file: $INSTALL_DIR/.env"
            echo ""
            grep -v "^#" "$INSTALL_DIR/.env" | grep -v "^$" | head -20
            echo "... (showing first 20 non-comment lines)"
        else
            echo "Usage: ./manage.sh config [edit|view]"
        fi
        ;;
    
    *)
        print_header "OpenAlgo Management Tool"
        echo "Usage: ./manage.sh <command> [options]"
        echo ""
        echo "Commands:"
        echo "  start              Start all services"
        echo "  stop               Stop all services"
        echo "  restart [service]  Restart services (optionally specific service)"
        echo "  status             Show container status"
        echo "  health             Run health checks"
        echo "  logs [service]     View logs (default: openalgo)"
        echo "  app-logs           View application logs"
        echo "  rebuild            Rebuild OpenAlgo image"
        echo "  update             Update to latest version"
        echo "  clean              Remove stopped containers and prune images"
        echo "  shell              Open bash shell in openalgo container"
        echo "  psql               Open PostgreSQL shell"
        echo "  backup             Backup database and strategies"
        echo "  restore <dir>      Restore from backup"
        echo "  config [edit|view] Manage configuration"
        echo ""
        echo "Examples:"
        echo "  ./manage.sh status"
        echo "  ./manage.sh logs nginx"
        echo "  ./manage.sh restart openalgo"
        echo "  ./manage.sh backup"
        echo ""
        ;;
esac
