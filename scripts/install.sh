#!/bin/bash
# Smite Panel Installer - Optimized for Speed

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Spinner function
spinner() {
    local pid=$1
    local delay=0.1
    local spinstr='|/-\'
    while [ "$(ps a | awk '{print $1}' | grep $pid)" ]; do
        local temp=${spinstr#?}
        printf " [%c]  " "$spinstr"
        local spinstr=$temp${spinstr%"$temp"}
        sleep $delay
        printf "\b\b\b\b\b\b"
    done
    printf "    \b\b\b\b"
}

# Progress function
progress() {
    echo -e "${GREEN}✓${NC} $1"
}

echo "=== Smite Panel Installer ==="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Please run as root (use sudo)${NC}"
    exit 1
fi

# Enable Docker BuildKit for faster builds
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1

# Detect OS
OS="$(uname -s)"
ARCH="$(uname -m)"

# Install git if not present
if ! command -v git &> /dev/null; then
    echo "Installing git..."
    apt-get update -qq && apt-get install -y git > /dev/null 2>&1
    progress "Git installed"
fi

# Install Node.js and npm if not present
if ! command -v node &> /dev/null || ! command -v npm &> /dev/null; then
    echo "Installing Node.js..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - > /dev/null 2>&1
    apt-get install -y nodejs > /dev/null 2>&1
    progress "Node.js installed"
fi

# Install Docker if not present
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh > /dev/null 2>&1
    rm get-docker.sh
    progress "Docker installed"
fi

# Check docker-compose
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo -e "${RED}docker-compose not found. Please install it separately${NC}"
    exit 1
fi

# Get installation directory
INSTALL_DIR="/opt/smite"
echo "Installing to: $INSTALL_DIR"

# Clone or update repository
if [ -d "$INSTALL_DIR" ] && [ -f "$INSTALL_DIR/docker-compose.yml" ]; then
    echo "Smite already installed in $INSTALL_DIR"
    cd "$INSTALL_DIR"
    # Update if needed
    if [ -d ".git" ]; then
        echo "Updating repository..."
        git pull --quiet || true
    fi
else
    # Clone from GitHub
    echo "Cloning Smite from GitHub..."
    rm -rf "$INSTALL_DIR"
    git clone --depth 1 https://github.com/zZedix/Smite.git "$INSTALL_DIR" || {
        echo -e "${RED}Error: Failed to clone repository${NC}"
        exit 1
    }
    cd "$INSTALL_DIR"
    progress "Repository cloned"
fi

# Minimal configuration prompts (only essential)
echo ""
echo "Configuration:"
read -p "Panel port (default: 8000): " PANEL_PORT
PANEL_PORT=${PANEL_PORT:-8000}

read -p "Database type [sqlite/mysql] (default: sqlite): " DB_TYPE
DB_TYPE=${DB_TYPE:-sqlite}

# Create .env file
cat > .env << EOF
PANEL_PORT=$PANEL_PORT
PANEL_HOST=0.0.0.0
HTTPS_ENABLED=false
DOCS_ENABLED=true

DB_TYPE=$DB_TYPE
DB_PATH=./data/smite.db

HYSTERIA2_PORT=4443
HYSTERIA2_CERT_PATH=./certs/ca.crt
HYSTERIA2_KEY_PATH=./certs/ca.key

SECRET_KEY=$(openssl rand -hex 32)
EOF

if [ "$DB_TYPE" = "mysql" ]; then
    read -p "MySQL host (default: localhost): " DB_HOST
    DB_HOST=${DB_HOST:-localhost}
    read -p "MySQL port (default: 3306): " DB_PORT
    DB_PORT=${DB_PORT:-3306}
    read -p "MySQL database name: " DB_NAME
    read -p "MySQL user: " DB_USER
    read -sp "MySQL password: " DB_PASSWORD
    echo ""
    
    cat >> .env << EOF

DB_HOST=$DB_HOST
DB_PORT=$DB_PORT
DB_NAME=$DB_NAME
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
EOF
fi

progress "Configuration saved"

# Create necessary directories
mkdir -p panel/data panel/certs
progress "Directories created"

# Generate CA certificate placeholder if not exists
if [ ! -f "panel/certs/ca.crt" ]; then
    touch panel/certs/ca.crt panel/certs/ca.key
fi

# Install CLI
echo ""
echo "Installing CLI tools..."
if [ -f "cli/install_cli.sh" ]; then
    bash cli/install_cli.sh > /dev/null 2>&1
else
    cp cli/smite.py /usr/local/bin/smite 2>/dev/null || true
    chmod +x /usr/local/bin/smite 2>/dev/null || true
fi
progress "CLI installed"

# Install minimal Python dependencies for CLI (if not in container)
if ! python3 -c "import requests" 2>/dev/null; then
    pip3 install requests --quiet 2>/dev/null || python3 -m pip install requests --quiet 2>/dev/null || true
fi

# Build frontend if needed (only if dist doesn't exist or is empty)
if [ -d "frontend" ]; then
    if [ ! -d "frontend/dist" ] || [ -z "$(ls -A frontend/dist 2>/dev/null)" ]; then
        echo ""
        echo "Building frontend..."
        cd frontend
        
        # Use npm ci for faster, reproducible builds
        echo "Installing frontend dependencies..."
        npm ci --silent --prefer-offline --no-audit --no-fund 2>/dev/null || npm install --silent --prefer-offline --no-audit --no-fund
        
        echo "Building frontend..."
        npm run build --silent
        
        if [ ! -d "dist" ] || [ -z "$(ls -A dist 2>/dev/null)" ]; then
            echo -e "${YELLOW}Warning: Frontend build failed. API will still be available at /api and /docs${NC}"
        else
            progress "Frontend built"
        fi
        cd ..
    else
        progress "Frontend already built"
    fi
fi

# Build Docker images in parallel
echo ""
echo "Building Docker images (this may take a moment on first run)..."
echo "  Using Docker BuildKit for faster builds..."

# Try to pull prebuilt images first (optional - will fallback to build if not available)
echo "  Checking for prebuilt images (optional)..."
if docker pull ghcr.io/zzedix/smite-panel:latest 2>/dev/null; then
    docker tag ghcr.io/zzedix/smite-panel:latest smite-panel:latest 2>/dev/null
    progress "Prebuilt panel image found"
fi

# Build with docker compose in parallel (will skip if prebuilt images exist)
echo "  Building images..."
if docker compose build --parallel 2>&1; then
    progress "Docker images built"
else
    echo -e "${YELLOW}Build completed with warnings${NC}"
fi

# Start services
echo ""
echo "Starting Smite Panel..."
docker compose up -d

# Wait for services
echo "Waiting for services to start..."
sleep 5

# Check status
if docker ps | grep -q smite-panel; then
    echo ""
    echo -e "${GREEN}✅ Smite Panel installed successfully!${NC}"
    echo ""
    echo "Panel URL: http://localhost:$PANEL_PORT"
    echo "API Docs: http://localhost:$PANEL_PORT/docs"
    echo ""
    echo "Next steps:"
    echo "  1. Create admin user: smite admin create"
    echo "  2. Access the web interface at http://localhost:$PANEL_PORT"
    echo ""
else
    echo -e "${RED}❌ Installation completed but panel is not running${NC}"
    echo "Check logs with: docker compose logs"
    exit 1
fi
