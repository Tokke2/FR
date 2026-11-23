"""Fasta betaluppgifter och en förberäknad Swish-QR för frivilligt stöd.

Stödet finns bara i programmet – det finns ingen egen webbsida. Swish visas
enbart som QR-kod enligt Swish standard för privatpersoner (belopp väljs i
Swish). PayPal och Ko-fi visas enbart som knappar med fast webbadress; de har
medvetet ingen QR-kod. Koden skapas som moduler i programmet: inga externa
QR-tjänster, ingen nätverkstrafik och inga redigerbara inställningar.
En QR-kod kan alltid avläsas.
"""
from __future__ import annotations

# Fast informationstext för donationsdialogen. Ingen del kan ändras i programmet.
INTRO_TITLE = 'Stöd Fordonsreg'
INTRO_TEXT = (
    'Fordonsreg är ett program som jag har byggt själv för att göra det dagliga arbetet '
    'med fordonsregistrering enklare – importer, årsflikar, färger, återförsäljare och '
    'underlag för TS på ett och samma ställe. Det är gratis att använda och kommer att '
    'förbli gratis.'
)
BODY_TEXT = (
    'Om programmet sparar tid för dig får du gärna stötta utvecklingen med en frivillig '
    'Swish-betalning. Stödet går till fortsatt utveckling, testning och underhåll, så att '
    'nya funktioner blir färdiga och fel blir åtgärdade. Det är jag som utvecklar och '
    'testar allt själv, vid sidan av arbetet. Du bestämmer helt själv om du vill ge något '
    'och hur mycket – beloppet väljer du direkt i Swish.'
)
NEVER_TEXT = (
    'Ingenting i programmet låses upp av en donation. Alla funktioner fungerar precis lika '
    'bra utan, och du får inga påminnelser och inga krav på att betala. Stödet visas bara '
    'här i programmet – det finns ingen separat stödsida.'
)
FOOTER_TEXT = (
    'Tack för att du använder Fordonsreg!  ·  © Rickard Längkvist'
)
QR_HINT = (
    'Öppna Swish på mobilen, välj Skanna och rikta kameran mot koden. '
    'Kontrollera mottagaren i Swish innan du godkänner.'
)
LINK_HINT = (
    'Vill du hellre använda PayPal eller Ko-fi? Öppna respektive sida med knappen nedan. '
    'Betalningen sker hos betaltjänsten och kan avbrytas när som helst.'
)


PAYPAL_URL = "https://paypal.me/Rickard3dPrint"
KOFI_URL = "https://ko-fi.com/tokke2"

# Swish-koden är förberäknade svartvita moduler med fyra modulrader vit marginal.
# Inget QR-bibliotek och ingen extern QR-tjänst används vid körning.
SWISH_QR = (
    '00000000000000000000000000000',
    '00000000000000000000000000000',
    '00000000000000000000000000000',
    '00000000000000000000000000000',
    '00001111111001101011111110000',
    '00001000001010010010000010000',
    '00001011101001101010111010000',
    '00001011101000010010111010000',
    '00001011101010111010111010000',
    '00001000001000110010000010000',
    '00001111111010101011111110000',
    '00000000000000000000000000000',
    '00001010101001001000100100000',
    '00001010110100010010010110000',
    '00001011011001110010100010000',
    '00001000100110011101000100000',
    '00001100001000110011110100000',
    '00000000000010100010111000000',
    '00001111111001001000100000000',
    '00001000001001000011010000000',
    '00001011101011101010101110000',
    '00001011101001010101101100000',
    '00001011101011010110011010000',
    '00001000001001111100000110000',
    '00001111111010010110101010000',
    '00000000000000000000000000000',
    '00000000000000000000000000000',
    '00000000000000000000000000000',
    '00000000000000000000000000000',
)

# Endast Swish har en QR-kod. PayPal och Ko-fi är knappar (se PAYPAL_URL/KOFI_URL).
QR_CODES = {
    "swish": ("Swish", SWISH_QR),
}


def qr_matrix(name: str) -> tuple[str, ...]:
    """Returnera en fastställd QR-kod; avvisa okänt namn eller skadad kod."""
    try:
        _label, matrix = QR_CODES[name]
    except KeyError as exc:
        raise ValueError(f"Okänd QR-kod: {name}") from exc
    size = len(matrix)
    if not 21 <= size <= 177 or any(len(row) != size or set(row) - {"0", "1"} for row in matrix):
        raise ValueError("QR-koden är skadad")
    if any(row[:4] != "0000" or row[-4:] != "0000" for row in matrix) or "1" in matrix[0]:
        raise ValueError("QR-koden saknar vit marginal")
    return matrix


def swish_qr_matrix() -> tuple[str, ...]:
    """Bakåtkompatibel hjälpare för Swish-koden."""
    return qr_matrix("swish")
