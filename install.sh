#!/bin/bash

# 🛠️ CONFIGURATION
GITHUB_USER="Wouamm"
REPO_NAME="proxmox-lcd-matrix-orbital"
BRANCH="main"

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

echo "🔍 Detecting Matrix Orbital screens..."

while true; do
    SERIAL_DEVICES=(/dev/serial/by-id/*)

    # Check if any serial devices are connected
    if [ ! -e "${SERIAL_DEVICES[0]}" ]; then
        echo "⚠️ No serial devices found in /dev/serial/by-id/."
        echo "   Please ensure your Matrix Orbital screen is plugged in."
        echo ""
        
        # Propose to retry or skip
        PS3="👉 What would you like to do? "
        REPLY="" # Reset selection to force menu redraw
        select OPT in "Retry detection (after plugging in the screen)" "Skip auto-configuration and continue"; do
            case $REPLY in
                1) echo "🔄 Retrying detection..."; break ;;
                2) echo "Skipping auto-configuration. Keeping the default placeholder."; SELECTED_PORT="/dev/serial/by-id/usb-MO_MX2_MX3_MX6_xxxxx-if00-port0"; break 2 ;;
                *) echo "❌ Invalid selection." ;;
            esac
        done
    else
        # If devices are found, show the selection menu
        echo "Found the following serial devices:"
        PS3="👉 Please select the number corresponding to your Matrix Orbital screen: "
        REPLY="" # Reset selection to force menu redraw
        
        select DEVICE in "${SERIAL_DEVICES[@]}" "Configure manually later"; do
            if [ "$DEVICE" == "Configure manually later" ]; then
                echo "Skipping auto-configuration. Keeping the default placeholder."
                SELECTED_PORT="/dev/serial/by-id/usb-MO_MX2_MX3_MX6_xxxxx-if00-port0"
                break 2
            elif [ -n "$DEVICE" ]; then
                echo "✅ You selected: $DEVICE"
                SELECTED_PORT="$DEVICE"
                break 2
            else
                echo "❌ Invalid selection."
            fi
        done
    fi
done

# Inject the selected port into the Python script
echo "⚙️ Injecting serial port into $SCRIPT_NAME..."
sed -i "s|^SERIAL_PORT\s*=.*|SERIAL_PORT       = '$SELECTED_PORT'|" "$SCRIPT_NAME"

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