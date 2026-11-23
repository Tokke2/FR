"""Kontroll av appens externa paket, utan krav på requirements.txt."""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from typing import NamedTuple

from core.no_console import hidden_kwargs


class Dependency(NamedTuple):
    package: str
    module: str


# Paketnamn skiljer sig ibland från importnamn. Listan är uttrycklig för att
# aldrig installera godtyckliga namn som kommer från loggar eller nätverk.
DEPENDENCIES = (
    Dependency("PySide6", "PySide6.QtWidgets"),
    Dependency("pandas", "pandas"),
    Dependency("openpyxl", "openpyxl"),
    Dependency("xlrd", "xlrd"),
)


def missing_packages() -> list[str]:
    """Snabb kontroll utan att importera Qt i appens process."""
    missing = []
    for dep in DEPENDENCIES:
        try:
            if importlib.util.find_spec(dep.module.split('.')[0]) is None:
                missing.append(dep.package)
        except (ValueError, ImportError, AttributeError):
            missing.append(dep.package)
    return missing


def probe() -> dict:
    """Prova riktiga importer i en separat process, även inbyggda bibliotek."""
    script = r'''
import importlib, importlib.util, json
items = json.loads(__import__('sys').argv[1])
missing, broken = [], {}
for package, module in items:
    try:
        if importlib.util.find_spec(module.split('.')[0]) is None:
            missing.append(package)
            continue
        importlib.import_module(module)
    except Exception as exc:
        broken[package] = type(exc).__name__ + ': ' + str(exc)
print(json.dumps({'missing': missing, 'broken': broken}))
'''
    # Utan dessa flaggor öppnas ett konsolfönster varje gång miljön undersöks.
    result = subprocess.run(
        [sys.executable, "-c", script, json.dumps(DEPENDENCIES)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
        **hidden_kwargs(),
    )
    if result.returncode:
        raise RuntimeError("Kunde inte undersöka Pythonmiljön: " + result.stderr[-2000:])
    return json.loads(result.stdout.strip().splitlines()[-1])


def outdated_packages(*, skip: tuple[str, ...] = ()) -> list[dict[str, str]]:
    """Kontrollera källan separat för varje apptillägg, utan installation.

    `pip list --outdated` kan returnera [] och status 0 vid nätverksfel. Därför
    använder vi `pip index versions`, som misslyckas när paketkällan inte nås,
    och vägrar behandla ofullständig/otolkbar information som aktuell status.
    """
    try:
        from pip._vendor.packaging.version import Version, InvalidVersion
    except ImportError as exc:
        raise RuntimeError("pip saknas eller kan inte jämföra paketversioner") from exc
    allowed = {dep.package for dep in DEPENDENCIES}
    if not set(skip).issubset(allowed):
        raise ValueError("Okänt paket i undantagslistan")
    found = []
    for item in DEPENDENCIES:
        if item.package in skip:
            continue
        command = [sys.executable, "-m", "pip", "index", "versions", item.package,
                   "--disable-pip-version-check", "--no-input", "--timeout", "5", "--retries", "1"]
        try:
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", timeout=45, **hidden_kwargs())
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"Kunde inte kontrollera uppdateringar för {item.package}") from exc
        if result.returncode:
            # pip-utskrift kan innehålla privata paketkällor och ska inte loggas.
            raise RuntimeError(f"pip kunde inte kontrollera {item.package} (status {result.returncode})")
        installed = re.search(r"^\s*INSTALLED:\s*(\S+)\s*$", result.stdout, re.MULTILINE)
        latest = re.search(r"^\s*LATEST:\s*(\S+)\s*$", result.stdout, re.MULTILINE)
        if not installed or not latest or len(installed.group(1)) > 100 or len(latest.group(1)) > 100:
            raise RuntimeError(f"Kunde inte tolka pips versionssvar för {item.package}")
        try:
            current_version, latest_version = Version(installed.group(1)), Version(latest.group(1))
        except InvalidVersion as exc:
            raise RuntimeError(f"Kunde inte tolka paketversionen för {item.package}") from exc
        if latest_version > current_version:
            found.append({"name": item.package, "version": installed.group(1), "latest_version": latest.group(1)})
    return found


def pip_command(packages: list[str], *, upgrade: bool = False) -> list[str]:
    allowed = {dep.package for dep in DEPENDENCIES}
    if not packages or not set(packages).issubset(allowed):
        raise ValueError("Okända eller inga paket valda")
    return [sys.executable, "-m", "pip", "install", "--no-input", *(["--upgrade"] if upgrade else []), *packages]
