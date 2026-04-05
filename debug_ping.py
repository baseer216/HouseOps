import subprocess
import os

os.chdir('/tmp')
r = subprocess.run("ping -c 2 -W 2 10.100.1.1", shell=True, capture_output=True, text=True, timeout=8)
print("Return code:", r.returncode)
print("STDOUT:", r.stdout[:500])
print("STDERR:", r.stderr[:500])