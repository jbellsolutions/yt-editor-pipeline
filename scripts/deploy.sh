#!/bin/bash
set -euo pipefail

# ─── YT Editor Pipeline — Deploy Script ───
# Syncs local code to production server and restarts services.
# Usage: ./scripts/deploy.sh [--backend-only | --frontend-only]

SERVER="root@142.93.54.26"
REMOTE_DIR="/opt/yt-editor"

echo "🚀 Deploying YT Editor Pipeline..."

# Parse args
DEPLOY_BACKEND=true
DEPLOY_FRONTEND=true
if [ "${1:-}" = "--backend-only" ]; then
    DEPLOY_FRONTEND=false
elif [ "${1:-}" = "--frontend-only" ]; then
    DEPLOY_BACKEND=false
fi

# ─── Backend Deploy ───
if [ "$DEPLOY_BACKEND" = true ]; then
    echo "📦 Syncing backend..."
    rsync -avz --delete \
        --exclude='venv/' \
        --exclude='__pycache__/' \
        --exclude='.env' \
        --exclude='config/client_secret.json' \
        --exclude='config/youtube_token.json' \
        --exclude='*.pyc' \
        --exclude='assets/' \
        backend/ "$SERVER:$REMOTE_DIR/backend/"

    echo "🔄 Restarting backend service..."
    ssh "$SERVER" "systemctl restart yt-backend"
    sleep 2
    ssh "$SERVER" "systemctl is-active yt-backend && echo '✅ Backend is running' || echo '❌ Backend failed to start'"
fi

# ─── Frontend Deploy ───
if [ "$DEPLOY_FRONTEND" = true ]; then
    echo "📦 Syncing frontend..."
    rsync -avz --delete \
        --exclude='node_modules/' \
        --exclude='.next/' \
        frontend/ "$SERVER:$REMOTE_DIR/frontend/"

    echo "🔨 Building frontend..."
    ssh "$SERVER" "cd $REMOTE_DIR/frontend && npm install --production=false && npm run build"

    echo "🔄 Restarting frontend..."
    ssh "$SERVER" "pm2 restart yt-frontend 2>/dev/null || (cd $REMOTE_DIR/frontend && pm2 start npm --name yt-frontend -- start)"
    echo "✅ Frontend deployed"
fi

# ─── Infra configs (only if changed) ───
echo "📋 Syncing infra configs..."
rsync -avz infra/nginx.conf "$SERVER:/etc/nginx/sites-enabled/yt-editor"
rsync -avz infra/yt-backend.service "$SERVER:/etc/systemd/system/yt-backend.service"
ssh "$SERVER" "nginx -t && systemctl reload nginx && systemctl daemon-reload"

echo ""
echo "✅ Deploy complete!"
echo "   Dashboard: http://142.93.54.26"
echo "   Backend:   http://142.93.54.26/health"
