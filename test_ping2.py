import subprocess
import json

r = subprocess.run(['ping', '-c', '2', '10.100.1.1'], capture_output=True, text=True, timeout=8)
print('returncode:', r.returncode)
print('stdout:', r.stdout[:300])
print('stderr:', r.stderr[:300])