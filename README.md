# HouseOPS

Smart Home Operations Dashboard - Real-time monitoring for UniFi, Proxmox, Home Assistant, and SNMP switches.

## Features

- **Power Monitoring**: Real-time wattage, cost estimates, device categorization, room breakdown
- **Network**: UniFi Dream Router integration with live client tracking, bandwidth, health
- **Proxmox**: VM status, storage monitoring
- **Switches**: SNMP monitoring for managed switches with port status, traffic, errors
- **PWA**: Installable on mobile/desktop, works offline with cached dashboard
- **Responsive**: Optimized for mobile portrait, landscape, tablet, and desktop

## Architecture

```
houseops/
├── backend/
│   └── main.py          # FastAPI backend with all API endpoints
├── frontend/
│   ├── index.html       # Main dashboard (PWA)
│   ├── network.html     # Detailed network page
│   ├── switches.html    # Detailed switch monitoring page
│   ├── manifest.json    # PWA manifest
│   ├── sw.js            # Service worker
│   └── icons/           # App icons
├── .env                 # Configuration (create from .env.example)
└── deploy.sh            # Proxmox LXC deployment script
```

## Quick Start

### Prerequisites

- Proxmox VE 8.x
- UniFi Dream Router 7 (or compatible UniFi controller)
- Home Assistant (optional, for power monitoring)
- SNMP-enabled switches (optional)

### Deployment

```bash
# On Proxmox host
wget https://raw.githubusercontent.com/YOUR_USERNAME/houseops/main/deploy.sh
chmod +x deploy.sh
bash deploy.sh
```

### Manual Setup

```bash
# Install dependencies
apt-get update && apt-get install -y python3 python3-pip python3-venv curl snmp

# Setup
cd /opt/houseops
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn requests python-dotenv

# Configure
cp .env.example .env
# Edit .env with your credentials

# Run
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

## Configuration

Copy `.env.example` to `.env` and configure:

```env
# UniFi Dream Router
UNIFI_IP=10.0.0.1
UNIFI_API_KEY=your_api_key_here

# Proxmox
PVE_IP=10.0.0.2
PVE_TOKEN_ID=root@pam!houseops
PVE_SECRET=your_token_secret

# Home Assistant
HA_URL=http://10.0.0.3:8123/api
HA_TOKEN=your_ha_token
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/dashboard` | Executive summary data |
| `GET /api/power` | Power device list and totals |
| `GET /api/unifi` | UniFi DR7 status and health |
| `GET /api/unifi/clients` | Live UniFi client list |
| `GET /api/switches` | SNMP switch status |
| `GET /api/proxmox/vms` | Proxmox VM list |
| `GET /api/network/clients` | Network client summary |
| `GET /api/network/devices` | Network device status |

## Screenshots

Dashboard includes:
- Executive summary KPIs
- Power usage with category donut chart
- Power by room breakdown
- Network bandwidth and client count
- Proxmox VM grid
- UniFi Dream Router status
- Live clients table (searchable, sortable)
- SNMP switch status cards

## License

MIT
