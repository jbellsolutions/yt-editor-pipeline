#!/bin/bash
set -e

echo "=== YT Editor Pipeline Setup ==="

# System deps
echo "[1/6] Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv ffmpeg nginx curl git

# Node 20
echo "[2/6] Installing Node.js 20..."
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y -qq nodejs

# Project structure
echo "[3/6] Creating project directories..."
mkdir -p /opt/yt-editor/{backend/config,frontend,data/{inbox,cleaned,shorts,thumbnails,metadata,published,logs}}

# Backend
echo "[4/6] Setting up Python backend..."
cd /opt/yt-editor/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Frontend
echo "[5/6] Setting up Next.js frontend..."
cd /opt/yt-editor/frontend
npm install
npm run build

# Services
echo "[6/6] Creating systemd services..."
cat > /etc/systemd/system/yt-backend.service << 'EOF'
[Unit]
Description=YT Editor FastAPI Backend
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/yt-editor/backend
EnvironmentFile=/opt/yt-editor/backend/.env
ExecStart=/opt/yt-editor/backend/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
Environment=PATH=/opt/yt-editor/backend/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/yt-frontend.service << 'EOF'
[Unit]
Description=YT Editor Next.js Frontend
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/yt-editor/frontend
ExecStart=/usr/bin/npx next start -p 3000
Restart=always
RestartSec=5
Environment=NODE_ENV=production

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable yt-backend yt-frontend
systemctl start yt-backend yt-frontend

echo ""
echo "=== Setup complete! ==="
echo "Dashboard: http://YOUR_SERVER_IP"
echo "API: http://YOUR_SERVER_IP/health"
echo ""
echo "Next steps:"
echo "1. Copy .env.example to /opt/yt-editor/backend/.env and fill in your API keys"
echo "2. Place your Google OAuth client_secret.json in /opt/yt-editor/backend/config/"
echo "3. Set up SSH tunnel: ssh -L 8000:localhost:8000 root@YOUR_SERVER_IP"
echo "4. Visit http://localhost:8000/auth/youtube to connect YouTube"
echo "5. Restart backend: systemctl restart yt-backend"
