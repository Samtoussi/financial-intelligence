
import json
import os
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunTracker:
    def __init__(self, pipeline: str, root: Path, arguments: dict | None = None):
        self.run_id = (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + "_"
            + uuid4().hex[:8]
        )
        self.run_dir = Path(root) / "data" / "runs" / pipeline / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self.manifest_path = self.run_dir / "run.json"

        self._started = time.perf_counter()
        self._stage_started = None
        self._active_stage = None

        self.manifest = {
            "run_id": self.run_id,
            "pipeline": pipeline,
            "arguments": arguments or {},
            "status": "running",
            "started_at": utc_now(),
            "finished_at": None,
            "duration_seconds": None,
            "stages": [],
        }
        self._save(self.manifest)

    def _save(self, manifest: dict) -> None:
        temporary = self.manifest_path.with_suffix(".json.tmp")
        try:
            temporary.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.manifest_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _commit(self, manifest: dict) -> None:
        self._save(manifest)
        self.manifest = manifest

    def _require_running(self) -> None:
        if self.manifest["status"] != "running":
            raise RuntimeError(
                f"Run is already {self.manifest['status']}"
            )

    def start_stage(self, name: str, company: str | None = None) -> None:
        self._require_running()

        if self._active_stage is not None:
            raise RuntimeError("A stage is already running")

        started = time.perf_counter()

        stage = {
            "name": name,
            "company": company,
            "status": "running",
            "started_at": utc_now(),
            "finished_at": None,
            "duration_seconds": None,
        }

        updated = deepcopy(self.manifest)
        updated["stages"].append(stage)
        self._commit(updated)

        self._active_stage = len(updated["stages"]) - 1
        self._stage_started = started

    def complete_stage(self, artifacts: dict | None = None) -> None:
        self._require_running()

        if self._active_stage is None:
            raise RuntimeError("No active stage to complete")

        updated = deepcopy(self.manifest)
        stage = updated["stages"][self._active_stage]

        stage["status"] = "success"
        stage["finished_at"] = utc_now()
        stage["duration_seconds"] = round(
            time.perf_counter() - self._stage_started, 3
        )

        if artifacts:
            stage["artifacts"] = artifacts

        self._commit(updated)
        self._active_stage = None
        self._stage_started = None

    def fail(self, error: Exception) -> None:
        self._require_running()

        updated = deepcopy(self.manifest)

        if self._active_stage is not None:
            stage = updated["stages"][self._active_stage]
            stage["status"] = "failed"
            stage["finished_at"] = utc_now()
            stage["duration_seconds"] = round(
                time.perf_counter() - self._stage_started, 3
            )
            stage["error_type"] = type(error).__name__

        updated["status"] = "failed"
        updated["error_type"] = type(error).__name__
        updated["finished_at"] = utc_now()
        updated["duration_seconds"] = round(
            time.perf_counter() - self._started, 3
        )

        self._commit(updated)
        self._active_stage = None
        self._stage_started = None

    def complete(self) -> None:
        self._require_running()

        if self._active_stage is not None:
            raise RuntimeError("Cannot complete a run with an active stage")

        updated = deepcopy(self.manifest)
        updated["status"] = "success"
        updated["finished_at"] = utc_now()
        updated["duration_seconds"] = round(
            time.perf_counter() - self._started, 3
        )

        self._commit(updated)
