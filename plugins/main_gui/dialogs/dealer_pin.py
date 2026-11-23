"""PIN-dialog för ändringar av återförsäljare; koden lämnas aldrig i loggen."""
from PySide6.QtWidgets import QInputDialog, QLineEdit, QMessageBox
from core.dealer_pin import PinError


def _input(parent, title, label):
    value, ok = QInputDialog.getText(parent, title, label, QLineEdit.EchoMode.Password)
    return value if ok else None


def request_pin(parent, plugin, *, resource="återförsäljarregistret"):
    """Fråga vid varje ändring; skapa personlig PIN vid första användning."""
    try:
        manager = plugin.dealer_pin()
        if not manager.configured():
            answer = QMessageBox.question(parent, 'Skapa PIN-kod',
                f'Ingen gemensam PIN är skapad för återförsäljare och färger. Vill du skapa en nu? '
                'Den krävs vid ändringar och bör förvaras säkert. PIN skyddar ändringar i '
                'programmet, men krypterar inte filerna på datorn.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return None
            first = _input(parent, 'Skapa PIN-kod', 'Välj 6–12 siffror:')
            if first is None:
                return None
            second = _input(parent, 'Bekräfta PIN-kod', 'Ange samma PIN-kod igen:')
            if second is None:
                return None
            if first != second:
                raise PinError('PIN-koderna stämmer inte överens. Ingen PIN skapades.')
            manager.create(first)
            return first
        pin = _input(parent, 'PIN-kod krävs', f'Ange den gemensamma PIN-koden för att ändra {resource}:')
        if pin is None:
            return None
        if not manager.verify(pin):
            raise PinError('Felaktig PIN-kod. Inga ändringar gjordes.')
        return pin
    except (PinError, OSError) as exc:
        QMessageBox.warning(parent, 'PIN-skydd', str(exc))
        return None


def change_pin(parent, plugin):
    try:
        manager = plugin.dealer_pin()
        if not manager.configured():
            request_pin(parent, plugin, resource='inställningarna')
            return
        changed = manager.last_changed()
        QMessageBox.information(parent, 'Gemensam PIN-kod',
            f'Senaste PIN-byte: {changed.isoformat()}.\nVälj OK för att byta PIN eller avbryt vid nästa fråga.')
        old = _input(parent, 'Byt PIN-kod', 'Nuvarande PIN-kod:')
        if old is None:
            return
        if not manager.verify(old):
            raise PinError('Felaktig nuvarande PIN-kod.')
        new = _input(parent, 'Byt PIN-kod', 'Ny PIN-kod, 6–12 siffror:')
        if new is None:
            return
        confirm = _input(parent, 'Bekräfta PIN-kod', 'Ange den nya PIN-koden igen:')
        if confirm is None:
            return
        if new != confirm:
            raise PinError('PIN-koderna stämmer inte överens.')
        manager.change(old, new)
        QMessageBox.information(parent, 'PIN-skydd', 'PIN-koden har ändrats.')
    except (PinError, OSError) as exc:
        QMessageBox.warning(parent, 'PIN-skydd', str(exc))


def request_migrated_pin(parent, plugin, scope, identity_now, legacy_verify, label):
    """Begär gemensam kod och verifiera gammalt skydd vid första övergången."""
    from core.pin_transition import PinTransitions
    try:
        shared = request_pin(parent, plugin, resource=label)
        if shared is None:
            return None
        manager = plugin.dealer_pin()
        transitions = PinTransitions(manager)
        identity = identity_now()
        if transitions.migrated(scope, identity):
            return shared
        old = _input(parent, 'Säker PIN-övergång',
                     f'Ange den tidigare koden för {label}. Den krävs bara vid övergången:')
        if old is None:
            return None
        transitions.migrate(scope, identity, shared, old,
                            legacy_verify=legacy_verify, identity_now=identity_now)
        QMessageBox.information(parent, 'PIN-övergång',
                                f'{label} använder nu den gemensamma PIN-koden. Den tidigare filen har behållits.')
        return shared
    except (PinError, OSError, ValueError) as exc:
        QMessageBox.warning(parent, 'PIN-övergång', str(exc))
        return None
