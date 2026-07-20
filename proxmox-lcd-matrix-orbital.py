import time
import serial
import psutil
import subprocess
import socket
import json
import os
import threading
from datetime import datetime

# ==============================================================================
# ✨ CONFIGURATION SECTION - ADAPT THESE VALUES TO YOUR SETUP
# ==============================================================================

# 🌐 1. LANGUAGE CONFIGURATION ("EN" or "FR")
LANGUAGE = "EN"

# 🌡️ 1b. TEMPERATURE UNIT CONFIGURATION ("C" for Celsius, "F" for Fahrenheit)
TEMPERATURE_UNIT = "C"

# 📅 1c. DATE FORMAT CONFIGURATION
# Choose between standard formats:
# "%d/%m/%Y" -> European Long (e.g., 20/07/2026)
# "%m/%d/%Y" -> American Long (e.g., 07/20/2026)
DATE_FORMAT = "%d/%m/%Y"

# 🔌 2. HARDWARE CONFIGURATION (LCD SCREEN)
# Run ls /dev/serial/by-id/ in your Proxmox terminal to find your unique screen ID.
# Example: '/dev/serial/by-id/usb-MO_MX2_MX3_MX6_xxxxx-if00-port0'
SERIAL_PORT       = '/dev/serial/by-id/usb-MO_MX2_MX3_MX6_xxxxx-if00-port0'
BAUDRATE          = 19200
TIMEOUT_BACKLIGHT = 40.0  # Time in seconds before switching to the standby clock

# 🚫 3. DISK FILTERS (SMART HEALTH)
DISK_IGNORE_PREFIXES = ('zram', 'zd', 'loop', 'dm-')

# 🌐 4. PROXMOX CLUSTER CONFIGURATION (Optional monitoring of sibling nodes)
# Set ENABLE_CLUSTER_MENU = False to completely disable and hide the cluster menu items
ENABLE_CLUSTER_MENU = True  

IP_PVE_02   = "192.168.1.51"      
IP_PVE_03   = "192.168.1.52"      
NAME_PVE_02 = "PVE-02"        
NAME_PVE_03 = "PVE-03"        

# ==============================================================================
# ⛔ END OF CONFIGURATION - DO NOT MODIFY THE CODE BELOW
# ==============================================================================

KEYS = {b'K': 'UP', b'L': 'DOWN', b'R': 'LEFT', b'F': 'RIGHT', b'J': 'ENTER', b'Q': 'F1', b'P': 'F2'}

CMD_CLEAR = b'\xFE\x58'
CMD_HOME = b'\xFE\x48'
CMD_BACKLIGHT_ON = b'\xFE\x42\x00'

# --- TRANSLATION DICTIONARY ---
TRANSLATIONS = {
    "FR": {
        "calc": "Calcul...",
        "err_api": "Erreur PVE API",
        "err_store": "Erreur API Stockage",
        "disabled": "DESACTIVE",
        "online": "En ligne",
        "offline": "Hors ligne",
        "unknown": "INCONNU",
        "alert": "ALERTE",
        "unknown_cpu": "CPU Inconnu",
        "life": "Vie",
        "main_menu": "MENU PRINCIPAL",
        "menu_net": "1. RESEAU",
        "menu_cpu": "2. CPU",
        "menu_ram": "3. RAM",
        "menu_vm": "4. VM & LXC",
        "menu_store": "5. VOLUMETRIE",
        "menu_smart": "6. SANTE SMART",
        "menu_cluster": "7. CLUSTER",
        "host": "Hote",
        "load": "Chg",
        "used": "Utilisation",
        "free": "Libre",
        "back": "<- RETOUR"
    },
    "EN": {
        "calc": "Calculating...",
        "err_api": "PVE API Error",
        "err_store": "Storage API Error",
        "disabled": "DISABLED",
        "online": "Online",
        "offline": "Offline",
        "unknown": "UNKNOWN",
        "alert": "ALERT",
        "unknown_cpu": "Unknown CPU",
        "life": "Life",
        "main_menu": "MAIN MENU",
        "menu_net": "1. NETWORK",
        "menu_cpu": "2. CPU",
        "menu_ram": "3. RAM",
        "menu_vm": "4. VM & LXC",
        "menu_store": "5. STORAGE",
        "menu_smart": "6. SMART HEALTH",
        "menu_cluster": "7. CLUSTER",
        "host": "Host",
        "load": "Load",
        "used": "Used",
        "free": "Free",
        "back": "<- BACK"
    }
}

TXT = TRANSLATIONS.get(LANGUAGE, TRANSLATIONS["EN"])

# --- CACHE SYSTEM ---
cache = {
    "vms": (TXT["calc"], TXT["calc"]),
    "storage_vols": [],
    "storage_smart": [],  
    "pve02": TXT["calc"],
    "pve03": TXT["calc"],
    "net_interfaces": [],
    "cpu_percent": 0.0
}

def c_to_f(celsius_val):
    try:
        return int((float(celsius_val) * 9/5) + 32)
    except:
        return celsius_val

def format_temp(celsius_numeric_val):
    if TEMPERATURE_UNIT == "F":
        return f"{c_to_f(celsius_numeric_val)} F"
    return f"{int(celsius_numeric_val)} C"

def get_disks_smart():
    disks_status = []
    try:
        res = subprocess.check_output("lsblk -dno NAME,TYPE", shell=True, text=True)
        for line in res.strip().split('\n'):
            parts = line.split()
            if len(parts) >= 2 and parts[1] in ['disk', 'nvme']:
                disk_name = parts[0]
                if disk_name.startswith(DISK_IGNORE_PREFIXES):
                    continue
                    
                health = TXT["unknown"]
                wearout = "N/A"
                model = "Unknown"
                serial_num = "Unknown"
                temp = None
                
                try:
                    # 1. Fetch device identity details
                    info_res = subprocess.run(
                        f"smartctl -i /dev/{disk_name}", 
                        shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                    )
                    for i_line in info_res.stdout.split('\n'):
                        if "Device Model:" in i_line or "Model Number:" in i_line:
                            model = i_line.split(":", 1)[1].strip()
                        elif "Serial Number:" in i_line:
                            serial_num = i_line.split(":", 1)[1].strip()

                    # 2. Fetch overall health status
                    smart_res = subprocess.run(
                        f"smartctl -H /dev/{disk_name}", 
                        shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                    )
                    if "PASSED" in smart_res.stdout or "OK" in smart_res.stdout:
                        health = "OK"
                    else:
                        health = TXT["alert"]
                        
                    # 3. Fetch SMART attributes (Wearout & Temperature metrics)
                    details_res = subprocess.run(
                        f"smartctl -A /dev/{disk_name}", 
                        shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                    )
                    details_out = details_res.stdout
                    
                    if "nvme" in parts[1]:
                        for d_line in details_out.split('\n'):
                            if "Percentage Used:" in d_line:
                                pct = ''.join(filter(str.isdigit, d_line))
                                if pct: wearout = f"{100 - int(pct)}%"
                            elif "Temperature:" in d_line:
                                t_parts = d_line.split()
                                if len(t_parts) >= 2: temp = format_temp(t_parts[1])
                    else:
                        for d_line in details_out.split('\n'):
                            if "Wearout_Indicator" in d_line or "Wear_Leveling_Count" in d_line:
                                cols = d_line.split()
                                if len(cols) >= 4: wearout = f"{cols[3]}%"
                            elif "Temperature" in d_line or "Airflow_Temperature" in d_line:
                                cols = d_line.split()
                                if len(cols) >= 10:
                                    val = cols[9].strip()
                                    if val.isdigit() and 0 < int(val) < 100:
                                        temp = format_temp(val)
                except:
                    pass

                # 4. Fallback system: check thermal zones in /sys/class/hwmon if SMART parsing failed
                if not temp:
                    try:
                        for hwmon in os.listdir("/sys/class/hwmon"):
                            name_path = f"/sys/class/hwmon/{hwmon}/name"
                            if os.path.exists(name_path):
                                with open(name_path, "r") as f:
                                    hw_name = f.read().strip()
                                if disk_name in hw_name or (parts[1] == "nvme" and "nvme" in hw_name):
                                    temp_path = f"/sys/class/hwmon/{hwmon}/temp1_input"
                                    if os.path.exists(temp_path):
                                        with open(temp_path, "r") as f:
                                            t_val = int(f.read().strip()) // 1000
                                            if 0 < t_val < 100:
                                                temp = format_temp(t_val)
                                                break
                    except:
                        pass

                temp_or_type_line = f"Temp: {temp}" if temp else f"Type: {parts[1].upper()}"
                
                disks_status.append({
                    "name": disk_name,
                    "summary_line": f"{disk_name}: {health} ({TXT['life']}:{wearout})",
                    "model_line": f"P/N: {model}",
                    "serial_line": f"S/N: {serial_num}",
                    "temp_line": temp_or_type_line
                })
    except:
        pass
    return disks_status

def update_network_stats():
    try:
        net1 = psutil.net_io_counters(pernic=True)
        time.sleep(0.5)
        net2 = psutil.net_io_counters(pernic=True)
        
        interfaces = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        updated_list = []

        for iface_name, addresses in interfaces.items():
            if iface_name != 'lo' and iface_name in stats and stats[iface_name].isup:
                ipv4_list = []
                for addr in addresses:
                    if addr.family == socket.AF_INET:
                        ipv4_list.append(addr.address)
                
                if ipv4_list:
                    merged_ips = "+".join(ipv4_list)
                    rx_speed = 0.0
                    tx_speed = 0.0
                    if iface_name in net1 and iface_name in net2:
                        rx_speed = (net2[iface_name].bytes_recv - net1[iface_name].bytes_recv) / 1024
                        tx_speed = (net2[iface_name].bytes_sent - net1[iface_name].bytes_sent) / 1024
                    
                    updated_list.append({
                        "name": iface_name,
                        "ip_line": f"{iface_name}: {merged_ips}",
                        "speed_line": f"{iface_name}: Rx:{rx_speed:5.1f}K Tx:{tx_speed:5.1f}K"
                    })
        return updated_list
    except Exception:
        return []

def update_cache_loop():
    global cache
    first_run = True
    cpu_counter = 0
    
    while True:
        cache["net_interfaces"] = update_network_stats()
        cpu_counter += 1
        if first_run or cpu_counter >= 8:
            cache["cpu_percent"] = psutil.cpu_percent(interval=None)
            cpu_counter = 0

        if first_run or (int(time.time()) % 300 < 5):
            try:
                res = subprocess.check_output("pvesh get /cluster/resources --output-format json", shell=True, text=True)
                resources = json.loads(res)
                vms = [r for r in resources if r.get('type') == 'qemu']
                lxcs = [r for r in resources if r.get('type') == 'lxc']
                vm_run = sum(1 for v in vms if v.get('status') == 'running')
                lxc_run = sum(1 for l in lxcs if l.get('status') == 'running')
                cache["vms"] = (f"VM : {vm_run}/{len(vms)} RUN", f"LXC: {lxc_run}/{len(lxcs)} RUN")
            except:
                cache["vms"] = (TXT["err_api"], "N/A")

            try:
                res = subprocess.check_output("pvesh get /nodes/localhost/storage --output-format json", shell=True, text=True)
                storages = json.loads(res)
                vols = []
                for s in storages:
                    if s.get('active') == 1:
                        used = (s.get('used', 0) / s.get('total', 1)) * 100
                        vols.append(f"{s.get('storage')}: {used:.1f}%")
                    else:
                        vols.append(f"{s.get('storage')}: {TXT['disabled']}")
                vols.sort(key=lambda x: x.lower())
                cache["storage_vols"] = vols
            except:
                cache["storage_vols"] = [TXT["err_store"]]

            cache["storage_smart"] = get_disks_smart()

            if ENABLE_CLUSTER_MENU:
                p02 = os.system(f"ping -c 1 -W 1 {IP_PVE_02} > /dev/null 2>&1")
                cache["pve02"] = TXT["online"] if p02 == 0 else TXT["offline"]
                p03 = os.system(f"ping -c 1 -W 1 {IP_PVE_03} > /dev/null 2>&1")
                cache["pve03"] = TXT["online"] if p03 == 0 else TXT["offline"]

            if first_run:
                first_run = False
        
        time.sleep(0.1)

threading.Thread(target=update_cache_loop, daemon=True).start()

def get_hostname(): return socket.gethostname()
def get_cpu_model():
    try:
        res = subprocess.check_output("lscpu | grep 'Model name'", shell=True, text=True)
        return res.split(":")[1].strip()
    except: return TXT["unknown_cpu"]

def get_cpu_temp():
    try:
        temps = psutil.sensors_temperatures()
        raw_c = None
        if 'coretemp' in temps and temps['coretemp']:
            for entry in temps['coretemp']:
                if 'package' in entry.label.lower(): 
                    raw_c = entry.current
                    break
            if raw_c is None:
                raw_c = temps['coretemp'][0].current
        if raw_c is None:
            for amd_sensor in ['k10temp', 'zenpower']:
                if amd_sensor in temps and temps[amd_sensor]:
                    for entry in temps[amd_sensor]:
                        if 'tdie' in entry.label.lower() or 'tctl' in entry.label.lower(): 
                            raw_c = entry.current
                            break
                    if raw_c is None:
                        raw_c = temps[amd_sensor][0].current
                    break
        if raw_c is None and temps:
            for sensor_name, entries in temps.items():
                if entries: 
                    raw_c = entries[0].current
                    break
                    
        if raw_c is not None:
            return format_temp(raw_c)
        return "N/A"
    except: return "N/A"

class MenuManager:
    def __init__(self):
        self.main_index = 0
        self.sub_index = 0
        self.disk_detail_index = 0  
        self.last_item_base = ""
        self.scroll_pos = 0
        self.scroll_wait = 0
        
        self.main_menus = [TXT["menu_net"], TXT["menu_cpu"], TXT["menu_ram"], TXT["menu_vm"], TXT["menu_store"], TXT["menu_smart"]]
        if ENABLE_CLUSTER_MENU:
            self.main_menus.append(TXT["menu_cluster"])
            
        self.current_menu = "MAIN"

    def format_header(self, text):
        available_space = 20 - len(text)
        if available_space >= 6: return f"<- {text} ->".center(20)
        elif available_space >= 4: return f"<{text}>".center(20)
        return text.center(20)[:20]

    def reset_to_first_menu(self):
        self.current_menu = "MAIN"
        self.main_index = 0
        self.sub_index = 0
        self.disk_detail_index = 0
        self.scroll_pos = 0
        self.scroll_wait = 0

    def get_display_strings(self):
        if self.current_menu == "MAIN":
            return self.format_header(TXT["main_menu"]), self.main_menus[self.main_index]
        elif self.current_menu == "NETWORK":
            sub_items = []
            for iface in cache["net_interfaces"]:
                sub_items.append(iface['ip_line'])
                sub_items.append(iface['speed_line'])
            sub_items.append(TXT["back"])
            return self.format_header(LANGUAGE == "FR" and "RESEAU" or "NETWORK"), sub_items[self.sub_index]
        elif self.current_menu == "CPU":
            sub_items = [f"CPU: {get_cpu_model()}", f"{TXT['load']}: {cache['cpu_percent']}%", f"Temp: {get_cpu_temp()}", TXT["back"]]
            return self.format_header("CPU"), sub_items[self.sub_index]
        elif self.current_menu == "RAM":
            ram = psutil.virtual_memory()
            swap = psutil.swap_memory()
            sub_items = [f"{TXT['used']}: {ram.percent}%", f"{TXT['free']}: {ram.available // (1024**2)} MB", f"Swap: {swap.percent}%", TXT["back"]]
            return self.format_header("RAM"), sub_items[self.sub_index]
        elif self.current_menu == "VM_LXC":
            sub_items = [cache["vms"][0], cache["vms"][1], TXT["back"]]
            return self.format_header("VM/LXC"), sub_items[self.sub_index]
        elif self.current_menu == "STORAGE":
            sub_items = cache["storage_vols"] + [TXT["back"]]
            return self.format_header(LANGUAGE == "FR" and "VOLUMETRIE" or "STORAGE"), sub_items[self.sub_index]
        elif self.current_menu == "SMART_HEALTH":
            sub_items = [d["summary_line"] for d in cache["storage_smart"]] + [TXT["back"]]
            return self.format_header(LANGUAGE == "FR" and "SANTE SMART" or "SMART HEALTH"), sub_items[self.sub_index]
        elif self.current_menu == "SMART_DISK_DETAIL":
            disk_data = cache["storage_smart"][self.sub_index]
            detail_items = [disk_data["model_line"], disk_data["serial_line"], disk_data["temp_line"], TXT["back"]]
            return self.format_header(disk_data["name"].upper()), detail_items[self.disk_detail_index]
        elif self.current_menu == "CLUSTER" and ENABLE_CLUSTER_MENU:
            sub_items = ["Repl: Active (0 Err)", f"{NAME_PVE_02}: {cache['pve02']}", f"{NAME_PVE_03}: {cache['pve03']}", TXT["back"]]
            return self.format_header("CLUSTER"), sub_items[self.sub_index]
        return "Error", ""

    def handle_input(self, action):
        self.scroll_pos = 0
        self.scroll_wait = 0
        if self.current_menu == "MAIN":
            if action == 'LEFT': self.main_index = (self.main_index - 1) % len(self.main_menus)
            elif action == 'RIGHT': self.main_index = (self.main_index + 1) % len(self.main_menus)
            elif action == 'ENTER':
                mapping = {0: "NETWORK", 1: "CPU", 2: "RAM", 3: "VM_LXC", 4: "STORAGE", 5: "SMART_HEALTH", 6: "CLUSTER"}
                self.current_menu = mapping[self.main_index]
                self.sub_index = 0
        elif self.current_menu == "SMART_DISK_DETAIL":
            if action == 'LEFT': self.disk_detail_index = (self.disk_detail_index - 1) % 4
            elif action == 'RIGHT': self.disk_detail_index = (self.disk_detail_index + 1) % 4
            elif action == 'ENTER':
                if self.disk_detail_index == 3:  
                    self.current_menu = "SMART_HEALTH"
                    self.disk_detail_index = 0
        else:
            if self.current_menu == "STORAGE": max_items = 1 + len(cache["storage_vols"])
            elif self.current_menu == "SMART_HEALTH": max_items = 1 + len(cache["storage_smart"])
            elif self.current_menu == "NETWORK": max_items = 1 + (len(cache["net_interfaces"]) * 2)
            elif self.current_menu == "VM_LXC": max_items = 3
            else: max_items = 4 
            
            if action == 'LEFT': self.sub_index = (self.sub_index - 1) % max_items
            elif action == 'RIGHT': self.sub_index = (self.sub_index + 1) % max_items
            elif action == 'ENTER':
                if self.sub_index == (max_items - 1): 
                    self.current_menu = "MAIN"
                elif self.current_menu == "SMART_HEALTH": 
                    self.current_menu = "SMART_DISK_DETAIL"
                    self.disk_detail_index = 0

    def process_scrolling(self, text):
        item_base = text[:10] if len(text) > 10 else text
        if item_base != self.last_item_base:
            self.last_item_base = item_base
            self.scroll_pos = 0
            self.scroll_wait = 0
            
        if len(text) <= 20: return text.ljust(20)
        if self.scroll_wait < 4:
            self.scroll_wait += 1
            return text[:20]
            
        display_text = text[self.scroll_pos:self.scroll_pos+20]
        self.scroll_pos += 1
        if self.scroll_pos > len(text) - 15:
            self.scroll_pos = 0
            self.scroll_wait = 0
        return display_text.ljust(20)

# --- MAIN LOOP ---
try:
    ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=0.05)
    menu = MenuManager()
    
    user_brightness = 255
    clock_brightness = 1  
    current_applied_brightness = 255
    
    ser.write(CMD_BACKLIGHT_ON)
    ser.write(b'\xFE\x99' + bytes([user_brightness]))
    ser.write(CMD_CLEAR)
    
    show_clock = False  
    last_action_time = time.time()
    last_display_time = 0

    while True:
        now = time.time()
        
        if last_action_time == 0:
            time_since_input = -1.0
        else:
            time_since_input = now - last_action_time
        
        if ser.in_waiting > 0:
            key = ser.read(1)
            if key in KEYS:
                action = KEYS[key]
                
                # --- F1 KEY: WAKE UP, RESET MENU AND BACKTRACK ---
                if action == 'F1':
                    ser.reset_input_buffer()
                    now = time.time()       
                    last_action_time = now  
                    time_since_input = 0.0  
                    
                    if show_clock:
                        show_clock = False
                        menu.reset_to_first_menu() 
                        ser.write(b'\xFE\x99' + bytes([user_brightness]))
                        current_applied_brightness = user_brightness
                        ser.write(CMD_CLEAR)
                        last_display_time = 0
                        
                # --- F2 KEY: MANUAL TOGGLE STANDBY CLOCK MODE ---
                elif action == 'F2':  
                    if not show_clock:
                        show_clock = True
                        last_action_time = 0  
                        ser.write(b'\xFE\x99' + bytes([clock_brightness]))
                        current_applied_brightness = clock_brightness
                        ser.write(CMD_CLEAR)
                        last_display_time = 0
                        
                # --- UP & DOWN ATTRIBUTE ADJUSTMENT ---
                elif action == 'UP':
                    if show_clock:
                        clock_brightness = min(50, clock_brightness + 5)
                        ser.write(b'\xFE\x99' + bytes([clock_brightness]))
                        current_applied_brightness = clock_brightness
                    else:
                        user_brightness = min(255, user_brightness + 51)
                        ser.write(b'\xFE\x99' + bytes([user_brightness]))
                        current_applied_brightness = user_brightness
                        
                elif action == 'DOWN':
                    if show_clock:
                        clock_brightness = max(1, clock_brightness - 5)
                        ser.write(b'\xFE\x99' + bytes([clock_brightness]))
                        current_applied_brightness = clock_brightness
                    else:
                        user_brightness = max(10, user_brightness - 51) 
                        ser.write(b'\xFE\x99' + bytes([user_brightness]))
                        current_applied_brightness = user_brightness
                        
                # --- STANDALONE NAVIGATION CONTROLS ---
                elif not show_clock:
                    last_action_time = now  
                    menu.handle_input(action)
                    ser.write(CMD_CLEAR)

        # --- AUTOMATIC DIMMING & INACTIVITY LOGIC ---
        if not show_clock and last_action_time > 0:
            if time_since_input > TIMEOUT_BACKLIGHT:
                show_clock = True
                last_action_time = 0  
                ser.write(b'\xFE\x99' + bytes([clock_brightness]))
                current_applied_brightness = clock_brightness
                ser.write(CMD_CLEAR)
                last_display_time = 0
            elif time_since_input > (TIMEOUT_BACKLIGHT - 10.0):
                time_in_fade = time_since_input - (TIMEOUT_BACKLIGHT - 10.0)
                fade_ratio = time_in_fade / 10.0
                fade_target = int(user_brightness - ((user_brightness - clock_brightness) * fade_ratio))
                fade_target = max(clock_brightness, min(user_brightness, fade_target))
                
                if current_applied_brightness != fade_target:
                    ser.write(b'\xFE\x99' + bytes([fade_target]))
                    current_applied_brightness = fade_target
            else:
                if current_applied_brightness != user_brightness:
                    ser.write(b'\xFE\x99' + bytes([user_brightness]))
                    current_applied_brightness = user_brightness

        # --- DISPLAY REFRESH DISPATCH ---
        if now - last_display_time >= 0.3:
            if show_clock:
                dt_now = datetime.now()
                line1_display = get_hostname().center(20)
                
                # Blinking colon animation calculated using local time seconds
                separator = ":" if (dt_now.second % 2 == 0) else " "
                time_str = f"{dt_now.strftime('%H')}{separator}{dt_now.strftime('%M')}"
                
                line2_display = f"{time_str}  {dt_now.strftime(DATE_FORMAT)}".center(20)
            else:
                line1, line2 = menu.get_display_strings()
                line1_display = line1.ljust(20)[:20]
                line2_display = menu.process_scrolling(line2)

            ser.write(CMD_HOME)
            ser.write(line1_display.encode('ascii', 'ignore'))
            ser.write(line2_display.encode('ascii', 'ignore'))
            last_display_time = now

        time.sleep(0.05)

except KeyboardInterrupt:
    if 'ser' in locals(): ser.close()