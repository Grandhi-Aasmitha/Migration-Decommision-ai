"""Run the built React UI and API together, without loading any documents."""
import argparse
import os
import socket
import sys
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
from app.config import Settings
from app.main import create_app


def choose_port(preferred):
    """Use localhost only; let Windows choose a free port if the preferred one is unavailable."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        try:
            candidate.bind(("127.0.0.1", preferred))
            return candidate.getsockname()[1]
        except OSError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind(("127.0.0.1", 0))
        return candidate.getsockname()[1]


def create_workspace_app():
    settings = Settings(_env_file=ROOT / ".env")
    settings.data_dir = Path(os.getenv("MIGRATION_LOCAL_DATA_DIR", str(ROOT / "data/user-uploads")))
    if os.getenv("MIGRATION_LOCAL_DEMO") == "1":
        settings.graph_backend, settings.model_provider = "memory", "demo"
    api = create_app(settings)
    distribution = ROOT / "frontend/dist"
    if not (distribution / "index.html").is_file():
        raise RuntimeError("Build the frontend first: cd frontend && npm ci && npm run build")

    @asynccontextmanager
    async def lifespan(app):
        async with api.router.lifespan_context(api):
            print("Workspace ready. Upload your documents to build the graph.", flush=True)
            yield

    app = FastAPI(lifespan=lifespan)
    app.mount("/api", api)
    app.mount("/", StaticFiles(directory=distribution, html=True), name="workspace")
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Use the local in-memory graph and extractive provider")
    parser.add_argument("--reload", action="store_true", help="Restart automatically after Python source changes")
    parser.add_argument("--open-browser", action="store_true")
    parser.add_argument("--port", type=int, default=5173)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/user-uploads")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    port = choose_port(args.port)
    if port != args.port:
        print(f"Port {args.port} is unavailable; using local port {port}.", flush=True)
    os.environ["MIGRATION_LOCAL_DEMO"] = "1" if args.demo else "0"
    os.environ["MIGRATION_LOCAL_DATA_DIR"] = str(args.data_dir.resolve())
    if args.open_browser:
        timer = threading.Timer(2.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}/"))
        timer.daemon = True
        timer.start()
    uvicorn.run("run_local:create_workspace_app", host="127.0.0.1", port=port, factory=True,
                reload=args.reload, reload_dirs=[str(ROOT / "backend/app"), str(ROOT / "scripts")] if args.reload else None)


if __name__ == "__main__":
    main()
