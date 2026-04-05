# ─── Latency Tracker ──────────────────────────────────────────

_latency_history = {"wan": [], "wan1": [], "max_samples": 120}  # 120 samples @ 5s = 10 min

def _record_latency(data):
    """Record latency samples from dashboard data"""
    global _latency_history
    now = __import__('time').time()
    wan_lat = data.get("network", {}).get("latency_avg", 0)
    wan1_lat = data.get("network", {}).get("wan1_latency", 0)
    if wan_lat:
        _latency_history["wan"].append({"time": now, "value": wan_lat})
    if wan1_lat:
        _latency_history["wan1"].append({"time": now, "value": wan1_lat})
    # Trim old samples
    cutoff = now - 600  # 10 minutes
    _latency_history["wan"] = [s for s in _latency_history["wan"] if s["time"] > cutoff]
    _latency_history["wan1"] = [s for s in _latency_history["wan1"] if s["time"] > cutoff]

@app.get("/api/latency")
def api_latency():
    return _latency_history
