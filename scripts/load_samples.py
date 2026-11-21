"""Load the fixed synthetic corpus into a running API; no external credentials required."""
import argparse
import json
import time
from pathlib import Path

import httpx

root = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8000")
    args = parser.parse_args()
    jobs = []
    with httpx.Client(base_url=args.api, timeout=60) as client:
        for item in json.loads((root / "samples/manifest.json").read_text()):
            with (root / "samples" / item["file"]).open("rb") as source:
                response = client.post("/documents", data={k: v for k, v in item.items() if k != "file"},
                                       files={"file": (item["file"], source, "text/plain")})
            response.raise_for_status()
            jobs.append(response.json()["job_id"])
        deadline = time.monotonic() + 1800
        while jobs and time.monotonic() < deadline:
            for job_id in list(jobs):
                response = client.get(f"/ingestion-jobs/{job_id}")
                response.raise_for_status()
                job = response.json()
                if job["status"] == "failed":
                    raise SystemExit(f"Ingestion failed: {job['error']}")
                if job["status"] == "ready":
                    print(f"Ready: {job['document_id'][:12]}")
                    jobs.remove(job_id)
            if jobs:
                time.sleep(2)
        if jobs:
            raise SystemExit("Ingestion timed out. Inspect the ingestion jobs and API logs.")
    print("All seven sample documents are ready.")


if __name__ == "__main__":
    main()
