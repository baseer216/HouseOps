import subprocess
import os
import sys
sys.path.insert(0, '/opt/houseops/backend')

# Simulate the function
def ping_host(ip, count=2):
    try:
        r = subprocess.run(["ping", "-c", str(count), "-W", "2", ip], capture_output=True, text=True, timeout=8)
        print(f"Ping {ip}: returncode={r.returncode}", file=sys.stderr)
        print(f"stdout: {r.stdout[:200]}", file=sys.stderr)
        for line in r.stdout.split('\n'):
            if 'rtt' in line or 'round-trip' in line:
                parts = line.split('/')
                print(f"parts: {parts}", file=sys.stderr)
                if len(parts) >= 5:
                    print(f"Returning success", file=sys.stderr)
                    return {"reachable": True, "avg_ms": round(float(parts[4]), 1), "loss": 0}
        if r.returncode != 0:
            print(f"Returncode non-zero", file=sys.stderr)
            return {"reachable": False, "avg_ms": None, "loss": 100}
        print(f"Returning reachable=True, avg=0", file=sys.stderr)
        return {"reachable": True, "avg_ms": 0, "loss": 0}
    except Exception as e:
        print(f"Exception: {e}", file=sys.stderr)
        return {"reachable": False, "avg_ms": None, "loss": 100}

result = ping_host("10.100.1.1", 2)
print(f"Result: {result}")