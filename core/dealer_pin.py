"""Lokalt PIN-skydd för ändringar i återförsäljarregistret.

Skyddar programmets skrivvägar, inte filer mot någon som har filsystemåtkomst.
"""
from __future__ import annotations

import hashlib
import calendar
from datetime import date, datetime
import hmac
import json
import os
from pathlib import Path
import secrets
import tempfile

PIN_FILENAME = 'aterforsaljare_pin.json'
_ITERATIONS = 600_000


class PinError(ValueError):
    pass


class DealerPin:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self):
        if self.path.is_symlink():
            raise PinError('PIN-filen får inte vara en symbolisk länk')
        try:
            text = self.path.read_text(encoding='utf-8')
        except FileNotFoundError:
            return None
        except UnicodeError as exc:
            raise PinError('PIN-filen är oläsbar och har lämnats orörd') from exc
        try:
            data = json.loads(text)
            if not isinstance(data, dict) or data.get('version') != 1 or data.get('iterations') != _ITERATIONS:
                raise ValueError()
            identity = data.get('pin_id')
            if identity is not None and (not isinstance(identity, str) or len(bytes.fromhex(identity)) != 16):
                raise ValueError()
            salt, digest = bytes.fromhex(data['salt']), bytes.fromhex(data['hash'])
            if len(salt) != 16 or len(digest) != 32:
                raise ValueError()
            return salt, digest
        except (ValueError, TypeError, KeyError) as exc:
            raise PinError('PIN-filen är oläsbar eller ogiltig och har lämnats orörd') from exc

    def configured(self) -> bool:
        return self._load() is not None

    @staticmethod
    def _valid(pin):
        return isinstance(pin, str) and 6 <= len(pin) <= 12 and pin.isascii() and pin.isdigit()

    def verify(self, pin: str) -> bool:
        data = self._load()
        if not data or not self._valid(pin):
            return False
        salt, digest = data
        candidate = hashlib.pbkdf2_hmac('sha256', pin.encode('ascii'), salt, _ITERATIONS)
        return hmac.compare_digest(candidate, digest)

    def _contents(self, pin, pin_id=None):
        if not self._valid(pin):
            raise PinError('PIN-koden måste bestå av 6–12 siffror')
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac('sha256', pin.encode('ascii'), salt, _ITERATIONS)
        return (json.dumps({'version': 1, 'iterations': _ITERATIONS, 'salt': salt.hex(),
                            'hash': digest.hex(), 'pin_id': pin_id or secrets.token_hex(16), 'changed_on': date.today().isoformat()}, indent=2) + '\n').encode('utf-8')

    def create(self, pin):
        content = self._contents(pin)
        if self.path.is_symlink():
            raise PinError('PIN-filen får inte vara en symbolisk länk')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # O_EXCL skyddar befintlig eller samtidigt skapad PIN-fil.
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'wb') as out:
                out.write(content); out.flush(); os.fsync(out.fileno())
        except BaseException:
            # Lämna en ofullständig fil orörd: den får inte tyst återställas.
            raise

    def identity(self):
        if not self.configured():
            return None
        data = json.loads(self.path.read_text(encoding='utf-8'))
        return data.get('pin_id')

    def ensure_identity(self, pin):
        """Uppgradera äldre PIN-fil först efter att dess befintliga kod verifierats."""
        from core.color_storage import read_snapshot, decode_snapshot, save_snapshot
        if not self.verify(pin):
            raise PinError('Felaktig gemensam PIN-kod')
        original = read_snapshot(self.path)
        data = decode_snapshot(original, {})
        identity = data.get('pin_id')
        if identity:
            return identity
        data['pin_id'] = secrets.token_hex(16)
        if not self.verify(pin):
            raise PinError('PIN-filen ändrades under uppgraderingen')
        save_snapshot(self.path, original, data, other_path=self.path, other_expected=original,
                      backup_dir_name='backup_pin')
        return data['pin_id']

    def last_changed(self):
        if not self.configured():
            return None
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if 'changed_on' in data:
                return date.fromisoformat(data['changed_on'])
            return datetime.fromtimestamp(self.path.stat().st_mtime).date()
        except (ValueError, KeyError, UnicodeError) as exc:
            raise PinError('PIN-datumet är ogiltigt') from exc

    def reminder_due(self, today=None):
        """En kalendermånad efter byte, och högst en påminnelse per månad."""
        if not self.configured():
            return False
        today = today or date.today()
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            changed = date.fromisoformat(data['changed_on']) if 'changed_on' in data else datetime.fromtimestamp(self.path.stat().st_mtime).date()
            month = changed.month % 12 + 1
            year = changed.year + (changed.month == 12)
            due = date(year, month, min(changed.day, calendar.monthrange(year, month)[1]))
            reminder = self.path.with_name(self.path.name + '.reminder')
            if reminder.is_symlink():
                raise PinError('Påminnelsefilen får inte vara en symbolisk länk')
            last = reminder.read_text(encoding='ascii').strip() if reminder.exists() else ''
            return today >= due and last != today.strftime('%Y-%m')
        except (ValueError, KeyError, UnicodeError) as exc:
            raise PinError('PIN-datum eller påminnelse är ogiltig') from exc

    def mark_reminded(self, today=None):
        today = today or date.today()
        reminder = self.path.with_name(self.path.name + '.reminder')
        if reminder.is_symlink():
            raise PinError('Påminnelsefilen får inte vara en symbolisk länk')
        fd, name = tempfile.mkstemp(prefix='.pin-reminder-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='ascii') as out:
                out.write(today.strftime('%Y-%m') + '\n'); out.flush(); os.fsync(out.fileno())
            if reminder.is_symlink():
                raise PinError('Påminnelsefilen får inte vara en symbolisk länk')
            os.replace(name, reminder)
        finally:
            if os.path.exists(name): os.unlink(name)

    def change(self, old, new):
        if not self.verify(old):
            raise PinError('Felaktig nuvarande PIN-kod')
        if hmac.compare_digest(old, new):
            raise PinError('Välj en annan PIN-kod än den nuvarande')
        identity = self.identity()
        content = self._contents(new, identity)
        fd, name = tempfile.mkstemp(prefix='.dealer-pin-', suffix='.tmp', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'wb') as out:
                out.write(content); out.flush(); os.fsync(out.fileno())
            if self.path.is_symlink() or not self.verify(old):
                raise PinError('PIN-filen har ändrats; bytet avbröts')
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
