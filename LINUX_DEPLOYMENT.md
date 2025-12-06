# 🐧 Linux Deployment Guide - QuantumPulse Trading Bot

## 📋 Overview

This guide covers deploying QuantumPulse on Linux servers (Ubuntu 20.04+, Debian 11+) for 24/7 operation using systemd.

---

## 🚀 Quick Start

### **Option 1: Simple Build (Recommended for Testing)**

```bash
# Make executable
chmod +x build_linux_simple.sh

# Build
./build_linux_simple.sh

# Test
cd dist
./DiscordTradingBot
```

### **Option 2: Protected Build (Recommended for Production)**

```bash
# Make executable
chmod +x build_linux_protected.sh

# Build with PyArmor obfuscation
./build_linux_protected.sh

# Test
cd dist
./DiscordTradingBot
```

---

## 🔧 System Requirements

### **Minimum Specs:**
- **OS:** Ubuntu 20.04+, Debian 11+, or compatible
- **CPU:** 1 core (2+ recommended)
- **RAM:** 512 MB (1 GB+ recommended)
- **Disk:** 500 MB free space
- **Python:** 3.8+ (3.11+ recommended)

### **Required System Packages:**

```bash
sudo apt update
sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    build-essential \
    libffi-dev \
    libssl-dev \
    python3-dev
```

---

## 📦 Installation Methods

### **Method 1: Pre-Built Binary (Fastest)**

```bash
# 1. Copy dist folder from build machine
scp -r dist/ user@server:/opt/discord-trading-bot/

# 2. Make executable
chmod +x /opt/discord-trading-bot/DiscordTradingBot

# 3. Run
cd /opt/discord-trading-bot
./DiscordTradingBot
```

### **Method 2: Build on Server**

```bash
# 1. Clone/upload project to server
cd /opt
sudo git clone <your-repo> discord-trading-bot
cd discord-trading-bot

# 2. Build
chmod +x build_linux_simple.sh
./build_linux_simple.sh

# 3. Run from dist/
cd dist
./DiscordTradingBot
```

---

## 🔐 Credential Storage (Cross-Platform)

The bot uses different encryption methods per platform:

### **Windows:**
- Uses **Windows DPAPI** (Data Protection API)
- Credentials stored in: `%USERPROFILE%\.discord_trading_bot\credentials.dat`

### **Linux:**
- Uses **cryptography.Fernet** with machine-bound key derivation
- Credentials stored in: `~/.discord_trading_bot/credentials.dat`
- Key derived from: MAC address + CPU serial + hostname + salt

### **Security Notes:**
- ✅ Credentials encrypted at rest
- ✅ Machine-bound encryption (cannot copy to another server)
- ✅ No plaintext passwords in config files
- ✅ Automatic encryption on save

---

## 🔄 Systemd Service (24/7 Operation)

### **Create Systemd Service**

```bash
# 1. Create service file
sudo nano /etc/systemd/system/discord-trading-bot.service
```

**Paste this configuration:**

```ini
[Unit]
Description=QuantumPulse Discord Trading Bot
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/opt/discord-trading-bot/dist
ExecStart=/opt/discord-trading-bot/dist/DiscordTradingBot

# Restart policy
Restart=always
RestartSec=10

# Environment
Environment="PYTHONUNBUFFERED=1"

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=discord-trading-bot

# Security (optional hardening)
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

**Replace `YOUR_USERNAME` with your actual Linux username.**

---

### **Enable and Start Service**

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service (start on boot)
sudo systemctl enable discord-trading-bot

# Start service
sudo systemctl start discord-trading-bot

# Check status
sudo systemctl status discord-trading-bot
```

---

### **Service Management Commands**

```bash
# Start bot
sudo systemctl start discord-trading-bot

# Stop bot
sudo systemctl stop discord-trading-bot

# Restart bot
sudo systemctl restart discord-trading-bot

# Check status
sudo systemctl status discord-trading-bot

# View logs (real-time)
sudo journalctl -u discord-trading-bot -f

# View last 100 lines
sudo journalctl -u discord-trading-bot -n 100

# View logs since boot
sudo journalctl -u discord-trading-bot -b
```

---

## 📊 Monitoring & Logs

### **View Real-Time Logs:**
```bash
sudo journalctl -u discord-trading-bot -f
```

### **View Logs with Timestamps:**
```bash
sudo journalctl -u discord-trading-bot --since "1 hour ago"
sudo journalctl -u discord-trading-bot --since "2024-01-01"
```

### **Export Logs to File:**
```bash
sudo journalctl -u discord-trading-bot > bot-logs.txt
```

### **Web GUI Access:**
```bash
# Bot runs web GUI on http://localhost:5000 by default
# Access remotely via SSH tunnel:
ssh -L 5000:localhost:5000 user@server

# Then open in browser:
# http://localhost:5000
```

---

## 🔄 Updates & Maintenance

### **Update Bot (Without Systemd)**

```bash
# 1. Stop service
sudo systemctl stop discord-trading-bot

# 2. Backup old version
sudo mv /opt/discord-trading-bot /opt/discord-trading-bot.backup

# 3. Upload new version
sudo cp -r new-dist/ /opt/discord-trading-bot/

# 4. Restore credentials (if needed)
sudo cp /opt/discord-trading-bot.backup/credentials.dat \
        /opt/discord-trading-bot/

# 5. Start service
sudo systemctl start discord-trading-bot
```

### **Update Bot (With Git)**

```bash
# 1. Stop service
sudo systemctl stop discord-trading-bot

# 2. Update code
cd /opt/discord-trading-bot
sudo git pull

# 3. Rebuild
./build_linux_simple.sh

# 4. Start service
sudo systemctl start discord-trading-bot
```

---

## 🔥 Firewall Configuration

If using `ufw`:

```bash
# Allow Flask web GUI (optional, for remote access)
sudo ufw allow 5000/tcp

# Check status
sudo ufw status
```

**Security Note:** Only expose port 5000 if you need remote access. Use SSH tunneling instead for better security.

---

## 🐛 Troubleshooting

### **Bot Won't Start:**

```bash
# Check service status
sudo systemctl status discord-trading-bot

# View detailed logs
sudo journalctl -u discord-trading-bot -n 50 --no-pager

# Test manually
cd /opt/discord-trading-bot/dist
./DiscordTradingBot
```

### **Permission Errors:**

```bash
# Fix ownership
sudo chown -R $USER:$USER /opt/discord-trading-bot

# Fix permissions
chmod +x /opt/discord-trading-bot/dist/DiscordTradingBot
```

### **Missing Dependencies:**

```bash
# Reinstall system packages
sudo apt install -y build-essential libffi-dev libssl-dev python3-dev

# Check Python version
python3 --version  # Should be 3.8+
```

### **Web GUI Not Accessible:**

```bash
# Check if port 5000 is in use
sudo netstat -tulpn | grep 5000

# Test locally
curl http://localhost:5000

# SSH tunnel (if accessing remotely)
ssh -L 5000:localhost:5000 user@server
```

---

## 🔐 License Activation on Linux

### **Get Machine ID:**

```bash
cd /opt/discord-trading-bot/dist
./get_machine_id.sh
```

**Output:**
```
============================================================
Machine Fingerprint Information
============================================================
Machine ID: 05db47931c6a8c9e
============================================================

Share this Machine ID with your license provider
to receive a machine-bound license key.
```

### **Activate License:**

```bash
# Run bot
./DiscordTradingBot

# Choose option 2 (Subscription License)
# Paste your machine-bound license key
```

---

## 📈 Performance Optimization

### **Increase Open File Limits:**

```bash
# Edit limits
sudo nano /etc/security/limits.conf

# Add these lines:
* soft nofile 65536
* hard nofile 65536

# Reboot or re-login
```

### **Enable Swap (for low-memory servers):**

```bash
# Create 2GB swap
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Make permanent
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

---

## 🔄 Backup & Recovery

### **Backup Credentials:**

```bash
# Backup credentials
cp ~/.discord_trading_bot/credentials.dat ~/credentials.dat.backup

# Backup license info
cp /opt/discord-trading-bot/dist/config.ini ~/config.ini.backup
```

### **Restore Credentials:**

```bash
# Restore credentials
cp ~/credentials.dat.backup ~/.discord_trading_bot/credentials.dat
```

---

## 📚 Additional Resources

- **Build Methods:** `BUILD_METHODS_GUIDE.md`
- **Credential Management:** `CREDENTIAL_MANAGEMENT.md`
- **Windows Deployment:** `LOCAL_RUN_GUIDE.md`
- **AWS EC2 Deployment:** `AWS_QUICK_START.sh`

---

## ✅ Production Checklist

```
✅ System packages installed
✅ Bot built successfully
✅ License activated
✅ Credentials configured
✅ Systemd service created
✅ Service enabled (starts on boot)
✅ Service running successfully
✅ Logs accessible via journalctl
✅ Web GUI accessible (if needed)
✅ Firewall configured
✅ Credentials backed up
✅ Monitoring setup (optional)
```

---

## 🎯 Summary

**For quick deployment:**
1. Run `./build_linux_simple.sh` or `./build_linux_protected.sh`
2. Copy `dist/` to `/opt/discord-trading-bot/`
3. Create systemd service
4. Enable and start service
5. Monitor with `journalctl -u discord-trading-bot -f`

**For production:**
- Use protected build (PyArmor)
- Setup systemd service
- Enable automatic restarts
- Monitor logs regularly
- Backup credentials
- Use SSH tunneling for remote GUI access

**🚀 You're ready for 24/7 Linux deployment!**
