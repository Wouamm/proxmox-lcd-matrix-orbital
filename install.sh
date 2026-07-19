#!/bin/bash

# 🛠️ CONFIGURATION
GITHUB_USER="Wouamm"
REPO_NAME="proxmox-lcd-matrix-orbital"
BRANCH="main" # Or master depending on your main branch

SCRIPT_NAME="proxmox-lcd-matrix-orbital.py"
INSTALL_DIR="/root/scripts"
URL_RAW="https://raw.githubusercontent.com/$GITHUB_USER/$REPO_NAME/$BRANCH"

echo "📂 Creating installation directory..."
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR" || exit 1

echo "🚀 Installing system prerequisites and Python modules (APT)..."
apt update && apt install python3-serial python3-psutil smartmontools lm-sensors curl -y

echo "📥 Downloading the latest version of $SCRIPT_NAME..."
curl -sSL "$URL_RAW/$SCRIPT_NAME" -o "$SCRIPT_NAME"

if [ ! -f "$SCRIPT_NAME" ] || [ ! -s "$SCRIPT_NAME" ]; then
    echo "❌ Error: Failed to download the script from GitHub. Please check your username or repository name."
    exit 1
fi

echo "⚙️ Configuring Systemd service..."
cat <<EOF > /etc/systemd/system/proxmox-lcd.service
[Unit]
Description=Matrix Orbital Display Script for Proxmox
After=pve-cluster.service network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 $INSTALL_DIR/$SCRIPT_NAME
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "🔄 Loading and enabling systemd service..."
systemctl daemon-reload
systemctl enable proxmox-lcd.service
systemctl restart proxmox-lcd.service

echo ""
echo "💡 Quick Tip: Don't forget to edit the script to configure your variables (Serial port, language, etc.):"
echo "   nano $INSTALL_DIR/$SCRIPT_NAME"
echo ""
echo "✅ Installation complete! Checking service status:"
systemctl status proxmox-lcd.service