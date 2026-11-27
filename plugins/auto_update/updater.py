"""GitHub-releaseuppdatering för källkodsinstallationer.

Jämför innehåll, inte versionsnummer. Enbart Pythonfiler i core/, plugins/
 ui/ och tools/, startfilerna samt namngivna programikoner uppdateras. Data, konfiguration
 och filer som inte finns i releasen lämnas orörda. Inga arkivfiler extraheras direkt till disk.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import stat
import struct
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

LOG = logging.getLogger(__name__)
API_URL = "https://api.github.com/repos/Tokke2/FR/releases/latest"
HOSTS = {"api.github.com", "github.com", "codeload.github.com"}
MAX_ARCHIVE = 80 * 1024 * 1024
MAX_FILE = 10 * 1024 * 1024
MAX_TOTAL = 160 * 1024 * 1024
MAX_ENTRIES = 10000
START_SCRIPTS = {"start_fordonsreg.sh", "start_fordonsreg.cmd", "start_fordonsreg.ps1"}
ICON_SIZES = {f"ikon_{size}.png": size for size in (16, 32, 64, 256)}
ICON_FILES = frozenset({*ICON_SIZES, "ikon.ico"})
SVG_FILES = frozenset({"assets/fordonsreg-logo.svg", "assets/fordonsreg-icon.svg"})
BRAND_DOC_FILES = frozenset({"assets/LOGOTYP.md"})
LICENSE_FILES = frozenset({"LICENSE"})
# Gränssnittets ikoner följer med i releasen; bara kända SVG-filer i mappen.
ICON_DIR = "assets/icons"
ICON_SUFFIX = ".svg"
MAX_ICON_FILE = 64 * 1024


class UpdateError(Exception):
    pass


def _validate_url(url: str) -> None:
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https" or p.hostname not in HOSTS or p.username or p.password or p.port not in (None, 443):
        raise UpdateError("Otillåten uppdateringsadress")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _get(url: str, maximum: int) -> bytes:
    _validate_url(url)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Fordonsreg-updater", "Accept": "application/vnd.github+json",
        # Taggen kan flyttas utan att versionsnumret ändras. Be mellanliggande
        # cachar om en ny kontroll i stället för att återanvända ett gammalt svar.
        "Cache-Control": "no-cache", "Pragma": "no-cache",
    })
    opener = urllib.request.build_opener(_SafeRedirect())
    with opener.open(req, timeout=15) as response:
        content = response.read(maximum + 1)
    if len(content) > maximum:
        raise UpdateError("Nedladdningen är för stor")
    return content


def _release_commit(tag: str) -> str:
    """Slå upp taggens faktiska commit, även för annoterade taggar."""
    if (not isinstance(tag, str) or not tag or tag.startswith("/") or tag.endswith(("/", "."))
            or ".." in tag or "@{" in tag or "//" in tag
            or any(ord(c) < 32 or c in " ~^:?*[\\" for c in tag)):
        raise UpdateError("Ogiltig release-tagg")
    url = "https://api.github.com/repos/Tokke2/FR/git/ref/tags/" + urllib.parse.quote(tag, safe="/")
    data = json.loads(_get(url, 1024 * 1024))
    for _ in range(8):
        obj = data.get("object", {}) if isinstance(data, dict) else {}
        kind, sha = obj.get("type"), obj.get("sha")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
            raise UpdateError("Release-taggen saknar giltig commit")
        if kind == "commit":
            return sha.lower()
        if kind != "tag":
            raise UpdateError("Release-taggen pekar inte på en commit")
        data = json.loads(_get("https://api.github.com/repos/Tokke2/FR/git/tags/" + sha, 1024 * 1024))
    raise UpdateError("För många nästlade release-taggar")


def latest_archive() -> bytes | None:
    """Hämta den publicerade releasens exakta commit; ingen versionsjämförelse."""
    try:
        data = _get(API_URL, 1024 * 1024)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    release = json.loads(data)
    if release.get("draft") or release.get("prerelease"):
        raise UpdateError("Releasen är inte en publicerad stabil release")
    commit = _release_commit(release.get("tag_name"))
    LOG.info("Kontrollerar release %s, commit %s", release.get("tag_name"), commit)
    # Arkiv via immutable commit, inte en tagg som kan ha flyttats eller cachats.
    url = "https://api.github.com/repos/Tokke2/FR/zipball/" + commit
    return _get(url, MAX_ARCHIVE)


def _validate_icon(name: str, content: bytes) -> None:
    """Avvisa uppenbart trasiga ikoner före backup och installation."""
    if name in ICON_SIZES:
        if len(content) < 33 or content[:8] != b"\x89PNG\r\n\x1a\n" or content[12:16] != b"IHDR":
            raise UpdateError(f"Ogiltig PNG-ikon: {name}")
        width, height = struct.unpack(">II", content[16:24])
        if (width, height) != (ICON_SIZES[name], ICON_SIZES[name]):
            raise UpdateError(f"Fel storlek på ikon: {name}")
    elif name == "ikon.ico":
        if len(content) < 22 or content[:4] != b"\x00\x00\x01\x00":
            raise UpdateError("Ogiltig ICO-ikon")
        count = int.from_bytes(content[4:6], "little")
        if not 1 <= count <= 32 or len(content) < 6 + count * 16:
            raise UpdateError("Ogiltig ICO-ikon")
        for index in range(count):
            size, offset = struct.unpack_from("<II", content, 6 + index * 16 + 8)
            if not size or offset < 6 + count * 16 or offset + size > len(content):
                raise UpdateError("Ogiltig ICO-ikon")



def _validate_brand_svg(name: str, content: bytes) -> None:
    """Endast statiska, lokala vektorbanor; inga skript, resurser eller rasterbilder."""
    # Kommentarer och grupplager är tillåtna (de behövs för en redigerbar
    # logotyp), men aldrig DTD:er eller entiteter – de kan läsa lokala filer.
    lowered = content.lower()
    if len(content) > 1024 * 1024 or b'<!doctype' in lowered or b'<!entity' in lowered:
        raise UpdateError(f"Ogiltig SVG: {name}")
    try:
        root = ET.fromstring(content)
        ns = '{http://www.w3.org/2000/svg}'
        if root.tag != ns + 'svg' or 'viewBox' not in root.attrib:
            raise ValueError('SVG-rot eller viewBox saknas')
        allowed = {
            'svg': {'width', 'height', 'viewBox', 'role', 'aria-labelledby'},
            'title': {'id'}, 'desc': {'id'},
            # Ett namngivet lager som tryckeriet kan färgsätta var för sig.
            'g': {'id', 'fill'},
            'path': {'id', 'fill', 'fill-rule', 'd'},
            'rect': {'x', 'y', 'width', 'height', 'rx', 'ry', 'fill'},
        }
        paths = 0
        elements = list(root.iter())
        if len(elements) > 1000:
            raise ValueError('För många element')
        for element in elements:
            if not element.tag.startswith(ns):
                raise ValueError('Ogiltig namnrymd')
            tag = element.tag[len(ns):]
            if tag not in allowed or not set(element.attrib).issubset(allowed[tag]):
                raise ValueError('Otillåtet SVG-element eller attribut')
            if tag == 'path':
                paths += 1
                if not re.fullmatch(r'[MmLlHhVvCcSsQqTtAaZz0-9.,+\-eE\s]+', element.attrib.get('d', '')):
                    raise ValueError('Ogiltig vektorbana')
            if 'fill' in element.attrib and not re.fullmatch(r'#[0-9a-fA-F]{6}|none', element.attrib['fill']):
                raise ValueError('Otillåten fyllning')
            for key, value in element.attrib.items():
                if key not in {'d', 'fill', 'fill-rule', 'role', 'id', 'aria-labelledby'} and not re.fullmatch(r'[0-9.,+\-eE\s]+(?:mm|px)?', value):
                    raise ValueError('Otillåtet SVG-värde')
        if not paths:
            raise ValueError('Vektorbanor saknas')
    except (ET.ParseError, UnicodeError, ValueError, AttributeError) as exc:
        raise UpdateError(f"Ogiltig SVG: {name}") from exc

THEME_ICON_TAGS = frozenset({"svg", "title", "desc", "path", "rect", "circle", "line",
                             "polyline", "polygon", "ellipse", "g"})


def _validate_theme_icon(name: str, content: bytes) -> None:
    """En temaikon är en enkel 24 × 24-SVG utan skript eller externa resurser.

    Kontrollen görs **före** några filer byts ut. Utan den skulle ikonerna
    hamna i Python-kontrollen och hela uppdateringen avvisas.
    """
    if len(content) > MAX_ICON_FILE or not content.lstrip().startswith(b"<"):
        raise UpdateError(f"Ogiltig ikon: {name}")
    lowered = content.lower()
    for forbidden in (b"<script", b"<!doctype", b"<!entity", b"javascript:", b"href=", b"url(",
                      b"<image", b"<foreignobject", b"data:"):
        if forbidden in lowered:
            raise UpdateError(f"Ogiltig ikon: {name}")
    try:
        root = ET.fromstring(content)
    except (ET.ParseError, UnicodeError, ValueError) as exc:
        raise UpdateError(f"Ogiltig ikon: {name}") from exc
    ns = "{http://www.w3.org/2000/svg}"
    if root.tag != ns + "svg" or root.get("viewBox") != "0 0 24 24":
        raise UpdateError(f"Ogiltig ikon: {name}")
    for element in root.iter():
        if not isinstance(element.tag, str) or not element.tag.startswith(ns):
            raise UpdateError(f"Ogiltig ikon: {name}")
        if element.tag[len(ns):].lower() not in THEME_ICON_TAGS:
            raise UpdateError(f"Ogiltig ikon: {name}")


def release_files(archive: bytes) -> dict[str, bytes]:
    """Läs endast tillåtna reguljära källfiler från GitHubs zipball."""
    if len(archive) > MAX_ARCHIVE:
        raise UpdateError("Arkivet är för stort")
    files: dict[str, bytes] = {}
    casefolded = set()
    total = 0
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        entries = z.infolist()
        if len(entries) > MAX_ENTRIES:
            raise UpdateError("För många filer i arkivet")
        roots = set()
        for entry in entries:
            name = entry.filename
            if "\\" in name or "\x00" in name or name.startswith("/"):
                raise UpdateError("Ogiltig sökväg i arkivet")
            parts = PurePosixPath(name).parts
            if not parts or any(p in (".", "..") or ":" in p for p in parts):
                raise UpdateError("Ogiltig sökväg i arkivet")
            roots.add(parts[0])
            if len(roots) != 1:
                raise UpdateError("Arkivet har flera rotmappar")
            if entry.is_dir() or len(parts) < 2:
                continue
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise UpdateError("Symbolisk länk i arkivet")
            rel = PurePosixPath(*parts[1:])
            allowed = (rel.as_posix() in ({"start.pyw", "main.pyw"} | ICON_FILES | SVG_FILES | BRAND_DOC_FILES | LICENSE_FILES | START_SCRIPTS)
                       or _is_theme_icon(rel.as_posix())
                       or (len(rel.parts) >= 2 and rel.parts[0] in {"core", "plugins", "ui", "tools"}
                           and rel.suffix == ".py" and "__pycache__" not in rel.parts))
            if not allowed or rel.as_posix().casefold() == "tools/install_latest_python.py":
                continue
            key = rel.as_posix()
            _validate_relative(key)
            if key.casefold() in casefolded:
                raise UpdateError("Dubblerad sökväg i arkivet")
            casefolded.add(key.casefold())
            if entry.file_size > (MAX_ICON_FILE if _is_theme_icon(rel.as_posix()) else MAX_FILE):
                raise UpdateError("En källfil är för stor")
            total += entry.file_size
            if total > MAX_TOTAL:
                raise UpdateError("Arkivet är för stort efter uppackning")
            content = z.read(entry)
            # Fånga upp ofullständiga releasefiler innan några filer byts ut.
            if key in ICON_FILES:
                _validate_icon(key, content)
            elif _is_theme_icon(key):
                _validate_theme_icon(key, content)
            elif key in SVG_FILES:
                _validate_brand_svg(key, content)
            elif key in BRAND_DOC_FILES | LICENSE_FILES:
                try:
                    if len(content) > 65536 or b"\0" in content:
                        raise ValueError("Ogiltigt innehåll")
                    content.decode("utf-8")
                except (UnicodeError, ValueError) as exc:
                    raise UpdateError(f"Ogiltig dokumentfil: {key}") from exc
            elif key in START_SCRIPTS:
                try:
                    text = content.decode("utf-8")
                    if "\0" in text:
                        raise ValueError("Nollbyte i startfil")
                except (UnicodeError, ValueError) as exc:
                    raise UpdateError(f"Ogiltig startfil: {key}") from exc
            else:
                try:
                    compile(content, key, "exec")
                except (SyntaxError, ValueError) as exc:
                    raise UpdateError(f"Ogiltig Pythonfil: {key}") from exc
            files[key] = content
    if not files:
        raise UpdateError("Releasen saknar uppdateringsbara programfiler")
    return files


def _is_theme_icon(relative: str) -> bool:
    """Endast enkla SVG-filer direkt i ikonmappen får uppdateras."""
    parts = PurePosixPath(relative).parts
    return (len(parts) == 3 and parts[0] == "assets" and parts[1] == "icons"
            and parts[2].endswith(ICON_SUFFIX) and parts[2].strip(ICON_SUFFIX))


def _validate_relative(relative: str) -> tuple[str, ...]:
    parts = PurePosixPath(relative).parts
    allowed = (relative in ({"start.pyw", "main.pyw"} | ICON_FILES | SVG_FILES | BRAND_DOC_FILES | LICENSE_FILES | START_SCRIPTS)
               or _is_theme_icon(relative)
               or (len(parts) >= 2 and parts[0] in {"core", "plugins", "ui", "tools"}
                   and relative.endswith(".py")))
    if (not allowed or relative.casefold() == "tools/install_latest_python.py" or relative.startswith("/")
            or any(p in (".", "..") or p.startswith(".") or p.endswith((".", " "))
                   or any(c in p for c in '\\:*?"<>|')
                   or any(ord(c) < 32 for c in p) for p in parts)):
        raise UpdateError("Otillåten målsökväg")
    return parts


def _target(root: Path, relative: str) -> Path:
    parts = _validate_relative(relative)
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise UpdateError(f"Symbolisk länk i målsökväg: {relative}")
    return current


def changed_files(root: Path, files: dict[str, bytes]) -> dict[str, bytes]:
    root = root.resolve()
    changed = {}
    for name, content in files.items():
        path = _target(root, name)
        if path.exists() and not path.is_file():
            raise UpdateError(f"Inte en vanlig fil: {name}")
        if not path.exists() or hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(content).digest():
            changed[name] = content
    return changed


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".update-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        if path.exists():
            os.chmod(temp, stat.S_IMODE(path.stat().st_mode))
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def install(root: Path, files: dict[str, bytes]) -> tuple[int, Path | None]:
    """Säkerhetskopiera och byt ut ändrade filer; återställ vid skrivfel.

    Körs av hjälpprocessen efter att appen avslutats. Lokala ändringar som
    gjorts efter nedladdningen säkerhetskopieras också innan de ersätts.
    """
    root = root.resolve()
    changes = changed_files(root, files)
    if not changes:
        return 0, None
    backup_root = root / ".update-backups"
    if backup_root.is_symlink():
        raise UpdateError("Backupkatalogen får inte vara en symbolisk länk")
    backup_root.mkdir(exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-"), dir=backup_root))
    originals: dict[str, bytes | None] = {}
    applied: list[str] = []
    try:
        # Alla säkerhetskopior måste vara färdiga innan första filen ändras.
        for name in changes:
            target = _target(root, name)
            old = target.read_bytes() if target.exists() else None
            originals[name] = old
            if old is not None:
                path = backup.joinpath(*PurePosixPath(name).parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, path)
        _atomic_write(backup / "manifest.json", json.dumps({"files": list(changes), "new_files": [n for n, v in originals.items() if v is None]}, ensure_ascii=False, indent=2).encode("utf-8"))
        for name, content in changes.items():
            _atomic_write(_target(root, name), content)
            applied.append(name)
    except Exception as exc:
        failures = []
        for name in reversed(applied):
            try:
                target = _target(root, name)
                old = originals[name]
                if old is None:
                    target.unlink(missing_ok=True)
                else:
                    _atomic_write(target, old)
            except Exception as rollback_exc:
                failures.append(f"{name}: {rollback_exc}")
        if failures:
            raise UpdateError(f"Uppdatering misslyckades; återställ manuellt från {backup}: {failures}") from exc
        raise
    return len(changes), backup
