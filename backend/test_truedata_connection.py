"""Quick test to verify TrueData trial account connectivity and available data."""
import sys
import time

try:
    from truedata import TD_live
    print("[OK] truedata package imported successfully")
except ImportError as e:
    print(f"[FAIL] Import error: {e}")
    sys.exit(1)

# Trial credentials
USER = "trial761"
PASS = "prakash761"

print(f"\nConnecting to TrueData as '{USER}'...")

try:
    td = TD_live(USER, PASS)
    print("[OK] Connected to TrueData WebSocket")
except Exception as e:
    print(f"[FAIL] Connection error: {e}")
    sys.exit(1)

# Subscribe to index data
symbols = ["NIFTY 50", "NIFTY BANK"]
print(f"\nSubscribing to: {symbols}")

try:
    td.start_live_data(symbols)
    print("[OK] Live data subscription started")
except Exception as e:
    print(f"[FAIL] Subscription error: {e}")
    sys.exit(1)

# Wait a few seconds for data to arrive
print("\nWaiting 5 seconds for tick data...")
time.sleep(5)

# Check if we got data
for sym in symbols:
    try:
        data = td.live_data.get(sym)
        if data:
            print(f"\n[OK] {sym}:")
            print(f"  LTP: {data.ltp}")
            print(f"  Timestamp: {data.timestamp}")
            print(f"  Volume: {getattr(data, 'volume', 'N/A')}")
            print(f"  OI: {getattr(data, 'oi', 'N/A')}")
        else:
            print(f"\n[WARN] {sym}: No data yet (market may be closed)")
    except Exception as e:
        print(f"\n[WARN] {sym}: {e}")

print("\n--- Connection test complete ---")
print("Note: If market is closed (outside 9:15-15:30 IST), data values may be stale or unavailable.")

# Cleanup
try:
    td.disconnect()
    print("Disconnected.")
except:
    pass
