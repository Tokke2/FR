"""Donationsdialog under Hjälp-menyn: Swish-QR samt PayPal och Ko-fi som knappar.

Stödet finns bara i programmet – ingen egen webbsida. Swish visas enbart som
QR-kod enligt Swish standard för privatpersoner (beloppet väljs i Swish).
PayPal och Ko-fi visas enbart som knappar med fast, vitlistad adress och har
medvetet ingen QR-kod. Inga fält kan ändra mottagarna, inga belopp hanteras i
programmet och inga koder hämtas från nätet.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from core import theme as design
from core.donation import (
    BODY_TEXT, FOOTER_TEXT, INTRO_TEXT, INTRO_TITLE, KOFI_URL, LINK_HINT,
    NEVER_TEXT, PAYPAL_URL, QR_HINT, qr_matrix,
)

_log = logging.getLogger(__name__)

ALLOWED_URLS = frozenset({PAYPAL_URL, KOFI_URL})


def render_qr_pixmap(name: str, scale: int = 9, widget=None) -> QPixmap:
    """Skapa en knivskarp QR-kod i skärmens upplösning.

    Modulerna ritas i hela enheter av skalfaktorn och bilden får skärmens
    enhetspixelkvot, så att koden inte blir suddig på 125–200 % skalning.
    Ingen extern QR-tjänst och inget QR-bibliotek används.
    """
    matrix = qr_matrix(name)
    return design.qr_image(matrix, scale, design.device_pixel_ratio(widget))


class SwishQrDialog(QDialog):
    """Donationsruta med Swish-QR samt PayPal och Ko-fi som knappar utan QR."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Stöd Fordonsreg – donation')
        self.resize(600, 820)
        self.setMinimumSize(320, 420)
        self.setStyleSheet('''
            QDialog { background: #eef3f9; color: #132747; }
            QScrollArea { background: transparent; border: none; }
            QWidget#content { background: #eef3f9; }
            QFrame#hero { background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #071f40, stop:0.6 #12406b, stop:1 #0a7d90);
                border-radius: 16px; }
            QLabel#heroTitle { color: white; font-size: 24px; font-weight: bold; }
            QLabel#heroBody { color: #e2f2f8; font-size: 13px; }
            QLabel#badge { color: #8ef4fb; font-size: 11px; font-weight: bold; }
            QFrame#card { background: white; border: 1px solid #dbe5ef; border-radius: 14px; }
            QLabel#cardTitle { color: #132747; font-size: 16px; font-weight: bold; }
            QLabel#body { color: #42566b; font-size: 13px; }
            QLabel#muted { color: #5d7285; font-size: 12px; }
            QLabel#qr { background: white; border: 1px solid #dbe5ef; border-radius: 12px;
                padding: 10px; }
            QLabel#address { color: #33495e; font-size: 11px; }
            QFrame#noteBar { background: #eaf6ef; border: 1px solid #c9e8d5; border-radius: 12px; }
            QLabel#noteText { color: #1d5b3a; font-size: 12px; }
            QLabel#footer { color: #6b7f91; font-size: 11px; }
            QPushButton { border: 0; border-radius: 10px; padding: 10px 18px;
                font-size: 13px; font-weight: bold; }
            QPushButton#paypal { background: #0875ba; color: white; }
            QPushButton#paypal:hover { background: #06659f; }
            QPushButton#kofi { background: #e85f5c; color: white; }
            QPushButton#kofi:hover { background: #cf4d4a; }
            QPushButton#close { background: #dce8f1; color: #19334d; padding: 10px 22px; }
            QPushButton#close:hover { background: #cdddea; }
            QPushButton:focus { border: 2px solid #16b8cd; }
        ''')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName('content')
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(self._hero())
        layout.addWidget(self._swish_card())
        layout.addWidget(self._link_card())
        layout.addWidget(self._free_note())
        footer = QLabel(FOOTER_TEXT)
        footer.setObjectName('footer')
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setWordWrap(True)
        layout.addWidget(footer)
        layout.addStretch(1)

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton('Stäng')
        close.setObjectName('close')
        close.setDefault(True)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        outer.addLayout(buttons)

    # ── Byggstenar ────────────────────────────────────────────────────────────

    def _hero(self) -> QFrame:
        hero = QFrame()
        hero.setObjectName('hero')
        box = QVBoxLayout(hero)
        box.setContentsMargins(22, 20, 22, 20)
        box.setSpacing(8)
        badge = QLabel('FRIVILLIGT STÖD')
        badge.setObjectName('badge')
        title = QLabel(INTRO_TITLE)
        title.setObjectName('heroTitle')
        intro = QLabel(INTRO_TEXT)
        intro.setObjectName('heroBody')
        intro.setWordWrap(True)
        box.addWidget(badge)
        box.addWidget(title)
        box.addWidget(intro)
        return hero

    def _qr_label(self, name: str, description: str) -> QLabel:
        qr = QLabel()
        qr.setObjectName('qr')
        qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr.setAccessibleName(description)
        try:
            qr.setPixmap(render_qr_pixmap(name, widget=self))
        except Exception:
            _log.exception('Kunde inte visa QR-koden för %s', name)
            qr.setText('QR-koden kunde inte visas. Ingen betalning har startats.')
            qr.setWordWrap(True)
        return qr

    def _swish_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName('card')
        box = QVBoxLayout(card)
        box.setContentsMargins(20, 18, 20, 18)
        box.setSpacing(8)
        heading = QLabel('Swish · välj belopp själv')
        heading.setObjectName('cardTitle')
        body = QLabel(BODY_TEXT)
        body.setObjectName('body')
        body.setWordWrap(True)
        hint = QLabel(QR_HINT)
        hint.setObjectName('muted')
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(heading)
        box.addWidget(body)
        box.addWidget(self._qr_label('swish', 'Swish QR-kod för att stödja Fordonsreg'),
                     0, Qt.AlignmentFlag.AlignHCenter)
        box.addWidget(hint)
        return card

    def _link_card(self) -> QFrame:
        """PayPal och Ko-fi som knappar – medvetet utan QR-kod."""
        card = QFrame()
        card.setObjectName('card')
        box = QVBoxLayout(card)
        box.setContentsMargins(20, 18, 20, 18)
        box.setSpacing(8)
        heading = QLabel('PayPal och Ko-fi · knappar, ingen QR-kod')
        heading.setObjectName('cardTitle')
        hint = QLabel(LINK_HINT)
        hint.setObjectName('muted')
        hint.setWordWrap(True)
        box.addWidget(heading)
        box.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(12)
        for label, address, object_name, handler in (
            ('PayPal', PAYPAL_URL, 'paypal', self._open_paypal),
            ('Ko-fi', KOFI_URL, 'kofi', self._open_kofi),
        ):
            column = QVBoxLayout()
            column.setSpacing(6)
            button = QPushButton(f'Öppna {label}  ↗')
            button.setObjectName(object_name)
            button.setToolTip(address)
            button.setAccessibleName(f'Öppna {label} i webbläsaren')
            button.clicked.connect(handler)
            address_label = QLabel(address.replace('https://', ''))
            address_label.setObjectName('address')
            address_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            address_label.setWordWrap(True)
            column.addWidget(button)
            column.addWidget(address_label)
            row.addLayout(column, 1)
        box.addLayout(row)
        return card

    def _free_note(self) -> QFrame:
        note = QFrame()
        note.setObjectName('noteBar')
        box = QHBoxLayout(note)
        box.setContentsMargins(16, 12, 16, 12)
        icon = QLabel('✓')
        icon.setObjectName('noteText')
        icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        text = QLabel(NEVER_TEXT)
        text.setObjectName('noteText')
        text.setWordWrap(True)
        box.addWidget(icon)
        box.addWidget(text, 1)
        return note

    # ── Knappar ───────────────────────────────────────────────────────────────

    def _open_paypal(self, *_args) -> None:
        self._open_url(PAYPAL_URL)

    def _open_kofi(self, *_args) -> None:
        self._open_url(KOFI_URL)

    def _open_url(self, url: str) -> None:
        # Endast de två fasta adresserna får öppnas; ingen adress kommer från
        # inställningar eller användarinmatning.
        if url not in ALLOWED_URLS:
            raise ValueError('Okänd betalningsadress')
        if not QDesktopServices.openUrl(QUrl(url)):
            QMessageBox.warning(
                self, 'Kunde inte öppna sidan',
                'Webbläsaren kunde inte öppnas. Kontrollera systemets standardwebbläsare '
                f'eller skriv adressen själv: {url}')
