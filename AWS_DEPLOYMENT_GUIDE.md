# Ψ∿ QuantumPulse - AWS Linux EC2 Deployment Guide

Complete guide to deploy **QuantumPulse Discord Trading Bot** on AWS Linux server with 24/7 operation, systemd auto-restart, and web GUI access.

---

## 📋 **Prerequisites**

Before starting, make sure you have:

✅ **AWS EC2 Instance** (t2.micro eligible for free tier)  
✅ **SSH Access** to your EC2 instance  
✅ **Discord User Token**  
✅ **Webull Credentials** (access token, refresh token, trade PIN, device ID)  
✅ **API Keys** (optional):
   - OpenAI API Key (for AI trade analysis)
   - Alpha Vantage API Key (for option flow scanning)
   - Finnhub API Key (for real-time news)
   - Alpaca API Key + Secret (for live option chains)

---

## 🚀 **Part 1: Launch & Configure EC2 Instance**

### **Step 1: Launch EC2 Instance**

1. **Go to AWS Console** → EC2 → Launch Instance
2. **Choose AMI**: Amazon Linux 2023 (recommended) or Ubuntu 22.04
3. **Instance Type**: `t2.micro` (1 vCPU, 1GB RAM - free tier eligible)
4. **Key Pair**: Create/select your `.pem` file for SSH access
5. **Security Group**: Configure these rules:
   - **SSH (Port 22)**: Your IP address (for secure access)
   - **HTTP (Port 5000)**: Your IP or `0.0.0.0/0` (for web GUI access)
6. **Storage**: 10GB minimum (default 8GB is fine)
7. Click **Launch Instance**

### **Step 2: Connect to Your EC2 Instance**

```bash
# Make your key file secure
chmod 400 your-key.pem

# Connect via SSH (replace with your EC2 public IP)
ssh -i your-key.pem ec2-user@your-ec2-public-ip

# If using Ubuntu:
ssh -i your-key.pem ubuntu@your-ec2-public-ip
```

---

## 📦 **Part 2: Install Python & System Dependencies**

### **For Amazon Linux 2023:**

```bash
# Update system
sudo yum update -y

# Install Python 3.11, pip, git
sudo yum install python3.11 python3.11-pip git -y

# Install additional dependencies
sudo yum install gcc python3.11-devel -y
```

### **For Ubuntu 22.04:**

```bash
# Update system
sudo apt update
sudo apt upgrade -y

# Install Python 3.11, pip, git
sudo apt install python3.11 python3.11-venv python3-pip git -y

# Install additional dependencies
sudo apt install build-essential python3.11-dev -y
```

### **Verify Installation:**

```bash
python3.11 --version  # Should show: Python 3.11.x
pip3.11 --version     # Should show pip version
```

---

## 💾 **Part 3: Download QuantumPulse Bot Code**

You have **3 options** to get your code onto AWS:

### **Option 1: Download from Replit (Easiest)**

```bash
# On your AWS EC2 instance:
cd /home/ec2-user
mkdir quantumpulse-bot
cd quantumpulse-bot

# Download from Replit via ZIP export
# (First, on Replit: Click "⋮" menu → Download as ZIP)
# Then upload to EC2:
```

**On your local machine:**
```bash
scp -i your-key.pem /path/to/quantumpulse.zip ec2-user@your-ec2-ip:/home/ec2-user/
```

**Back on EC2:**
```bash
cd /home/ec2-user
unzip quantumpulse.zip
cd quantumpulse-bot  # or whatever folder name it creates
```

### **Option 2: Transfer via Git (Recommended)**

```bash
# Push your Replit code to GitHub first, then on EC2:
cd /home/ec2-user
git clone https://github.com/yourusername/quantumpulse-bot.git
cd quantumpulse-bot
```

### **Option 3: Direct File Transfer with SCP**

```bash
# On your local machine (if you have the code locally):
scp -i your-key.pem -r /path/to/quantumpulse-bot ec2-user@your-ec2-ip:/home/ec2-user/
```

---

## 🔧 **Part 4: Setup Python Environment**

```bash
# Navigate to bot directory
cd /home/ec2-user/quantumpulse-bot

# Create virtual environment (recommended)
python3.11 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install all dependencies
pip install -r requirements.txt
```

**Expected output:**
```
Successfully installed discord.py-self-1.9.2 webull-0.2.5 Flask-3.0.0 
cryptography-41.0.7 requests-2.31.0 openai-1.3.0 ta-0.11.0 
yfinance-0.2.32 aiohttp-3.9.1 alpaca-py-0.14.0 ib-insync-0.9.86 ...
```

---

## ⚙️ **Part 5: Configure Bot Settings**

### **Create Configuration File**

```bash
# Copy example config (if it exists)
cp config.ini.example config.ini

# OR create new config file
nano config.ini
```

### **Paste Configuration (Edit with YOUR credentials):**

```ini
[Discord]
user_token = YOUR_DISCORD_USER_TOKEN

[Webull]
access_token = YOUR_WEBULL_ACCESS_TOKEN
refresh_token = YOUR_WEBULL_REFRESH_TOKEN
trade_pin = YOUR_6_DIGIT_PIN
device_id = YOUR_WEBULL_DEVICE_ID

[Trading]
paper_trade = true
max_position_size = 500
profit_target_pct = 20
stop_loss_pct = 10
trailing_stop_pct = 5

[License]
license_key = TRIAL

[API_Keys]
openai_api_key = YOUR_OPENAI_KEY
alpha_vantage_api_key = YOUR_ALPHAVANTAGE_KEY
finnhub_api_key = YOUR_FINNHUB_KEY
alpaca_api_key = YOUR_ALPACA_KEY
alpaca_secret_key = YOUR_ALPACA_SECRET

[Webhook]
discord_webhook_url = YOUR_DISCORD_WEBHOOK_URL
```

**Save and exit:** Press `Ctrl+O`, `Enter`, `Ctrl+X`

### **Set File Permissions (Security)**

```bash
# Protect config file from unauthorized access
chmod 600 config.ini
```

---

## 🧪 **Part 6: Test Bot Manually**

Before setting up the systemd service, test the bot manually:

```bash
# Make sure you're in the bot directory with venv activated
cd /home/ec2-user/quantumpulse-bot
source venv/bin/activate

# Run the bot
python3 src/selfbot_webull.py
```

**Expected output:**
```
🔐 License validated: TRIAL (6 days remaining)
✅ Discord login successful!
✅ Webull session refreshed
🌐 Flask web GUI running on http://0.0.0.0:5000
📡 Monitoring Discord channels...
```

**Test Web GUI Access:**

Open your browser and visit:
```
http://your-ec2-public-ip:5000
```

You should see the **QuantumPulse Dashboard**!

**Stop the bot:** Press `Ctrl+C`

---

## 🔄 **Part 7: Setup Systemd Service (24/7 Auto-Restart)**

### **Step 1: Create Service File**

```bash
sudo nano /etc/systemd/system/quantumpulse-bot.service
```

### **Step 2: Paste This Configuration**

**For Amazon Linux (ec2-user):**

```ini
[Unit]
Description=QuantumPulse Discord Trading Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ec2-user
Group=ec2-user
WorkingDirectory=/home/ec2-user/quantumpulse-bot
Environment="PATH=/home/ec2-user/quantumpulse-bot/venv/bin"
ExecStart=/home/ec2-user/quantumpulse-bot/venv/bin/python3 src/selfbot_webull.py
Restart=on-failure
RestartSec=30
TimeoutStopSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**For Ubuntu (ubuntu user):**
Replace all instances of `ec2-user` with `ubuntu` in the above configuration.

**Save and exit:** `Ctrl+O`, `Enter`, `Ctrl+X`

### **Step 3: Start and Enable Service**

```bash
# Reload systemd to recognize new service
sudo systemctl daemon-reload

# Start the bot
sudo systemctl start quantumpulse-bot.service

# Check status
sudo systemctl status quantumpulse-bot.service

# Enable auto-start on boot
sudo systemctl enable quantumpulse-bot.service
```

**Expected output:**
```
● quantumpulse-bot.service - QuantumPulse Discord Trading Bot
   Loaded: loaded (/etc/systemd/system/quantumpulse-bot.service; enabled)
   Active: active (running) since Mon 2025-01-18 12:34:56 UTC
```

---

## 📊 **Part 8: Manage & Monitor the Bot**

### **Common Service Commands:**

```bash
# Check bot status
sudo systemctl status quantumpulse-bot.service

# Stop the bot
sudo systemctl stop quantumpulse-bot.service

# Start the bot
sudo systemctl start quantumpulse-bot.service

# Restart the bot (apply config changes)
sudo systemctl restart quantumpulse-bot.service

# View live logs (last 50 lines, follow mode)
sudo journalctl -u quantumpulse-bot.service -n 50 -f

# View all logs
sudo journalctl -u quantumpulse-bot.service --no-pager

# View logs from today only
sudo journalctl -u quantumpulse-bot.service --since today

# Search logs for errors
sudo journalctl -u quantumpulse-bot.service | grep ERROR
```

### **Check if Bot is Running:**

```bash
# Check process
ps aux | grep selfbot_webull.py

# Check web GUI (should return HTML)
curl http://localhost:5000
```

---

## 🌐 **Part 9: Access Web GUI from Your Computer**

### **Option 1: Direct Access (Security Group Port 5000 Open)**

Simply visit in your browser:
```
http://your-ec2-public-ip:5000
```

### **Option 2: SSH Tunnel (More Secure)**

If you didn't open port 5000 in security group:

```bash
# On your local machine, create SSH tunnel:
ssh -i your-key.pem -L 5000:localhost:5000 ec2-user@your-ec2-ip

# Then access via:
http://localhost:5000
```

### **Option 3: Setup Nginx Reverse Proxy (Production)**

```bash
# Install Nginx
sudo yum install nginx -y  # Amazon Linux
# OR
sudo apt install nginx -y  # Ubuntu

# Configure reverse proxy
sudo nano /etc/nginx/conf.d/quantumpulse.conf
```

**Paste:**
```nginx
server {
    listen 80;
    server_name your-domain.com;  # Or your-ec2-public-ip

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

```bash
# Start Nginx
sudo systemctl start nginx
sudo systemctl enable nginx

# Now access via: http://your-ec2-public-ip (port 80)
```

---

## 🔐 **Part 10: Security Best Practices**

### **1. Secure Your API Keys**

```bash
# Use environment variables instead of config.ini
nano /home/ec2-user/quantumpulse-bot/.env
```

**Add:**
```bash
DISCORD_TOKEN=your_discord_token
WEBULL_ACCESS_TOKEN=your_access_token
OPENAI_API_KEY=your_openai_key
```

**Update systemd service:**
```ini
# Add this line in [Service] section:
EnvironmentFile=/home/ec2-user/quantumpulse-bot/.env
```

### **2. Restrict SSH Access**

```bash
# Edit security group to only allow YOUR IP for SSH
# AWS Console → EC2 → Security Groups → Edit Inbound Rules
# SSH (22): My IP instead of 0.0.0.0/0
```

### **3. Setup Firewall (Optional)**

```bash
# Amazon Linux (firewalld)
sudo firewall-cmd --permanent --add-port=5000/tcp
sudo firewall-cmd --reload

# Ubuntu (ufw)
sudo ufw allow 5000/tcp
sudo ufw enable
```

### **4. Regular Updates**

```bash
# Amazon Linux
sudo yum update -y

# Ubuntu
sudo apt update && sudo apt upgrade -y
```

---

## 🔄 **Part 11: Update Bot Code**

When you need to update the bot:

```bash
# 1. Connect to EC2
ssh -i your-key.pem ec2-user@your-ec2-ip

# 2. Navigate to bot directory
cd /home/ec2-user/quantumpulse-bot

# 3. Pull latest changes (if using Git)
git pull origin main

# OR upload new files via SCP from local machine:
# scp -i your-key.pem -r ./updated-files ec2-user@your-ec2-ip:/home/ec2-user/quantumpulse-bot/

# 4. Update dependencies if requirements.txt changed
source venv/bin/activate
pip install -r requirements.txt

# 5. Restart the service
sudo systemctl restart quantumpulse-bot.service

# 6. Verify it's running
sudo systemctl status quantumpulse-bot.service
```

---

## 🛠️ **Troubleshooting**

### **Bot won't start - Check logs:**

```bash
sudo journalctl -u quantumpulse-bot.service -n 100 --no-pager
```

### **Common Issues:**

#### **"Module not found" errors**
```bash
cd /home/ec2-user/quantumpulse-bot
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart quantumpulse-bot.service
```

#### **"Permission denied" errors**
```bash
sudo chown -R ec2-user:ec2-user /home/ec2-user/quantumpulse-bot
chmod 600 /home/ec2-user/quantumpulse-bot/config.ini
```

#### **Web GUI not accessible**
```bash
# Check if Flask is running on port 5000
sudo netstat -tulpn | grep 5000

# Check security group allows port 5000 inbound
# AWS Console → EC2 → Security Groups → Inbound Rules

# Test locally on EC2
curl http://localhost:5000
```

#### **Discord login fails**
```bash
# Regenerate your Discord token (it may have expired)
# Use GET_DISCORD_TOKEN.html locally, then update config.ini
nano /home/ec2-user/quantumpulse-bot/config.ini
# Update user_token, save, then:
sudo systemctl restart quantumpulse-bot.service
```

#### **Webull tokens expired**
```bash
# Use GET_WEBULL_TOKENS.html locally to get fresh tokens
nano /home/ec2-user/quantumpulse-bot/config.ini
# Update access_token, refresh_token, then:
sudo systemctl restart quantumpulse-bot.service
```

#### **Bot crashes immediately**
```bash
# Test manually to see detailed error
cd /home/ec2-user/quantumpulse-bot
source venv/bin/activate
python3 src/selfbot_webull.py
# Fix the error shown, then restart service
```

---

## 📊 **Part 12: Monitor System Resources**

```bash
# Check CPU/RAM usage
htop
# OR
top

# Check disk space
df -h

# Check bot's memory usage
ps aux | grep selfbot_webull.py

# Monitor network connections
sudo netstat -tulpn | grep python3
```

**Recommended System Requirements:**
- **CPU**: 1 vCPU (t2.micro sufficient)
- **RAM**: 1GB minimum, 2GB recommended
- **Storage**: 10GB
- **Network**: Stable internet connection

---

## 💰 **AWS Costs**

### **Free Tier Eligible (First 12 Months):**
- **t2.micro**: 750 hours/month FREE (enough for 24/7 operation)
- **Storage**: 30GB EBS free
- **Data Transfer**: 15GB outbound free

### **After Free Tier:**
- **t2.micro**: ~$8-10/month
- **Storage (10GB)**: ~$1/month
- **Total**: ~$9-11/month

**Tip:** Set up billing alerts in AWS Console to avoid surprises!

---

## 🎉 **You're Live on AWS!**

Your **QuantumPulse** bot is now running 24/7 on AWS with:

✅ **Automatic restarts** on crashes  
✅ **Boot persistence** (starts automatically after server reboot)  
✅ **Web GUI access** via `http://your-ec2-ip:5000`  
✅ **Systemd logging** for easy debugging  
✅ **Secure credential management**  
✅ **Production-ready deployment**  

**Access Points:**
- **Web Dashboard**: `http://your-ec2-public-ip:5000`
- **SSH Console**: `ssh -i your-key.pem ec2-user@your-ec2-ip`
- **Logs**: `sudo journalctl -u quantumpulse-bot.service -f`

**Happy Trading!** 🚀📈
