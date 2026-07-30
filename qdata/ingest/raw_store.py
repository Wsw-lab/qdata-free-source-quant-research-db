from __future__ import annotations

from datetime import datetime
from pathlib import Path
from shutil import copy2


def store_raw_files(
    files_by_dataset: dict[str, str | Path],
    raw_root: str | Path = "raw",
    source_name: str = "local_csv",
    batch_id: str | None = None,
) -> list[str]:
    batch = batch_id or datetime.now().strftime("%Y%m%d%H%M%S")
    stored_paths = []
    for dataset_code, source_path in files_by_dataset.items():
        source = Path(source_path)
        target_dir = Path(raw_root) / "imports" / source_name / dataset_code / f"batch_id={batch}"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / source.name
        copy2(source, target)
        stored_paths.append(str(target))
    return stored_paths
