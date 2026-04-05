import os
import ssl
import urllib.request
import json
from dotenv import load_dotenv
load_dotenv(dotenv_path='/opt/houseops/.env')

UNIFI_IP = os.getenv('UNIFI_IP')
UNIFI_API_KEY = os.getenv('UNIFI_API_KEY', '')

url = f'https://{UNIFI_IP}/proxy/network/api/s/default/stat/device'
print(f'UNIFI_IP={UNIFI_IP}')
print(f'UNIFI_API_KEY present: {bool(UNIFI_API_KEY)}')

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
req = urllib.request.Request(url, headers={'X-API-KEY': UNIFI_API_KEY})
try:
    r = urllib.request.urlopen(req, context=ctx, timeout=10)
    print(f'Success: {r.status}')
    data = json.loads(r.read().decode())
    print(f'Devices: {len(data.get("data", []))}')
except Exception as e:
    print(f'Error: {e}')