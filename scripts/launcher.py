"""One-command launcher for laptops (Windows / macOS / Linux) - no Docker, no database install.

    python scripts/launcher.py setup   # once: models + portable Qdrant & Redis + .env (SQLite catalogue)
    python scripts/launcher.py start   # start everything, load the catalogue on first run, open the UI
    python scripts/launcher.py stop    # stop everything
    python scripts/launcher.py status

Windows users run setup_windows.bat / start_windows.bat / stop_windows.bat, which call this file.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import webbrowser
import zipfile
from pathlib import Path

# Corporate networks / antivirus often inspect HTTPS with their own root certificate, which Python's
# bundled CA list does not know (CERTIFICATE_VERIFY_FAILED). truststore makes Python use the
# operating-system certificate store instead, where that root certificate is installed.
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
LOGS = ROOT / "logs"
PIDS = LOGS / "pids.json"
IS_WIN = sys.platform == "win32"
EXE = ".exe" if IS_WIN else ""

QDRANT_WIN = "https://github.com/qdrant/qdrant/releases/download/v1.19.0/qdrant-x86_64-pc-windows-msvc.zip"
QDRANT_LINUX = "https://github.com/qdrant/qdrant/releases/download/v1.19.0/qdrant-x86_64-unknown-linux-gnu.tar.gz"
REDIS_WIN = "https://github.com/tporadowski/redis/releases/download/v5.0.14.1/Redis-x64-5.0.14.1.zip"

SERVICES = [  # name, module, port  (start order matters: catalogue before retrieval)
    ("catalogue", "services.catalogue.app:app", 8005),
    ("embedding", "services.embedding.app:app", 8002),
    ("intent", "services.intent.app:app", 8001),
    ("ranking", "services.ranking.app:app", 8004),
    ("retrieval", "services.retrieval.app:app", 8003),
    ("indexer", "services.indexer.worker:app", 8006),
    ("gateway", "services.gateway.app:app", 8000),
]


def say(msg: str) -> None:
    print(msg, flush=True)


def http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def port_open(port: int) -> bool:
    import socket
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait(pred, what: str, timeout: float = 300) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            say(f"  [ok] {what}")
            return True
        time.sleep(1)
    say(f"  [!!] {what} did not become ready in {timeout:.0f}s - see logs/")
    return False


def download(url: str, dest: Path) -> None:
    if dest.exists():
        return
    say(f"  downloading {url.rsplit('/', 1)[-1]} ...")
    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(dest)


# ------------------------------------------------------------------ setup
def setup() -> None:
    say("[1/3] models")
    subprocess.check_call([sys.executable, str(ROOT / "scripts" / "download_models.py")])
    say("[2/3] portable Qdrant + Redis")
    TOOLS.mkdir(exist_ok=True)
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    qdir, rdir = TOOLS / "qdrant", TOOLS / "redis"
    if not (qdir / f"qdrant{EXE}").exists():
        qdir.mkdir(parents=True, exist_ok=True)
        if IS_WIN:
            download(QDRANT_WIN, cache / "qdrant.zip")
            zipfile.ZipFile(cache / "qdrant.zip").extractall(qdir)
        elif platform.system() == "Linux":
            import tarfile
            download(QDRANT_LINUX, cache / "qdrant.tgz")
            tarfile.open(cache / "qdrant.tgz").extractall(qdir, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
        else:
            say("  macOS: install Qdrant with `brew install qdrant` (or Docker); skipping download")
    say("  [ok] qdrant")
    if IS_WIN and not (rdir / "redis-server.exe").exists():
        rdir.mkdir(parents=True, exist_ok=True)
        download(REDIS_WIN, cache / "redis.zip")
        zipfile.ZipFile(cache / "redis.zip").extractall(rdir)
    if not IS_WIN and not shutil.which("redis-server"):
        say("  ! redis-server not found: install it (apt install redis-server / brew install redis)")
    say("  [ok] redis")
    say("[3/3] configuration")
    env = ROOT / ".env"
    if not env.exists():
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        if "CATALOGUE_DB=postgres" in text:
            text = text.replace("CATALOGUE_DB=postgres", "CATALOGUE_DB=sqlite   # laptop mode (set by launcher setup)")
        else:
            text += "\nCATALOGUE_DB=sqlite\n"
        env.write_text(text, encoding="utf-8")
        say("  [ok] .env created (CATALOGUE_DB=sqlite - no PostgreSQL needed)")
    else:
        say("  [ok] .env already exists (left unchanged)")
    say("\nSetup complete. Next: start_windows.bat  (or: python scripts/launcher.py start)")


# ------------------------------------------------------------------ start / stop
def _spawn(name: str, cmd: list[str], env: dict | None = None, cwd: Path | None = None) -> int:
    LOGS.mkdir(exist_ok=True)
    log = open(LOGS / f"{name}.log", "ab")
    kw = {}
    if IS_WIN:
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env, cwd=cwd or ROOT, **kw)
    pids = json.loads(PIDS.read_text()) if PIDS.exists() else {}
    pids[name] = p.pid
    PIDS.write_text(json.dumps(pids, indent=1))
    return p.pid


def _bin(name: str, env_var: str) -> str | None:
    if os.environ.get(env_var):
        return os.environ[env_var]
    local = next((p for p in (TOOLS / name).rglob(f"{'redis-server' if name == 'redis' else 'qdrant'}{EXE}")), None) \
        if (TOOLS / name).exists() else None
    if local:
        return str(local)
    return shutil.which("redis-server" if name == "redis" else "qdrant")


SERVICE_PORTS = [p for _n, _m, p in SERVICES] + [8501]


def _listening_pids(port: int) -> set[int]:
    pids: set[int] = set()
    try:
        if IS_WIN:
            out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[3] == "LISTENING" and parts[1].endswith(f":{port}"):
                    pids.add(int(parts[4]))
        else:
            out = subprocess.run(["ss", "-ltnpH", f"sport = :{port}"], capture_output=True, text=True).stdout
            import re
            pids.update(int(x) for x in re.findall(r"pid=(\d+)", out))
    except Exception:
        pass
    return {p for p in pids if p > 0}


def free_service_ports() -> None:
    """Stop leftovers from an earlier (possibly failed) run so the CURRENT code is what starts."""
    for port in SERVICE_PORTS:
        for pid in _listening_pids(port):
            try:
                if IS_WIN:
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
                else:
                    os.kill(pid, signal.SIGTERM)
                say(f"  stopped leftover process on port {port} (pid {pid})")
            except Exception:
                pass


def diagnose(name: str, port: int) -> None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/ready", timeout=3) as r:
            body = r.read().decode()
    except urllib.error.HTTPError as e:
        body = e.read().decode()
    except Exception as e:
        body = f"not reachable ({type(e).__name__})"
    say(f"\n--- {name} readiness: {body}")
    log = LOGS / f"{name}.log"
    if log.exists():
        lines = [l for l in log.read_text(encoding="utf-8", errors="replace").splitlines() if '"msg": "request"' not in l]
        say(f"--- last lines of logs/{name}.log:")
        for l in lines[-15:]:
            say("    " + l[:400])


def start() -> None:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "libs"), str(ROOT)])}
    stop(quiet=True)          # leftovers from a previous run (incl. failed ones) -> start fresh with current code
    free_service_ports()
    say("Starting infrastructure ...")
    if not port_open(6379):
        rb = _bin("redis", "REDIS_BIN")
        if not rb:
            sys.exit("redis-server not found - run setup first")
        _spawn("redis", [rb, "--port", "6379", "--save", ""])
    wait(lambda: port_open(6379), "redis :6379", 30)
    if not port_open(6333):
        qb = _bin("qdrant", "QDRANT_BIN")
        if not qb:
            sys.exit("qdrant not found - run setup first")
        storage = ROOT / "data" / "qdrant_storage"
        storage.mkdir(parents=True, exist_ok=True)
        _spawn("qdrant", [qb], env={**os.environ, "QDRANT__STORAGE__STORAGE_PATH": str(storage),
                                    "QDRANT__STORAGE__SNAPSHOTS_PATH": str(ROOT / "data" / "qdrant_snapshots"),
                                    "QDRANT__TELEMETRY_DISABLED": "true"}, cwd=Path(qb).parent)
    wait(lambda: http_ok("http://127.0.0.1:6333/healthz"), "qdrant :6333", 60)

    say("Starting MOSAIC services (first start loads the AI models, ~30-60 s) ...")
    for name, module, port in SERVICES:
        if not http_ok(f"http://127.0.0.1:{port}/health"):
            _spawn(name, [sys.executable, str(ROOT / "scripts" / "serve.py"), module, str(port)], env=env)
        if name == "catalogue" and not wait(lambda: http_ok("http://127.0.0.1:8005/ready"), "catalogue :8005", 120):
            diagnose("catalogue", 8005)
            sys.exit("\nCatalogue failed to start - please copy the lines above (readiness + log) and share them.")
    failed = [(name, port) for name, _m, port in SERVICES
              if not wait(lambda p=port: http_ok(f"http://127.0.0.1:{p}/ready"), f"{name} :{port}", 300)]
    # identity check: each port must run the service whose code it is supposed to run
    for name, _m, port in SERVICES:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as r:
                actual = json.loads(r.read()).get("service")
        except Exception:
            continue
        if actual and actual != name:
            say(f"\n[!!] Port {port} should run the '{name}' service but is running '{actual}'.")
            say(f"     The file services\\{name}\\app.py was probably overwritten with the {actual} service's app.py.")
            say(f"     Re-download the correct {name} app.py, then run stop_windows.bat and start_windows.bat.")
            failed.append((name, port))
    if failed:
        for name, port in failed:
            diagnose(name, port)
        sys.exit("\nSome services failed to start - please copy the lines above and share them.")

    with urllib.request.urlopen("http://127.0.0.1:8005/stats", timeout=10) as r:
        n = json.loads(r.read())["products"]
    if n == 0:
        say("First run: loading the 5,000-product catalogue and indexing it (~3-5 min) ...")
        subprocess.check_call([sys.executable, "-m", "ingestion.load_catalogue", "--file", str(ROOT / "data" / "catalogue.jsonl")],
                              env=env, cwd=ROOT)
    else:
        say(f"  [ok] catalogue already loaded ({n} products)")

    if not http_ok("http://127.0.0.1:8501/_stcore/health"):
        _spawn("ui", [sys.executable, "-m", "streamlit", "run", str(ROOT / "ui" / "streamlit_app.py"), "--server.port", "8501",
                      "--server.headless", "true", "--browser.gatherUsageStats", "false"], env=env)
    wait(lambda: http_ok("http://127.0.0.1:8501/_stcore/health"), "ui :8501", 120)
    say("\nMOSAIC-Fashion is running.\n  UI : http://localhost:8501\n  API: http://localhost:8000/docs\n"
        "Stop everything with stop_windows.bat (or: python scripts/launcher.py stop)")
    if os.environ.get("NO_BROWSER") != "1":
        webbrowser.open("http://localhost:8501")


def stop(quiet: bool = False) -> None:
    if not PIDS.exists():
        if not quiet:
            say("nothing to stop (no logs/pids.json)")
        return
    pids = json.loads(PIDS.read_text())
    for name, pid in reversed(list(pids.items())):
        try:
            if IS_WIN:
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
            else:
                os.killpg(pid, signal.SIGTERM)
            if not quiet:
                say(f"  stopped {name}")
        except Exception:
            pass
    PIDS.unlink()
    if quiet:
        time.sleep(1)


def status() -> None:
    for name, port, path in [("redis", 6379, None), ("qdrant", 6333, "/healthz")] + [(n, p, "/ready") for n, _m, p in SERVICES] + [("ui", 8501, "/_stcore/health")]:
        up = port_open(port) if path is None else http_ok(f"http://127.0.0.1:{port}{path}")
        say(f"  {'UP  ' if up else 'DOWN'} {name:10s} :{port}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    {"setup": setup, "start": start, "stop": stop, "status": status}[cmd]()