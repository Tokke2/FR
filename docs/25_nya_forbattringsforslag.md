# 25 nya förbättringsförslag – så blir Fordonsreg bättre än alternativen

Uppföljning av `docs/25_forbattringsforslag.md`. Den här listan fokuserar på
**skärm, layout, ikoner, design och skärpa** samt på sådant som användare av
fordonsregister- och Excelflöden faktiskt efterfrågar – inte sådant som redan är
byggt (Ctrl+K, instrumentpanel, bevakad mapp, bakgrundsimport, TS-verifiering,
hälsokontroll, felkodsguide och donation).

Varje förslag anger **Vad**, **Varför**, **Genomförande**, **Insats** (S/M/L) och
**Beroende**. Inga siffror på förväntad tidsvinst är påhittade; allt som kräver
nya data eller nya filer från Transportstyrelsen/Dispatch är markerat.

---

## Nuvarande läge (utgångspunkt)

* Tema, typsnitt, ikoner och skärmbredd finns i `core/theme.py`; mörkt, ljust och
  *följ systemet*.
* Fönstret räknas fram ur skärmens arbetsyta och sidomenyn anpassas vid resize.
* Hög-DPI är påslaget med `PassThrough`-avrundning, full hinting och ikoner som
  ritas i skärmens verkliga upplösning.
* Tabeller har responsiva kolumnbredder via `core/responsive_layout.py`.

Det som **saknas** är framför allt: kompakthet på små skärmar, densitet,
tillgänglighet, minnesvärda genvägar per användare, förhandsgranskning före
skrivning och stöd för att arbeta med två skärmar.

---

## A. Skärm, fönster och densitet

### 1. Kompakt läge för små skärmar

**Vad:** En brytpunkt under 1100 px bredd som automatiskt gör sidomenyn till en
ikonrad (enbart ikoner med verktygstips), sänker radhöjden i tabeller från 40
till 30 px och drar ihop luften mellan korten.
**Varför:** En 13-tums bärbar dator på 1366×768 får i dag en meny som tar 210 px
och tabellrader som tar en tredjedel av höjden. Användaren tvingas rulla i
onödan, vilket är det vanligaste klagomålet på registerappar.
**Genomförande:** `design.compact_mode(width)` i `core/theme.py`; två varianter
av `QPushButton#NavButton` (`:checked` med ikon enbart); `resizeEvent` byter
läge. Inställningen `ui.density` (`comfortable`/`compact`/`auto`).
**Insats:** M. **Beroende:** inget.

### 2. Justerbar sidomeny och ihågkommen bredd

**Vad:** Användaren kan dra i sidomenyns kant; bredden sparas per skärmstorlek.
**Varför:** Olika arbetsuppgifter behöver olika mycket meny. En fast bredd
tvingar användaren att leva med någon annans val.
**Genomförande:** `QSplitter` i stället för fast `setFixedWidth`, min/max-gränser
från `design.sidebar_width()`, spara i `settings.json` under `window.sidebar_width`
med skärmens storlek som nyckel.
**Insats:** S. **Beroende:** 1.

### 3. Fönsterplacering per skärm

**Vad:** Fönstret kommer ihåg position och storlek separat för varje skärm, och
öppnas på den skärm det senast användes på.
**Varför:** Den som växlar mellan bärbar dator och dockningsstation får i dag
fönstret på fel skärm eller utanför skärmkanten.
**Genomförande:** Spara `(skärmnamn, geometri)` i `settings.json`; validera mot
`QScreen.availableGeometry()` före återställning; **Visa → Anpassa fönstret till
skärmen** finns redan som manuell reserv.
**Insats:** S. **Beroende:** inget.

### 4. Skalningsoberoende gränssnitt (125–200 %)

**Vad:** Ett testläge som ritar om gränssnittet vid 1,0 / 1,25 / 1,5 / 2,0 och
kontrollerar att inga etiketter klipps och att inga tabeller får vågrät rullning.
**Varför:** Skärpan är nu bra, men på 150 % kan fasta pixelmått fortfarande
klippa svensk text som "Godkännandenummer".
**Genomförande:** Utöka `tests/test_theme.py` med en beräkning av textbredd via
`QFontMetrics` när Qt finns; annars en konservativ teckenbreddsmodell.
Rapportera minsta fönsterbredd per textspråk.
**Insats:** M. **Beroende:** 1.

### 5. Ett gemensamt sidhuvud

**Vad:** Alla sidor får samma rubrik, underrubrik, verktygsrad och
"senast uppdaterad" – i stället för att varje plugin bygger sin egen.
**Varför:** Sidorna ser olika ut i dag, vilket gör appen rörig och svårare att
lära sig.
**Genomförande:** `PageHeader`-widget i `core/theme.py` (Qt-del), som plugins
använder via `create_widget`; rubrik/underrubrik/åtgärder som parametrar.
**Insats:** M. **Beroende:** inget.

---

## B. Tabeller och innehåll

### 6. Frysta kolumner och rubriker

**Vad:** VIN-koden kan frysas längst till vänster och rubrikraden alltid överst.
**Varför:** När användaren rullar i en bred tabell försvinner VIN-koden, som är
den enda säkra identifieraren.
**Genomförande:** `QTableView.setFrozenColumnCount(1)` via en liten hjälpklass;
standardkolumn i `vehicle_registry_page`.
**Insats:** S. **Beroende:** inget.

### 7. Kolumnprofil per årsflik

**Vad:** Varje årsflik minns vilka kolumner som visas, ordningen och bredderna.
**Varför:** 2026 och 2023 används olika; att ställa om manuellt varje gång är
onödigt arbete.
**Genomförande:** Spara per `(år, tabell)` i `data/table_profiles.json`; återställ
efter att kolumnerna byggts, med validering mot kända kolumnnamn.
**Insats:** M. **Beroende:** 6.

### 8. Radhöjd och textbrytning som användaren styr

**Vad:** Tre radhöjder (kompakt/normal/luftig) och frivillig textbrytning i celler.
**Varför:** Långa färgnamn och återförsäljarnamn klipps i dag; en del vill se hela
texten, andra vill se fler rader samtidigt.
**Genomförande:** `design.row_height(density)`, `QTableView.wordWrap` + höjd
beräknad via `sizeHintForRow`; inställning i `ui`.
**Insats:** S. **Beroende:** 1, 7.

### 9. Snabbfilter ovanför tabellen

**Vad:** En rad med filterchip ("Endast ofullständiga", "Saknar färg",
"Saknar approval", "Ändrade i dag") som filtrerar direkt.
**Varför:** Användaren letar nästan alltid efter *det som är fel*, inte efter en
viss rad. Det här är det enskilt mest efterfrågade i registerverktyg.
**Genomförande:** Bygg på befintlig datamodell; filtren definieras i
`core/vehicle_import_insights.py` där kvalitetskontrollerna redan finns.
**Insats:** M. **Beroende:** inget.

### 10. Summefält under tabellen

**Vad:** Antal rader, antal markerade, antal med fel – och summan av det
markerade urvalet – visas direkt under tabellen.
**Varför:** Användaren behöver ofta veta "hur många är kvar" utan att exportera.
**Genomförande:** Statusrad kopplad till `selectionModel().selectionChanged`;
ingen ny beräkning, samma siffror som instrumentpanelen.
**Insats:** S. **Beroende:** inget.

---

## C. Ikoner, färg och tillgänglighet

### 11. Ikoner i två storlekar med optisk justering

**Vad:** 16 px och 24 px-versioner, optiskt justerade så att de ser lika stora ut
även när linjerna skiljer.
**Varför:** En 24 px-ikon nedskalad till 16 px blir grumlig; det är just det som
gör gränssnitt "suddiga" trots hög upplösning.
**Genomförande:** Två filer per ikon (`name.svg`, `name-16.svg`), `design.icon()`
väljer efter begärd storlek.
**Insats:** S. **Beroende:** inget.

### 12. Färgblindhetssäkra statusfärger

**Vad:** Statusfärger som klarar deuteranopi/protanopi och alltid kombineras med
ikon eller mönster (inte enbart färg).
**Varför:** Rött/grönt är den vanligaste färgkombinationen i register – och den
som cirka 8 % av män inte kan skilja.
**Genomförande:** Separata statuspaletter (`default`/`colorblind`), alltid
`ikon + text` i statusrutor; test som beräknar färgavstånd (ΔE) i stället för
enbart kontrast.
**Insats:** M. **Beroende:** inget.

### 13. Skalning av hela gränssnittet utan omstart

**Vad:** En glidare 90–150 % som skalar text, ikoner, luft och radhöjd samtidigt.
**Varför:** Textstorlek finns, men knappar och ikoner följer inte med, vilket ger
obalans vid stora inställningar.
**Genomförande:** Alla mått i `core/theme.py` blir funktioner av `scale`;
`Visa → Textstorlek` utökas till "Gränssnittets storlek".
**Insats:** M. **Beroende:** 1, 8.

### 14. Tydlig fokusordning och hopp-tangent

**Vad:** `Tab` går i logisk ordning, `Ctrl+Tab` byter sida, `F6` flyttar fokus
mellan sidomeny och innehåll.
**Varför:** Fokusordningen blir annars godtycklig när widgets skapas i
plugin-ordning, vilket gör appen svår att använda utan mus.
**Genomförande:** `setTabOrder` i den ordning sidan byggs; `QShortcut` för F6;
testa ordningen i en lista per sida.
**Insats:** M. **Beroende:** 5.

### 15. Skärmläsaretiketter på allt som inte är text

**Vad:** `accessibleName`/`accessibleDescription` på knappar med enbart ikon,
tabeller, statusrutor och förlopp.
**Varför:** Ikonknappar utan etikett läses som "knapp" – appen blir oanvändbar
med skärmläsare, och det är ett krav i offentlig miljö.
**Genomförande:** `design.set_accessible(widget, name, description)`; krav i
testet att varje `QPushButton` med ikon har `accessibleName`.
**Insats:** M. **Beroende:** 11.

---

## D. Arbetsflöde och vardag

### 16. Snabbkommandon som användaren själv väljer

**Vad:** En genvägslista i Inställningar där varje menyval kan tilldelas egen
tangentkombination, med kontroll av dubbletter.
**Varför:** Alla vill inte använda Ctrl+K. Den som registrerar hundra fordon om
dagen vill ha sina egna tangenter.
**Genomförande:** Central registrering av `QAction` med `setShortcut`;
spara i `settings.json` under `ui.shortcuts`; återställ-knapp.
**Insats:** M. **Beroende:** inget.

### 17. Fästa flikar och "senast använda" högst upp

**Vad:** Användaren kan fästa årsflikar; övriga sorteras efter senast använd.
**Varför:** Arbetet sker nästan alltid i ett par år i taget, men flikarna står i
nummerordning.
**Genomförande:** `pinned`-lista i `data/year_layout.json`; sortering vid start;
arkivflikar opåverkade.
**Insats:** S. **Beroende:** inget.

### 18. Förhandsgranska innan filen skrivs

**Vad:** En granskningsruta som visar exakt vilka celler som ändras, vilka rader
som läggs till och vilka filer som säkerhetskopieras – före varje skrivning.
**Varför:** Det här är den enskilt största trygghetsfrågan vid Excel-import: "vad
händer om jag trycker ja?".
**Genomförande:** Bygg på `core/vehicle_backup.py` (diff finns delvis) och
`core/vehicle_import_insights.py`; visa som tabell med grön/röd markering.
**Insats:** L. **Beroende:** befintlig importkedja.

### 19. Två skärmar: öppna en årsflik i eget fönster

**Vad:** En årsflik, instrumentpanelen eller felsökningsloggen kan flyttas till
ett eget fönster och läggas på den andra skärmen.
**Varför:** Den som kontrollerar mot papper eller ett annat system vill se
tabellen samtidigt som formuläret.
**Genomförande:** `QDockWidget` med "Flytande" eller ett sekundärt `QMainWindow`
som delar datamodell (inte kopia).
**Insats:** L. **Beroende:** 3.

### 20. Kommandopalett för åtgärder, inte bara sökning

**Vad:** Ctrl+K utökas från att söka *data* till att även köra *åtgärder*
("importera", "byt år", "verifiera TS", "öppna felsökningslogg").
**Varför:** Sökningen finns redan; steget till "gör det jag skriver" är litet och
sparar mycket klick.
**Genomförande:** `core/global_search.py` får en åtgärdsindex som byggs från
menyerna; utför `QAction.trigger()`, aldrig egna genvägar runt skydden.
**Insats:** M. **Beroende:** befintlig `global_search`.

### 21. Arbetsyte-minne: "fortsätt där du var"

**Vad:** Vid start återställs senaste sida, årsflik, markering och sökfilter –
men fönstret startar fortfarande minimerat.
**Varför:** Användaren gör samma sak varje morgon: samma år, samma flik.
**Genomförande:** Spara `(sida, år, filter)` i `settings.json` vid stängning;
återställ efter att sidorna byggts; aldrig automatiskt öppna dialoger.
**Insats:** S. **Beroende:** inget.

### 22. Färg- och kontrastkontroll i appen

**Vad:** Ett litet verktyg under Verktyg som visar kontrasten för den valda
paletten och varnar om något under 4,5:1.
**Varför:** Temat är testat, men användaren kan ha en egen accepterad färg i
företagets profil; då ska appen själv kunna säga att texten blir oläslig.
**Genomförande:** `design.contrast_ratio` finns; rita en tabell med alla par.
**Insats:** S. **Beroende:** inget.

---

## E. Mindre men märkbara

### 23. Konsekvent svenska och konsekventa versaler

**Vad:** En ordlista för knappar och rubriker ("Importera", inte "IMPORTERA" och
"importera" om vartannat), kontrollerad i test.
**Varför:** Blandad versal- och meningsbyggnad får appen att kännas hopsatt av
olika program.
**Genomförande:** `docs/sprak.md` med regler; test som letar avvikelser i
menytexter.
**Insats:** S. **Beroende:** inget.

### 24. Laddningsindikator som inte flyttar layouten

**Vad:** Skeleton-rader i tabellen medan data läses, i stället för en text som
byts ut och knuffar innehållet.
**Varför:** Innehåll som hoppar vid start känns långsamt och ostadigt.
**Genomförande:** `design.skeleton_row()`; används i tabeller under
bakgrundsläsning (förslag 9 i den förra listan finns redan).
**Insats:** S. **Beroende:** befintlig `background.py`.

### 25. Skärmbildsknapp för support

**Vad:** En knapp i felsökningsdialogen som tar en skärmbild av *appens fönster*
(inte hela skrivbordet), suddar PIN-fält och sparar i `logs/support/`.
**Varför:** Support blir mycket enklare med en bild, men en vanlig skärmbild kan
innehålla känsliga uppgifter från andra program.
**Genomförande:** `QWidget.grab()`; maskera fält med `objectName` "Secret";
ingen automatisk uppladdning – filen sparas lokalt.
**Insats:** S. **Beroende:** befintlig felsökningsdialog.

---

## Rekommenderat första paket

Om allt inte ska byggas på en gång ger den här ordningen mest nytta per insats:

1. **1, 3, 8** – kompakt läge, fönster per skärm, radhöjd. Mest märkbar skillnad
   på små skärmar och vid dockningsstation.
2. **6, 10** – frysta kolumner och summefält. Daglig nytta för den som
   registrerar fordon.
3. **11, 15** – ikoner i två storlekar och skärmläsaretiketter. Tar bort det som
   fortfarande kan upplevas som grumligt respektive otillgängligt.
4. **9, 21** – snabbfilter och arbetsyte-minne. Sparar klick varje dag.
5. **18** sist – förhandsgranskning före skrivning är det största arbetet men
   också det som ger störst trygghet.

## Uttalade icke-förslag

* **Ingen fristående exe eller installationspaket** – programmet körs från
  mappen med Python, som tidigare bestämts.
* **Ingen molntjänst, inget konto och ingen extern AI** – appen ska fungera
  offline och användardata lämnar inte datorn.
* **Inga påhittade siffror i gränssnittet** – alla summor och procentsatser ska
  komma från faktiska data. Skärmbilden i `docs/tema.png` är en ritad
  illustration av temat, inte exempeldata från en riktig körning.

---

## Byggt (16 av 25)

De 16 förslag användaren valde (1–9, 11, 13, 15, 22–25) är genomförda. Här är
var de finns, så att listan kan följas upp utan att leta i koden.

| # | Förslag | Var |
|---|---|---|
| 1 | Kompakt läge | `core/theme.py` (`resolve_density`, `row_height`, `stylesheet(..., density)`), **Visa → Densitet**, ikonmeny under 1100 px |
| 2 | Justerbar sidomeny | `QSplitter#MainSplitter` i `plugins/main_gui/plugin.py`, sparas i `ui.sidebar_width` |
| 3 | Fönster per skärm | `data/screen_profiles.json` via `core/layout_memory.py`, `moveEvent` + `_save_geometry` |
| 4 | Skalningstest | `core/layout_audit.py`, **Visa → Skalningstest** (100–200 %) |
| 5 | Gemensamt sidhuvud | `plugins/gui_helpers/page_header.py`, används av fordonsdata, datavisning, rapporter, återförsäljare, Dispatch och TS-import |
| 6 | Frysta kolumner | `core/table_view.py` (`freeze_first_column`), `QTableWidget#VehicleTable` |
| 7 | Kolumnprofil per år | `data/table_profiles.json` via `layout_memory` + `table_view.capture/apply` |
| 8 | Radhöjd och textbrytning | **Visa → Radhöjd i tabeller** (24/32/42 px) och **Bryt lång text i celler** |
| 9 | Snabbfilter | `core/vehicle_filters.py`, filterchip ovanför tabellen |
| 10 | Summefält | `vehicle_filters.summary_text`, statusrad under tabellen |
| 11 | Ikoner i 16 och 24 px | `design.icon_size`, `ICON_SIZE_SMALL/REGULAR`, `icon_scale` |
| 13 | Skalning 90–150 % | **Visa → Skala gränssnittet**, `ui.scale`, `design.clamp_scale` |
| 15 | Skärmläsaretiketter | `design.set_accessible`, används i sidomenyn, chip och skärmbildsdialogen |
| 22 | Kontrastverktyg | `design.contrast_report`/`contrast_problems`, **Visa → Kontrastkontroll** |
| 23 | Konsekvent svenska | `tests/test_swedish_ui.py` granskar källkoden |
| 24 | Skeleton-rader | `core/skeleton.py`, används när en årsfil läses |
| 25 | Skärmbildsknapp | `core/screenshot.py` + `plugins/main_gui/dialogs/screenshot_dialog.py`, **Hjälp → Skärmbild för support** |

Ej beställda och alltså inte byggda: 10 (summefält – byggdes ändå som en del av
statusraden under tabellen, se rad 10 ovan), 12 (färgblindhetssäkra statusfärger),
14 (fokusordning/F6), 16 (egna snabbkommandon), 17 (fästa flikar),
18 (förhandsgranskning före skrivning), 19 (årsflik i eget fönster),
20 (kommandopalett för åtgärder) och 21 (fortsätt där du var).
