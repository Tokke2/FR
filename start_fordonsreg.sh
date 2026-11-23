#!/bin/sh
# Startfil för Linux och macOS. Ingen Python krävs för denna kontroll.
set -u
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1
cd "$ROOT" || exit 1
SYSTEM=$(uname -s)
FOUND_PYTHON=0

try_python() {
    candidate=$1
    [ -x "$candidate" ] || return 1
    # Apples /usr/bin/python3 kan vara en installationsstub, inte Python.
    # Kör inte stubben då den själv kan visa en installationsfråga.
    if [ "$SYSTEM" = Darwin ] && [ "$candidate" = /usr/bin/python3 ]; then
        if ! command -v xcode-select >/dev/null 2>&1 || ! xcode-select -p >/dev/null 2>&1; then
            return 1
        fi
    fi
    FOUND_PYTHON=1
    if "$candidate" -c 'import sys; assert sys.version_info.major == 3' >/dev/null 2>&1; then
        exec "$candidate" "$ROOT/start.pyw"
    fi
    return 1
}

# Den Python som redan finns i PATH ska användas utan fråga eller uppdatering.
for name in python3 python; do
    candidate=$(command -v "$name" 2>/dev/null || :)
    [ -z "$candidate" ] || try_python "$candidate"
done
# Sök även namngivna Python 3-versioner i PATH (t.ex. python3.13 utan python3-länk).
old_ifs=$IFS
IFS=:
for directory in $PATH; do
    [ -n "$directory" ] || directory=.
    for candidate in "$directory"/python3.[0-9]*; do
        [ -f "$candidate" ] || continue
        try_python "$candidate"
    done
done
IFS=$old_ifs
if [ "$FOUND_PYTHON" -eq 1 ]; then
    echo 'Python finns men ingen fungerande Python 3 kunde startas. Ingen ny installation erbjuds; kontrollera den befintliga installationen.' >&2
    exit 1
fi

# En installerad men trasig/dold Python ska inte räknas som frånvarande.
if [ "$SYSTEM" = Linux ]; then
    if command -v dpkg-query >/dev/null 2>&1 && dpkg-query -W -f='${db:Status-Status}\n' 'python3*' 2>/dev/null | grep -qx installed; then
        echo 'Ett Python 3-paket finns redan; kontrollera eller reparera det. Ingen ny installation erbjuds.' >&2
        exit 1
    fi
    if command -v rpm >/dev/null 2>&1 && rpm -q python3 >/dev/null 2>&1; then
        echo 'Ett Python 3-paket finns redan; kontrollera eller reparera det. Ingen ny installation erbjuds.' >&2
        exit 1
    fi
    if command -v pacman >/dev/null 2>&1 && pacman -Q python >/dev/null 2>&1; then
        echo 'Ett Python-paket finns redan; kontrollera eller reparera det. Ingen ny installation erbjuds.' >&2
        exit 1
    fi
elif [ "$SYSTEM" = Darwin ]; then
    if command -v pkgutil >/dev/null 2>&1 && pkgutil --pkgs 2>/dev/null | grep -qi '^org\.python\.Python'; then
        echo 'Ett Python-paket finns redan; kontrollera eller reparera det. Ingen ny installation erbjuds.' >&2
        exit 1
    fi
    for candidate in /usr/local/bin/python3 /opt/homebrew/bin/python3 /Library/Frameworks/Python.framework/Versions/*/bin/python3; do
        [ -f "$candidate" ] || continue
        try_python "$candidate"
    done
    if [ "$FOUND_PYTHON" -eq 1 ]; then
        echo 'Python finns redan men kunde inte startas. Ingen ny installation erbjuds.' >&2
        exit 1
    fi
else
    echo 'Operativsystemet stöds inte av startfilen. Ingen installation erbjuds.' >&2
    exit 1
fi

printf '%s\n' 'Ingen Python 3 hittades i PATH eller de kontrollerade systempaketen.'
printf '%s\n' 'Portabla eller oregistrerade installationer kan finnas på andra platser; kontrollera först att Python verkligen saknas.'
printf '%s\n' 'Öppna Pythons officiella nedladdningssida för manuell installation av senaste stabila version? [j/N]'
IFS= read -r answer || exit 1
case "$answer" in j|J|ja|JA|y|Y|yes|YES) ;; *) echo 'Avbrutet. Ingen installation gjordes.'; exit 0 ;; esac
url='https://www.python.org/downloads/'
if [ "$SYSTEM" = Darwin ] && command -v open >/dev/null 2>&1; then
    open "$url" || { echo "Öppna sidan manuellt: $url" >&2; exit 1; }
elif [ "$SYSTEM" = Linux ] && command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url" || { echo "Öppna sidan manuellt: $url" >&2; exit 1; }
else
    echo "Öppna sidan manuellt: $url"
fi
echo 'Installationen görs manuellt. Starta Fordonsreg igen när Python är installerat.'
