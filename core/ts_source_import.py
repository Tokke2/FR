"""Ta emot TS-underlag utan att göra antaganden om filformatets innehåll."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import uuid
import zipfile

MAX_FILE = 25 * 1024 * 1024
MAX_UNCOMPRESSED = 150 * 1024 * 1024


def import_source(source: Path, archive: Path) -> dict:
    source, archive = Path(source), Path(archive)
    suffix = source.suffix.lower()
    if suffix not in {'.xlsx', '.xlsm', '.xls'}:
        raise ValueError('Välj en Excel-fil (.xlsx, .xlsm eller .xls).')
    with source.open('rb') as stream:
        content = stream.read(MAX_FILE + 1)
    if not content or len(content) > MAX_FILE:
        raise ValueError('Filen är tom eller större än 25 MB.')
    if suffix in {'.xlsx', '.xlsm'}:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as package:
                infos = package.infolist()
                if len(infos) > 10000 or sum(info.file_size for info in infos) > MAX_UNCOMPRESSED:
                    raise ValueError('Excel-filen är för stor för säker granskning.')
                if package.testzip() is not None:
                    raise ValueError('Excel-filens innehåll är skadat.')
            import openpyxl
            workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=False, keep_links=False)
            try:
                sheets = list(workbook.sheetnames)
            finally:
                workbook.close()
        except ImportError as exc:
            raise ValueError('openpyxl krävs för att läsa Excel-filen.') from exc
        except (zipfile.BadZipFile, OSError, KeyError) as exc:
            raise ValueError('Filen är inte en läsbar Excel-arbetsbok.') from exc
    else:
        try:
            import xlrd
            workbook = xlrd.open_workbook(file_contents=content, on_demand=True)
            try:
                sheets = workbook.sheet_names()
            finally:
                workbook.release_resources()
        except ImportError as exc:
            raise ValueError('xlrd krävs för att läsa äldre .xls-filer.') from exc
        except Exception as exc:
            raise ValueError('Filen är inte en läsbar Excel-arbetsbok.') from exc
    if not sheets or len(sheets) > 200:
        raise ValueError('Excel-filen saknar blad eller har fler än 200 blad.')
    if archive.is_symlink():
        raise ValueError('Katalogen för TS-underlag får inte vara en symbolisk länk.')
    archive.mkdir(parents=True, exist_ok=True)
    destination = archive / uuid.uuid4().hex
    destination.mkdir(mode=0o700)
    digest = hashlib.sha256(content).hexdigest()
    metadata = {'source_name': source.name, 'sha256': digest, 'size': len(content),
                'imported_at': datetime.now(timezone.utc).isoformat(), 'sheets': sheets,
                'status': 'ej_granskat', 'file': 'underlag' + suffix}
    try:
        for path, body in ((destination / metadata['file'], content),
                           (destination / 'information.json', (json.dumps(metadata, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))):
            with path.open('xb') as out:
                out.write(body); out.flush(); os.fsync(out.fileno())
            if path.read_bytes() != body:
                raise OSError('Den importerade kopian kunde inte verifieras.')
    except BaseException:
        shutil.rmtree(destination)
        raise
    return {**metadata, 'directory': str(destination)}
