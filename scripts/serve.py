"""Portable service launcher:  python scripts/serve.py <module:app> <port>

On Windows, uvicorn defaults to the ProactorEventLoop, which psycopg (async Postgres driver) cannot use.
This launcher forces the SelectorEventLoop on Windows and otherwise behaves like `uvicorn <app> --port <port>`.
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "libs"), str(ROOT)]
os.chdir(ROOT)

import uvicorn  # noqa: E402


def main() -> None:
    app, port = sys.argv[1], int(sys.argv[2])
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    asyncio.run(server.serve())


if __name__ == "__main__":
    main()
