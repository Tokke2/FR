# Granskning av PT45 för MC/moped

Underlag: bilderna av Transportstyrelsens **13.2-postbeskrivning för filregistrering**, PT45 registrering av MC eller moped enligt 168/2013/EG, sida 1–4 som användaren bifogat. Positionerna nedan är 1-baserade och inklusive slutposition. De avser just denna fordonstyp och får inte antas gälla andra PT45-varianter.

| Nr | Fält | Position | Nr | Fält | Position |
|---:|---|---|---:|---|---|
| 1 | Löpnummer | 1–4 | 2 | Posttyp | 5–6 |
| 3 | Fordonsägarens person-/organisationsnummer | 7–16 | 4 | Registreringsnummer (blankt i indata) | 17–22 |
| 5 | Felkod (blank i indata) | 23–26 | 6 | Feltext (blank i indata) | 27–106 |
| 7 | Behörighetskod vid kommissionärsspärr (blank i indata) | 107–114 | 8 | Årtal för småseriefordon | 115–118 |
| 9 | Sekvensnummer för småseriefordon | 119–122 | 10 | Fabrikat | 123–146 |
| 11 | Fabrikatskod | 147–149 | 12 | Gruppnummer | 150–155 |
| 13 | Typ | 156–179 | 14 | Variant | 180–219 |
| 15 | Version | 220–259 | 16 | Handelsbeteckning | 260–283 |
| 17 | Fordonskategori | 284–291 | 18 | Identifieringsnummer/VIN | 292–308 |
| 19 | Typgodkännandenummer | 309–333 | 20 | Datum för typgodkännande | 334–341 |
| 21 | Datum för intyg om överensstämmelse | 342–349 | 22 | Antal axlar | 350–351 |
| 23 | Antal hjul | 352–354 | 24 | Avancerat bromssystem | 355–361 |
| 25 | Längd | 362–366 | 26 | Bredd | 367–371 |
| 27 | Höjd | 372–375 | 28 | Reserv, `000000` | 376–381 |
| 29 | Vikt i körklart skick/tjänstevikt | 382–387 | 30 | Största tekniskt tillåten vikt/totalvikt | 388–393 |
| 31 | Släpvagnsvikt, bromsat släp | 394–399 | 32 | Släpvagnsvikt, obromsat släp | 400–405 |
| 33 | Arbetssätt/funktionsprincip för förbränningsmotorn | 406–410 | 34 | Slagvolym/motorkapacitet | 411–415 |
| 35 | Effekt, drivmedel 1 | 416–421 | 36 | Varvtal för effekt, drivmedel 1 | 422–426 |
| 37 | Effekt, drivmedel 2 | 427–432 | 38 | Varvtal för effekt, drivmedel 2 | 433–437 |
| 39 | Drivmedel, bränsletyp | 438–443 | 40 | Drivmedel 2 | 444–449 |
| 41 | Elfordon, konfiguration | 450–459 | 42 | Max hastighet, drivmedel 1 | 460–464 |
| 43 | Max hastighet, drivmedel 2 | 465–469 | 44 | Däck, axel 1 | 470–489 |
| 45 | Däck, axel 2 | 490–509 | 46 | Antal sittplatser | 510–510 |
| 47 | Euroklass | 511–516 | 48 | Ljudnivå, stillastående | 517–519 |
| 49 | Varvtal, stillastående | 520–524 | 50 | Ljudnivå under körning | 525–527 |
| 51 | Ljudnivå, stillastående, drivmedel 2 | 528–530 | 52 | Varvtal, stillastående, drivmedel 2 | 531–535 |
| 53 | Ljudnivå under körning, drivmedel 2 | 536–538 | 54 | Avgasdirektiv | 539–568 |
| 55 | Färg | 569–570 | 56 | Tillverkningsår och månad | 571–576 |
| 57 | Skyltformat, bak | 577–577 | 58 | Kommissionärsspärr | 578–578 |
| 59 | Beställning av registreringsbevis | 579–579 | 60 | CO2-utsläpp, drivmedel 1 | 580–584 |
| 61 | CO2-utsläpp, viktad/blandad | 585–589 | 62 | CO2-utsläpp, drivmedel 2 | 590–594 |
| 63 | Effekt under 15 minuter, elmotor | 595–600 | 64 | Effekt under 30 minuter, elmotor | 601–606 |
| – | Reserv | 607–2500 | | | |

## Resultat och begränsningar

- Den tidigare schemafria fallbacken lade VIN på position 7–23 och stämmer **inte** med underlaget. Det schemafria genereringsflödet är spärrat.
- `core/ts_safety.py` jämför samtliga intervall ovan mot ett schema och kan kontrollera några verifierbara fält i en post. Ingen aktiv PT45-specifikation fanns tillgänglig i projektet att jämföra på riktigt. En intervallmatch är inte bevis för att fältens semantik, typer, koder, obligatoriska värden eller hela filen stämmer.
- Reserven på 376–381 anges som `000000`. Slutreserven 607–2500 har ingen uttrycklig fyllnadsregel i de bifogade bilderna; vi antar inte att den är blank eller nollfylld.
- Underlaget beskriver inte PT28 och PT99, komplett filstruktur, radslut eller teckenkodning. Därför är **produktion av TS-filer tills vidare spärrad även om ett schema finns**. Ladda upp kompletta postbeskrivningar för PT28 och PT99 samt uppgifter om filformatet. Innan spärren kan tas bort måste även PT45:s fältnamn, datatyper, indataregler och verklig mappning verifieras med riktigt underlag/testfil.
