from __future__ import annotations

import json
import os
import time
from pathlib import Path


def ensure_job_root(root):
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_path(root, analysis_id):
    return ensure_job_root(root) / analysis_id


def create_job_dir(root, analysis_id):
    path = job_path(root, analysis_id)
    path.mkdir(mode=0o700, parents=True, exist_ok=False)
    return path


def save_job(root, job):
    path = job_path(root, job["analysis_id"])
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload_path = path / "job.json"
    payload_path.write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")


def load_job(root, analysis_id):
    payload_path = job_path(root, analysis_id) / "job.json"
    if not payload_path.exists():
        raise FileNotFoundError("Analysis job was not found.")
    return json.loads(payload_path.read_text(encoding="utf-8"))


def save_target_image(root, analysis_id, image_bytes):
    image_path = target_image_path(root, analysis_id)
    image_path.write_bytes(image_bytes)


def target_image_path(root, analysis_id):
    return job_path(root, analysis_id) / "target.png"


def cleanup_old_jobs(root, ttl_seconds):
    root_path = ensure_job_root(root)
    cutoff = time.time() - int(ttl_seconds)
    for child in root_path.iterdir():
        if not child.is_dir():
            continue
        try:
            if child.stat().st_mtime >= cutoff:
                continue
            _remove_tree(child)
        except OSError:
            continue


def _remove_tree(path):
    for current_root, dirs, files in os.walk(path, topdown=False):
        for filename in files:
            Path(current_root, filename).unlink(missing_ok=True)
        for dirname in dirs:
            Path(current_root, dirname).rmdir()
    path.rmdir()
