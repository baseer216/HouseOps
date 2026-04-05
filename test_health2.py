import subprocess
import os
from dotenv import load_dotenv

load_dotenv('/opt/houseops/.env')
print('UNIFI_IP:', os.getenv('UNIFI_IP'))

# Test ping
r = subprocess.run('ping -c 2 -W 2 10.100.1.1', shell=True, capture_output=True, text=True)
print('ping rc:', r.returncode)
print('ping out:', r.stdout[:200])

# Import and test device health function directly
import sys
sys.path.insert(0, '/opt/houseops/backend')
from main import get_device_health_summary

health = get_device_health_summary()
print('Health result:', health)