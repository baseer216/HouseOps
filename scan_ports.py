import socket
ports = [80, 443, 22, 23, 161, 162, 8080, 8443, 8000, 9000, 53, 8081, 8888, 10000]
results = []
for port in ports:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    result = sock.connect_ex(("10.100.1.6", port))
    if result == 0:
        results.append(f"Port {port}: OPEN")
    sock.close()

for r in results:
    print(r)

print("\n--- Scanning Studio Switch (10.100.1.14) ---")
for port in ports:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    result = sock.connect_ex(("10.100.1.14", port))
    if result == 0:
        print(f"Port {port}: OPEN")
    sock.close()