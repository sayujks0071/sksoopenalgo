#!/bin/bash

# Configuration
SERVER_IP="77.37.45.69"
USER="root"
TARGET="$USER@$SERVER_IP"
REPO_URL="https://github.com/openclaw/openclaw.git"
INSTALL_DIR="/opt/openclaw"
SSH_KEY="/Users/mac/sks1989"
KIMI_API_KEY="${KIMI_API_KEY:-}"

if [ -z "$KIMI_API_KEY" ]; then
    echo "❌ KIMI_API_KEY is not set."
    echo "   Export it first, then rerun:"
    echo "   export KIMI_API_KEY='your-kimi-api-key'"
    exit 1
fi

echo "🚀 Starting OpenClaw Deployment to $TARGET..."

# 1. Check SSH Connection
echo "📡 Checking connectivity..."
if ssh -q -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=5 "$TARGET" exit; then
    echo "✅ SSH connection successful."
else
    echo "❌ SSH connection failed." 
    echo "   ensure the public key is added to the VPS authorized_keys."
    echo "   Public Key to Add:"
    cat "${SSH_KEY}.pub"
    exit 1
fi

# 2. Remote Installation Commands
echo "📦 Installing dependencies and deploying on remote server..."
ssh -i "$SSH_KEY" "$TARGET" 'bash -s' <<EOF
    set -e

    # Update system
    echo "   🔄 Updating apt cache..."
    apt-get update -qq

    # Install Docker & Git if missing
    if ! command -v docker &> /dev/null; then
        echo "   🐳 Installing Docker..."
        apt-get install -y -qq docker.io docker-compose-plugin git
    else
        echo "   ✅ Docker already installed."
    fi

    # Clone/Update Repository
    if [ -d "$INSTALL_DIR" ]; then
        echo "   🔄 Updating existing repository at $INSTALL_DIR..."
        cd "$INSTALL_DIR"
        git pull
    else
        echo "   📥 Cloning OpenClaw to $INSTALL_DIR..."
        git clone "$REPO_URL" "$INSTALL_DIR"
        cd "$INSTALL_DIR"
    fi

    # Create .env file to fix volume mapping errors
    echo "   ⚙️  Configuring environment variables..."
    mkdir -p config workspace
    
    # Generate a random token
    GENERATED_TOKEN=$(openssl rand -hex 16)
    
    # Write .env file (docker compose substitution + runtime env)
    cat <<ENV > .env
OPENCLAW_CONFIG_DIR=$INSTALL_DIR/config
OPENCLAW_WORKSPACE_DIR=$INSTALL_DIR/workspace
OPENCLAW_GATEWAY_TOKEN=$GENERATED_TOKEN
KIMI_API_KEY=$KIMI_API_KEY
CLAUDE_WEB_SESSION_KEY=
CLAUDE_WEB_COOKIE=
CLAUDE_AI_SESSION_KEY=
ENV

    # Create override to force build from source with unique image names
    # and pass Kimi API key into runtime containers.
    cat <<OVERRIDE > docker-compose.override.yml
services:
  openclaw-gateway:
    build: .
    image: openclaw:gateway-local
    environment:
      KIMI_API_KEY: \${KIMI_API_KEY}
  openclaw-cli:
    build: .
    image: openclaw:cli-local
    environment:
      KIMI_API_KEY: \${KIMI_API_KEY}
OVERRIDE

    # Start Service
    echo "   🚀 Starting OpenClaw with Docker Compose..."
    # Try different docker compose commands just in case
    if docker compose version &> /dev/null; then
        docker compose up -d --build
    elif docker-compose version &> /dev/null; then
        docker-compose up -d --build
    else
         echo "❌ Docker Compose not found. Installing plugin..."
         apt-get install -y -qq docker-compose-plugin
         docker compose up -d --build
    fi

    # Switch default model to Kimi provider.
    echo "   🤖 Setting default model to kimi-coding/k2p5..."
    SET_MODEL_CMD_COMPOSE="docker-compose"
    if docker compose version &> /dev/null; then
        SET_MODEL_CMD_COMPOSE="docker compose"
    fi

    SET_MODEL_OK=0
    for i in 1 2 3 4 5; do
        if $SET_MODEL_CMD_COMPOSE exec -T openclaw-cli node dist/index.js config set agents.defaults.model.primary "kimi-coding/k2p5"; then
            SET_MODEL_OK=1
            break
        fi
        echo "   ⏳ Waiting for openclaw-cli to be ready (attempt $i/5)..."
        sleep 2
    done

    if [ "$SET_MODEL_OK" -ne 1 ]; then
        echo "❌ Could not set default model to kimi-coding/k2p5 after retries."
        exit 1
    fi
    
    echo "   ✅ Service started."
    echo "   🔑 YOUR GATEWAY TOKEN: $GENERATED_TOKEN"
EOF

echo ""
echo "✨ Deployment Complete!"
echo "🌍 Access OpenClaw at: http://$SERVER_IP:18789"
echo "🔑 Login Token: (Shown in output above)"
echo "   (Make sure port 18789 is open in your Hostinger firewall if it's not working)"
