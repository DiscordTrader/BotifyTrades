#!/bin/bash
# Ψ∿ QuantumPulse - AWS EC2 Quick Setup Script
# Run this on your AWS Linux instance for automated installation

set -e  # Exit on any error

echo "🚀 QuantumPulse AWS Deployment - Quick Setup"
echo "==========================================="
echo ""

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
else
    echo "❌ Cannot detect OS. Please use manual installation."
    exit 1
fi

echo "✓ Detected OS: $OS"

# Update system
echo ""
echo "📦 Step 1: Updating system packages..."
if [ "$OS" = "amzn" ]; then
    sudo yum update -y
    sudo yum install python3.11 python3.11-pip git gcc python3.11-devel -y
elif [ "$OS" = "ubuntu" ] || [ "$OS" = "debian" ]; then
    sudo apt update
    sudo apt upgrade -y
    sudo apt install python3.11 python3.11-venv python3-pip git build-essential python3.11-dev -y
else
    echo "⚠️  Unknown OS. Please install Python 3.11 manually."
    exit 1
fi

echo "✓ System updated and Python 3.11 installed"

# Create bot directory
echo ""
echo "📁 Step 2: Creating bot directory..."
cd ~
mkdir -p quantumpulse-bot
cd quantumpulse-bot

echo "✓ Directory created: ~/quantumpulse-bot"

# Setup Python virtual environment
echo ""
echo "🐍 Step 3: Setting up Python virtual environment..."
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip

echo "✓ Virtual environment created"

echo ""
echo "==========================================="
echo "✅ Base setup complete!"
echo ""
echo "📋 Next Steps:"
echo ""
echo "1. Upload your bot files to ~/quantumpulse-bot/"
echo "   Option A: Use SCP from local machine:"
echo "            scp -i your-key.pem -r ./bot-files/* ec2-user@your-ec2-ip:~/quantumpulse-bot/"
echo ""
echo "   Option B: Clone from GitHub:"
echo "            git clone https://github.com/yourusername/repo.git ~/quantumpulse-bot"
echo ""
echo "2. Install dependencies:"
echo "   cd ~/quantumpulse-bot"
echo "   source venv/bin/activate"
echo "   pip install -r requirements.txt"
echo ""
echo "3. Configure credentials:"
echo "   nano config.ini"
echo ""
echo "4. Test the bot:"
echo "   python3 src/selfbot_webull.py"
echo ""
echo "5. Setup systemd service (see AWS_DEPLOYMENT_GUIDE.md)"
echo ""
echo "📚 Full guide: cat AWS_DEPLOYMENT_GUIDE.md"
echo "==========================================="
