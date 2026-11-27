# AGENTS.md – hårda regler för Fordonsreg

De här reglerna gäller allt arbete i det här repot. De är **hårda**: de får inte
kringgås, "tillfälligt" undantas eller lösas upp av en senare ändring utan att
Rickard Längkvist uttryckligen ändrar regeln.

Senast uppdaterad: 2026-10-29.

---

## 1. Branch – endast en utvecklingsgren

* Arbeta **aldrig** mot `main`. `main` är bara ursprung och får inte ändras av
  agenten.
* Allt arbete sker på **en** branch: `arena/2f11bf41-fr` (eller den gren som
  uttryckligen anges för sessionen). Regeln gäller även efter byte av chatt.
* Skapa inte fler grenar, byt inte namn på grenen och radera inte grenen.
* **Ingen merge, ingen pull request.** Varken mot `main` eller mellan grenar.
* Vid appuppdateringar gäller samma sak: uppdateraren hämtar **release från
  GitHub**, aldrig `main` direkt, och aldrig en annan gren.

## 2. Release – alltid uppdaterad, alltid Latest

* **Vid varje kodändring** som pushas ska en ny GitHub-release publiceras.
* Releasen ska vara **markerad som Latest** (inte draft, inte prerelease).
* Releasen ska vara byggd från **samma commit** som koden ligger på, så att
  appens uppdaterare jämför filer mot exakt det som finns i grenen.
* Appens uppdaterare jämför **filer** (innehåll), inte versionsnummer. Därför
  räcker det att releasen pekar på rätt commit – men den måste finnas.
* Versionsnummer höjs när koden ändras (`main.pyw` → `VERSION`), utan att
  fråga, om inte annat sagts för det aktuella arbetet.

## 3. Uppdateraren – säkerhet och filjämförelse

* Uppdateraren får bara hämta från `api.github.com`, `github.com` och
  `codeload.github.com`, och bara via **immutable commit-SHA** – aldrig en
  flyttbar tagg, aldrig ett arkiv direkt från `main`.
* Endast en vitlista av filändelser och kataloger får installeras. Symboliska
  länkar, dolda sökvägar och `..` avvisas.
* Filer jämförs med **SHA-256** mot den lokala kopian. Ingen uppdatering sker
  om inget skiljer.
* Före byte säkerhetskopieras allt som skrivs över.
* **Lyckas uppdateringen** (alla filer installerade och verifierade) ska
  säkerhetskopian **tas bort**. Misslyckas den återställs kopian och behålls.
* Efter en lyckad uppdatering ska appen **starta om automatiskt**.
* Automatisk kontroll sker **en gång per dygn, klockan 00:00** lokal tid.
  Finns uppdatering installeras den och appen startar om.

## 4. Testkrav innan något kallas klart

* `python -m unittest discover -s tests -q` ska vara **grönt**, utan skippade
  tester som döljer fel.
* Alla `.py`/`.pyw` ska gå att kompilera (`py_compile`).
* `python main.pyw --validate-config` ska svara att konfigurationen är giltig.
* Nya funktioner ska ha tester som granskar **beteendet**, inte bara att koden
  finns.
* Inga tysta beroenden: en ny modul ska antingen importera utan Qt (och testas
  så) eller ha en uttrycklig Qt-gräns.
* Inga tysta gränssnittsbrott: tas en meny, knapp eller flik bort ska det stå i
  chatten och i `INSTALLATION.md`.

## 5. Tio meddelanden – ny förslagslista

* Efter **tio chattmeddelanden** ska en **ny** lista med **tio nya förslag**
  presenteras.
* Förslagen får **inte** återanvändas från tidigare listor.
* Listan ska **alltid skrivas ut i chatten**, inte bara sparas som fil.

## 6. Dokumentation och språk

* All text i gränssnitt, dokumentation och loggar är på **svenska**, med versal
  i början av menyer, knappar och rubriker.
* Ändrar du beteende ska `INSTALLATION.md` uppdateras i samma ändring.
* Hårda regler som tillkommer skrivs in **här** i `AGENTS.md`.

## 7. Gränssnitt – bestående krav

* Fönstret anpassar sig till skärmen: startar i **maximal höjd** för skärmens
  arbetsyta och anpassar bredden. Inget får gömmas; rullning ska minimeras.
* Programmet startar **alltid minimerat**, utan terminalfönster – varken vid
  start, skanning, import eller uppdatering.
* Skärpan ska vara skarp: hög-DPI med `PassThrough`, full hinting, ikoner ritade
  i skärmens upplösning och vektorlogotyp (inte uppskalad rasterbild).
* Tema, typsnitt, ikoner, densitet och skalning hämtas från `core/theme.py`.
  Ingen annan fil får skriva egna färgkoder eller typsnittsnamn.

## 8. Loggar

* Föregående dags logg arkiveras.
* Arkiverade loggar **raderas efter 7 dagar**.
* Det finns en **komplett fellogg** (`logs/felsokning.log`) och en **applogg**.
* Felloggen innehåller alla **aktiva** fel. När ett fel är åtgärdat ska det
  kunna tas bort ur loggen – av användaren, via **Verktyg → Visa
  felsökningslogg → Rensa åtgärdade fel**.

## 9. Data och integritet

* Inga påhittade siffror, koder eller statusar i gränssnittet. Saknade värden
  visas som tomma eller `—`.
* Allt arbete sker offline. Ingen molntjänst, inget konto, ingen extern AI.
* PIN-koder, färgkoder och återförsäljardata hanteras som tidigare beslutats:
  PIN-skyddade tabeller, ingen gissad Dispatch-kod, ingen klartext-PIN i GUI.

## 10. Vad som aldrig får göras

* Ingen fristående exe eller installationspaket.
* Inga gissade TS-koder. TS-spärren gäller tills formatet är verifierat och
  godkänt loggats.
* Ingen ändring av SAP-originalfiler eller årsfiler utan säkerhetskopia.
* Ingen merge och ingen pull request.
