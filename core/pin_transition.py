"""Säker övergång per äldre skydd utan att ta bort dess ursprungliga data."""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import secrets

from core.color_storage import read_snapshot, decode_snapshot, save_snapshot
from core.dealer_pin import PinError


class PinTransitions:
    def __init__(self, shared_pin):
        self.pin = shared_pin
        self.path = Path(shared_pin.path).with_name('pin_overgangar.json')

    def _read(self):
        raw = read_snapshot(self.path)
        data = decode_snapshot(raw, {'version': 1, 'transitions': {}})
        if (not isinstance(data, dict) or data.get('version') != 1
                or not isinstance(data.get('transitions'), dict)):
            raise PinError('PIN-övergångarna har ogiltigt format och lämnas orörda')
        for key, entry in data['transitions'].items():
            if (not isinstance(key, str) or not isinstance(entry, dict)
                    or not isinstance(entry.get('salt'), str) or not isinstance(entry.get('identity'), str)):
                raise PinError('PIN-övergångarna har ogiltigt format och lämnas orörda')
            try:
                if len(bytes.fromhex(entry['salt'])) != 16 or len(bytes.fromhex(entry['identity'])) != 32:
                    raise ValueError()
            except ValueError as exc:
                raise PinError('PIN-övergångarna har ogiltiga värden och lämnas orörda') from exc
        return data, raw

    @staticmethod
    def _digest(identity: str, salt: bytes) -> str:
        if not isinstance(identity, str) or not identity:
            raise PinError('Det tidigare skyddet kan inte identifieras säkert')
        return hashlib.pbkdf2_hmac('sha256', identity.encode('utf-8'), salt, 600_000).hex()

    def migrated(self, scope: str, identity: str) -> bool:
        data, _ = self._read()
        entry = data['transitions'].get(scope)
        if not entry:
            return False
        pin_id = self.pin.identity()
        if not pin_id:
            return False
        digest = self._digest(pin_id + ':' + identity, bytes.fromhex(entry['salt']))
        return hmac.compare_digest(digest, entry['identity'])

    def migrate(self, scope: str, identity: str, shared: str, legacy: str,
                *, legacy_verify, identity_now) -> None:
        if not isinstance(scope, str) or not scope:
            raise PinError('Ogiltigt skydd')
        if not self.pin.verify(shared):
            raise PinError('Felaktig gemensam PIN-kod')
        pin_id = self.pin.ensure_identity(shared)
        data, original = self._read()
        pin_bytes = read_snapshot(self.pin.path)
        if not legacy_verify(legacy):
            raise PinError('Felaktig tidigare kod; övergången avbröts')
        if identity_now() != identity or not self.pin.verify(shared):
            raise PinError('Skyddet ändrades under övergången; försök igen')
        salt = secrets.token_bytes(16)
        data['transitions'][scope] = {'salt': salt.hex(), 'identity': self._digest(pin_id + ':' + identity, salt)}
        if identity_now() != identity:
            raise PinError('Det tidigare skyddet ändrades; övergången avbröts')
        save_snapshot(self.path, original, data, other_path=self.pin.path, other_expected=pin_bytes, backup_dir_name="backup_pin")


def sap_legacy_identity(auth) -> str:
    """Bind övergången till både aktiv auth-konfiguration och eventuell fil."""
    if not getattr(auth, '_initialized', False) or not isinstance(getattr(auth, '_password_config', None), dict):
        raise PinError('Det tidigare SAP-lösenordsskyddet är inte tillgängligt')
    path = getattr(auth, '_password_path', None)
    if path is None:
        raise PinError('Sökvägen till det tidigare SAP-skyddet saknas')
    raw = read_snapshot(Path(path))
    if raw is not None:
        try:
            on_disk = json.loads(raw.decode('utf-8'))
            if not isinstance(on_disk, dict):
                raise ValueError()
            if (on_disk.get('password_hash') or '') != (auth._password_config.get('password_hash') or ''):
                raise PinError('SAP-lösenordet har ändrats sedan det lästes; starta om och försök igen')
        except (ValueError, UnicodeError) as exc:
            raise PinError('Den tidigare SAP-lösenordsfilen är oläsbar och lämnas orörd') from exc
    active = json.dumps(auth._password_config, ensure_ascii=False, sort_keys=True)
    return active + ':' + hashlib.sha256(raw or b'').hexdigest()
