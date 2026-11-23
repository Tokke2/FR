"""Läs konservativt avgränsade tabeller utan att ändra originalfilen.

PDF-stödet avser textbaserade tabeller med tydligt separerade kolumner. Osäkra eller ojämna rader avvisas; OCR och fri dokumenttolkning ingår inte.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
import io
from itertools import chain
from pathlib import Path
import re
from typing import Iterable

MAX_BYTES = 50 * 1024 * 1024
MAX_ROWS = 100_000
MAX_COLUMNS = 500
DELIMITERS = {'Semikolon (;)': ';', 'Komma (,)': ',', 'Tabulator': '\t', 'Vertikalstreck (|)': '|'}
PDF_SPACING = '__pdf_spacing__'
PDF_DELIMITERS = {**DELIMITERS, 'Mellanrum mellan PDF-kolumner': PDF_SPACING}


class ImportFormatError(ValueError):
    pass


class PdfDependencyMissing(ImportFormatError):
    pass


@dataclass(frozen=True)
class Table:
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    sheet: str = ''


def _check_file(path: Path) -> None:
    if not path.is_file():
        raise ImportFormatError('Filen finns inte eller är inte en vanlig fil')
    if path.stat().st_size > MAX_BYTES:
        raise ImportFormatError('Filen är större än 50 MB; importen avbröts')


def _validate(headers: Iterable[object], rows: Iterable[Iterable[object]], sheet: str = '') -> Table:
    names = tuple('' if v is None else str(v).strip() for v in headers)
    if not 1 < len(names) <= MAX_COLUMNS or any(not name for name in names):
        raise ImportFormatError('Tabellen måste ha 2–500 namngivna kolumner')
    # Samma normalisering som befintlig mappningsdialog: förhindra kollisioner.
    from plugins.vehicle_registry.excel_importer import _normalize_column_name
    normalized = [_normalize_column_name(name) for name in names]
    if any(not n for n in normalized) or len(set(normalized)) != len(normalized):
        raise ImportFormatError('Rubriker saknas eller är tvetydiga efter normalisering')
    result = []
    for number, row in enumerate(rows, start=2):
        values = tuple('' if v is None else str(v) for v in row)
        if not any(v.strip() for v in values):
            continue
        if len(values) != len(names):
            raise ImportFormatError(f'Rad {number} har {len(values)} kolumner i stället för {len(names)}')
        if len(result) >= MAX_ROWS:
            raise ImportFormatError('Fler än 100 000 rader; importen avbröts')
        result.append(values)
    if not result:
        raise ImportFormatError('Tabellen saknar datarader')
    return Table(names, tuple(result), sheet)


def _read_delimited_text(text: str, delimiter: str, sheet: str = '') -> Table:
    if delimiter not in DELIMITERS.values():
        raise ImportFormatError('Välj en giltig kolumnseparator')
    try:
        reader = csv.reader(io.StringIO(text, newline=''), delimiter=delimiter, strict=True)
        header = next(reader, None)
        if header is None:
            raise ImportFormatError('Filen är tom')
        return _validate(header, reader, sheet)
    except csv.Error as exc:
        raise ImportFormatError(f'Felaktig tabell: {exc}') from exc


def read_csv(path: Path, delimiter: str) -> Table:
    path = Path(path); _check_file(path)
    try:
        text = path.read_text(encoding='utf-8-sig')
    except UnicodeError as exc:
        raise ImportFormatError('CSV-filen måste vara UTF-8. Exportera den som UTF-8 och försök igen.') from exc
    return _read_delimited_text(text, delimiter, path.name)


def read_pdf(path: Path, delimiter: str) -> Table:
    path = Path(path); _check_file(path)
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise PdfDependencyMissing('PDF-läsning kräver tillägget pypdf i den befintliga Pythonmiljön.') from exc
    try:
        pdf = PdfReader(path, strict=True)
        if pdf.is_encrypted:
            raise ImportFormatError('Lösenordsskyddad PDF stöds inte')
        if not 1 <= len(pdf.pages) <= 20:
            raise ImportFormatError('PDF-tabellen måste ha mellan 1 och 20 sidor')
        texts = []
        for page in pdf.pages:
            if delimiter == PDF_SPACING:
                part = page.extract_text(extraction_mode='layout', layout_mode_space_vertically=False) or ''
            else:
                part = page.extract_text() or ''
            if not part.strip():
                raise ImportFormatError('En PDF-sida saknar markerbar text. Skannade PDF:er kräver OCR och stöds inte här.')
            texts.append(part)
        text = '\n'.join(texts)
    except ImportFormatError:
        raise
    except Exception as exc:
        raise ImportFormatError(f'PDF-filen kunde inte läsas: {exc}') from exc
    if not text.strip():
        raise ImportFormatError('PDF-filen saknar markerbar text. Skannade PDF:er kräver OCR och stöds inte här.')
    if delimiter == PDF_SPACING:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        rows = [re.split(r'[ \t]{2,}', line) for line in lines]
        if not rows:
            raise ImportFormatError('PDF-filen saknar en läsbar tabell')
        table = _validate(rows[0], rows[1:], path.name)
    else:
        table = _read_delimited_text(text, delimiter, path.name)
    # En upprepad rubrik kan annars bli en falsk datapost på nästa sida.
    if any(tuple(value.strip() for value in row) == table.headers for row in table.rows):
        raise ImportFormatError('PDF-tabellen innehåller upprepade rubriker. Separera tabellen eller använd CSV.')
    return table


def excel_sheets(path: Path) -> list[str]:
    path = Path(path); _check_file(path)
    try:
        import pandas as pd
        with pd.ExcelFile(path) as xls:
            return list(xls.sheet_names)
    except Exception as exc:
        raise ImportFormatError(f'Excel-filen kunde inte öppnas: {exc}') from exc


def read_excel(path: Path, sheet: str) -> Table:
    path = Path(path); _check_file(path)
    try:
        import pandas as pd
        if path.suffix.lower() in ('.xlsx', '.xlsm'):
            # Excel kan visa ett numeriskt ID som 0012 trots att värdet är 12.
            # Omvandling till text skulle då ändra ID:t utan att det syns här.
            from openpyxl import load_workbook
            book = load_workbook(path, read_only=True, data_only=True)
            try:
                for row in book[sheet].iter_rows():
                    for cell in row:
                        if isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool):
                            fmt = str(cell.number_format or '').split(';', 1)[0].strip()
                            if re.fullmatch(r'0{2,}', fmt):
                                raise ImportFormatError(
                                    f'Blad {sheet}: numerisk cell {cell.coordinate} har inledande nollor i visningsformatet. '
                                    'Spara kolumnen som text så att identiteten inte ändras.')
            finally:
                book.close()
        if path.suffix.lower() == '.xls':
            import xlrd
            book = xlrd.open_workbook(str(path), formatting_info=True)
            sheet_xls = book.sheet_by_name(sheet)
            for row in range(sheet_xls.nrows):
                for col in range(sheet_xls.ncols):
                    cell = sheet_xls.cell(row, col)
                    if cell.ctype == xlrd.XL_CELL_NUMBER:
                        xf = book.xf_list[cell.xf_index]
                        fmt = book.format_map[xf.format_key].format_str.split(';', 1)[0].strip()
                        if re.fullmatch(r'0{2,}', fmt):
                            raise ImportFormatError(
                                f'Blad {sheet}, rad {row + 1}, kolumn {col + 1}: '
                                'numeriskt värde har inledande nollor i visningsformatet. Spara kolumnen som text.')
        # Läs första raden som vanliga värden: pandas får inte tyst döpa om dubbletter.
        frame = pd.read_excel(path, sheet_name=sheet, header=None, dtype=str, keep_default_na=False)
        if frame.empty:
            raise ImportFormatError('Bladet är tomt')
        return _validate(frame.iloc[0].tolist(), (row for row in frame.iloc[1:].itertuples(index=False, name=None)), sheet)
    except ImportFormatError:
        raise
    except Exception as exc:
        raise ImportFormatError(f'Excel-bladet kunde inte läsas: {exc}') from exc


def to_temporary_xlsx(table: Table, destination: Path) -> None:
    """Mellanfil för den befintliga fordonsimportören; alla värden skrivs som text."""
    from openpyxl import Workbook
    wb = Workbook()
    sheet = wb.active
    sheet.title = 'Import'
    for row in chain((table.headers,), table.rows):
        sheet.append(list(row))
        for cell in sheet[sheet.max_row]:
            cell.data_type = 's'  # även värden som börjar med = är text, inte formler
    try:
        wb.save(destination)
    finally:
        wb.close()
