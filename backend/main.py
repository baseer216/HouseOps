from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import sqlite3, requests, os, urllib3, json, ssl, urllib.request, urllib.error, subprocess
from dotenv import load_dotenv

load_dotenv(dotenv_path="/opt/houseops/.env", override=True)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DB_PATH = os.getenv("DB_PATH")
PVE_IP = os.getenv("PVE_IP")
PVE_TOKEN = os.getenv("PVE_TOKEN_ID")
PVE_SECRET = os.getenv("PVE_SECRET")
UNIFI_IP = os.getenv("UNIFI_IP", "10.0.0.1")
UNIFI_API_KEY = os.getenv("UNIFI_API_KEY", "")
HA_URL = os.getenv("HA_URL", "http://10.0.0.2:8123/api")
HA_TOKEN = os.getenv("HA_TOKEN", "")

app = FastAPI(title="HouseOPS", version="2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ─── Helpers ───────────────────────────────────────────────

def pve_headers():
    return {"Authorization": f"PVEAPIToken={PVE_TOKEN}={PVE_SECRET}", "Accept": "application/json"}

def ha_headers():
    return {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}

def pve_get(path):
    r = requests.get(f"https://{PVE_IP}:8006/api2/json{path}", headers=pve_headers(), verify=False, timeout=10)
    r.raise_for_status()
    return r.json().get("data", {})

def ha_get(path):
    r = requests.get(f"{HA_URL}{path}", headers=ha_headers(), timeout=10)
    r.raise_for_status()
    return r.json()

def unifi_get(ep):
    if not UNIFI_API_KEY:
        return []
    url = f"https://{UNIFI_IP}/proxy/network/api/s/default{ep}"
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={"X-API-KEY": UNIFI_API_KEY, "Accept": "application/json"})
        r = urllib.request.urlopen(req, context=ctx, timeout=5)
        return json.loads(r.read().decode()).get("data", [])
    except Exception as e:
        print(f"unifi_get error {ep}: {e}")
        return []

def snmp_get(ip, community, oid):
    try:
        r = subprocess.run(
            ["/usr/bin/snmpget", "-v2c", "-c", community, "-t", "1", "-r", "0", "-Oqv", ip, oid],
            capture_output=True, text=True, timeout=3
        )
        return r.stdout.strip().strip('"') if r.returncode == 0 else None
    except:
        return None

def snmp_walk_indexed(ip, community, oid):
    try:
        r = subprocess.run(
            ["/usr/bin/snmpwalk", "-v2c", "-c", community, "-t", "1", "-r", "0", "-On", ip, oid],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode != 0:
            return {}
        result = {}
        for line in r.stdout.strip().split('\n'):
            line = line.strip()
            if '=' not in line:
                continue
            oid_part, val_part = line.split('=', 1)
            idx = oid_part.strip().split('.')[-1]
            val_part = val_part.strip()
            if ':' in val_part:
                val = val_part.split(':', 1)[1].strip().strip('"')
            else:
                val = val_part.strip().strip('"')
            result[idx] = val
        return result
    except:
        return {}

def fmt_bytes(b):
    if b < 1024: return f"{b} B"
    if b < 1048576: return f"{b/1024:.1f} KB"
    if b < 1073741824: return f"{b/1048576:.1f} MB"
    return f"{b/1073741824:.2f} GB"

# ─── Switches Config ──────────────────────────────────────────

SWITCHES = [
    {"name": "Core Switch", "ip": os.getenv("SWITCH_CORE_IP", "10.0.0.10"), "community": os.getenv("SWITCH_CORE_COMM", "public"), "model": "10G Managed"},
    {"name": "Office Switch", "ip": os.getenv("SWITCH_OFFICE_IP", "10.0.0.11"), "community": os.getenv("SWITCH_OFFICE_COMM", "public"), "model": "2.5G Managed"},
    {"name": "Studio Switch", "ip": os.getenv("SWITCH_STUDIO_IP", "10.0.0.12"), "community": os.getenv("SWITCH_STUDIO_COMM", "public"), "model": "2.5G Managed"},
]

def get_switch_status(sw):
    try:
        num_ports_raw = snmp_get(sw["ip"], sw["community"], "1.3.6.1.2.1.2.1.0")
        if not num_ports_raw:
            raise Exception("SNMP unreachable")
        num_ports = int(num_ports_raw)
        
        uptime_raw = snmp_get(sw["ip"], sw["community"], "1.3.6.1.2.1.1.3.0")
        if uptime_raw and ':' in uptime_raw:
            parts = uptime_raw.split(':')
            uptime_seconds = int(parts[0]) * 86400 + int(parts[1]) * 3600 + int(parts[2]) * 60 + int(float(parts[3]))
        elif uptime_raw:
            uptime_seconds = int(uptime_raw) / 100
        else:
            uptime_seconds = 0
        uptime_days = round(uptime_seconds / 86400, 1)
        
        if_oper = snmp_walk_indexed(sw["ip"], sw["community"], "1.3.6.1.2.1.2.2.1.8")
        if_speed = snmp_walk_indexed(sw["ip"], sw["community"], "1.3.6.1.2.1.2.2.1.5")
        if_names = snmp_walk_indexed(sw["ip"], sw["community"], "1.3.6.1.2.1.2.2.1.2")
        if_in_oct = snmp_walk_indexed(sw["ip"], sw["community"], "1.3.6.1.2.1.2.2.1.10")
        if_out_oct = snmp_walk_indexed(sw["ip"], sw["community"], "1.3.6.1.2.1.2.2.1.16")
        if_in_err = snmp_walk_indexed(sw["ip"], sw["community"], "1.3.6.1.2.1.2.2.1.14")
        if_out_err = snmp_walk_indexed(sw["ip"], sw["community"], "1.3.6.1.2.1.2.2.1.20")
        
        physical_ports = sorted([int(k) for k in if_oper.keys() if int(k) < 100])
        
        port_status = []
        port_traffic = []
        
        for i in physical_ports:
            idx = str(i)
            port_status.append({
                "port": i,
                "name": if_names.get(idx, f"Port {i}"),
                "status": "up" if if_oper.get(idx) == "1" else "down",
                "speed": int(if_speed.get(idx, "0") or 0),
            })
            port_traffic.append({
                "port": i,
                "in_octets": int(if_in_oct.get(idx, "0") or 0),
                "out_octets": int(if_out_oct.get(idx, "0") or 0),
                "in_errors": int(if_in_err.get(idx, "0") or 0),
                "out_errors": int(if_out_err.get(idx, "0") or 0),
            })
        
        ports_up = sum(1 for p in port_status if p["status"] == "up")
        
        return {
            "name": sw["name"], "ip": sw["ip"], "model": sw["model"],
            "online": True, "total_ports": len(port_status),
            "ports_up": ports_up, "ports_down": len(port_status) - ports_up,
            "uptime_days": uptime_days, "ports": port_status, "traffic": port_traffic,
        }
    except Exception as e:
        return {
            "name": sw["name"], "ip": sw["ip"], "model": sw["model"],
            "online": False, "total_ports": 0, "ports_up": 0, "ports_down": 0,
            "uptime_days": 0, "ports": [], "traffic": [], "error": str(e),
        }

# ─── API Endpoints ────────────────────────────────────────────

@app.get("/api/dashboard")
def api_dashboard():
    result = {"power": {}, "network": {}, "proxmox": {}}
    try:
        entities = ha_get("/states")
        power_entities = [e for e in entities if e.get("attributes", {}).get("unit_of_measurement") == "W"]
        total_w = sum(float(e["state"]) for e in power_entities if e["state"] not in ["unknown", "unavailable"])
        result["power"] = {"total_watts": total_w, "active_devices": len(power_entities)}
    except:
        result["power"] = {"total_watts": 0, "active_devices": 0}
    
    try:
        health = unifi_get("/stat/health")
        wlan = next((h for h in health if h.get("subsystem") == "wlan"), {})
        lan = next((h for h in health if h.get("subsystem") == "lan"), {})
        wan = next((h for h in health if h.get("subsystem") == "wan"), {})
        result["network"] = {
            "total_clients": wlan.get("num_user", 0) + lan.get("num_user", 0),
            "wifi": wlan.get("num_user", 0),
            "wired": lan.get("num_user", 0),
            "wan_down_bps": wan.get("rx_bytes-r", 0) * 8,
            "wan_up_bps": wan.get("tx_bytes-r", 0) * 8,
        }
    except:
        result["network"] = {"total_clients": 0, "wifi": 0, "wired": 0}
    
    try:
        vms = pve_get("/cluster/resources?type=vm")
        running = sum(1 for v in vms if v.get("status") == "running")
        result["proxmox"] = {"vms_running": running, "vms_total": len(vms), "cpu_pct": 0, "ram_pct": 0}
    except:
        result["proxmox"] = {"vms_running": 0, "vms_total": 0}
    
    return result

@app.get("/api/power")
def api_power():
    try:
        entities = ha_get("/states")
        power_entities = [e for e in entities if e.get("attributes", {}).get("unit_of_measurement") == "W"]
        all_devices = []
        for e in power_entities:
            try:
                watts = float(e["state"])
            except:
                watts = 0
            all_devices.append({
                "name": e["attributes"].get("friendly_name", e["entity_id"]),
                "entity": e["entity_id"],
                "watts": watts,
            })
        total = sum(d["watts"] for d in all_devices)
        return {"total_watts": total, "active_devices": len(all_devices), "all": all_devices}
    except Exception as e:
        return {"total_watts": 0, "active_devices": 0, "all": [], "error": str(e)}

@app.get("/api/proxmox/vms")
def api_vms():
    try:
        vms = pve_get("/cluster/resources?type=vm")
        return {"vms": vms}
    except Exception as e:
        return {"vms": [], "error": str(e)}

@app.get("/api/proxmox/storage")
def api_storage():
    try:
        storage = pve_get("/storage")
        return {"storage": storage}
    except Exception as e:
        return {"storage": [], "error": str(e)}

@app.get("/api/network/clients")
def api_net_clients():
    try:
        clients = unifi_get("/stat/sta")
        result = []
        for c in clients:
            result.append({
                "name": c.get("name") or c.get("hostname") or c.get("mac", "Unknown"),
                "mac": c.get("mac", ""),
                "ip": c.get("ip", ""),
                "wired": c.get("is_wired", False),
                "essid": c.get("essid", ""),
                "signal": c.get("rssi", 0),
                "rx_bytes": fmt_bytes(c.get("rx_bytes", 0)),
                "tx_bytes": fmt_bytes(c.get("tx_bytes", 0)),
                "rx_rate": round(c.get("rx_rate", 0) / 1000, 1),
                "tx_rate": round(c.get("tx_rate", 0) / 1000, 1),
            })
        result.sort(key=lambda x: x["rx_rate"] + x["tx_rate"], reverse=True)
        return {"clients": result, "total": len(result),
                "wifi": sum(1 for c in clients if not c.get("is_wired")),
                "wired": sum(1 for c in clients if c.get("is_wired"))}
    except Exception as e:
        return {"clients": [], "error": str(e)}

@app.get("/api/network/devices")
def api_net_devices():
    try:
        devices = unifi_get("/stat/device")
        result = []
        for d in devices:
            stats = d.get("system-stats", {})
            result.append({
                "name": d.get("name") or d.get("model", "Unknown"),
                "type": d.get("type", ""),
                "ip": d.get("ip", ""),
                "version": d.get("version", ""),
                "cpu_pct": round(float(stats.get("cpu", 0)) * 100, 1),
                "mem_pct": round(float(stats.get("mem", 0)) * 100, 1),
                "clients": d.get("num_sta", 0),
                "status": "online" if d.get("state", 1) == 1 else "offline",
            })
        return {"devices": result}
    except Exception as e:
        return {"devices": [], "error": str(e)}

@app.get("/api/network/health")
def api_net_health():
    try:
        health = unifi_get("/stat/health")
        result = []
        for h in health:
            sub = h.get("subsystem", "unknown")
            result.append({
                "subsystem": sub,
                "status": h.get("status", "unknown"),
                "num_user": h.get("num_user", 0),
                "rx_bytes_r": h.get("rx_bytes-r", 0),
                "tx_bytes_r": h.get("tx_bytes-r", 0),
            })
        return {"health": result}
    except Exception as e:
        return {"health": [], "error": str(e)}

@app.get("/api/network/flows")
def api_net_flows():
    return {"flows": [], "total": 0, "wan1": {"download_bps": 0, "upload_bps": 0}}

@app.get("/api/water")
def api_water():
    try:
        entities = ha_get("/states")
        water = []
        for e in entities:
            attrs = e.get("attributes", {})
            unit = attrs.get("unit_of_measurement", "")
            if "water" in e.get("entity_id", "") or unit in ["L", "gal", "m³", "GPM"]:
                try:
                    state = float(e["state"])
                except:
                    state = e["state"]
                water.append({"name": attrs.get("friendly_name", e["entity_id"]), "state": state, "unit": unit})
        return {"water": {"sensors": water}}
    except Exception as e:
        return {"water": {"error": str(e)}}

# ─── Switches API ─────────────────────────────────────────────

@app.get("/api/switches")
def api_switches():
    result = []
    for sw in SWITCHES:
        result.append(get_switch_status(sw))
    return {"switches": result}

@app.get("/api/switches/{switch_ip}/ports")
def api_switch_ports(switch_ip: str):
    sw = next((s for s in SWITCHES if s["ip"] == switch_ip), None)
    if not sw:
        raise HTTPException(status_code=404, detail="Switch not found")
    return get_switch_status(sw)

# ─── UniFi API ────────────────────────────────────────────────

@app.get("/api/unifi")
def api_unifi():
    result = {"online": False, "error": "No response"}
    health_list = unifi_get("/stat/health")
    if not health_list:
        return result
    result["online"] = True
    result["health"] = {}
    for h in health_list:
        sub = h.get("subsystem", "unknown")
        result["health"][sub] = {
            "status": h.get("status", "?"),
            "num_user": h.get("num_user", 0),
            "num_ap": h.get("num_ap", 0),
            "tx_bytes_r": h.get("tx_bytes-r", 0),
            "rx_bytes_r": h.get("rx_bytes-r", 0),
        }
        if sub == "wan":
            result["health"][sub]["wan_ip"] = h.get("wan_ip", "")
            gw_stats = h.get("gw_system-stats", {})
            result["health"][sub]["gw_uptime"] = gw_stats.get("uptime", 0)
    sysinfo = unifi_get("/stat/sysinfo")
    if sysinfo:
        si = sysinfo[0]
        result["name"] = si.get("name", "UniFi Dream Router")
        result["version"] = si.get("version", "?")
        result["uptime"] = si.get("uptime", 0)
        ss = si.get("system-stats", {})
        result["cpu"] = ss.get("cpu", 0)
        result["mem"] = ss.get("mem", 0)
    devices = unifi_get("/stat/device")
    result["devices"] = [{"name": d.get("name", d.get("model", "?")), "model": d.get("model", "?"),
                          "type": d.get("type", "?"), "ip": d.get("ip", "?"),
                          "adopted": d.get("adopted", False), "upgradable": d.get("upgradable", False)} for d in devices]
    clients = unifi_get("/stat/sta")
    result["total_clients"] = len(clients)
    result["wifi_clients"] = sum(1 for c in clients if not c.get("is_wired"))
    result["wired_clients"] = sum(1 for c in clients if c.get("is_wired"))
    dashboard = unifi_get("/stat/dashboard")
    if dashboard:
        latest = dashboard[0]
        result["latency_avg"] = latest.get("latency_avg", 0)
    alarms = unifi_get("/stat/alarm")
    result["alarms"] = len(alarms)
    return result

@app.get("/api/unifi/clients")
def api_unifi_clients():
    clients = unifi_get("/stat/sta")
    if not clients:
        return {"error": "No data", "clients": []}
    result = []
    for c in clients:
        result.append({
            "name": c.get("name", c.get("hostname", c.get("mac", "?"))),
            "mac": c.get("mac", ""), "ip": c.get("ip", ""),
            "is_wired": c.get("is_wired", False), "essid": c.get("essid", ""),
            "rssi": c.get("rssi", 0), "rx_rate": c.get("rx_rate", 0),
            "tx_rate": c.get("tx_rate", 0), "rx_bytes": c.get("rx_bytes", 0),
            "tx_bytes": c.get("tx_bytes", 0),
        })
    result.sort(key=lambda x: x["rx_bytes"] + x["tx_bytes"], reverse=True)
    return {"clients": result}

# ─── Static Files ─────────────────────────────────────────────

frontend_dir = "/opt/houseops/frontend"

@app.get("/manifest.json")
def serve_manifest():
    return FileResponse(os.path.join(frontend_dir, "manifest.json"), media_type="application/json")

@app.get("/sw.js")
def serve_sw():
    return FileResponse(os.path.join(frontend_dir, "sw.js"), media_type="application/javascript")

@app.get("/icons/{filename}")
def serve_icon(filename: str):
    return FileResponse(os.path.join(frontend_dir, "icons", filename))

@app.get("/network")
def serve_network():
    return FileResponse(os.path.join(frontend_dir, "network.html"))

@app.get("/switches")
def serve_switches():
    return FileResponse(os.path.join(frontend_dir, "switches.html"))

@app.get("/")
def serve_frontend():
    return FileResponse(os.path.join(frontend_dir, "index.html"))

if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="frontend")
