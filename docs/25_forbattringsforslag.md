# 25 förslag som gör Fordonsreg starkare än andra program i samma arbetsflöde

Utgångspunkt: Fordonsreg är redan ensam om att kombinera årsflikar, Dispatch-styrd
färgkontroll, säker Excel-import med PIN-skydd, inlärda kolumnmappningar, daglig
loggarkivering och uppdatering med hashkontroll och backup i ett och samma
skrivbordsprogram. Förslagen nedan bygger vidare på det – de är valda för att de
löser verkliga problem i det dagliga arbetet, inte för att de är tekniskt roliga.

Beteckningar: **Insats** S = några dagar, M = 1–2 veckor, L = större arbete.
**Beroende** anger vad som måste vara klart eller verifierat först.

---

> **Status:** Förslag 7, 9, 11, 17, 20, 21, 22 och 24 är genomförda. Se
> `INSTALLATION.md` avsnittet "Sökning, översikt och skydd" för hur de används.

## A. Förtroende för data – att våga lita på det som skrivs

### 1. Ångra senaste importen
**Vad:** Varje import skriver en journal med före/efter-värden per rad. En knapp
"Ångra senaste import" återställer exakt det som ändrades, med kontroll att inget
annat hunnit ändras efteråt.
**Varför:** Idag tas backup före skrivning, men en återställning är ett manuellt
filjobb. Möjligheten att ångra i programmet gör att man vågar importera.
**Genomförande:** Bygg vidare på `core/vehicle_backup.py` och den befintliga
snapshotkontrollen; journal i `data/journal/`.
**Insats:** M. **Beroende:** Inget.

### 2. Förhandsgranskning av exakt vad som ändras
**Vad:** Före skrivning visas en tabell: rad, fält, gammalt värde → nytt värde,
markerat som ny rad, ändrad rad eller oförändrad. Godkännande per radgrupp.
**Varför:** Dagens import varnar för konflikter men visar inte hela effekten.
En full diff gör importen granskningsbar och är det som skiljer ett yrkesverktyg
från ett skript.
**Genomförande:** `core/vehicle_import_insights.py` har redan insiktsdata –
utöka till full fältdiff och återanvänd `plugins/main_gui/dialogs/task_progress.py`.
**Insats:** M. **Beroende:** Förslag 1 för smidig ångra-knapp.

### 3. Datakvalitetskontroll före export
**Vad:** En kontrollpanel som listar VIN med fel längd eller tecken, år som inte
stämmer med flik, saknade färgkopplingar, föräldralösa Dispatch-rader,
dubbletter och tomma obligatoriska fält – med klick för att hoppa till posten.
**Varför:** Fel som hittas före export kostar minuter; fel som hittas av kund
kostar förtroende.
**Genomförande:** Ny `core/data_quality.py` som läser samma datakällor som
tabellerna; resultatet kan köras både manuellt och före export.
**Insats:** M. **Beroende:** Inget.

### 4. Posthistorik med fältdiff
**Vad:** Varje fordon sparar en kronologisk historik: när, vilket fält, gammalt
och nytt värde, och om ändringen kom från import eller manuell redigering.
**Varför:** Vid frågor i efterhand ("varför står det så?") finns svaret i appen.
**Genomförande:** Skriv historik i samma transaktion som sparningen, komprimerad
och roterad per år.
**Insats:** M. **Beroende:** Förslag 1 (samma journalteknik).

### 5. Återställningscenter
**Vad:** En vy som listar alla säkerhetskopior med datum, orsak och checksumma,
och som kan återställa en vald kopia efter bekräftelse – med automatisk
säkerhetskopia av nuvarande läge först.
**Varför:** Backup som ingen kan återställa är ingen backup.
**Genomförande:** Bygg vidare på `core/vehicle_backup.py`; verifiera SHA-256 före
återställning och logga resultatet.
**Insats:** S–M. **Beroende:** Inget.

---

## B. Import som blir snabbare för varje gång

### 6. Automatiskt igenkänd återkommande fil
**Vad:** En fil med samma struktur som en tidigare godkänd import känns igen på
kolumnrubriker och filnamnsmönster, och föreslår rätt mappningsprofil direkt –
men kräver alltid ett klick innan något skrivs.
**Varför:** Samma veckofil varje gång ska inte kräva samma klick varje gång.
**Genomförande:** `core/vehicle_mapping_profiles.py` och `core/learning.py` finns;
lägg till fingeravtryck på rubrikuppsättning och ett tydligt "föreslagen" läge.
**Insats:** S. **Beroende:** Inget.

### 7. Bevakad mapp ✅ genomförd
**Vad:** Peka ut en mapp (t.ex. nedladdningar). När en ny Excel- eller CSV-fil
dyker upp visas en diskret notis: "Ny fil hittad – importera?" Inget importeras
automatiskt.
**Varför:** Tar bort steget att leta efter filen, utan att ta bort kontrollen.
**Genomförande:** Lättviktsbevakning via `QFileSystemWatcher`, avstängd som
standard, alla beslut kvar hos användaren.
**Insats:** S. **Beroende:** Förslag 6.

### 8. Importkö med status
**Vad:** Flera filer kan läggas i kö, granskas i tur och ordning och köras med
progress, avbrott och sammanfattning per fil.
**Varför:** Månadens fyra filer blir en operation i stället för fyra.
**Genomförande:** Utöka `plugins/main_gui/dialogs/task_progress.py` till en kö;
all skrivning fortsatt sekventiell och ångringsbar.
**Insats:** M. **Beroende:** Förslag 1 och 2.

### 9. Import i bakgrunden ✅ genomförd
**Vad:** Tunga importer och stora Excel-filer körs utanför GUI-tråden, med
progress, avbryt och felrapport – fönstret svarar hela tiden.
**Varför:** Idag kan stora filer frysa gränssnittet, vilket känns som en krasch.
**Genomförande:** Arbetstråd med samma säkerhetsspärrar som i dag; ingen ändring
av skrivlogiken, bara var den körs.
**Insats:** M. **Beroende:** Förslag 1 (för att avbruten import ska vara säker).

### 10. Egna rapportmallar för export
**Vad:** Spara namngivna exportmallar (vilka kolumner, ordning, filter, rubrik
och logotyp) och skriv ut dem som PDF eller Excel med ett klick.
**Varför:** Samma rapport till samma mottagare varje gång, i stället för
manuell kolumnflytt.
**Genomförande:** `core/vehicle_text_export.py` och `plugins/reports/` finns som
grund; mallar versionshanteras som vanliga JSON-filer.
**Insats:** M. **Beroende:** Inget.

---

## C. Dispatch, färger och TS – där mest tid och mest risk sitter

### 11. Verktyg för att verifiera TS-formatet ✅ genomförd
**Vad:** Ett granskningsverktyg där en riktig TS-fil läses in, dess struktur
sammanfattas (fält, ordning, radslut, kodning, decimalkomma) och jämförs med
appens generator. Skillnader listas rad för rad. Först när du godkänner låses
spärren upp.
**Varför:** TS-genereringen är spärrad eftersom formatet inte är verifierat. Det
här förslaget är den kortaste vägen till en säker upplåsning – och gör
verifieringen reproducerbar i stället för en engångsbedömning.
**Genomförande:** Bygg vidare på `core/ts_safety.py` och `core/ts_source_import.py`;
spärren flyttas bara av ett explicit, loggat godkännande.
**Insats:** M. **Beroende:** En riktig TS-fil från dig. Ingen TS-fil skrivs förrän
du godkänt jämförelsen.

### 12. Ändringslogg för Dispatch-filen
**Vad:** När en ny Dispatch-version importeras visas exakt vad som tillkommit,
försvunnit eller ändrats sedan förra versionen – nya färger, borttagna rader,
ändrade kopplingar.
**Varför:** Då upptäcks en tyst ändring i underlaget innan den påverkar en enda
fordonspost.
**Genomförande:** Jämför normaliserade rader och spara diffen tillsammans med
källans SHA-256.
**Insats:** S–M. **Beroende:** Inget.

### 13. Kö för okopplade färger
**Vad:** En arbetslista över alla färger som väntar på koppling, med sökning,
förslag på närmast befintlig färg och masskoppling bakom PIN.
**Varför:** Kodlösa rader skapas redan automatiskt – men de behöver också bli
färdiga, annars växer högen.
**Genomförande:** `core/color_storage.py` och `plugins/colors_manager/` finns;
lägg till en kövy med status och spårbarhet.
**Insats:** S–M. **Beroende:** Inget.

### 14. Färgförslag med konfidens – aldrig gissning
**Vad:** Vid nära matchning visas "85 % likhet med Färg X" som förslag som du
bekräftar. Ingenting sparas eller genereras utan ditt val.
**Varför:** Sparar tid vid uppenbara varianter, utan att bryta principen att en
TS-kod aldrig gissas.
**Genomförande:** Normalisera namn och jämför mot färgtabellen; visa alltid
källraden så att bedömningen går att kontrollera.
**Insats:** S. **Beroende:** Förslag 13.

### 15. TS-generering med förhandsvisning och avbrott
**Vad:** Genererad TS visas som text och tabell innan den skrivs, med radantal,
kontrollsummor och möjlighet att avbryta. Skrivning sker atomiskt: hel fil eller
ingen fil.
**Varför:** Ingen halvskriven fil och ingen överraskning i efterhand.
**Genomförande:** Finns delvis; flytta till arbetstråd och skriv via temporär fil
med byte.
**Insats:** M. **Beroende:** Förslag 11.

### 16. Varningslista före generering
**Vad:** En checklista som måste vara grön innan en TS-fil får skrivas: alla
färger kopplade, inga dubbletter med olika approval, inga saknade obligatoriska
fält, rätt schema valt.
**Varför:** Gör spärren begriplig i stället för bara blockerad – du ser exakt vad
som återstår.
**Genomförande:** Återanvänd `core/dispatch_color_gate.py` och
`core/ts_safety.py` som datakälla till panelen.
**Insats:** S. **Beroende:** Förslag 11 för upplåsning.

---

## D. Snabbhet i vardagen

### 17. Global sökning (Ctrl+K) ✅ genomförd
**Vad:** Ett sökfält som hittar VIN3, approval, regnr, färg, återförsäljare och
menyval – och hoppar direkt till rätt post och år.
**Varför:** Det enskilt största tidsbesparingen i ett program med tusentals rader
och flera årsflikar.
**Genomförande:** Ett index per år som byggs vid import och sparas; sökningen är
lokal och omedelbar.
**Insats:** M. **Beroende:** Inget.

### 18. Sparade vyer och filter
**Vad:** Spara filterkombinationer som namngivna vyer ("Saknar färg 2026",
"Min återförsäljare"), och växla mellan dem med en knapp.
**Varför:** Samma fråga ställs varje dag; svaret ska inte behöva byggas om.
**Genomförande:** Filter definieras som data, sparas per användare, kan inte
kringgå PIN-skydd.
**Insats:** S–M. **Beroende:** Förslag 17 underlättar.

### 19. Massredigering med förhandsgranskning
**Vad:** Markera flera rader, ändra ett fält, se exakt vad som ändras, bekräfta
med PIN och få en ångra-punkt.
**Varför:** Rättar tio likadana fel på en gång i stället för tio gånger.
**Genomförande:** Samma journal som förslag 1; PIN krävs som i dag för ändringar.
**Insats:** M. **Beroende:** Förslag 1.

### 20. Snabbknappar i systemfältet ✅ genomförd
**Vad:** Högerklick på tray-ikonen ger "Ny import", "Sök VIN" och "Senaste
logg" – utan att öppna hela fönstret.
**Varför:** Appen är redan minimerad större delen av dagen; då ska de vanligaste
sakerna vara ett klick bort.
**Genomförande:** Utöka `plugins/main_gui/plugin.py` där trayn redan hanteras.
**Insats:** S. **Beroende:** Inget.

### 21. Instrumentpanel vid start ✅ genomförd
**Vad:** En liten översikt: fordon per år, senaste import, väntande färger,
kommande arkivering, senaste fel – med klickbara genvägar.
**Varför:** Ger svar på "är allt i ordning?" innan man ens öppnat en flik.
**Genomförande:** Samma data som förslag 3 och 4; inga nya datakällor.
**Insats:** S–M. **Beroende:** Förslag 3.

---

## E. Drift som håller i längden

### 22. Hälso­kontroll vid start med automatiskt återfall ✅ genomförd
**Vad:** Efter en uppdatering kontrolleras att programmet startar och att
nyckelfiler finns. Misslyckas det återställs föregående version automatiskt vid
nästa start och felet loggas.
**Varför:** En dålig uppdatering ska aldrig kunna låsa ute användaren.
**Genomförande:** `plugins/auto_update/` har redan backup och hashkontroll; lägg
till en startmarkör som rensas först när appen är uppe.
**Insats:** M. **Beroende:** Inget.

### 23. Supportpaket med ett klick
**Vad:** Skapar en zip med loggar, felkoder, versioner och inställningar – utan
PIN-hashar, sökvägar till användardata eller personuppgifter – för felsökning.
**Varför:** Gör felrapporter användbara utan att känsliga data lämnar datorn.
**Genomförande:** Vitlista exakt vilka filer och fält som får ingå; granska
innehållet innan zip skapas.
**Insats:** S. **Beroende:** Inget.

### 24. Felkoder med åtgärdsguide ✅ genomförd
**Vad:** Varje felkod får en kort förklaring, trolig orsak och konkreta steg.
När du bekräftat att felet är löst markeras det automatiskt som åtgärdat.
**Varför:** `logs/felkoder.json` finns redan; guiden gör den användbar även för
någon som inte skrev koden.
**Genomförande:** Bygg vidare på `core/error_log_view.py` och
`core/error_summary.py`.
**Insats:** S–M. **Beroende:** Inget.

### 25. Skyddad data i vila och kontrollerad PIN
**Vad:** Känsliga lokala filer kan kryssas för kryptering, PIN får växande
fördröjning efter felaktiga försök och en tidsgräns för upplåst läge. Loggar
maskerar känsliga fält automatiskt.
**Varför:** PIN skyddar i dag appens vägar, inte filerna på disken. Det här sluter
glappet och skyddar även om datorn lånas ut.
**Genomförande:** Befintlig PBKDF2-migrering behålls; kryptering är opt-in och
kräver att backupflödet först verifieras med krypterade filer.
**Insats:** L. **Beroende:** Förslag 5, samt noggrann testning av backup och
återställning.

---

## Rekommenderat första paket

Om du vill ha mest effekt per insats, i den här ordningen:

1. **1, 2 och 5** – ångra import, exakt diff och återställningscenter. Det höjer
   förtroendet för hela programmet och gör senare förslag säkrare att bygga.
2. **17 och 20** – global sökning och snabbknappar. Störst tidsbesparing per dag.
3. **11 och 16** – TS-verifiering och varningslista. Enda vägen till en säker
   upplåsning av TS-genereringen.
4. **3 och 21** – datakvalitet och instrumentpanel. Gör kvaliteten synlig utan
   att man letar efter den.

Förslag 25 är det mest omfattande och bör vänta tills backup och återställning är
testade med verkliga filer.

## Vad som inte föreslås – och varför

- **Ingen fristående exe**, enligt tidigare beslut.
- **Ingen molntjänst eller extern AI** som standard: appen ska fungera offline och
  utan att användardata lämnar datorn. En opt-in-synk kan bli aktuell senare, men
  kräver först kryptering och konflikthantering enligt förslag 25.
- **Inga påhittade siffror eller gissade TS-koder.** Spärren ligger kvar tills
  formatet är verifierat enligt förslag 11.
