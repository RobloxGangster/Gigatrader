# dev/smoke.py
import os, json, time, requests, pathlib

BASE = os.environ.get("API_BASE_URL","http://127.0.0.1:8000").rstrip("/")

def call(method, path, **kw):
    u=f"{BASE}{path}"
    r=getattr(requests, method)(u, timeout=15, **kw)
    r.raise_for_status()
    return r.json()

def main():
    print("[*] GET /status"); print(json.dumps(call("get","/status"), indent=2))
    print("[*] POST /paper/start")
    print(json.dumps(call("post","/paper/start", params={"preset":"balanced"}), indent=2))
    time.sleep(1.0)
    print("[*] GET /positions"); print(json.dumps(call("get","/positions"), indent=2))
    print("[*] GET /orders"); print(json.dumps(call("get","/orders"), indent=2))
    try:
        print("[*] GET /sentiment?symbol=AAPL")
        print(json.dumps(call("get","/sentiment", params={"symbol":"AAPL"}), indent=2))
    except Exception as e:
        print("[i] sentiment endpoint not available or errored:", e)
    print("[*] POST /paper/flatten"); print(json.dumps(call("post","/paper/flatten"), indent=2))
    pathlib.Path(".kill_switch").write_text("")
    print("[OK] smoke complete. kill_switch written.")

if __name__ == "__main__":
    main()
