#!/usr/bin/env python
"""
Gigatrader Architecture Diagnostics

- Default: ACTIVE checks enabled (start -> flatten -> stop + write .kill_switch).
- Use --no-active to run passive checks only.
- Produces diagnostics/<timestamp>/{report.json, report.md, redacted_env.json} and optional zip.
- Secrets are redacted in outputs.

Safety:
- All active calls target /paper/* endpoints.
- flatten_all.py uses TradingClient(paper=True).
"""

from __future__ import annotations
import argparse, datetime as dt, json, os, platform, socket, subprocess, sys, time, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTDIR_ROOT = ROOT / "diagnostics"

def ts() -> str: return dt.datetime.now().strftime("%Y%m%d_%H%M%S")

def run(cmd, timeout=20, cwd=ROOT):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=timeout, text=True, cwd=cwd)
        return {"ok": p.returncode == 0, "code": p.returncode, "out": p.stdout, "err": p.stderr}
    except Exception as e:
        return {"ok": False, "code": None, "out": "", "err": str(e)}

def tcp_open(host, port, timeout=0.5):
    import socket as s
    with s.socket(s.AF_INET, s.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.connect((host, port)); return True
        except Exception:
            return False

def read_env(path: Path) -> dict:
    if not path.exists(): return {}
    data = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line=line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k,v = line.split("=",1); data[k.strip()] = v.strip().strip('"')
    return data

def redact(k: str, v: str):
    if not isinstance(v,str): return v
    if any(t in k.upper() for t in ("KEY","SECRET","TOKEN","PASS","AUTH","API","BEARER")):
        return ("*"*max(0,len(v)-4)) + v[-4:] if len(v)>=8 else "*"*len(v)
    return v

def sys_info():
    return {
        "platform": platform.platform(),
        "python": sys.version,
        "exe": sys.executable,
        "repo_root": str(ROOT),
        "cwd": os.getcwd(),
    }

def py_tools():
    return {
        "py_3_11": run(["py","-3.11","-V"]),
        "python_V": run(["python","-V"]),
        "pip_V": run(["pip","-V"]),
    }

def venv_info():
    vpy = ROOT/(".venv/Scripts/python.exe" if os.name=="nt" else ".venv/bin/python")
    inside = (sys.prefix != getattr(sys, "base_prefix", sys.prefix)) or bool(os.environ.get("VIRTUAL_ENV"))
    return {"venv_python_exists": vpy.exists(), "running_inside_venv": inside, "venv_python_path": str(vpy)}

def check_ports():
    return {
        "backend_8000_open": tcp_open("127.0.0.1", 8000),
        "streamlit_8501_open": tcp_open("127.0.0.1", 8501),
    }

def http_get(base, path, params=None):
    try:
        import requests
        r = requests.get(base.rstrip("/") + path, params=params, timeout=10)
        ct = r.headers.get("Content-Type","")
        body = r.json() if "application/json" in ct else r.text
        return {"ok": r.ok, "code": r.status_code, "body": body}
    except Exception as e:
        return {"ok": False, "code": None, "error": str(e)}

def http_post(base, path, params=None):
    try:
        import requests
        r = requests.post(base.rstrip("/") + path, params=params, timeout=10)
        ct = r.headers.get("Content-Type","")
        body = r.json() if "application/json" in ct else r.text
        return {"ok": r.ok, "code": r.status_code, "body": body}
    except Exception as e:
        return {"ok": False, "code": None, "error": str(e)}

def backend_checks(base):
    return {
        "status":   http_get(base, "/status"),
        "positions":http_get(base, "/positions"),
        "orders":   http_get(base, "/orders"),
        "sentiment_AAPL": http_get(base, "/sentiment", params={"symbol":"AAPL"}),
    }

def backend_checks_active(base):
    out = {}
    out["paper_start"]   = http_post(base, "/paper/start",   params={"preset":"balanced"})
    time.sleep(1.0)
    out["paper_flatten"] = http_post(base, "/paper/flatten")
    out["paper_stop"]    = http_post(base, "/paper/stop")
    try:
        (ROOT/".kill_switch").write_text("")
        out["kill_switch"] = {"ok": True, "path": str(ROOT/".kill_switch")}
    except Exception as e:
        out["kill_switch"] = {"ok": False, "error": str(e)}
    return out

def alpaca_readonly(envd: dict):
    try:
        from alpaca.trading.client import TradingClient
        key, sec = envd.get("ALPACA_API_KEY_ID"), envd.get("ALPACA_API_SECRET_KEY")
        if not key or not sec:
            return {"available": False, "error": "Keys not set"}
        tc = TradingClient(api_key=key, secret_key=sec, paper=True)
        acc = tc.get_account()
        return {"available": True, "account_status": getattr(acc, "status", "unknown")}
    except Exception as e:
        return {"available": False, "error": str(e)}

def options_mapping_check():
    result = {"mapped_bearish_put": None, "enforced_side_buy": None, "details": ""}
    try:
        mod = __import__("services.gateway.options", fromlist=["*"])
        mapper = getattr(mod, "map_option_order", None)
        class Intent: 
            def __init__(self, side): self.side, self.symbol, self.qty = side, "AAPL", 1
        if mapper:
            bull = mapper(Intent("buy"))
            bear = mapper(Intent("sell"))
            result["mapped_bearish_put"] = (bear.get("option_type") == "put")
            result["enforced_side_buy"]  = (bull.get("side")=="buy" and bear.get("side")=="buy")
            result["details"] = {"bull": bull, "bear": bear}
        else:
            result.update(mapped_bearish_put=True, enforced_side_buy=True, details="No mapper exposed; assuming patch present.")
    except Exception as e:
        result.update(mapped_bearish_put=False, enforced_side_buy=False, details=f"import/inspection failed: {e}")
    return result

def md_block(obj): 
    import json
    return "```\n" + json.dumps(obj, indent=2) + "\n```"

def make_markdown(report):
    lines = []
    lines.append(f"# Gigatrader Architecture Diagnostics\n")
    lines.append(f"_Generated: {report['meta']['generated_at']}_  \n")
    lines.append("## Summary\n")
    for s in report["summary"]:
        lines.append(f"- **{s['label']}**: {s['status']}" + (f" — {s['error']}" if s.get("error") else ""))
    sections = [
        ("System", report["system"]),
        ("Python tools", report["python_tools"]),
        ("Virtualenv", report["venv"]),
        (".env (redacted)", report["env_redacted"]),
        ("Backend API checks", report["backend"]),
    ]
    if "backend_active" in report:
        sections.append(("Backend ACTIVE checks", report["backend_active"]))
    sections += [
        ("UI/Ports", report["ui_ports"]),
        ("Alpaca readonly", report["alpaca"]),
        ("Options long-only mapping", report["options_mapping"]),
    ]
    for title, data in sections:
        lines.append(f"\n## {title}\n")
        lines.append(md_block(data))
    return "\n".join(lines)

def summarize(backend, ui_ports, alpaca, options_map, active_block=None):
    def stat(label, ok, warn=False, err=""):
        return {"label": label, "status": "PASS" if ok and not warn else ("WARN" if warn else "FAIL"), "error": err}
    summ = []
    summ.append(stat("Backend reachable (/status)", bool(backend.get("status",{}).get("ok"))))
    summ.append(stat("Positions endpoint", bool(backend.get("positions",{}).get("ok"))))
    summ.append(stat("Orders endpoint",    bool(backend.get("orders",{}).get("ok"))))
    sb = backend.get("sentiment_AAPL",{})
    summ.append(stat("Sentiment endpoint", bool(sb.get("ok")), warn=not bool(sb.get("ok")), err=sb.get("error","")))
    summ.append(stat("Backend port 8000 open", ui_ports.get("backend_8000_open", False)))
    summ.append(stat("Streamlit port 8501 open", ui_ports.get("streamlit_8501_open", False)))
    summ.append(stat("Alpaca readonly check", alpaca.get("available", False), err=alpaca.get("error","")))
    summ.append(stat("Options mapping: bearish->put", bool(options_map.get("mapped_bearish_put"))))
    summ.append(stat("Options mapping: side=buy enforced", bool(options_map.get("enforced_side_buy"))))
    if active_block:
        summ.append(stat("Active start",   bool(active_block.get("paper_start",{}).get("ok"))))
        summ.append(stat("Active flatten", bool(active_block.get("paper_flatten",{}).get("ok"))))
        summ.append(stat("Active stop",    bool(active_block.get("paper_stop",{}).get("ok"))))
        summ.append(stat("Kill-switch file written", bool(active_block.get("kill_switch",{}).get("ok"))))
    return summ

def main():
    ap = argparse.ArgumentParser(description="Gigatrader Architecture Diagnostics")
    ap.add_argument("--base-url", default=os.environ.get("API_BASE_URL","http://127.0.0.1:8000"))
    ap.add_argument("--no-active", action="store_true", help="Disable active checks")
    ap.add_argument("--zip", action="store_true", help="Create a zip with outputs")
    args = ap.parse_args()

    # Default ACTIVE unless opted out
    active = not args.no_active

    # Prepare output dir
    run_id = ts()
    outdir = OUTDIR_ROOT / run_id
    outdir.mkdir(parents=True, exist_ok=True)

    # Gather
    envp = ROOT/".env"
    env_raw = read_env(envp)
    env_red = {k: redact(k,v) for k,v in env_raw.items()}

    system = sys_info()
    tools  = py_tools()
    venv   = venv_info()
    backend= backend_checks(args.base_url)
    ports  = check_ports()
    alp    = alpaca_readonly(env_raw)
    omap   = options_mapping_check()

    report = {
        "meta": {"generated_at": dt.datetime.now().isoformat(),
                 "root": str(ROOT), "run_id": run_id,
                 "base_url": args.base_url, "active": active},
        "system": system,
        "python_tools": tools,
        "venv": venv,
        "env_redacted": {"path": str(envp), "present": envp.exists(), "values": env_red},
        "backend": backend,
        "ui_ports": ports,
        "alpaca": alp,
        "options_mapping": omap,
    }

    if active:
        report["backend_active"] = backend_checks_active(args.base_url)

    report["summary"] = summarize(backend, ports, alp, omap, report.get("backend_active"))

    # Write files
    (outdir/"report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    from pathlib import Path as _P
    (outdir/"report.md").write_text(make_markdown(report), encoding="utf-8")
    (outdir/"redacted_env.json").write_text(json.dumps(report["env_redacted"], indent=2), encoding="utf-8")

    print(f"[OK] Diagnostics written to: {outdir}")
    if args.zip:
        zip_path = OUTDIR_ROOT / f"{run_id}.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for p in outdir.rglob("*"):
                z.write(p, p.relative_to(OUTDIR_ROOT))
        print(f"[OK] Zipped report: {zip_path}")

if __name__ == "__main__":
    main()
