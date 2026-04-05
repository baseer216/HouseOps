# HouseOPS Dashboard Ideas

## Currently collected but NOT displayed
- Proxmox storage data (fetched but never rendered)
- Stopped VMs/CTs
- UniFi device upgradable/adopted flags
- Alarm details (only count shown)
- Pi-hole gravity domain counts, per-instance blocked domains
- AdGuard filter counts, protection status
- Switch per-port cumulative traffic & individual errors
- Full 10-min latency history
- Gateway uptime
- Water sensors (gallons today, capacity remaining)
- HA binary sensors, media players, weather, history

## Not integrated at all
- HA history API (time-series trends)
- Pi-hole top queries / top blocked domains
- AdGuard top clients / blocked services
- Proxmox node-level stats (host CPU/RAM/disk I/O)
- Proxmox backup status
- UniFi traffic stats per-client historical
- UniFi events (client connect/disconnect)
- Uptime Kuma heartbeat history
- External weather API

---

## 10 New Dashboard Ideas

### 1. Storage & Backups — Proxmox storage utilization
Show all storage pools (local, local-lvm, NFS, etc.) with capacity bars, usage %, and alerts when >80%. Add backup job status from vzdump — last run, success/fail, next scheduled.
**Data available:** Yes (Proxmox /storage endpoint already fetched, just not rendered)
**Priority:** High — easy win

### 2. Network Performance — Bandwidth, latency charts, WAN saturation
Replace the heatmap with real time-series charts. Show WAN utilization %, latency history (10-min sparklines), per-device bandwidth leaders, and alert when approaching ISP link capacity. Pull from UniFi traffic stats + switch port octets over time.
**Data available:** Partially (latency history collected, switch octets available, needs time-series storage)
**Priority:** High

### 3. DNS & Privacy — Pi-hole vs AdGuard comparison
Side-by-side comparison of all 3 resolvers. Top queried domains, top blocked domains, block rate trends, gravity list sizes. Show which resolver is handling the most load and which is most effective.
**Data available:** Partially (stats already collected, top queries/blocked domains needs Pi-hole/AdGuard API calls)
**Priority:** High — easy win

### 4. Security & Access — Doors, windows, motion, cameras
Pull HA binary sensors (door/window open/closed, motion detected, lock status). Show camera feeds or snapshots. Alert on unexpected motion, doors left open, or cameras offline.
**Data available:** No — needs HA binary_sensor and camera integration
**Priority:** Medium

### 5. Weather & Climate — Indoor vs outdoor comparison
Pull outdoor weather (HA weather integration or external API). Compare indoor vs outdoor temps across all rooms. Show HVAC correlation — when power spikes match temp changes. Trend charts for temperature over time.
**Data available:** Partially (indoor temps collected, needs outdoor weather source)
**Priority:** Medium

### 6. Energy & Cost Deep Dive — Time-series power analytics
Hourly/daily power usage charts. Cost breakdown by room and by device. Identify vampire power trends over time. Show peak usage hours. If solar/battery entities exist in HA, show net metering.
**Data available:** No — needs HA history API for time-series
**Priority:** Medium

### 7. Device Lifecycle — VMs, firmware, updates
All VMs/CTs (running AND stopped). UniFi devices with pending firmware upgrades. Proxmox node health. Show what's upgradable, what's been offline too long, and maintenance windows.
**Data available:** Yes (VMs already fetched, UniFi upgradable flag available, just not rendered)
**Priority:** High — easy win

### 8. Water & Environment — Usage, leaks, air quality
Water consumption today/week/month with trends. Capacity remaining alerts. Humidity sensors across rooms. Leak detector status. Correlate water usage with specific devices/times.
**Data available:** Partially (water sensors fetched, humidity not yet collected)
**Priority:** Medium

### 9. Incident Timeline — Correlated events across all systems
Unified timeline showing: Uptime Kuma outages, device health drops, switch port errors, DNS block spikes, power anomalies, UniFi alarms. Cross-correlate — e.g., "Internet went down at 2:15, 3 devices became unreachable, DNS queries dropped 40%."
**Data available:** Partially (all data sources available, needs event correlation engine + time-series storage)
**Priority:** High

### 10. Media & Entertainment — What's playing, where
HA media players — what's running on each TV, speaker, streaming device. Show active media sessions, who's watching what. Power correlation — entertainment zone power usage when media is active.
**Data available:** No — needs HA media_player integration
**Priority:** Low

---

## Implementation Priority Order
1. **Storage & Backups** — Easy, data already collected
2. **DNS & Privacy** — Easy, data partially collected
3. **Device Lifecycle** — Easy, data already collected
4. **Network Performance** — Medium, needs time-series storage
5. **Incident Timeline** — Medium, needs correlation engine
6. **Water & Environment** — Medium, needs humidity sensors
7. **Weather & Climate** — Medium, needs outdoor weather
8. **Energy & Cost Deep Dive** — Hard, needs HA history API
9. **Security & Access** — Hard, needs binary_sensor integration
10. **Media & Entertainment** — Hard, needs media_player integration
