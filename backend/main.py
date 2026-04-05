from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import sqlite3, requests, os, urllib3, json, ssl, urllib.request, urllib.error, subprocess, time, threading
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

UPTIME_KUMA_URL = os.getenv("UPTIME_KUMA_URL", "http://10.100.1.58:3001")
UPTIME_KUMA_SLUGS = ["internet", "home-gear"]
PIHOLE_1 = {"url": "https://10.100.1.3:443/api", "token": "01KC8628RM3HQE6V5DSFS5RY1R", "name": "Pi-hole 1"}
PIHOLE_2 = {"url": "http://10.100.1.101/api", "token": "01KKM9N39V7D9VW5KGHSEQW7A1", "name": "Pi-hole 2"}
ADGUARD_IP = os.getenv("ADGUARD_IP", "10.100.1.99")

app = FastAPI(title="HouseOPS", version="2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ─── In-Memory Cache ─────────────────────────────────────────

class Cache:
    def __init__(self):
        self._data = {}
    def get(self, key):
        entry = self._data.get(key)
        if entry and time.time() - entry["time"] < entry["ttl"]:
            return entry["value"]
        return None
    def set(self, key, value, ttl=10):
        self._data[key] = {"value": value, "time": time.time(), "ttl": ttl}

cache = Cache()

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

def _guess_room(eid, attrs):
    name = (eid + " " + attrs.get("friendly_name", "")).lower()
    room_map = [
        ("kitchen", "Kitchen"), ("fridge", "Kitchen"), ("oven", "Kitchen"), ("dishwasher", "Kitchen"),
        ("living", "Living Room"), ("lounge", "Living Room"), ("tv", "Living Room"),
        ("bedroom", "Bedroom"), ("bed", "Bedroom"),
        ("bath", "Bathroom"), ("shower", "Bathroom"),
        ("office", "Office"), ("desk", "Office"), ("study", "Office"),
        ("garage", "Garage"),
        ("hall", "Hallway"), ("corridor", "Hallway"),
        ("laundry", "Laundry"), ("washer", "Laundry"), ("dryer", "Laundry"),
        ("server", "Server Room"), ("rack", "Server Room"), ("nas", "Server Room"), ("proxmox", "Server Room"),
        ("outdoor", "Outdoor"), ("garden", "Outdoor"), ("patio", "Outdoor"),
        ("dining", "Dining Room"),
        ("basement", "Basement"), ("attic", "Attic"),
        ("studio", "Studio"),
    ]
    for keyword, room in room_map:
        if keyword in name:
            return room
    return "Other"

def ping_host(ip, count=2):
    try:
        r = subprocess.run(["ping", "-c", str(count), "-W", "2", ip], capture_output=True, text=True, timeout=8)
        for line in r.stdout.split('\n'):
            if 'rtt' in line or 'round-trip' in line:
                parts = line.split('/')
                if len(parts) >= 5:
                    return {"reachable": True, "avg_ms": round(float(parts[4]), 1), "loss": 0}
        if r.returncode != 0:
            return {"reachable": False, "avg_ms": None, "loss": 100}
        return {"reachable": True, "avg_ms": 0, "loss": 0}
    except:
        return {"reachable": False, "avg_ms": None, "loss": 100}

def http_test(url, timeout=3):
    try:
        start = time.time()
        r = requests.get(url, timeout=timeout, verify=False)
        elapsed = round((time.time() - start) * 1000, 0)
        return {"reachable": True, "status": r.status_code, "response_ms": elapsed}
    except:
        return {"reachable": False, "status": None, "response_ms": None}

# ─── Switches Config ──────────────────────────────────────────

CORE_10G_PORTS = {2, 7, 8}

SWITCHES = [
    {"name": "Core Switch", "ip": os.getenv("SWITCH_CORE_IP", "10.0.0.10"), "community": os.getenv("SWITCH_CORE_COMM", "public"), "model": "10G Managed", "is_core": True},
    {"name": "Office Switch", "ip": os.getenv("SWITCH_OFFICE_IP", "10.0.0.11"), "community": os.getenv("SWITCH_OFFICE_COMM", "public"), "model": "2.5G Managed", "is_core": False},
    {"name": "Studio Switch", "ip": os.getenv("SWITCH_STUDIO_IP", "10.0.0.12"), "community": os.getenv("SWITCH_STUDIO_COMM", "public"), "model": "2.5G Managed", "is_core": False},
]

# ─── 5-Min SNMP Averages ─────────────────────────────────────

_switch_5min = {}  # {ip: {"samples": [...], "ports_up_avg": 0, "ports_down_avg": 0, "errors_5min": 0, "availability_pct": 100.0}}

def _poll_switches_5min():
    while True:
        try:
            for sw in SWITCHES:
                ip = sw["ip"]
                if ip not in _switch_5min:
                    _switch_5min[ip] = {"samples": [], "availability_checks": 0, "availability_ok": 0}
                
                result = ping_host(ip, 1)
                _switch_5min[ip]["availability_checks"] += 1
                if result["reachable"]:
                    _switch_5min[ip]["availability_ok"] += 1
                
                sample = {"time": time.time(), "ping_ms": result["avg_ms"], "reachable": result["reachable"], "ports_up": 0, "ports_down": 0, "total_errors": 0, "port_details": []}
                
                try:
                    if_oper = snmp_walk_indexed(ip, sw["community"], "1.3.6.1.2.1.2.2.1.8")
                    if_in_err = snmp_walk_indexed(ip, sw["community"], "1.3.6.1.2.1.2.2.1.14")
                    if_out_err = snmp_walk_indexed(ip, sw["community"], "1.3.6.1.2.1.2.2.1.20")
                    if_speed = snmp_walk_indexed(ip, sw["community"], "1.3.6.1.2.1.2.2.1.5")
                    if_in_oct = snmp_walk_indexed(ip, sw["community"], "1.3.6.1.2.1.2.2.1.10")
                    if_out_oct = snmp_walk_indexed(ip, sw["community"], "1.3.6.1.2.1.2.2.1.16")
                    
                    physical_ports = sorted([int(k) for k in if_oper.keys() if int(k) < 100])
                    ports_up = sum(1 for k in physical_ports if if_oper.get(str(k)) == "1")
                    ports_down = len(physical_ports) - ports_up
                    total_errors = sum(int(if_in_err.get(str(k), 0) or 0) + int(if_out_err.get(str(k), 0) or 0) for k in physical_ports)
                    
                    sample["ports_up"] = ports_up
                    sample["ports_down"] = ports_down
                    sample["total_errors"] = total_errors
                    
                    port_details = []
                    for i in physical_ports:
                        idx = str(i)
                        spd = int(if_speed.get(idx, "0") or 0)
                        port_details.append({
                            "port": i,
                            "status": "up" if if_oper.get(idx) == "1" else "down",
                            "speed": spd,
                            "in_octets": int(if_in_oct.get(idx, "0") or 0),
                            "out_octets": int(if_out_oct.get(idx, "0") or 0),
                            "in_errors": int(if_in_err.get(idx, "0") or 0),
                            "out_errors": int(if_out_err.get(idx, "0") or 0),
                        })
                    sample["port_details"] = port_details
                except:
                    pass
                
                _switch_5min[ip]["samples"].append(sample)
                cutoff = time.time() - 300
                _switch_5min[ip]["samples"] = [s for s in _switch_5min[ip]["samples"] if s["time"] > cutoff]
        except:
            pass
        time.sleep(30)

threading.Thread(target=_poll_switches_5min, daemon=True).start()

def get_switch_5min_avg(ip):
    data = _switch_5min.get(ip)
    if not data or not data["samples"]:
        return None
    samples = data["samples"]
    reachable_samples = [s for s in samples if s["reachable"]]
    avail_pct = round((data["availability_ok"] / max(data["availability_checks"], 1)) * 100, 1) if data["availability_checks"] > 0 else 100.0
    
    avg_ping = round(sum(s["ping_ms"] for s in reachable_samples if s["ping_ms"]) / max(len([s for s in reachable_samples if s["ping_ms"]]), 1), 1)
    avg_ports_up = round(sum(s["ports_up"] for s in samples) / len(samples), 1)
    avg_ports_down = round(sum(s["ports_down"] for s in samples) / len(samples), 1)
    total_errors = sum(s["total_errors"] for s in samples)
    
    latest = samples[-1]
    return {
        "avg_ping_ms": avg_ping,
        "avg_ports_up": avg_ports_up,
        "avg_ports_down": avg_ports_down,
        "total_errors_5min": total_errors,
        "availability_pct": avail_pct,
        "samples_collected": len(samples),
        "latest_ports": latest.get("port_details", []),
    }

# ─── Device Health Monitor ────────────────────────────────────

_device_health = {}
_NETWORK_DEVICES = [
    {"name": "Gateway", "ip": "10.100.1.1", "type": "gateway"},
    {"name": "UniFi Dream Router", "ip": UNIFI_IP, "type": "router"},
    {"name": "Proxmox", "ip": PVE_IP, "type": "server"},
    {"name": "Home Assistant", "ip": "10.100.1.120", "type": "server"},
]
for sw in SWITCHES:
    _NETWORK_DEVICES.append({"name": sw["name"], "ip": sw["ip"], "type": "switch"})

def _monitor_devices():
    while True:
        try:
            now = time.time()
            for dev in _NETWORK_DEVICES:
                ip = dev["ip"]
                if ip not in _device_health:
                    _device_health[ip] = {"name": dev["name"], "type": dev["type"], "pings": [], "http_checks": []}
                
                ping_result = ping_host(ip, 1)
                _device_health[ip]["pings"].append({"time": now, **ping_result})
                _device_health[ip]["pings"] = [p for p in _device_health[ip]["pings"] if now - p["time"] < 300]
                
                if dev["type"] == "server":
                    url = f"http://{ip}:8123" if "100.1.120" in ip else f"https://{ip}:8006"
                    http_result = http_test(url)
                    _device_health[ip]["http_checks"].append({"time": now, **http_result})
                    _device_health[ip]["http_checks"] = [h for h in _device_health[ip]["http_checks"] if now - h["time"] < 300]
        except:
            pass
        time.sleep(15)

threading.Thread(target=_monitor_devices, daemon=True).start()

def get_device_health_summary():
    result = []
    for dev in _NETWORK_DEVICES:
        ip = dev["ip"]
        data = _device_health.get(ip)
        
        if not data or not data["pings"]:
            ping_result = ping_host(ip, 1)
            http_status = None
            if dev["type"] == "server":
                url = f"http://{ip}:8123" if "100.1.120" in ip else f"https://{ip}:8006"
                http_result = http_test(url)
                http_status = http_result.get("status")
            
            status = "online" if ping_result["reachable"] else "offline"
            result.append({"name": dev["name"], "ip": ip, "type": dev["type"], "status": status, "avg_ping_ms": ping_result["avg_ms"], "availability_pct": 100.0 if ping_result["reachable"] else 0.0, "http_status": http_status, "ping_samples": 1})
            continue
        
        pings = data["pings"]
        reachable = sum(1 for p in pings if p["reachable"])
        avail = round((reachable / len(pings)) * 100, 1)
        avg_ping = round(sum(p["avg_ms"] for p in pings if p["avg_ms"]) / max(len([p for p in pings if p["avg_ms"]]), 1), 1)
        
        http_status = None
        if data["http_checks"]:
            latest_http = data["http_checks"][-1]
            http_status = latest_http.get("status")
        
        status = "online" if avail > 90 else ("degraded" if avail > 50 else "offline")
        result.append({"name": dev["name"], "ip": ip, "type": dev["type"], "status": status, "avg_ping_ms": avg_ping, "availability_pct": avail, "http_status": http_status, "ping_samples": len(pings)})
    return result

# ─── Uptime Kuma ──────────────────────────────────────────────

def get_uptime_kuma():
    all_monitors = []
    for slug in UPTIME_KUMA_SLUGS:
        try:
            r = requests.get(f"{UPTIME_KUMA_URL}/api/status-page/heartbeat/{slug}", timeout=5)
            r.raise_for_status()
            data = r.json()
            monitors = data.get("monitorList", [])
            for m in monitors:
                heartbeats = m.get("heartbeatList", {})
                latest = None
                for key, beats in heartbeats.items():
                    if beats:
                        latest = beats[-1]
                        break
                all_monitors.append({
                    "name": m.get("name", "?"),
                    "status": m.get("status", 0),
                    "uptime_24h": m.get("uptime", 0),
                    "latest_ping": latest.get("ping", None) if latest else None,
                    "url": m.get("url", ""),
                    "group": slug,
                })
        except Exception as e:
            all_monitors.append({"name": f"Status Page: {slug}", "status": 0, "uptime_24h": 0, "latest_ping": None, "url": "", "group": slug, "error": str(e)})
    return {"monitors": all_monitors, "total": len(all_monitors), "up": sum(1 for m in all_monitors if m["status"] == 1)}

# ─── Pi-hole V6 ───────────────────────────────────────────────

def get_pihole_v6(config):
    try:
        r = requests.get(f"{config['url']}/stats/summary", headers={"X-API-Key": config["token"]}, timeout=5, verify=False)
        r.raise_for_status()
        data = r.json()
        queries = data.get("queries", {})
        gravity = data.get("gravity", {})
        return {
            "name": config["name"],
            "online": True,
            "ads_blocked": queries.get("blocked", 0),
            "ads_pct": round(queries.get("percent_blocked", 0), 1),
            "queries": queries.get("total", 0),
            "blocked": queries.get("blocked", 0),
            "domains_blocked": gravity.get("domains_being_blocked", 0),
            "status": "active",
        }
    except Exception as e:
        return {"name": config["name"], "online": False, "status": "offline", "error": str(e)}

# ─── AdGuard Home ─────────────────────────────────────────────

def get_adguard():
    try:
        stats = requests.get(f"http://{ADGUARD_IP}/control/stats", timeout=5)
        status = requests.get(f"http://{ADGUARD_IP}/control/status", timeout=5)
        if stats.status_code != 200:
            raise Exception(f"HTTP {stats.status_code}")
        sd = stats.json()
        st = status.json() if status.status_code == 200 else {}
        total_q = sd.get("num_dns_queries", 0)
        blocked_q = sd.get("num_blocked_filtering", 0)
        blocked_pct = round((blocked_q / total_q * 100) if total_q > 0 else 0, 1)
        return {
            "name": f"AdGuard Home ({ADGUARD_IP})",
            "ip": ADGUARD_IP,
            "online": True,
            "ads_blocked": blocked_q,
            "ads_pct": blocked_pct,
            "queries": total_q,
            "blocked": blocked_q,
            "domains_blocked": sd.get("num_filters", 0),
            "status": "enabled" if st.get("protection_enabled", True) else "disabled",
        }
    except Exception as e:
        return {"name": f"AdGuard Home ({ADGUARD_IP})", "ip": ADGUARD_IP, "online": False, "status": "offline", "error": str(e)}

# ─── DNS/Ad Blocking Summary ─────────────────────────────────

@app.get("/api/dns")
def api_dns():
    cached = cache.get("dns")
    if cached is not None:
        return cached
    p1 = get_pihole_v6(PIHOLE_1)
    p2 = get_pihole_v6(PIHOLE_2)
    ag = get_adguard()
    total_queries = (p1.get("queries", 0) or 0) + (p2.get("queries", 0) or 0) + (ag.get("queries", 0) or 0)
    total_blocked = (p1.get("blocked", 0) or 0) + (p2.get("blocked", 0) or 0) + (ag.get("blocked", 0) or 0)
    total_pct = round((total_blocked / total_queries * 100) if total_queries > 0 else 0, 1)
    result = {
        "piholes": [p1, p2],
        "adguard": ag,
        "total_queries": total_queries,
        "total_blocked": total_blocked,
        "total_blocked_pct": total_pct,
    }
    cache.set("dns", result, ttl=15)
    return result

# ─── Uptime Kuma API ──────────────────────────────────────────

@app.get("/api/uptime-kuma")
def api_uptime_kuma():
    cached = cache.get("uptime_kuma")
    if cached is not None:
        return cached
    result = get_uptime_kuma()
    cache.set("uptime_kuma", result, ttl=10)
    return result

# ─── Switch Status (instant) ──────────────────────────────────

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
            spd = int(if_speed.get(idx, "0") or 0)
            port_status.append({
                "port": i,
                "name": if_names.get(idx, f"Port {i}"),
                "status": "up" if if_oper.get(idx) == "1" else "down",
                "speed": spd,
                "is_10g": sw.get("is_core") and i in CORE_10G_PORTS,
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
            "name": sw["name"], "ip": sw["ip"], "model": sw["model"], "is_core": sw.get("is_core", False),
            "online": True, "total_ports": len(port_status),
            "ports_up": ports_up, "ports_down": len(port_status) - ports_up,
            "uptime_days": uptime_days, "ports": port_status, "traffic": port_traffic,
        }
    except Exception as e:
        return {
            "name": sw["name"], "ip": sw["ip"], "model": sw["model"], "is_core": sw.get("is_core", False),
            "online": False, "total_ports": 0, "ports_up": 0, "ports_down": 0,
            "uptime_days": 0, "ports": [], "traffic": [], "error": str(e),
        }

# ─── API Endpoints ────────────────────────────────────────────

@app.get("/api/dashboard")
def api_dashboard():
    cached = cache.get("dashboard")
    if cached is not None:
        return cached

    result = {"power": {}, "network": {}, "proxmox": {}, "environment": {}, "dns": {}}
    try:
        entities = ha_get("/states")
        power_entities = [e for e in entities if e.get("attributes", {}).get("unit_of_measurement") == "W"]
        total_w = sum(float(e["state"]) for e in power_entities if e["state"] not in ["unknown", "unavailable"])
        active_devices = [{"name": e["attributes"].get("friendly_name", e["entity_id"]), "entity": e["entity_id"], "watts": float(e["state"]), "room": _guess_room(e["entity_id"], e.get("attributes", {}))} for e in power_entities if e["state"] not in ["unknown", "unavailable"]]
        active_devices.sort(key=lambda x: x["watts"], reverse=True)
        result["power"] = {"total_watts": total_w, "active_devices": len(active_devices), "devices": active_devices}
    except:
        result["power"] = {"total_watts": 0, "active_devices": 0, "devices": []}
    
    try:
        entities2 = ha_get("/states")
        temp_sensors = []
        for e in entities2:
            eid = e.get("entity_id", "").lower()
            attrs = e.get("attributes", {})
            unit = attrs.get("unit_of_measurement", "")
            if ("temperature" in eid or "temp" in eid) and unit in ["°C", "°F", "C", "F"]:
                try:
                    val = float(e["state"])
                    temp_sensors.append({
                        "name": attrs.get("friendly_name", e["entity_id"]),
                        "entity": e["entity_id"],
                        "value": val,
                        "unit": unit,
                        "room": _guess_room(eid, attrs),
                    })
                except:
                    pass
        temp_sensors.sort(key=lambda x: x["value"])
        result["environment"] = {"temp_sensors": temp_sensors}
    except:
        result["environment"] = {"temp_sensors": []}
    
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
        running_vms = [v for v in vms if v.get("status") == "running"]
        total_cpu = sum(v.get("cpu", 0) for v in running_vms)
        total_ram = sum(v.get("mem", 0) for v in running_vms)
        total_max_ram = sum(v.get("maxmem", 1) for v in running_vms)
        cpu_pct = round((total_cpu / len(running_vms)) * 100, 1) if running_vms else 0
        ram_pct = round((total_ram / total_max_ram) * 100, 1) if total_max_ram else 0
        result["proxmox"] = {
            "vms_running": len(running_vms),
            "vms_total": len(vms),
            "cpu_pct": cpu_pct,
            "ram_pct": ram_pct,
        }
    except:
        result["proxmox"] = {"vms_running": 0, "vms_total": 0, "cpu_pct": 0, "ram_pct": 0}
    
    try:
        entities = ha_get("/states")
        temp_sensor = None
        for e in entities:
            eid = e.get("entity_id", "").lower()
            attrs = e.get("attributes", {})
            unit = attrs.get("unit_of_measurement", "")
            if ("temperature" in eid or "temp" in eid) and unit in ["°C", "°F", "C", "F"]:
                if any(x in eid for x in ["indoor", "inside", "living", "main", "house", "room", "hall"]):
                    try:
                        temp_sensor = {"name": attrs.get("friendly_name", e["entity_id"]), "value": float(e["state"]), "unit": unit}
                        break
                    except:
                        pass
        if not temp_sensor:
            for e in entities:
                eid = e.get("entity_id", "").lower()
                attrs = e.get("attributes", {})
                unit = attrs.get("unit_of_measurement", "")
                if ("temperature" in eid or "temp" in eid) and unit in ["°C", "°F", "C", "F"]:
                    try:
                        temp_sensor = {"name": attrs.get("friendly_name", e["entity_id"]), "value": float(e["state"]), "unit": unit}
                        break
                    except:
                        pass
        result["environment"] = {"indoor_temp": temp_sensor}
    except:
        result["environment"] = {"indoor_temp": None}
    
    try:
        p1 = get_pihole_v6(PIHOLE_1)
        p2 = get_pihole_v6(PIHOLE_2)
        ag = get_adguard()
        total_queries = (p1.get("queries", 0) or 0) + (p2.get("queries", 0) or 0) + (ag.get("queries", 0) or 0)
        total_blocked = (p1.get("blocked", 0) or 0) + (p2.get("blocked", 0) or 0) + (ag.get("blocked", 0) or 0)
        total_pct = round((total_blocked / total_queries * 100) if total_queries > 0 else 0, 1)
        result["dns"] = {
            "piholes": [p1, p2],
            "adguard": ag,
            "total_queries": total_queries,
            "total_blocked": total_blocked,
            "total_blocked_pct": total_pct,
        }
    except:
        result["dns"] = {"total_queries": 0, "total_blocked": 0, "total_blocked_pct": 0, "piholes": [], "adguard": {}}
    
    cache.set("dashboard", result, ttl=8)
    return result

@app.get("/api/power")
def api_power():
    cached = cache.get("power")
    if cached is not None:
        return cached
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
        result = {"total_watts": total, "active_devices": len(all_devices), "all": all_devices}
    except Exception as e:
        result = {"total_watts": 0, "active_devices": 0, "all": [], "error": str(e)}
    cache.set("power", result, ttl=10)
    return result

@app.get("/api/proxmox/vms")
def api_vms():
    cached = cache.get("proxmox_vms")
    if cached is not None:
        return cached
    try:
        vms = pve_get("/cluster/resources?type=vm")
        result_vms = []
        for v in vms:
            if v.get("status") != "running":
                continue
            cpu_pct = round(v.get("cpu", 0) * 100, 1)
            mem_pct = round((v.get("mem", 0) / v.get("maxmem", 1)) * 100, 1) if v.get("maxmem") else 0
            disk_pct = round((v.get("disk", 0) / v.get("maxdisk", 1)) * 100, 1) if v.get("maxdisk") else 0
            uptime_sec = v.get("uptime", 0)
            uptime_str = f"{uptime_sec // 86400}d {(uptime_sec % 86400) // 3600}h" if uptime_sec else "0h"
            result_vms.append({
                "vmid": v.get("vmid"),
                "name": v.get("name", f"VM {v.get('vmid')}"),
                "type": v.get("type", "qemu"),
                "status": "running",
                "cpu": cpu_pct,
                "mem_pct": mem_pct,
                "disk_pct": disk_pct,
                "disk_total": v.get("maxdisk", 0),
                "uptime": uptime_str,
            })
        result = {"vms": result_vms}
    except Exception as e:
        result = {"vms": [], "error": str(e)}
    cache.set("proxmox_vms", result, ttl=15)
    return result

@app.get("/api/proxmox/storage")
def api_storage():
    cached = cache.get("proxmox_storage")
    if cached is not None:
        return cached
    try:
        storage = pve_get("/storage")
        result = {"storage": storage}
    except Exception as e:
        result = {"storage": [], "error": str(e)}
    cache.set("proxmox_storage", result, ttl=30)
    return result

@app.get("/api/network/clients")
def api_net_clients():
    cached = cache.get("net_clients")
    if cached is not None:
        return cached
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
        out = {"clients": result, "total": len(result),
                "wifi": sum(1 for c in clients if not c.get("is_wired")),
                "wired": sum(1 for c in clients if c.get("is_wired"))}
    except Exception as e:
        out = {"clients": [], "error": str(e)}
    cache.set("net_clients", out, ttl=5)
    return out

@app.get("/api/network/devices")
def api_net_devices():
    cached = cache.get("net_devices")
    if cached is not None:
        return cached
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
        out = {"devices": result}
    except Exception as e:
        out = {"devices": [], "error": str(e)}
    cache.set("net_devices", out, ttl=10)
    return out

@app.get("/api/network/health")
def api_net_health():
    cached = cache.get("net_health")
    if cached is not None:
        return cached
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
        out = {"health": result}
    except Exception as e:
        out = {"health": [], "error": str(e)}
    cache.set("net_health", out, ttl=10)
    return out

@app.get("/api/network/flows")
def api_net_flows():
    return {"flows": [], "total": 0, "wan1": {"download_bps": 0, "upload_bps": 0}}

@app.get("/api/water")
def api_water():
    cached = cache.get("water")
    if cached is not None:
        return cached
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
        result = {"water": {"sensors": water}}
    except Exception as e:
        result = {"water": {"error": str(e)}}
    cache.set("water", result, ttl=15)
    return result

# ─── Switches API ─────────────────────────────────────────────

@app.get("/api/switches")
def api_switches():
    cached = cache.get("switches")
    if cached is not None:
        return cached
    result = []
    for sw in SWITCHES:
        status = get_switch_status(sw)
        avg5 = get_switch_5min_avg(sw["ip"])
        if avg5:
            status["avg_5min"] = avg5
        result.append(status)
    out = {"switches": result}
    cache.set("switches", out, ttl=8)
    return out

@app.get("/api/switches/{switch_ip}/ports")
def api_switch_ports(switch_ip: str):
    sw = next((s for s in SWITCHES if s["ip"] == switch_ip), None)
    if not sw:
        raise HTTPException(status_code=404, detail="Switch not found")
    return get_switch_status(sw)

@app.get("/api/device-health")
def api_device_health():
    return {"devices": get_device_health_summary()}

# ─── Insights API ─────────────────────────────────────────────

@app.get("/api/insights")
def api_insights():
    cached = cache.get("insights")
    if cached is not None:
        return cached
    
    insights = []
    
    try:
        total_w = 0
        power_devices = []
        indoor_temp = None
        
        try:
            entities = ha_get("/states")
            power_entities = [e for e in entities if e.get("attributes", {}).get("unit_of_measurement") == "W"]
            total_w = sum(float(e["state"]) for e in power_entities if e["state"] not in ["unknown", "unavailable"])
            for e in power_entities:
                try:
                    watts = float(e["state"])
                except:
                    watts = 0
                power_devices.append({"name": e["attributes"].get("friendly_name", e["entity_id"]), "entity": e["entity_id"], "watts": watts})
            
            for e in entities:
                eid = e.get("entity_id", "").lower()
                attrs = e.get("attributes", {})
                unit = attrs.get("unit_of_measurement", "")
                if ("temperature" in eid or "temp" in eid) and unit in ["°C", "°F", "C", "F"]:
                    if any(x in eid for x in ["indoor", "inside", "living", "main", "house", "room", "hall"]):
                        try:
                            indoor_temp = {"name": attrs.get("friendly_name", e["entity_id"]), "value": float(e["state"]), "unit": unit}
                            break
                        except:
                            pass
            if not indoor_temp:
                for e in entities:
                    eid = e.get("entity_id", "").lower()
                    attrs = e.get("attributes", {})
                    unit = attrs.get("unit_of_measurement", "")
                    if ("temperature" in eid or "temp" in eid) and unit in ["°C", "°F", "C", "F"]:
                        try:
                            indoor_temp = {"name": attrs.get("friendly_name", e["entity_id"]), "value": float(e["state"]), "unit": unit}
                            break
                        except:
                            pass
        except:
            pass
        
        watts_devices = sorted([d for d in power_devices if d.get("watts", 0) > 0], key=lambda x: x["watts"], reverse=True)
        top3 = watts_devices[:3]
        standby = [d for d in watts_devices if d["watts"] < 5]
        standby_w = sum(d["watts"] for d in standby)
        
        if indoor_temp and indoor_temp.get("value"):
            temp_val = indoor_temp["value"]
            if temp_val > 28:
                insights.append({"level": "warn", "icon": "🌡️", "title": "High Indoor Temp", "detail": f"{temp_val}{indoor_temp.get('unit','°C')} — consider ventilation or AC"})
            elif temp_val > 25:
                insights.append({"level": "info", "icon": "🌡️", "title": "Warm Indoors", "detail": f"{temp_val}{indoor_temp.get('unit','°C')} — monitor if it climbs"})
            if total_w > 500 and temp_val > 24:
                insights.append({"level": "warn", "icon": "⚡🌡️", "title": "Power + Temp Correlation", "detail": f"High draw ({total_w:.0f}W) may be raising indoor temp ({temp_val}{indoor_temp.get('unit','°C')})"})
        
        if top3:
            top3_pct = (sum(d["watts"] for d in top3) / max(total_w, 1)) * 100
            if top3_pct > 60:
                insights.append({"level": "info", "icon": "🔥", "title": "Power Concentration", "detail": f"Top 3 devices use {top3_pct:.0f}%: {', '.join(d['name'] for d in top3)}"})
        
        if standby and len(standby) > 5:
            monthly_cost = (standby_w / 1000) * 24 * 30 * 0.15
            insights.append({"level": "warn", "icon": "👻", "title": "Vampire Power", "detail": f"{len(standby)} devices in standby — ~${monthly_cost:.2f}/mo wasted"})
        
        for sw in SWITCHES:
            sw_data = get_switch_status(sw)
            if not sw_data["online"]:
                insights.append({"level": "critical", "icon": "🔌", "title": f"{sw['name']} Offline", "detail": sw_data.get("error", "No response")})
            else:
                avg5 = get_switch_5min_avg(sw["ip"])
                if avg5:
                    if avg5["availability_pct"] < 100:
                        insights.append({"level": "warn", "icon": "📉", "title": f"{sw['name']} Availability", "detail": f"{avg5['availability_pct']}% over last 5 min"})
                    if avg5["total_errors_5min"] > 0:
                        insights.append({"level": "warn", "icon": "⚠️", "title": f"{sw['name']} Port Errors", "detail": f"{avg5['total_errors_5min']} errors in last 5 min"})
                    if avg5["avg_ping_ms"] and avg5["avg_ping_ms"] > 50:
                        insights.append({"level": "warn", "icon": "🐌", "title": f"{sw['name']} High Latency", "detail": f"Avg {avg5['avg_ping_ms']}ms over 5 min"})
        
        device_health = get_device_health_summary()
        for dev in device_health:
            if dev["status"] == "offline":
                insights.append({"level": "critical", "icon": "❌", "title": f"{dev['name']} Unreachable", "detail": f"IP: {dev['ip']}"})
            elif dev["status"] == "degraded":
                insights.append({"level": "warn", "icon": "⚠️", "title": f"{dev['name']} Unstable", "detail": f"{dev['availability_pct']}% availability"})
        
        try:
            health = unifi_get("/stat/health")
            wlan = next((h for h in health if h.get("subsystem") == "wlan"), {})
            lan = next((h for h in health if h.get("subsystem") == "lan"), {})
            wifi_clients = wlan.get("num_user", 0)
            wired_clients = lan.get("num_user", 0)
            total_clients = wifi_clients + wired_clients
            if total_clients > 0 and wifi_clients / total_clients > 0.8:
                insights.append({"level": "info", "icon": "📶", "title": "WiFi Heavy", "detail": f"{wifi_clients}/{total_clients} clients on WiFi — consider wiring stationary devices"})
        except:
            pass
        
        if not insights:
            insights.append({"level": "ok", "icon": "✅", "title": "All Systems Normal", "detail": "No issues detected"})
    except Exception as e:
        insights = [{"level": "error", "icon": "❌", "title": "Insights Error", "detail": str(e)}]
    
    result = {"insights": insights}
    cache.set("insights", result, ttl=15)
    return result

# ─── UniFi API ────────────────────────────────────────────────

@app.get("/api/unifi")
def api_unifi():
    cached = cache.get("unifi")
    if cached is not None:
        return cached
    result = {"online": False, "error": "No response"}
    health_list = unifi_get("/stat/health")
    if not health_list:
        cache.set("unifi", result, ttl=5)
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
        result["wan1_latency"] = latest.get("wan1_latency", 0)
    alarms = unifi_get("/stat/alarm")
    result["alarms"] = len(alarms)
    cache.set("unifi", result, ttl=10)
    return result

@app.get("/api/unifi/clients")
def api_unifi_clients():
    cached = cache.get("unifi_clients")
    if cached is not None:
        return cached
    clients = unifi_get("/stat/sta")
    if not clients:
        result = {"error": "No data", "clients": []}
    else:
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
        result = {"clients": result}
    cache.set("unifi_clients", result, ttl=5)
    return result

# ─── Latency Tracker ──────────────────────────────────────────

_latency_history = {"wan": [], "wan1": [], "max_samples": 120}

def _ping_latency(host, count=2):
    try:
        r = subprocess.run(
            ["ping", "-c", str(count), "-W", "2", host],
            capture_output=True, text=True, timeout=10
        )
        output = r.stdout
        for line in output.split('\n'):
            if 'rtt' in line or 'round-trip' in line:
                parts = line.split('/')
                if len(parts) >= 5:
                    return float(parts[4])
        return None
    except:
        return None

def _track_latency():
    while True:
        try:
            now = time.time()
            wan_lat = _ping_latency("10.100.1.1", 2)
            wan1_lat = _ping_latency("192.168.12.1", 2)
            _latency_history["wan"].append({"time": now, "value": wan_lat if wan_lat else 0})
            _latency_history["wan1"].append({"time": now, "value": wan1_lat if wan1_lat else 0})
            cutoff = now - 600
            _latency_history["wan"] = [s for s in _latency_history["wan"] if s["time"] > cutoff]
            _latency_history["wan1"] = [s for s in _latency_history["wan1"] if s["time"] > cutoff]
        except:
            pass
        time.sleep(5)

threading.Thread(target=_track_latency, daemon=True).start()

@app.get("/api/latency")
def api_latency():
    return _latency_history

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
