# HouseOPS Deploy Script
# Usage: .\deploy.ps1
# Deploys updated backend + frontend to LXC 200 on Proxmox

$ErrorActionPreference = "Stop"

$PROXMOX = "root@10.100.1.253"
$VMID = 200
$SRC = "C:\Users\user\Documents\VibeCode\starthere\houseops"

$FILES = @(
    @{ Local = "$SRC\backend\main.py"; Remote = "/opt/houseops/backend/main.py" },
    @{ Local = "$SRC\frontend\index.html"; Remote = "/opt/houseops/frontend/index.html" },
    @{ Local = "$SRC\frontend\network.html"; Remote = "/opt/houseops/frontend/network.html" },
    @{ Local = "$SRC\frontend\switches.html"; Remote = "/opt/houseops/frontend/switches.html" },
    @{ Local = "$SRC\frontend\manifest.json"; Remote = "/opt/houseops/frontend/manifest.json" },
    @{ Local = "$SRC\frontend\sw.js"; Remote = "/opt/houseops/frontend/sw.js" }
)

Write-Host "=== HouseOPS Deploy ===" -ForegroundColor Cyan
Write-Host "Target: $PROXMOX (LXC $VMID)" -ForegroundColor Cyan
Write-Host ""

# Step 1: SCP files to Proxmox /tmp
Write-Host "[1/3] Copying files to Proxmox..." -ForegroundColor Yellow
foreach ($f in $FILES) {
    $name = [System.IO.Path]::GetFileName($f.Local)
    Write-Host "  $name" -ForegroundColor Gray
    $remotePath = $PROXMOX + ":/tmp/" + $name
    scp $f.Local $remotePath
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  FAILED: $name" -ForegroundColor Red
        exit 1
    }
}
Write-Host "  Done." -ForegroundColor Green
Write-Host ""

# Step 2: Push into container and restart
Write-Host "[2/3] Pushing files into LXC $VMID..." -ForegroundColor Yellow
$CMD = @"
pct push $VMID /tmp/main.py /opt/houseops/backend/main.py &&
pct push $VMID /tmp/index.html /opt/houseops/frontend/index.html &&
pct push $VMID /tmp/network.html /opt/houseops/frontend/network.html &&
pct push $VMID /tmp/switches.html /opt/houseops/frontend/switches.html &&
pct push $VMID /tmp/manifest.json /opt/houseops/frontend/manifest.json &&
pct push $VMID /tmp/sw.js /opt/houseops/frontend/sw.js &&
pct exec $VMID -- systemctl restart houseops &&
echo 'RESTART_OK'
"@

ssh $PROXMOX $CMD
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Deploy failed!" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Step 3: Verify
Write-Host "[3/3] Verifying..." -ForegroundColor Yellow
Start-Sleep -Seconds 3
try {
    $r = Invoke-WebRequest -Uri "http://10.100.1.200:8000/" -TimeoutSec 5 -UseBasicParsing
    if ($r.StatusCode -eq 200) {
        Write-Host "  Dashboard: OK" -ForegroundColor Green
    }
} catch {
    Write-Host "  Dashboard: Not responding yet (service may still be starting)" -ForegroundColor Yellow
}

try {
    $r = Invoke-WebRequest -Uri "http://10.100.1.200:8000/api/dashboard" -TimeoutSec 5 -UseBasicParsing
    if ($r.StatusCode -eq 200) {
        Write-Host "  API: OK" -ForegroundColor Green
    }
} catch {
    Write-Host "  API: Not responding yet" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Deploy Complete ===" -ForegroundColor Cyan
Write-Host "Dashboard: http://10.100.1.200:8000/" -ForegroundColor Cyan
Write-Host "Network:   http://10.100.1.200:8000/network" -ForegroundColor Cyan
Write-Host "Switches:  http://10.100.1.200:8000/switches" -ForegroundColor Cyan
