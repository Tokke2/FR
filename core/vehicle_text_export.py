"""Atomisk export av fordonsrader med ärlig förloppsrapportering."""
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import tempfile
from typing import Any, Callable, Iterable


def write_vehicle_text_file(path: Path, selected: list[tuple[int, dict[str, Any]]],
                            field_keys: Iterable[str],
                            progress: Callable[[int, int, str], None] | None = None) -> None:
    keys = list(field_keys)
    total = len(selected) + 1  # sista steget är flush/fsync + atomisk ersättning
    def report(current: int, message: str) -> None:
        if progress:
            progress(current, total, message)

    report(0, "Förbereder textfil...")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=f".{path.name}.tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("Fordonsexport;%s\n" % datetime.now().isoformat())
            handle.write(";".join(["year"] + keys) + "\n")
            for index, (year, vehicle) in enumerate(selected, 1):
                row = [str(year)]
                for key in keys:
                    value = str(vehicle.get(key, ""))
                    row.append(value.replace(";", ",").replace("\n", " ").replace("\r", ""))
                handle.write(";".join(row) + "\n")
                if index % 100 == 0 or index == len(selected):
                    report(index, f"Skriver fordon: {index} av {len(selected)}")
            report(len(selected), "Slutför och sparar filen...")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    report(total, "Filen är sparad.")
