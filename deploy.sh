#!/bin/bash
# HouseOPS - One-click Proxmox LXC Deployment
# Usage: bash deploy.sh

set -e

VMID=200
HOSTNAME="houseops"
PASSWORD="houseops2026"
IP="10.100.1.200/24"
GW="10.100.1.1"
DNS="10.100.1.1"
MEMORY=2048
CORES=2
DISK=16
STORAGE="local-lvm"
TEMPLATE="debian-13-standard_13.1-2_amd64.tar.zst"

# UniFi config
UNIFI_IP="10.100.1.1"
UNIFI_KEY="vKBN69Exrt7ud2gHx3iNZvVFh5yZdXEu"

echo "=== HouseOPS LXC Deployment ==="
echo "VM ID: $VMID | IP: $IP"

# Download template if needed
if ! pveam list local | grep -q "$TEMPLATE"; then
    echo "Downloading template..."
    pveam download local $TEMPLATE
fi

# Create LXC
pct create $VMID local:vztmpl/$TEMPLATE \
    --hostname $HOSTNAME --password $PASSWORD \
    --net0 name=eth0,bridge=vmbr0,ip=$IP,gw=$GW \
    --nameserver $DNS --memory $MEMORY --cores $CORES \
    --rootfs $STORAGE:$DISK --features nesting=1,keyctl=1 \
    --unprivileged 0 --onboot 1 --start 1

echo "Waiting for boot..."
sleep 10

# Push and run setup
pct push $VMID /tmp/houseops_setup.sh /tmp/houseops_setup.sh
pct exec $VMID -- bash /tmp/houseops_setup.sh

echo ""
echo "=== Complete ==="
echo "Dashboard: http://$IP:8000"
echo "Network:   http://$IP:8000/network"
echo "Switches:  http://$IP:8000/switches"
