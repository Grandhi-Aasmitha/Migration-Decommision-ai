import importlib.util
import socket
from pathlib import Path

from fastapi.testclient import TestClient


def test_local_launcher_starts_empty_and_accepts_manual_uploads(tmp_path, monkeypatch):
    monkeypatch.setenv("MIGRATION_LOCAL_DEMO", "1")
    monkeypatch.setenv("MIGRATION_LOCAL_DATA_DIR", str(tmp_path))
    script = Path(__file__).resolve().parents[2] / "scripts/run_local.py"
    spec = importlib.util.spec_from_file_location("local_workspace_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # API CI verifies mounting without depending on the separate React build job.
    root = tmp_path / "workspace"
    (root / "frontend/dist").mkdir(parents=True)
    (root / "frontend/dist/index.html").write_text("<html>Upload workspace</html>")
    monkeypatch.setattr(module, "ROOT", root)
    with TestClient(module.create_workspace_app()) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/documents").json() == {"documents": []}
        assert client.get("/api/graph").json()["nodes"] == []
        assert client.get("/api/health").json()["demo"]


def test_launcher_chooses_a_free_port_when_preferred_port_is_busy():
    script = Path(__file__).resolve().parents[2] / "scripts/run_local.py"
    spec = importlib.util.spec_from_file_location("local_port_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        preferred = occupied.getsockname()[1]
        assert module.choose_port(preferred) != preferred
