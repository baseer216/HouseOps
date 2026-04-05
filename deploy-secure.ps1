# HouseOPS Secure Deploy Script
# Creates new .env on server from existing config + new variables
# IMPORTANT: Configure your environment variables below before running

$ErrorActionPreference = "Stop"

# CONFIGURE THESE FOR YOUR ENVIRONMENT
$PROXMOX = "root@YOUR_PROXMOX_IP"
$VMID = 200
$SRC = "C:\path\to\houseops"

$FILES = @(
    @{ Local = "$SRC\backend\main.py"; Remote = "/opt/houseops/backend/main.py" },
    @{ Local = "$SRC\frontend\index.html"; Remote = "/opt/houseops/frontend/index.html" },
    @{ Local = "$SRC\frontend\network.html"; Remote = "/opt/houseops/frontend/network.html" },
    @{ Local = "$SRC\frontend\switches.html"; Remote = "/opt/houseops/frontend/switches.html" },
    @{ Local = "$SRC\frontend\manifest.json"; Remote = "/opt/houseops/frontend/manifest.json" },
    @{ Local = "$SRC\frontend\sw.js"; Remote = "/opt/houseops/frontend/sw.js" }
)

Write-Host "=== HouseOPS Secure Deploy ===" -ForegroundColor Cyan
Write-Host "Target: $PROXMOX (LXC $VMID)" -ForegroundColor Cyan
Write-Host ""

# Step 1: Generate new .env from existing config
Write-Host "[1/4] Generating secure .env from existing config..." -ForegroundColor Yellow
$existingEnv = ssh $PROXMOX "pct exec $VMID -- cat /opt/houseops/.env 2>/dev/null || echo ''"

# Extract existing values
$envVars = @{}
if ($existingEnv) {
    $existingEnv -split "`n" | ForEach-Object {
        if ($_ -match '^([^=]+)=(.*)$') {
            $key = $matches[1].Trim()
            $val = $matches[2].Trim()
            if ($key -and $val -and $val -notmatch '^(your_|placeholder|)') {
                $envVars[$key] = $val
            }
        }
    }
    Write-Host "  Found $($envVars.Count) existing config values" -ForegroundColor Green
}

# Build new .env with all required variables
$newEnv = @"
# HouseOPS Configuration - Generated $(Get-Date -Format 'yyyy-MM-dd')
# All secrets and IPs are now loaded from environment variables

# ==================== DATABASE ====================
DB_PATH=$($envVars['DB_PATH'])

# ==================== PROXMOX ====================
PVE_IP=$($envVars['PVE_IP'])
PVE_TOKEN_ID=$($envVars['PVE_TOKEN_ID'])
PVE_SECRET=$($envVars['PVE_SECRET'])

# ==================== UNIFI ====================
UNIFI_IP=$($envVars['UNIFI_IP'])
UNIFI_API_KEY=$($envVars['UNIFI_API_KEY'])

# ==================== HOME ASSISTANT ====================
HA_URL=$($envVars['HA_URL'])
HA_TOKEN=$($envVars['HA_TOKEN'])
HA_IP=$($envVars['HA_IP'])

# ==================== NETWORK DEVICES ====================
GATEWAY_IP=$($envVars['GATEWAY_IP'])

# ==================== SWITCHES ====================
SWITCH_CORE_IP=$($envVars['SWITCH_CORE_IP'])
SWITCH_CORE_COMM=$($envVars['SWITCH_CORE_COMM'])
SWITCH_CORE_MODEL=$($envVars['SWITCH_CORE_MODEL'])
SWITCH_OFFICE_IP=$($envVars['SWITCH_OFFICE_IP'])
SWITCH_OFFICE_COMM=$($envVars['SWITCH_OFFICE_COMM'])
SWITCH_OFFICE_MODEL=$($envVars['SWITCH_OFFICE_MODEL'])
SWITCH_STUDIO_IP=$($envVars['SWITCH_STUDIO_IP'])
SWITCH_STUDIO_COMM=$($envVars['SWITCH_STUDIO_COMM'])
SWITCH_STUDIO_MODEL=$($envVars['SWITCH_STUDIO_MODEL'])

# ==================== DNS / AD BLOCKING ====================
PIHOLE_1_URL=$($envVars['PIHOLE_1_URL'])
PIHOLE_1_TOKEN=$($envVars['PIHOLE_1_TOKEN'])
PIHOLE_1_NAME=$($envVars['PIHOLE_1_NAME'])
PIHOLE_2_URL=$($envVars['PIHOLE_2_URL'])
PIHOLE_2_TOKEN=$($envVars['PIHOLE_2_TOKEN'])
PIHOLE_2_NAME=$($envVars['PIHOLE_2_NAME'])
ADGUARD_IP=$($envVars['ADGUARD_IP'])
ADGUARD_USER=$($envVars['ADGUARD_USER'])
ADGUARD_PASS=$($envVars['ADGUARD_PASS'])

# ==================== UPTIME KUMA ====================
UPTIME_KUMA_URL=$($envVars['UPTIME_KUMA_URL'])
UPTIME_KUMA_SLUGS=$($envVars['UPTIME_KUMA_SLUGS'])

# ==================== LATENCY TRACKING ====================
WAN_LATENCY_TARGET=$($envVars['WAN_LATENCY_TARGET'])
WAN1_LATENCY_TARGET=$($envVars['WAN1_LATENCY_TARGET'])
"@

# Save new .env to temp and copy
$newEnv | Out-File -FilePath "$env:TEMP\houseops.env" -Encoding UTF8
Write-Host "  Created new .env with $($envVars.Count) values" -ForegroundColor Green
Write-Host ""

# Step 2: Copy files to Proxmox
Write-Host "[2/4] Copying files to Proxmox..." -ForegroundColor Yellow
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
# Also copy the new .env
scp "$env:TEMP\houseops.env" "${PROXMOX}:/tmp/houseops.env"
Write-Host "  Done." -ForegroundColor Green
Write-Host ""

# Step 3: Push into container
Write-Host "[3/4] Pushing files into LXC $VMID..." -ForegroundColor Yellow
$CMD = @"
pct push $VMID /tmp/main.py /opt/houseops/backend/main.py &&
pct push $VMID /tmp/index.html /opt/houseops/frontend/index.html &&
pct push $VMID /tmp/network.html /opt/houseops/frontend/network.html &&
pct push $VMID /tmp/switches.html /opt/houseops/frontend/switches.html &&
pct push $VMID /tmp/manifest.json /opt/houseops/frontend/manifest.json &&
pct push $VMID /tmp/sw.js /opt/houseops/frontend/sw.js &&
pct push $VMID /tmp/houseops.env /opt/houseops/.env &&
pct exec $VMID -- systemctl restart houseops &&
echo 'RESTART_OK'
"@

ssh $PROXMOX $CMD
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Deploy failed!" -ForegroundColor Red
    exit 1
}
Write-Host "  Done." -ForegroundColor Green
Write-Host ""

# Step 4: Verify
Write-Host "[4/4] Verifying..." -ForegroundColor Yellow
Start-Sleep -Seconds 3
$TARGET_IP = "YOUR_LXC_IP"
try {
    $r = Invoke-WebRequest -Uri "http://${TARGET_IP}:8000/" -TimeoutSec 5 -UseBasicParsing
    if ($r.StatusCode -eq 200) {
        Write-Host "  Dashboard: OK" -ForegroundColor Green
    }
} catch {
    Write-Host "  Dashboard: Not responding" -ForegroundColor Yellow
}

try {
    $r = Invoke-WebRequest -Uri "http://${TARGET_IP}:8000/api/dashboard" -TimeoutSec 5 -UseBasicParsing
    if ($r.StatusCode -eq 200) {
        Write-Host "  API: OK" -ForegroundColor Green
    }
} catch {
    Write-Host "  API: Not responding" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Deploy Complete ===" -ForegroundColor Cyan
Write-Host "Security: All IPs/tokens moved to .env, not in code" -ForegroundColor Green
