#!/bin/bash
set -e

# ──────────────────────────────────────────────────────────────
# YT Editor Pipeline — Interactive Installer
# Supported: Ubuntu 22.04+, Debian 12+
# Usage: sudo ./scripts/setup.sh
# ──────────────────────────────────────────────────────────────

INSTALL_DIR="/opt/yt-editor"
SERVICE_USER="yt-editor"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail()  { echo -e "${RED}[FAIL]${NC} $1"; }

# ──────────────────────────────────────────────────────────────
# Pre-flight checks
# ──────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}========================================${NC}"
echo -e "${BOLD}  YT Editor Pipeline — Setup Installer  ${NC}"
echo -e "${BOLD}========================================${NC}"
echo ""

# Must be root
if [ "$EUID" -ne 0 ]; then
    fail "This script must be run as root (use sudo)."
    exit 1
fi

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS_ID="$ID"
    OS_VERSION="$VERSION_ID"
else
    fail "Cannot detect OS. /etc/os-release not found."
    exit 1
fi

case "$OS_ID" in
    ubuntu|debian)
        ok "Detected $PRETTY_NAME"
        ;;
    *)
        fail "Unsupported OS: $OS_ID. Only Ubuntu and Debian are supported."
        exit 1
        ;;
esac

echo ""
info "Install directory: $INSTALL_DIR"
info "Source directory:   $REPO_DIR"
echo ""
read -p "Press Enter to begin installation, or Ctrl+C to cancel... "

# ──────────────────────────────────────────────────────────────
# Step 1: System dependencies
# ──────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}[1/8] Installing system dependencies...${NC}"
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv ffmpeg nginx curl git > /dev/null 2>&1
ok "System packages installed (python3, ffmpeg, nginx, curl, git)"

# ──────────────────────────────────────────────────────────────
# Step 2: Node.js 20
# ──────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}[2/8] Installing Node.js 20...${NC}"
if command -v node &>/dev/null && [[ "$(node --version)" == v20* ]]; then
    ok "Node.js $(node --version) already installed"
else
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - > /dev/null 2>&1
    apt-get install -y -qq nodejs > /dev/null 2>&1
    ok "Node.js $(node --version) installed"
fi

# ──────────────────────────────────────────────────────────────
# Step 3: Service user
# ──────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}[3/8] Creating service user...${NC}"
if id -u "$SERVICE_USER" &>/dev/null; then
    ok "User '$SERVICE_USER' already exists"
else
    useradd --system --home-dir "$INSTALL_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
    ok "Created system user '$SERVICE_USER'"
fi

# ──────────────────────────────────────────────────────────────
# Step 4: Project structure
# ──────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}[4/8] Setting up project structure...${NC}"
mkdir -p "$INSTALL_DIR"/{backend/config,frontend,data/{inbox,cleaned,shorts,thumbnails,metadata,published,logs,checkpoints}}

# Copy source files
cp -r "$REPO_DIR/backend/"* "$INSTALL_DIR/backend/" 2>/dev/null || true
cp -r "$REPO_DIR/frontend/"* "$INSTALL_DIR/frontend/" 2>/dev/null || true

# Copy nginx config
if [ -f "$REPO_DIR/infra/nginx.conf" ]; then
    cp "$REPO_DIR/infra/nginx.conf" /etc/nginx/sites-available/yt-editor
    ln -sf /etc/nginx/sites-available/yt-editor /etc/nginx/sites-enabled/yt-editor
    rm -f /etc/nginx/sites-enabled/default
    ok "Nginx config installed"
fi

chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR"
ok "Project structure created at $INSTALL_DIR"

# ──────────────────────────────────────────────────────────────
# Step 5: Python backend
# ──────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}[5/8] Setting up Python backend...${NC}"
cd "$INSTALL_DIR/backend"

if [ ! -d venv ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip -q > /dev/null 2>&1
pip install -r requirements.txt -q > /dev/null 2>&1
deactivate

chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR/backend"
ok "Python virtual environment created and dependencies installed"

# ──────────────────────────────────────────────────────────────
# Step 6: Frontend build
# ──────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}[6/8] Building Next.js frontend...${NC}"
cd "$INSTALL_DIR/frontend"
npm install --silent > /dev/null 2>&1
npm run build --silent > /dev/null 2>&1
chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR/frontend"
ok "Frontend built successfully"

# ──────────────────────────────────────────────────────────────
# Step 7: API keys (interactive)
# ──────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}[7/8] Configuring API keys...${NC}"
echo ""

ENV_FILE="$INSTALL_DIR/backend/.env"

if [ -f "$ENV_FILE" ]; then
    echo "Existing .env file found at $ENV_FILE"
    read -p "Overwrite it? (y/N): " OVERWRITE
    if [[ ! "$OVERWRITE" =~ ^[Yy]$ ]]; then
        ok "Keeping existing .env file"
        SKIP_ENV=true
    fi
fi

if [ "${SKIP_ENV:-}" != "true" ]; then
    echo ""
    echo -e "${CYAN}You will need API keys from three services.${NC}"
    echo -e "  OpenAI     — Whisper transcription (speech-to-text)"
    echo -e "  Anthropic  — Claude AI for Shorts detection and SEO metadata"
    echo -e "  Replicate  — FLUX model for AI thumbnail generation"
    echo ""
    echo "Press Enter to skip any key you want to fill in later."
    echo ""

    read -p "OpenAI API key (starts with sk-): " OPENAI_KEY
    read -p "Anthropic API key (starts with sk-ant-): " ANTHROPIC_KEY
    read -p "Replicate API token (starts with r8_): " REPLICATE_TOKEN

    cat > "$ENV_FILE" << ENVEOF
OPENAI_API_KEY=${OPENAI_KEY:-sk-your-openai-key-here}
ANTHROPIC_API_KEY=${ANTHROPIC_KEY:-sk-ant-your-anthropic-key-here}
REPLICATE_API_TOKEN=${REPLICATE_TOKEN:-r8_your-replicate-token-here}
ALLOWED_ORIGINS=http://localhost:3000
DATA_DIR=$INSTALL_DIR/data
CONFIG_DIR=$INSTALL_DIR/backend/config
OAUTH_REDIRECT_URI=http://localhost:8000/auth/callback
ENVEOF

    chmod 600 "$ENV_FILE"
    chown "$SERVICE_USER":"$SERVICE_USER" "$ENV_FILE"
    ok ".env file written to $ENV_FILE"
fi

# Google OAuth setup prompt
echo ""
echo -e "${BOLD}Google OAuth Setup (YouTube uploads)${NC}"
echo ""
echo "To enable YouTube uploads, you need a Google Cloud OAuth credential."
echo ""
echo "  1. Go to https://console.cloud.google.com"
echo "  2. Create a project and enable 'YouTube Data API v3'"
echo "  3. Create an OAuth 2.0 Client ID (type: Web application)"
echo "  4. Set redirect URI to: http://localhost:8000/auth/callback"
echo "  5. Download the JSON credentials file"
echo ""
read -p "Path to your client_secret.json (or press Enter to skip): " OAUTH_PATH

if [ -n "$OAUTH_PATH" ] && [ -f "$OAUTH_PATH" ]; then
    cp "$OAUTH_PATH" "$INSTALL_DIR/backend/config/client_secret.json"
    chmod 600 "$INSTALL_DIR/backend/config/client_secret.json"
    chown "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR/backend/config/client_secret.json"
    ok "OAuth credentials installed"
else
    if [ -n "$OAUTH_PATH" ]; then
        warn "File not found: $OAUTH_PATH"
    fi
    warn "Skipping OAuth setup. Place your client_secret.json at:"
    echo "       $INSTALL_DIR/backend/config/client_secret.json"
fi

# ──────────────────────────────────────────────────────────────
# Step 8: Systemd services
# ──────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}[8/8] Creating and enabling systemd services...${NC}"

cat > /etc/systemd/system/yt-backend.service << EOF
[Unit]
Description=YT Editor FastAPI Backend
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR/backend
EnvironmentFile=$INSTALL_DIR/backend/.env
ExecStart=$INSTALL_DIR/backend/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
Environment=PATH=$INSTALL_DIR/backend/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=$INSTALL_DIR/data $INSTALL_DIR/backend/config
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/yt-frontend.service << EOF
[Unit]
Description=YT Editor Next.js Frontend
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR/frontend
ExecStart=/usr/bin/npx next start -p 3000
Restart=always
RestartSec=5
Environment=NODE_ENV=production
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable yt-backend yt-frontend > /dev/null 2>&1
systemctl restart nginx
systemctl start yt-backend yt-frontend

ok "Systemd services created and started"

# ──────────────────────────────────────────────────────────────
# Health check
# ──────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}Running health checks...${NC}"
echo ""

# Give the backend a moment to start
sleep 3

HEALTH_OK=true

if command -v ffmpeg &>/dev/null; then
    ok "FFmpeg installed ($(ffmpeg -version 2>&1 | head -1 | awk '{print $3}'))"
else
    fail "FFmpeg not found"
    HEALTH_OK=false
fi

if command -v node &>/dev/null; then
    ok "Node.js installed ($(node --version))"
else
    fail "Node.js not found"
    HEALTH_OK=false
fi

if command -v python3 &>/dev/null; then
    ok "Python installed ($(python3 --version 2>&1 | awk '{print $2}'))"
else
    fail "Python3 not found"
    HEALTH_OK=false
fi

if systemctl is-active --quiet yt-backend; then
    ok "Backend service running"
else
    warn "Backend service not running (check: journalctl -u yt-backend)"
    HEALTH_OK=false
fi

if systemctl is-active --quiet yt-frontend; then
    ok "Frontend service running"
else
    warn "Frontend service not running (check: journalctl -u yt-frontend)"
    HEALTH_OK=false
fi

if systemctl is-active --quiet nginx; then
    ok "Nginx running"
else
    warn "Nginx not running (check: journalctl -u nginx)"
    HEALTH_OK=false
fi

if [ -f "$INSTALL_DIR/backend/.env" ]; then
    ok ".env file present"
else
    warn ".env file missing — backend will not start correctly"
    HEALTH_OK=false
fi

if [ -f "$INSTALL_DIR/backend/config/client_secret.json" ]; then
    ok "OAuth credentials present"
else
    warn "OAuth credentials missing — YouTube uploads will not work"
fi

# Try hitting the health endpoint
HEALTH_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/health 2>/dev/null || echo "000")
if [ "$HEALTH_RESPONSE" = "200" ]; then
    ok "Backend /health endpoint responding (HTTP 200)"
else
    warn "Backend /health endpoint not responding yet (HTTP $HEALTH_RESPONSE)"
    echo "       This is normal if API keys are not yet configured."
fi

# ──────────────────────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────────────────────

SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "YOUR_SERVER_IP")

echo ""
echo -e "${BOLD}========================================${NC}"
echo -e "${BOLD}  Setup Complete!${NC}"
echo -e "${BOLD}========================================${NC}"
echo ""
echo -e "  Dashboard:  ${GREEN}http://$SERVER_IP${NC}"
echo -e "  API:        ${GREEN}http://$SERVER_IP/health${NC}"
echo -e "  Install:    $INSTALL_DIR"
echo ""

if [ ! -f "$INSTALL_DIR/backend/config/client_secret.json" ]; then
    echo -e "${YELLOW}Next steps:${NC}"
    echo "  1. Place your Google OAuth client_secret.json at:"
    echo "     $INSTALL_DIR/backend/config/client_secret.json"
    echo "  2. Set up SSH tunnel: ssh -L 8000:localhost:8000 user@$SERVER_IP"
    echo "  3. Visit http://localhost:8000/auth/youtube to connect YouTube"
    echo "  4. Restart backend: sudo systemctl restart yt-backend"
else
    echo -e "${YELLOW}Next step:${NC}"
    echo "  1. Set up SSH tunnel: ssh -L 8000:localhost:8000 user@$SERVER_IP"
    echo "  2. Visit http://localhost:8000/auth/youtube to connect YouTube"
    echo "  3. Restart backend: sudo systemctl restart yt-backend"
fi

echo ""
echo "Useful commands:"
echo "  sudo systemctl status yt-backend    # Check backend status"
echo "  sudo systemctl status yt-frontend   # Check frontend status"
echo "  sudo journalctl -u yt-backend -f    # Stream backend logs"
echo "  sudo journalctl -u yt-frontend -f   # Stream frontend logs"
echo ""
