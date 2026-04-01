# BotifyTrades — Centralized Deployment Plan
# Docker Containers + Cloudflare Tunnel + Flask GUI Auth
---

## Architecture Overview

```
                        INTERNET
                           |
                  botifytrades.com (Cloudflare DNS)
                           |
               ┌───────────┴───────────┐
               │   Cloudflare Tunnel    │
               │   (Single cloudflared  │
               │    daemon on VPS)      │
               └───────────┬───────────┘
                           |
          ┌────────────────┼────────────────┐
          │                │                │
   john.botifytrades.com  mike.botifytrades.com  sara.botifytrades.com
     :5001 → container     :5002 → container     :5003 → container
          │                │                │
   ┌──────┴──────┐  ┌─────┴──────┐  ┌──────┴──────┐
   │  user-john  │  │ user-mike  │  │  user-sara  │
   │  Flask GUI  │  │ Flask GUI  │  │  Flask GUI  │
   │  Discord Bot│  │ Discord Bot│  │  Discord Bot│
   │  bot_data.db│  │ bot_data.db│  │  bot_data.db│
   └─────────────┘  └────────────┘  └─────────────┘
          │                │                │
          └────────────────┼────────────────┘
                           │
                   Host VPS ($40-80/mo)
                   Ubuntu 22.04 / 24.04
```

**Key points:**
- Each user = 1 Docker container = fully isolated bot instance
- Own database, own broker credentials, own Discord token
- NOT multi-tenant — just efficient single-server hosting
- Cloudflare Tunnel = no port forwarding, no firewall rules, free SSL
- Flask GUI gets login auth so only the user can access their dashboard

---

## Phase 1: VPS Setup

### 1.1 Server Requirements

| Users     | VPS Spec                  | Estimated Cost |
|-----------|---------------------------|----------------|
| 1-10      | 4 CPU, 8GB RAM, 80GB SSD  | $20-40/mo      |
| 10-25     | 8 CPU, 16GB RAM, 160GB SSD| $40-80/mo      |
| 25-50     | 16 CPU, 32GB RAM, 320GB SSD| $80-160/mo    |
| 50+       | Split across 2+ servers   | Scale horizontally |

**Recommended providers:** Hetzner ($4-6/CPU), Contabo, DigitalOcean, Vultr, Linode

Each BotifyTrades container uses approximately:
- 200-400MB RAM
- Minimal CPU (spikes during trade execution)
- 50-100MB disk per user (database + logs)

### 1.2 Initial Server Setup

```bash
# SSH into your VPS
ssh root@your-vps-ip

# Update system
apt update && apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh

# Install Docker Compose
apt install docker-compose-plugin -y

# Verify
docker --version
docker compose version

# Create project directory
mkdir -p /opt/botifytrades
cd /opt/botifytrades

# Create directories for user data
mkdir -p users configs scripts backups
```

---

## Phase 2: Dockerize BotifyTrades

### 2.1 Dockerfile

Create `/opt/botifytrades/Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libffi-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data /app/logs

ENV PYTHONUNBUFFERED=1
ENV GUI_PORT=5001

EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:5001/health || exit 1

CMD ["python", "-u", "start.py"]
```

### 2.2 Docker Ignore File

Create `/opt/botifytrades/.dockerignore`:

```
.git
.env
*.db
__pycache__
*.pyc
node_modules
landing-page/
admin_panel/
india_bot/
tests/
docs/
*.exe
*.spec
backups/
users/
```

### 2.3 Docker Compose — Multi-User Template

Create `/opt/botifytrades/docker-compose.yml`:

```yaml
version: "3.8"

services:
  # === USER: john ===
  user-john:
    build: .
    container_name: botify-john
    restart: unless-stopped
    env_file:
      - ./users/john/.env
    volumes:
      - ./users/john/data:/app/data
      - ./users/john/logs:/app/logs
      - ./users/john/bot_data.db:/app/bot_data.db
    ports:
      - "5001:5001"
    networks:
      - botify-net
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: "0.5"
        reservations:
          memory: 256M

  # === USER: mike ===
  user-mike:
    build: .
    container_name: botify-mike
    restart: unless-stopped
    env_file:
      - ./users/mike/.env
    volumes:
      - ./users/mike/data:/app/data
      - ./users/mike/logs:/app/logs
      - ./users/mike/bot_data.db:/app/bot_data.db
    ports:
      - "5002:5001"
    networks:
      - botify-net
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: "0.5"
        reservations:
          memory: 256M

  # === USER: sara ===
  user-sara:
    build: .
    container_name: botify-sara
    restart: unless-stopped
    env_file:
      - ./users/sara/.env
    volumes:
      - ./users/sara/data:/app/data
      - ./users/sara/logs:/app/logs
      - ./users/sara/bot_data.db:/app/bot_data.db
    ports:
      - "5003:5001"
    networks:
      - botify-net
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: "0.5"
        reservations:
          memory: 256M

networks:
  botify-net:
    driver: bridge
```

**Port mapping rule:** Each user gets `HOST_PORT:5001`
- User 1 → 5001:5001
- User 2 → 5002:5001
- User 3 → 5003:5001
- User N → (5000 + N):5001

---

## Phase 3: Cloudflare Tunnel Setup

### 3.1 Prerequisites

- Domain `botifytrades.com` added to Cloudflare (free plan)
- Cloudflare account with Zero Trust enabled (free for <50 users)

### 3.2 Install cloudflared on VPS

```bash
# Install cloudflared
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb \
  -o cloudflared.deb
dpkg -i cloudflared.deb

# Authenticate (opens browser link — copy URL if headless)
cloudflared tunnel login

# Create tunnel
cloudflared tunnel create botifytrades

# Note the tunnel ID (e.g., a1b2c3d4-e5f6-...)
```

### 3.3 Tunnel Configuration

Create `/opt/botifytrades/cloudflared/config.yml`:

```yaml
tunnel: <YOUR_TUNNEL_ID>
credentials-file: /root/.cloudflared/<YOUR_TUNNEL_ID>.json

ingress:
  # User: john
  - hostname: john.botifytrades.com
    service: http://localhost:5001

  # User: mike
  - hostname: mike.botifytrades.com
    service: http://localhost:5002

  # User: sara
  - hostname: sara.botifytrades.com
    service: http://localhost:5003

  # Main landing page (optional)
  - hostname: botifytrades.com
    service: http://localhost:8080

  # Catch-all (required by cloudflared)
  - service: http_status:404
```

### 3.4 DNS Setup

```bash
# Create DNS records for each user (run once per user)
cloudflared tunnel route dns botifytrades john.botifytrades.com
cloudflared tunnel route dns botifytrades mike.botifytrades.com
cloudflared tunnel route dns botifytrades sara.botifytrades.com
```

### 3.5 Run Tunnel as System Service

```bash
# Install as system service
cloudflared service install

# Start the tunnel
systemctl start cloudflared
systemctl enable cloudflared

# Verify
systemctl status cloudflared
```

### 3.6 Cloudflare Access (Optional — Extra Auth Layer)

In Cloudflare Zero Trust dashboard:
1. Go to **Access → Applications → Add Application**
2. Set subdomain pattern: `*.botifytrades.com`
3. Add policy: **Allow** → Email domain or one-time PIN
4. Users get a Cloudflare login screen before reaching the Flask GUI

This gives you **two layers of auth**: Cloudflare Access + Flask GUI login.

---

## Phase 4: Flask GUI Authentication

### 4.1 What Gets Added to the Bot Code

Add login/password protection to the Flask GUI so each user's dashboard requires authentication. The implementation:

```
gui_app/
├── auth.py              ← NEW: Login/session management
├── app.py               ← MODIFIED: Add auth middleware
├── routes.py            ← MODIFIED: Protect all routes
└── templates/
    └── login.html       ← NEW: Login page
```

### 4.2 Authentication Design

```
User visits john.botifytrades.com
        ↓
  Cloudflare Access check (optional layer)
        ↓
  Flask login page (username + password)
        ↓
  Session cookie (secure, httponly, 24hr expiry)
        ↓
  Dashboard access
```

**Security features:**
- Passwords hashed with bcrypt (already in requirements.txt)
- Session-based auth with secure cookies
- CSRF protection on login form
- Rate limiting on login attempts (5 per minute)
- Auto-logout after 24 hours of inactivity
- First-run setup: user creates their password on initial access

### 4.3 Auth Implementation — auth.py

```python
import bcrypt
import secrets
import time
from functools import wraps
from flask import request, redirect, url_for, session, flash

MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION = 300  # 5 minutes
SESSION_LIFETIME = 86400  # 24 hours

_login_attempts = {}

def init_auth(app):
    app.secret_key = app.config.get('SECRET_KEY') or secrets.token_hex(32)
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password, hashed):
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def is_locked_out(ip):
    if ip in _login_attempts:
        attempts, lockout_time = _login_attempts[ip]
        if attempts >= MAX_LOGIN_ATTEMPTS:
            if time.time() - lockout_time < LOCKOUT_DURATION:
                return True
            else:
                del _login_attempts[ip]
    return False

def record_failed_attempt(ip):
    if ip in _login_attempts:
        attempts, _ = _login_attempts[ip]
        _login_attempts[ip] = (attempts + 1, time.time())
    else:
        _login_attempts[ip] = (1, time.time())

def clear_attempts(ip):
    _login_attempts.pop(ip, None)

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('authenticated'):
            return redirect(url_for('auth.login'))
        if time.time() - session.get('login_time', 0) > SESSION_LIFETIME:
            session.clear()
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated
```

### 4.4 Auth Routes — Added to Flask App

```python
# Login page
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        # Verify against stored hash in bot_data.db
        # Set session['authenticated'] = True on success
        # Rate limit failed attempts
    return render_template('login.html')

# First-run password setup
@auth_bp.route('/setup', methods=['GET', 'POST'])
def setup():
    # Only accessible if no password has been set yet
    # User creates their dashboard password on first visit
    return render_template('setup.html')

# Logout
@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
```

### 4.5 Database Addition

Add to the `settings` table in bot_data.db:

```sql
-- Stored in the existing global settings
-- Key: 'gui_password_hash'
-- Value: bcrypt hash of the user's chosen password
```

No new tables needed — uses the existing settings key-value store.

### 4.6 Login Page Template

Clean, branded login page with:
- Password field
- "Remember me" checkbox (extends session to 7 days)
- Error messages for failed attempts
- Lockout notification (5 failed = 5 min lockout)
- First-run redirect to password setup page

---

## Phase 5: Admin Management Scripts

### 5.1 User Provisioning Script

Create `/opt/botifytrades/scripts/add_user.sh`:

```bash
#!/bin/bash
set -e

USERNAME=$1
HOST_PORT=$2

if [ -z "$USERNAME" ] || [ -z "$HOST_PORT" ]; then
    echo "Usage: ./add_user.sh <username> <host_port>"
    echo "Example: ./add_user.sh john 5001"
    exit 1
fi

USER_DIR="/opt/botifytrades/users/$USERNAME"

echo "=== Creating user: $USERNAME (port $HOST_PORT) ==="

# Create user directory
mkdir -p "$USER_DIR/data" "$USER_DIR/logs"

# Create empty database (bot will initialize on first run)
touch "$USER_DIR/bot_data.db"

# Copy .env template
cp /opt/botifytrades/configs/.env.template "$USER_DIR/.env"

echo "1. User directory created: $USER_DIR"
echo "2. Edit the .env file: nano $USER_DIR/.env"
echo "3. Add service to docker-compose.yml:"
echo ""
echo "  user-$USERNAME:"
echo "    build: ."
echo "    container_name: botify-$USERNAME"
echo "    restart: unless-stopped"
echo "    env_file:"
echo "      - ./users/$USERNAME/.env"
echo "    volumes:"
echo "      - ./users/$USERNAME/data:/app/data"
echo "      - ./users/$USERNAME/logs:/app/logs"
echo "      - ./users/$USERNAME/bot_data.db:/app/bot_data.db"
echo "    ports:"
echo "      - \"$HOST_PORT:5001\""
echo "    networks:"
echo "      - botify-net"
echo "    deploy:"
echo "      resources:"
echo "        limits:"
echo "          memory: 512M"
echo "          cpus: \"0.5\""
echo ""
echo "4. Add to cloudflared config.yml:"
echo "  - hostname: $USERNAME.botifytrades.com"
echo "    service: http://localhost:$HOST_PORT"
echo ""
echo "5. Create DNS route:"
echo "   cloudflared tunnel route dns botifytrades $USERNAME.botifytrades.com"
echo ""
echo "6. Restart services:"
echo "   docker compose up -d user-$USERNAME"
echo "   systemctl restart cloudflared"
```

### 5.2 Code Update Script

Create `/opt/botifytrades/scripts/update_all.sh`:

```bash
#!/bin/bash
set -e

echo "=== BotifyTrades — Update All Containers ==="

cd /opt/botifytrades

# Pull latest code (from your private git repo)
git pull origin main

# Rebuild Docker image
echo "Building new image..."
docker compose build --no-cache

# Rolling restart — one container at a time
for container in $(docker compose ps --services); do
    echo "Restarting $container..."
    docker compose up -d --no-deps "$container"
    sleep 5  # Wait for container to stabilize
done

echo "=== Update complete ==="
docker compose ps
```

### 5.3 Backup Script

Create `/opt/botifytrades/scripts/backup_all.sh`:

```bash
#!/bin/bash
set -e

BACKUP_DIR="/opt/botifytrades/backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

echo "=== Backing up all user databases ==="

for USER_DIR in /opt/botifytrades/users/*/; do
    USERNAME=$(basename "$USER_DIR")
    if [ -f "$USER_DIR/bot_data.db" ]; then
        cp "$USER_DIR/bot_data.db" "$BACKUP_DIR/${USERNAME}_bot_data.db"
        echo "✓ Backed up: $USERNAME"
    fi
done

# Keep only last 7 days of backups
find /opt/botifytrades/backups/ -maxdepth 1 -type d -mtime +7 -exec rm -rf {} +

echo "=== Backup complete: $BACKUP_DIR ==="
ls -la "$BACKUP_DIR"
```

### 5.4 Monitoring Script

Create `/opt/botifytrades/scripts/health_check.sh`:

```bash
#!/bin/bash

echo "=== BotifyTrades Health Check ==="
echo ""

# Container status
echo "--- Container Status ---"
docker compose ps

echo ""
echo "--- Resource Usage ---"
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}"

echo ""
echo "--- Health Endpoints ---"
for USER_DIR in /opt/botifytrades/users/*/; do
    USERNAME=$(basename "$USER_DIR")
    PORT=$(docker port "botify-$USERNAME" 5001 2>/dev/null | cut -d: -f2)
    if [ -n "$PORT" ]; then
        STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$PORT/health" 2>/dev/null || echo "DOWN")
        echo "  $USERNAME (port $PORT): $STATUS"
    fi
done

echo ""
echo "--- Disk Usage ---"
du -sh /opt/botifytrades/users/*/bot_data.db 2>/dev/null
```

### 5.5 Cron Jobs

```bash
# Add to crontab (crontab -e)

# Backup all databases daily at 2 AM
0 2 * * * /opt/botifytrades/scripts/backup_all.sh >> /var/log/botify-backup.log 2>&1

# Health check every 5 minutes
*/5 * * * * /opt/botifytrades/scripts/health_check.sh >> /var/log/botify-health.log 2>&1

# Auto-restart crashed containers every minute
* * * * * cd /opt/botifytrades && docker compose up -d >> /dev/null 2>&1
```

---

## Phase 6: Step-by-Step Deployment Walkthrough

### Day 1: Server + Docker

```bash
# 1. Get a VPS (Hetzner/Contabo/DigitalOcean)
# 2. SSH in and run:

apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh
apt install docker-compose-plugin git -y

mkdir -p /opt/botifytrades
cd /opt/botifytrades

# 3. Clone your private repo
git clone https://github.com/yourorg/botifytrades.git .

# 4. Build the Docker image
docker build -t botifytrades:latest .
```

### Day 1: Cloudflare Tunnel

```bash
# 5. Install cloudflared
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb \
  -o cloudflared.deb && dpkg -i cloudflared.deb

# 6. Login and create tunnel
cloudflared tunnel login
cloudflared tunnel create botifytrades

# 7. Copy config (edit with your tunnel ID)
cp configs/cloudflared-config.yml /etc/cloudflared/config.yml
nano /etc/cloudflared/config.yml

# 8. Start tunnel
cloudflared service install
systemctl enable cloudflared
systemctl start cloudflared
```

### Day 1: First User

```bash
# 9. Provision first user
./scripts/add_user.sh john 5001

# 10. Edit their .env with their credentials
nano users/john/.env

# 11. Start the container
docker compose up -d user-john

# 12. Create DNS route
cloudflared tunnel route dns botifytrades john.botifytrades.com

# 13. Test access
curl https://john.botifytrades.com
```

### Adding More Users (5 minutes each)

```bash
./scripts/add_user.sh mike 5002
nano users/mike/.env
# Add service to docker-compose.yml (copy template from add_user output)
docker compose up -d user-mike
cloudflared tunnel route dns botifytrades mike.botifytrades.com
systemctl restart cloudflared
```

---

## Phase 7: Security Checklist

### Server Level
- [ ] SSH key-only login (disable password SSH)
- [ ] UFW firewall — only allow SSH (port 22), block all other inbound
- [ ] Automatic security updates (`unattended-upgrades`)
- [ ] Non-root user for daily operations
- [ ] Fail2ban for SSH brute-force protection

### Cloudflare Level
- [ ] Cloudflare Access enabled (email OTP or Google login)
- [ ] SSL mode set to "Full (Strict)"
- [ ] WAF rules enabled (free tier includes basic protection)
- [ ] Bot protection enabled
- [ ] Rate limiting on login endpoints

### Application Level
- [ ] Flask GUI login with bcrypt-hashed passwords
- [ ] Session cookies: HttpOnly, Secure, SameSite=Lax
- [ ] Login rate limiting (5 attempts, 5-min lockout)
- [ ] CSRF tokens on all forms
- [ ] Auto-logout after 24 hours

### Container Level
- [ ] Resource limits (512MB RAM, 0.5 CPU per container)
- [ ] Read-only file system where possible
- [ ] No privileged containers
- [ ] Separate Docker network (no inter-container communication needed)

### Data Level
- [ ] Daily automated backups
- [ ] Broker credentials encrypted in bot_data.db (existing AES encryption)
- [ ] .env files readable only by root (`chmod 600`)
- [ ] No credentials in Docker image (all via .env mount)

---

## Phase 8: Cost Analysis

### Per-User Cost Breakdown

| Component         | Cost/User/Month | Notes                                |
|-------------------|-----------------|--------------------------------------|
| VPS share          | $2-4            | Based on 15-20 users per $60 server |
| Cloudflare         | $0              | Free plan covers everything needed  |
| Cloudflare Access  | $0              | Free for <50 users                  |
| Domain             | ~$1             | $12/year ÷ 12                       |
| Backups            | $0-2            | VPS disk or S3                       |
| **Total**          | **$3-7/user**   |                                      |

### Scaling Path

| Users | Infrastructure                     | Monthly Cost  |
|-------|-------------------------------------|---------------|
| 1-15  | 1 × 8GB VPS                        | $40-60        |
| 15-30 | 1 × 16GB VPS                       | $60-100       |
| 30-50 | 2 × 16GB VPS + load distribution   | $120-200      |
| 50+   | 3+ VPS with per-region deployment  | $200+         |

---

## File Structure on VPS

```
/opt/botifytrades/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── start.py
├── src/                          ← Bot source code
├── gui_app/                      ← Flask GUI (with auth)
│
├── configs/
│   ├── .env.template             ← Template for new users
│   └── cloudflared-config.yml    ← Tunnel route config
│
├── users/
│   ├── john/
│   │   ├── .env                  ← John's credentials
│   │   ├── bot_data.db           ← John's database
│   │   ├── data/                 ← John's data files
│   │   └── logs/                 ← John's log files
│   ├── mike/
│   │   ├── .env
│   │   ├── bot_data.db
│   │   ├── data/
│   │   └── logs/
│   └── sara/
│       └── ...
│
├── scripts/
│   ├── add_user.sh               ← Provision new user
│   ├── update_all.sh             ← Deploy code updates
│   ├── backup_all.sh             ← Backup all databases
│   └── health_check.sh           ← Monitor all containers
│
├── backups/
│   ├── 20260401_020000/
│   │   ├── john_bot_data.db
│   │   └── mike_bot_data.db
│   └── ...
│
└── cloudflared/
    └── config.yml                ← Tunnel routing rules
```

---

## Quick Reference Commands

```bash
# Start all containers
docker compose up -d

# Start one user
docker compose up -d user-john

# Stop one user
docker compose stop user-john

# View logs for a user
docker compose logs -f user-john

# Restart after code update
docker compose build && docker compose up -d

# Check resource usage
docker stats

# Add Cloudflare DNS route
cloudflared tunnel route dns botifytrades newuser.botifytrades.com

# Restart tunnel after config change
systemctl restart cloudflared

# Backup single user
cp users/john/bot_data.db backups/john_$(date +%Y%m%d).db

# Enter a container for debugging
docker exec -it botify-john bash
```

---

## Summary

| Step | What | Time  |
|------|------|-------|
| 1    | Buy VPS, install Docker | 30 min |
| 2    | Clone code, build Docker image | 15 min |
| 3    | Install cloudflared, create tunnel | 15 min |
| 4    | Add Flask GUI authentication | 2-3 hours (code change) |
| 5    | Provision first user | 10 min |
| 6    | Set up backup cron jobs | 10 min |
| 7    | Each additional user | 5 min |

**Total setup time: ~4 hours for the first time, 5 minutes per new user after that.**

The only code change needed in BotifyTrades itself is **Phase 4 — adding login authentication to the Flask GUI**. Everything else is infrastructure and scripts around the existing bot.
