"""Namngivna mappningsprofiler för Fordonsdatas Excel-import.

Separat från befintliga fingerprint- och PIN-mappningar. Filen är användardata
som aldrig ingår i den automatiska programuppdateringen.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Callable


class ProfileError(ValueError):
    pass


def unmapped_headers(headers: list[str], mapping: dict[str, str],
                     normalize: Callable[[str], str]) -> list[str]:
    """Rubriker som faktiskt inte kommer med, i samma ordning som dialogen."""
    return [header for header in headers if not mapping.get(normalize(header))]


class ProfileStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> dict:
        if self.path.is_symlink():
            raise ProfileError("Profilfilen får inte vara en symbolisk länk")
        if not self.path.exists():
            return {"version": 1, "profiles": {}}
        try:
            with self.path.open(encoding="utf-8") as stream:
                data = json.load(stream)
        except (OSError, UnicodeError, ValueError) as exc:
            raise ProfileError("Profilfilen kunde inte läsas; den har lämnats orörd") from exc
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("profiles"), dict):
            raise ProfileError("Profilfilen har ett okänt format och har lämnats orörd")
        for name, mapping in data["profiles"].items():
            if not isinstance(name, str) or not isinstance(mapping, dict) or any(
                not isinstance(k, str) or not isinstance(v, str) for k, v in mapping.items()
            ):
                raise ProfileError("Profilfilen är ogiltig och har lämnats orörd")
        return data

    def list_profiles(self) -> dict[str, dict[str, str]]:
        return {name: dict(mapping) for name, mapping in self._load()["profiles"].items()}

    def save(self, name: str, mapping: dict[str, str], *, overwrite: bool = False) -> None:
        name = name.strip()
        if not name or len(name) > 80 or any(ord(c) < 32 for c in name):
            raise ProfileError("Profilnamnet måste innehålla 1–80 tecken utan radbrytningar")
        if not mapping or any(not isinstance(k, str) or not k or not isinstance(v, str) or not v for k, v in mapping.items()):
            raise ProfileError("Mappa minst en kolumn innan profilen sparas")
        data = self._load()
        profiles = data["profiles"]
        existing = next((key for key in profiles if key.casefold() == name.casefold()), None)
        if existing and not overwrite:
            raise FileExistsError(f"Profilen '{existing}' finns redan")
        if existing:
            name = existing  # bevara namnet som användaren redan valt
        profiles[name] = dict(mapping)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".vehicle-profiles-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            if self.path.is_symlink():
                raise ProfileError("Profilfilen får inte vara en symbolisk länk")
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
