# Running on Windows: 3 double-clicks, no Docker, no database install

**You need:** Python **3.12** (3.11–3.14 also work) from https://www.python.org/downloads/. Tick **"Add python.exe to PATH"** in the installer.

| step | what to do | time |
|---|---|---|
| 1 | Double-click **`setup_windows.bat`** (once). It creates `.venv`, installs packages, downloads the AI models and portable Qdrant + Redis into `tools\`, and writes `.env` | 10–20 min (one time) |
| 2 | Double-click **`start_windows.bat`**. It starts everything and opens **http://localhost:8501**. The first run also loads and indexes the 5,000 products | 3–5 min first time, ~1 min after |
| 3 | Double-click **`stop_windows.bat`** when finished | seconds |

The same commands work from the VS Code terminal:
```bat
cd D:\mosaic-fashion\mosaic-fashion
setup_windows.bat
start_windows.bat
stop_windows.bat
```

### How it works without Docker
* **Catalogue database:** SQLite (`data\catalogue.db`, set by `CATALOGUE_DB=sqlite` in `.env`), with the same transactional-outbox guarantees as PostgreSQL. Nothing to install.
* **Qdrant:** the official portable `qdrant.exe`, downloaded to `tools\qdrant\`. Its data is kept in `data\qdrant_storage\`.
* **Redis:** the portable Redis-for-Windows build, downloaded to `tools\redis\`.
* All services run in the background without console windows. Their logs are in `logs\*.log`.
* Status check: `.venv\Scripts\python scripts\launcher.py status`.

### Troubleshooting
| problem | fix |
|---|---|
| "Python not found" | Install Python 3.12 with "Add to PATH" ticked, close and reopen the terminal |
| A service shows `[!!]` | Open `logs\<service>.log`. Usually a port is busy (8000–8006, 8501, 6333, 6379): close the other program or reboot |
| Windows Firewall prompt | Click **Allow**. The services only listen on `localhost` |
| Want PostgreSQL instead of SQLite | Set `CATALOGUE_DB=postgres` and `POSTGRES_DSN=...` in `.env` |

### Tests and evaluation (while running)
```bat
.venv\Scripts\activate
set PYTHONPATH=libs;.
python -m pytest -q
python -m evaluation.run_offline_eval
```
The offline evaluation sends about 1,300 requests quickly. Set `RATE_LIMIT_RPS=0` in `.env`, then run stop and start again before running it.
