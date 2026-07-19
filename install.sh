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

echo "===================================================="
echo "🎯 INTERACTIVE CONFIGURATION WIZARD"
echo "===================================================="

# 🌐 1. LANGUAGE SELECTION
echo "🌐 Selecting display language..."
PS3="👉 Please select your language: "
REPLY=""
select LANG_CHOICE in "English (EN)" "French (FR)"; do
    case $REPLY in
        1) SELECTED_LANG="EN"; break ;;
        2) SELECTED_LANG="FR"; break ;;
        *) echo "❌ Invalid selection." ;;
    esac
done
echo "✅ Language set to: $SELECTED_LANG"
echo ""

# 🔌 2. SCREEN DETECT & SELECTION
echo "🔍 Detecting Matrix Orbital screens..."
while true; do
    SERIAL_DEVICES=(/dev/serial/by-id/*)

    if [ ! -e "${SERIAL_DEVICES[0]}" ]; then
        echo "⚠️ No serial devices found in /dev/serial/by-id/."
        echo "   Please ensure your Matrix Orbital screen is plugged in."
        echo ""
        
        PS3="👉 What would you like to do? "
        REPLY=""
        select OPT in "Retry detection (after plugging in the screen)" "Skip auto-configuration and continue"; do
            case $REPLY in
                1) echo "🔄 Retrying detection..."; break ;;
                2) echo "Skipping auto-configuration. Keeping the default placeholder."; SELECTED_PORT="/dev/serial/by-id/usb-MO_MX2_MX3_MX6_xxxxx-if00-port0"; break 2 ;;
                *) echo "❌ Invalid selection." ;;
            esac
        done
    else
        echo "Found the following serial devices:"
        PS3="👉 Please select the number corresponding to your Matrix Orbital screen: "
        REPLY=""
        
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
echo ""

# 🌐 3. CLUSTER CONFIGURATION
echo "🖥️ Cluster configuration..."
PS3="👉 Do you want to enable the Proxmox Cluster monitoring menu? "
REPLY=""
select CLUSTER_CHOICE in "Yes" "No"; do
    case $REPLY in
        1) 
            SELECTED_CLUSTER="True"
            echo "✅ Cluster menu enabled."
            echo ""
            read -p "📝 Enter IP address for PVE-02: " INPUT_IP_02
            read -p "📝 Enter display name for PVE-02 [PVE-02]: " INPUT_NAME_02
            INPUT_NAME_02=${INPUT_NAME_02:-PVE-02} # Fallback to default if empty
            
            echo ""
            read -p "📝 Enter IP address for PVE-03: " INPUT_IP_03
            read -p "📝 Enter display name for PVE-03 [PVE-03]: " INPUT_NAME_03
            INPUT_NAME_03=${INPUT_NAME_03:-PVE-03} # Fallback to default if empty
            break 
            ;;
        2) 
            SELECTED_CLUSTER="False"
            echo "✅ Cluster menu disabled."
            break 
            ;;
        *) echo "❌ Invalid selection." ;;
    esac
done
echo ""

# ⚙️ INJECTING CONFIGURATION INTO PYTHON SCRIPT
echo "⚙️ Applying configuration settings to $SCRIPT_NAME..."

# Inject Language
sed -i "s|^LANGUAGE\s*=.*|LANGUAGE = \"$SELECTED_LANG\"|" "$SCRIPT_NAME"

# Inject Serial Port
sed -i "s|^SERIAL_PORT\s*=.*|SERIAL_PORT       = '$SELECTED_PORT'|" "$SCRIPT_NAME"

# Inject Cluster Menu Activation
sed -i "s|^ENABLE_CLUSTER_MENU\s*=.*|ENABLE_CLUSTER_MENU = $SELECTED_CLUSTER|" "$SCRIPT_NAME"

# Inject Cluster Nodes details if enabled
if [ "$SELECTED_CLUSTER" == "True" ]; then
    sed -i "s|^IP_PVE_02\s*=.*|IP_PVE_02   = \"$INPUT_IP_02\"|" "$SCRIPT_NAME"
    sed -i "s|^NAME_PVE_02\s*=.*|NAME_PVE_02 = \"$INPUT_NAME_02\"|" "$SCRIPT_NAME"
    sed -i "s|^IP_PVE_03\s*=.*|IP_PVE_03   = \"$INPUT_IP_03\"|" "$SCRIPT_NAME"
    sed -i "s|^NAME_PVE_03\s*=.*|NAME_PVE_03 = \"$INPUT_NAME_03\"|" "$SCRIPT_NAME"
fi

echo "✅ Configuration successfully written!"
echo "===================================================="
echo ""

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
echo "💡 Quick Tip: If you ever need to manually adjust variables in the future, run:"
echo "   nano $INSTALL_DIR/$SCRIPT_NAME"
echo ""
echo "✅ Installation complete! Checking service status:"
systemctl status proxmox-lcd.service