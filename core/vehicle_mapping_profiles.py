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
        self._save(data)

    def _save(self, data: dict) -> None:
        """Skriv hela filen atomiskt; en avbruten skrivning lämnar inget halvt."""
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

    def _profile_key(self, name: str) -> str:
        """Hitta profilens namn utan hänsyn till versaler."""
        if not isinstance(name, str) or not name.strip():
            raise ProfileError("Ange profilens namn")
        wanted = name.strip().casefold()
        for key in self._load()["profiles"]:
            if key.casefold() == wanted:
                return key
        raise ProfileError(f"Profilen '{name.strip()}' finns inte")

    def delete(self, name: str) -> None:
        """Ta bort en profil. Filen skrivs om atomiskt."""
        data = self._load()
        key = self._profile_key(name)
        del data["profiles"][key]
        self._save(data)

    def rename(self, name: str, new_name: str) -> str:
        """Byt namn på en profil och behåll mappningen. Returnerar det nya namnet."""
        new_name = str(new_name or "").strip()
        if not new_name or len(new_name) > 80 or any(ord(c) < 32 for c in new_name):
            raise ProfileError("Profilnamnet måste innehålla 1–80 tecken utan radbrytningar")
        data = self._load()
        key = self._profile_key(name)
        if new_name.casefold() != key.casefold():
            taken = next((other for other in data["profiles"]
                          if other.casefold() == new_name.casefold()), None)
            if taken:
                raise FileExistsError(f"Profilen '{taken}' finns redan")
        mapping = data["profiles"].pop(key)
        data["profiles"][new_name] = mapping
        self._save(data)
        return new_name


def profile_rows(store: "ProfileStore") -> list[tuple[str, int]]:
    """Profilnamn och antal mappade kolumner, sorterade i namnordning.

    Ligger här (utan Qt) så att både profilfliken och testerna kan använda den.
    En trasig profilfil ger en tom lista i stället för ett krasch.
    """
    try:
        profiles = store.list_profiles()
    except ProfileError:
        return []
    return sorted(((name, len(mapping)) for name, mapping in profiles.items()),
                  key=lambda row: row[0].casefold())
