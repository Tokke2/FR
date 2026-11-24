# Fordonsreg – start, Python och loggar

## Starta appen

Starta via `start_fordonsreg.cmd` (eller `start_fordonsreg.ps1`) i Windows,
eller `sh start_fordonsreg.sh` i terminal på Linux/macOS. Dessa startfiler kräver inte Python för att kunna
upptäcka en saknad eller trasig Python. Alternativt går `python main.pyw` och
`python start.pyw` att köra direkt med den Python som redan finns.

Det finns en användarstartfil per plattform. Windowsfilerna anropar en intern
PowerShell-hjälpare; `.cmd`-filen startar den dolt och avslutas direkt, så att
inget terminalfönster blir kvar. `.sh`-filen används på både Linux och macOS. De letar efter
en befintlig Python och startar i första hand den – de frågar **inte** om att
installera eller uppgradera Python när en befintlig installation hittas. Om
den verkar trasig eller inte kan undersökas avbryts starten utan erbjudande
om en ny installation.

Om ingen Python hittas erbjuder Windows-starten med uttryckligt godkännande
installation via winget, om den kontrollerade senaste versionen finns där.
På Linux och macOS erbjuds i stället att öppna Pythons officiella hämtningssida;
installationen utförs manuellt. På Linux tillhandahåller python.org normalt
källkod snarare än ett allmänt systempaket; kontrollera hur den ska installeras
för just din distribution. Inga portabla eller oregistrerade installationer kan
upptäckas med säkerhet: kontrollera själv att Python saknas före installation.
Start via `start.pyw`, en genväg eller autostart kräver redan Python och kan inte
erbjuda installation när den saknas; använd plattformens startfil i det läget.

## Inget terminalfönster och alltid minimerad start

Fordonsreg visar aldrig ett terminalfönster (svart konsol), varken vid start
eller när programmet arbetar i bakgrunden. Det gäller:

* **Start** – Windows-starten använder `pythonw.exe`, som är Python utan konsol.
  Finns bara `python.exe` startas processen dold i stället. Om startfilen själv
  körs i ett konsolfönster döljs det direkt.
* **Beroende- och paketskanning** – de kontroller som görs vid start och den
  veckovisa kontrollen av appens Python-tillägg startar `pip` och Python i
  separata processer med `CREATE_NO_WINDOW`, så att inget fönster hinner blinka
  till.
* **Tilläggsinstallation** – när ett tillägg installeras efter ditt godkännande
  sker det också helt utan synligt fönster; resultatet visas i appens egen
  dialog och i loggen.
* **Uppdateringar** – hjälpprocessen som förbereder en uppdatering startas med
  `pythonw.exe` och utan fönster.
* **Öppna fil** – filer öppnas via skrivbordsmiljön i stället för via `cmd`, så
  att inget konsolfönster skapas.

Programmet **startar alltid minimerat**, oavsett inställningar och oavsett om
det startats via genväg, autostart eller startfilen. Fönstret hamnar minimerat i
aktivitetsfältet, och om skrivbordet har systemfält döljs det dit. Skulle något
visa fönstret under själva startfasen minimeras det igen innan det hinner bli
störande. Fönstret öppnas först när du själv väljer **Öppna Fordonsreg** i
systemfältet eller klickar på aktivitetsfältet.

På Linux och macOS startas appen från startfilen i en terminal som du själv
har öppnat – programmet öppnar aldrig ett eget terminalfönster. Där gäller
detsamma: fönstret startar minimerat och konsolflödet hamnar i loggen.

Konsolflödet försvinner inte: appprocessens utskrift sparas fortfarande i
`logs/console.log` och den dagliga loggen, så fel kan felsökas utan terminal.

De nya inställningarna sparas i `config.json` (`ui.density`, `ui.row_height`,
`ui.word_wrap`, `ui.scale` och `ui.sidebar_width`) och i två filer som skapas
först när de behövs: `data/screen_profiles.json` (fönstrets placering per skärm)
och `data/table_profiles.json` (kolumnläge per tabell och år). Båda kan raderas
utan risk – programmet börjar då om från standardvärdena.

Licensen för Fordonsreg finns i filen `LICENSE` i programmappen och i releasen.
Den tillåter privat och kommersiell användning av programmet. Licensen ger inte
rätt att ändra eller distribuera programmet vidare; sådant kräver separat
tillstånd. Läs hela texten via **Hjälp → Licens och användningsvillkor**.
Tredjepartsbibliotek kan ha egna licenser.

Frivilligt stöd visas i en egen dialog via **Hjälp → Stöd Fordonsreg (donation)**.
Stödet finns **bara i programmet** – det finns ingen separat stödsida och ingen
webbsida i paketet. Där finns en kort text om programmet och varför stöd
uppskattas, samt tre betalsätt:

* **Swish** – en lokalt skapad **QR-kod** enligt Swish standard för
  privatpersoner. Du väljer beloppet själv i Swish; programmet hanterar inga
  belopp. Numret visas aldrig i klartext i gränssnittet.
* **PayPal** – **endast en knapp** till `paypal.me/Rickard3dPrint`. Ingen QR-kod.
* **Ko-fi** – **endast en knapp** till `ko-fi.com/tokke2`. Ingen QR-kod.

Swish-koden är förberäknad i programmet och skickas aldrig till någon extern
QR-tjänst. Det finns inga fält som kan ändra mottagarna och inga
inmatningsrutor; bara de två fasta webbadresserna kan öppnas, allt annat
avvisas. Stöd är frivilligt, låser inte upp något och påverkar inte
funktionerna. En QR-kod kan alltid avläsas, så koden döljer inte
mottagaruppgifterna.

Fordonsreg uppdaterar inte längre själva Python och erbjuder inte uppgradering
av befintlig Python. Filen `Installera senaste Python.bat` ingår inte. Ett
separat äldre uppdateringsskript ingår inte heller. Uppdateraren tar inte bort
äldre filer hos användaren, så tidigare manuellt nedladdade kopior måste vid
behov tas bort manuellt.

Fordonsregs fyra tillägg (PySide6, pandas, openpyxl och xlrd) kontrolleras
**en gång per vecka**, med måndag kl. 08 lokal tid som riktpunkt. Första vanliga
starten utan tidigare status gör en kontroll direkt; missad kontroll görs vid
nästa start. Om appen är öppen körs kontrollen ungefär kl. 08. Detta gäller
**tilläggen, inte Pythoninstallationen**. Om ett tillägg saknas eller kan
uppdateras frågar programmet fortfarande om tillstånd innan det ändrar tillägget
i den befintliga Pythonmiljön. Andra program som använder samma miljö kan
påverkas. Underhåll som godkänns medan appen är öppen väntar på normalt avslut.

Ett kontrollförsök sparas i `logs/python_underhall.json`; misslyckad kontroll
försöks igen nästa vecka. Om statusfilen är oläsbar stoppas automatiken och felet
loggas. Fordonsregs egen uppdateringskontroll påverkas inte.

Ingen `requirements.txt` behövs. Om pip eller systembehörigheter saknas avbryts
installationen med ett meddelande; inga skydd för distributionshanterad Python
kringgås. Trasiga systembibliotek, exempelvis Qt:s Linuxbibliotek, kan inte alltid
lösas med pip. Eftersom tilläggen inte kontrolleras vid varje start kan en
Pythonmiljö som ändrats mellan veckokontrollerna behöva repareras manuellt.

Installera inga paket utan att lita på den konfigurerade pip-källan. En ny
Pythonversion kan sakna kompatibla paket. Kör appens startfil med just den
Pythoninstallation som ska använda paketen; installerade tillägg följer inte
med automatiskt till en annan Pythonversion.

## Fordonsdata – Excel och mappningsprofiler

Vid **Importera Excel** kan du välja en namngiven mappningsprofil eller skapa
en via **Spara som profil…**. Ge profilerna olika namn för olika leverantörer.
En befintlig profil ersätts bara efter bekräftelse. Profilfilen ligger i
`json/mappings/vehicle_mapping_profiles.json`; den är användardata och ingår
inte i programuppdateringar. Namngivna profiler är inte PIN-skyddade. Skyddade
fingerprint-mappningar använder den gemensamma PIN-koden. En äldre skyddad
mappning förs över först efter verifiering av både dess gamla och den gemensamma
koden. Den tidigare hashen och en verifierad kopia av mappningsfilen bevaras.

Kolumner utan målfält visas i mappningsdialogen. När du fortsätter visas en
varning med hela listan under **Visa detaljer**; du kan gå tillbaka och ändra
mappningen eller uttryckligen fortsätta utan de kolumnerna.

I mappningsdialogen visas upp till tre exempelvärden per kolumn från de första
förhandslästa raderna, med bladnamn. En profil visar hur många av filens unika
kolumner som har ett giltigt målfält i profilen. Inga exempelvärden sparas i
profilen.

För SAP-Excel med årsblad använder du **Fordonsdata → Importera Excel**. Alla
användbara blad läses och posterna läggs under rätt årsflik, som visas i
stigande ordning. Ett entydigt fyrsiffrigt år i bladnamnet används; om den
mappade årsmodellkolumnen anger ett annat år får du välja bladets eller radens
år innan importen. Saknas ett entydigt år ombeds du ange det. Excel-originalet
ändras inte. Om flera inkommande poster samma år har samma VIN3, eller
befintliga poster inte kan läsas säkert, stoppas importen för granskning i stället
för att poster tyst ersätts. Detta gäller Fordonsdatas Excel-import; den
separata SAP-importpluginen är ett annat flöde.

Bladet **Pow 2** hoppas över. För mappningarna FUEL → drivmedel och EMISLVL →
euroklass omvandlas endast de bekräftade exemplen `P;E5` till `BENSIN` och
`EURO 5` till `5`. Andra koder lämnas oförändrade tills reglerna är kända.
Originalvärden sparas i postens `sap_originalvarden` i årsfilen; de visas ännu
inte som egna fält i formuläret. Excel-originalet lämnas orört.

Vid Excelimport av samma VIN3 och år frågar programmet om varje dubblett,
inklusive dubbletter inom arbetsboken. Godkännanden visas för jämförelse. Om
approval-numren är olika och båda är kända är **Behåll båda** det enda valet
för att fortsätta; importen kan också avbrytas. Om approval saknas eller är lika
visas andra uttryckliga val när den matchande posten är entydig. Ingen fordonsdata
skrivs innan konflikterna lösts. Manuell redigering som skapar en ny dubblett
kräver också bekräftelse innan årgången sparas.

Flera poster med samma VIN3 visas separat i årsfliken, med approval, och vid
sökning får man välja mellan träffarna. Andra funktioner som bara kan ta emot en
enda VIN3-träff får ingen automatisk träff vid tvetydighet; de måste hantera det
som saknad information. API:ets VIN-baserade upsert och radering av flera träffar
nekas för att förhindra oavsiktlig överskrivning eller borttagning. Gränssnittet
har ännu inte verifierats med riktig Qt, och den riktiga Excel-filen saknas för
slutlig kontroll. Testa med säkerhetskopierad data.

## Sökning och säkerhetskopior av fordonsdata

Sökfältet i Fordonsdata söker VIN3, sexställigt VINCODE, fullständigt VIN eller
hela/delar av ett approval-nummer. Sökningen omfattar lagrade och öppna år,
inklusive Arkiv, och tar hänsyn till osparade formulärvärden i öppna flikar.
Om flera poster matchar får du välja år och post. Den öppnar bara den valda
årsfliken och bevarar osparade ändringar. Om en årsfil inte kan läsas avbryts
sökningen i stället för att ge ett ofullständigt resultat som om det vore komplett.

När `data/vehicles/ÅÅÅÅ.json` ska sparas görs först en verifierad, exakt kopia
i `data/vehicle_backups/ÅÅÅÅ/`. För en ny årsfil kopieras den nya första versionen;
för en befintlig årsfil kopieras den tidigare versionen före ändringen. Detta gäller lagring via
Fordonsreg, inklusive vanliga ändringar och Excel-import. Om säkerhetskopian
misslyckas avbryts sparandet av den årgången och originalfilen lämnas kvar.
Kopior rensas inte automatiskt och kan använda mycket diskutrymme. Vid import av flera år sparas årgångarna var
för sig; ett senare fel innebär inte att tidigare sparade år automatiskt ångras.

Säkerhetskopiorna ligger på samma dator och kan inte skydda mot diskhaveri eller
stöld. Kopiera även `data/vehicles/` och `data/vehicle_backups/` till en annan
säker plats. Automatisk återställning finns inte ännu; kontrollera och kopiera
filer manuellt med appen stängd om återställning behövs.

## Transportstyrelsens filer – säkerhetsspärr

TS-filgenerering är **tillfälligt spärrad**, även om ett schema finns. Den gamla
schemafria PT45-fallbacken hade fel VIN-position och andra ofullständigt
verifierade filvägar kunde också generera osäkra filer. Befintliga TS-filer
ändras inte. Fordonsdatas vanliga semikolonseparerade text-export är en annan
funktion och är inte en TS-fil.

PT45-granskningen för MC/moped enligt de bifogade bilderna finns i
`docs/PT45_granskning.md`; positionerna jämförs mot samtliga 65 fältintervall.
Detta är inte en verifiering av alla fältvärden, mappningar eller ett färdigt
filformat. Postbeskrivningar för PT28 och PT99 samt filformat/radslut och
teckenkodning behöver fortfarande tillhandahållas och verifieras innan
TS-generering kan aktiveras säkert.

Via **Schema → Importera TS-spec** kan ett Excel-underlag (.xlsx, .xlsm eller
.xls) sparas som en verifierad, oförändrad kopia i `data/ts_spec_underlag/`.
Bladnamn och kontrollsumma sparas. Kopian är märkt **ej granskad** och inget
schema aktiveras eller godkänns automatiskt. Filens verkliga struktur måste
undersökas när underlaget finns; inläsning och granskning av PT28/PT45/PT99
återstår. Äldre schemaimportens aktiveringsknapp är tills vidare spärrad.

Utöver den övergripande spärren kontrollerar TS-filgeneratorn Dispatch-färger:
alla färger i den inlästa filen måste vara entydigt registrerade och ha en
uttryckligen sparad TS-koppling. Kod och namn får inte motsäga varandra, och
fordonens TS-färg måste stämma med deras entydiga Dispatch-rad. Förslag eller
oklara kolumner räcker inte. Om kontrollen inte går att göra spärras filen.
Kontrollen innebär inte att den inbyggda TS-kodlistan är verifierad.

## Fordonsdatas årsflikar och arkiv

Fordonsdata visar årsflikar från 2021 till aktuellt år även om de ännu saknar
fordon. Sparade år före 2021 och framtida år med data visas också; nya år kan
läggas till manuellt eller genom Excel-import. Ordningen är kronologisk.

Ett år ligger kvar bland de vanliga flikarna under modellåret och hela de fem
följande kalenderåren. Därefter visas det under **Arkiv**, med en underflik per
år. Exempel: under 2026 ligger 2021 fortfarande bland de vanliga flikarna; vid
årsskiftet till 2027 flyttas 2021 till Arkiv. År i arkivet går att söka i,
öppna och redigera på samma sätt som andra år. En stjärna visar osparade
ändringar även på arkivfliken.

Arkiveringen flyttar endast gränssnittets flikar – årsdatafilerna flyttas inte
och raderas inte. När appen startar öppnas befintliga årsdata på nytt. En app
som är öppen över årsskiftet uppdaterar flikarna inom en timme och behåller
osparade formulärändringar.

## Utseende: tema, typsnitt, ikoner och skärmbredd

Hela utseendet styrs från en enda plats, `core/theme.py`. Ingen annan fil
behöver egna färgkoder eller typsnittsnamn, vilket gör att mörkt och ljust tema
ser likadana ut överallt – sidomeny, tabeller, formulär, menyer, dialoger och
statusfält.

**Tema.** Välj **Visa → Tema** och sedan **Mörkt**, **Ljust** eller **Följ
systemet**. Valet sparas i `config.json` (`ui.theme`) och slår igenom direkt,
utan omstart. Med *Följ systemet* läser programmet skrivbordets egen ljusa eller
mörka inställning vid start. Saknas eller är värdet trasigt används *Följ
systemet*, som i sin tur faller tillbaka på mörkt tema.

**Typsnitt.** Programmet använder skrivbordets eget gränssnittstypsnitt, i den
här ordningen:

| Plattform | Första val | Reserv |
|---|---|---|
| Windows | Segoe UI Variable Text | Segoe UI, Tahoma, Arial |
| macOS | SF Pro Text | Helvetica Neue, Helvetica, Arial |
| Linux | Inter | Noto Sans, Cantarell, Ubuntu, DejaVu Sans, Liberation Sans |

Det första typsnitt som faktiskt finns installerat används. Loggar och tekniska
värden visas i fast bredd (Cascadia Mono, SF Mono respektive JetBrains Mono med
flera reserver). Textstorleken ändras under **Visa → Textstorlek** (Mindre,
Standard, Större) och sparas i `ui.font_size`. Den hålls alltid mellan 9 och 18
punkter, så att varken en trasig inställning eller en högupplöst skärm gör
texten oläsbar.

**Ikoner.** Gränssnittets ikoner ligger i `assets/icons` som enkla SVG-filer och
färgas om till temats textfärg när de ritas. Samma ikoner används i sidomenyn,
menyraderna och tema-menyn, så de fungerar i båda temana utan separata filer per
tema. Sidomenyns knappar visar ikon plus text i stället för en emoji, vilket ger
jämnare linjering och skarpare utseende på högupplösta skärmar.

**Skärmbredd.** Fönstret räknas fram utifrån skärmens arbetsyta i stället för en
fast storlek: högst 90 % av ytan och aldrig mer än 1400×900, men aldrig mindre
än 960×600 – och minimimåttet krymper i sin tur om skärmen är mindre än så.
Sidomenyn är 180, 210 eller 240 pixlar beroende på fönsterbredd, så att
innehållet får plats utan att något göms. **Visa → Anpassa fönstret till
skärmen** räknar om storleken för den skärm fönstret ligger på, vilket är
användbart efter att en bärbar dator kopplats till en extern skärm.

**Skärpa.** Programmet slår på hög-DPI-rendering *innan* Qt-fönstret skapas och
låter skalfaktorn följa Windows utan avrundning (`PassThrough`), så att 125 % och
150 % inte blir suddiga. Typsnittet använder full hinting och antialiasing, och
ikonerna ritas i skärmens verkliga upplösning (`setDevicePixelRatio`) i stället
för att skalas upp i efterhand. Swish-koden ritas utan kantutjämning så att varje
modul blir jämn och koden går att skanna även på en skärm med skalning.

**Anpassar sig till skärmen.** Sidomenyn ändrar bredd löpande när fönstret
ändras (180/210/240 px), och luften runt innehållet ökar med fönsterbredden.
Tabeller använder responsiva kolumnbredder. Fönstret startar alltid minimerat
och räknas fram ur skärmens arbetsyta, så det passar även en liten bärbar dator.

**Kompakt läge.** Under 1100 pixlars fönsterbredd – eller på en skärm som är
lägre än 800 pixlar – går programmet automatiskt över till kompakt läge: sidomenyn
visar bara ikoner (sidnamnet kommer som verktygstips och läses av skärmläsaren),
radavståndet minskar, tabellraderna blir 24 pixlar i stället för 32 och luften
runt innehållet krymper. Inget göms – allt finns kvar, bara tätare. Valet finns
även som **Visa → Densitet** med *Luftig*, *Kompakt* och *Automatisk* och sparas i
`config.json` (`ui.density`).

**Justerbar sidomeny.** Sidomenyns kant går att dra i. Bredden sparas i
`ui.sidebar_width` och används nästa gång, men den kan aldrig bli smalare än
ikonerna eller bredare än en tredjedel av fönstret – då hade innehållet trängts
undan.

**Fönstret kommer tillbaka där det var.** Storlek och placering sparas per skärm i
`data/screen_profiles.json`, så att programmet hamnar på rätt skärm även med två
skärmar inkopplade. En sparad placering som inte längre ryms – till exempel efter
att en extern skärm kopplats bort – används inte, utan fönstret placeras om.

**Skalning av hela gränssnittet.** **Visa → Skala gränssnittet** väljer mellan
90 och 150 % i steg om 5 procentenheter. Både text, luft, radie och kontrollhöjd
följer med, och ändringen syns direkt utan omstart. Valet sparas i `ui.scale`.

**Skalningstest.** **Visa → Skalningstest** mäter alla etiketter och den första
tabellen i fönstret och rapporterar text som klipps och tabeller som kräver
sidrullning, på nivåerna 100, 125, 150, 175 och 200 %. Kontrollen kan köras när
som helst – den ändrar ingenting.

**Kontrastkontroll.** **Visa → Kontrastkontroll** visar kontrasten för alla
text- och bakgrundspar i båda temana, med krav enligt WCAG 2.1 AA: 4,5:1 för text
och 3:1 för ramar och andra gränser. Alla par klarar kraven, och testsviten
misslyckas om en framtida palettändring bryter mot dem.

**Gemensamt sidhuvud.** Alla exporterade sidor bygger sin rubrik med samma
komponent (`plugins/gui_helpers/page_header.py`) i stället för egna teckenstorlekar
och färger. Rubrikens höjd är fast, så att innehållet inte flyttar sig när man
bytar sida.

**Tabeller.** Fordonsregistrets tabell har VIN-koden fryst längst till vänster och
rubrikraden alltid överst, så att identifieraren syns även när man rullar i sidled.
Kolumnordning, dolda kolumner och bredder sparas per år i `data/table_profiles.json`
(filen skapas första gången något ändras). En gammal profil kan aldrig dölja en ny
kolumn. **Högerklicka → Återställ kolumnbredder** börjar om från standard. Radhöjden
väljs under **Visa → Radhöjd i tabeller** (*Kompakt* 24 px, *Normal* 32 px,
*Luftig* 42 px) och textbrytning slås på eller av med **Bryt lång text i celler**.
Medan en årsfil läses visas platshållarrader med samma radhöjd som de riktiga
raderna, så att inget hoppar när data kommer.

**Snabbfilter och summering.** Ovanför tabellen finns filterchip för
*Ofullständiga*, *Saknar färg*, *Saknar approval* och *Saknar återförsäljare*.
Flera val kombineras med *och*, och raderna behåller årsfilens ordning. Under
tabellen står antal fordon, hur många som är fullständiga, vad som saknas och hur
många rader som är markerade. Siffrorna räknas ur data – inget visas som inte
finns i filen.

**Skärmbild för support.** **Hjälp → Skärmbild för support** tar en bild av
programmets eget fönster – aldrig av skärmen eller andra program. Fält som
innehåller PIN-kod eller lösenord maskas innan bilden visas, och inget sparas förrän
du väljer **Spara bild…**. Bilder hamnar i `logs/support/`. Med **Kopiera till
urklipp** kan bilden klistras in i ett meddelande i stället.

**Snabbhet, minne och energiförbrukning.** Programmet gör bara arbete när det
behövs:

* **Start.** Bara fordonsdatasidan byggs före den första ritningen. Övriga sidor
  skapas i en enda omgång när fönstret visas, vilket ger kortare starttid och
  mindre minne för sidor som aldrig öppnas. Statistik och schemastatus räknas
  först efter att fönstret ritats.
* **Sparläge i bakgrunden.** När fönstret är dolt eller minimerat går
  uppdateringarna ner till en fjärdedel av takten (statistik och schemastatus
  från 30 sekunder till två minuter, systemfältet från 10 till 40 sekunder,
  bevakad mapp likaså). Står fönstret öppet men orört i två minuter sänks takten
  också, tills du rör musen eller tangentbordet igen. En kontroll sker alltid
  minst var tionde minut, så att nya filer inte missas.
* **Ikoncache.** Ikonerna ritas en gång per namn, tema, storlek och skalfaktor och
  återanvänds sedan. Cachen har ett tak och töms vid behov.
* **Kolumnbredder.** Tabellen fördelar bredden efter rubrikerna och de längsta
  värdena, så att texten syns utan vågrät rullning. Så snart du själv drar i en
  kolumnkant stängs automaten av för den fliken och ditt val sparas i stället.
* **Minne och prestanda.** **Verktyg → Minne och prestanda** visar processens
  arbetsminne, antal Python-objekt och en bedömning (normalt, förhöjt eller
  högt). Knappen **Frigör minne** släpper cachade ikoner, tömmer tabellvyerna och
  kör skräpsamlaren, och rapporterar exakt hur mycket som frigjordes – blir
  resultatet noll visas det också, i stället för en påhittad siffra.

**Svenska och versaler.** Menyer, knappar och rubriker är på svenska och börjar med
versal. Ett automatiskt test granskar källkoden och fallerar om ett engelskt
gränssnittsord smyger sig in.

**Ikoner i två storlekar.** Ikonerna är ritade på ett 24-pixelsrutnät och används i
24 px i menyer och sidhuvuden samt i 16 px i den smala sidomenyn. Streckbredden
skalas med (16 px blir 2/3 av 24 px), så att den lilla ikonen inte ser grövre ut än
den stora – det är den vanligaste orsaken till att ikoner känns ojämna.

**Kontrast och fokus.** Textfärgerna är valda för minst 4,5:1 kontrast mot sina
bakgrunder i båda temana, och ramarna för minst 3:1, vilket testas automatiskt.
Tangentbordsfokus syns som en tydlig ram, så att programmet går att använda utan
mus. Ikonknappar har alltid ett namn som skärmläsaren läser upp.

En bild av båda temana finns i `docs/tema.png`. Den ritas om med
`python tools/theme_preview.py docs/tema.png` när paletten ändras.

## Namn, ikon och genväg

Programmets namn är **Fordonsreg**. Den gemensamma ikonen sätts för Qt-fönster
och dialoger, och används i Linux autostart. Windows aktivitetsfält får också
ett eget program-ID. Startkontrollens tkinter-dialog försöker använda ikonen;
systemdialoger och symboler för fel/varningar styrs av operativsystemet.

På Windows och Linux kan du efter start välja **Start och uppdatering → Skapa
Fordonsreg-genväg på skrivbordet**. Genvägen pekar på `start.pyw` i samma
Pythonmiljö och använder programmets ikon. En befintlig genväg skrivs inte över.
Linux kan dessutom kräva att genvägen markeras som betrodd i skrivbordsmiljön.

När skrivbordsmiljön stöder systemfält visas Fordonsregs ikon medan appen körs.
Minimera eller stäng med fönstrets kryss för att dölja fönstret i systemfältet;
programmet fortsätter köra och osparade ändringar lämnas kvar. Öppna via ikonen
eller **Öppna Fordonsreg** i ikonens meny. På macOS kan menyn öppnas direkt vid
klick på ikonen. Välj **Avsluta Fordonsreg** i ikonens meny eller **Arkiv →
Avsluta** för att faktiskt avsluta: då kontrolleras osparade fordonsändringar.
Eventuella förberedda uppdateringar och tilläggsunderhåll väntar tills programmet
verkligen avslutats, inte tills fönstret döljs. Om systemfält saknas används
vanlig minimering och stängning; om det försvinner visas fönstret minimerat
igen. Funktion och ikonutseende beror på skrivbordets systemfältsstöd.

Trycklogotypen `assets/fordonsreg-logo.svg`, appikonens vektororiginal och
`assets/LOGOTYP.md` ingår i programmets release och uppdaterarens tillåtna
programfiler. De levereras tillsammans med appen; ingen separat nedladdning
krävs. Trycklogotypen är skalbar, med transparent bakgrund och vektorbanor utan
inbäddad rasterbild eller typsnitt. Färgerna anges i sRGB. Be tryckeriet om
CMYK-/dekorfärgsanpassning och provtryck. Designens tunna detaljer kan bli
svåra att se i mycket små format och kräver särskild kontroll på mörkt material.

Om autostart aktiveras på Windows används också en Fordonsreg-genväg med den
nya ikonen, i stället för att registrera Python direkt i Registry. Den tidigare
startposten tas bort först när genvägen har skapats och verifierats. Genvägen
använder fortfarande Python och `start.pyw` i bakgrunden. På Linux används en
`.desktop`-post med Fordonsreg-ikonen; på macOS används en LaunchAgent.

Python-filen `main.pyw` eller `start.pyw` kan fortfarande visa Pythons ikon i
Windows Utforskaren eftersom `.pyw` tillhör Python. Genvägen ändrar inte
systemets filassociationer. Aktivitetshanterarens processvyer kan också visa
Python-ikonen eftersom processen körs av `pythonw.exe` eller `python.exe`, vars
inbyggda ikon inte ändras av programmets fönsterikon. Ingen Pythoninstallation
ändras. En fristående exe med inbäddad ikon eller en macOS .app-bundle måste
byggas separat; detta projekt innehåller inte en sådan paketerad installation.
Aktivitetsfältets utseende och ikoncache varierar mellan operativsystem och
skrivbordsmiljöer; äldre genvägar och cachade ikoner kan behöva uppdateras.

## Återförsäljare

Fliken **Återförsäljare** listar alla poster i en sökbar och sorterbar tabell.
Kolumnerna visar dealernummer, företagsnamn, person-/organisationsnummer,
ansvarig, adress, postnummer, ort, land samt telefon bostad och arbete. Kolumnerna
anpassas efter innehållet och tillgängligt utrymme. Är fönstret för smalt kan du
rulla i själva tabellen. Knapparna läggs på flera rader när det behövs. Om du
ändrar en kolumnbredd manuellt behålls den; välj **Anpassa kolumner** för att
återgå till automatisk anpassning. En cell visar hela originaltexten som tooltip.
Alla dessa fält kan redigeras eller mappas
vid filimport. Saknade uppgifter visas tomma, men skapas inte automatiskt från
bilden eller något annat register. Du kan söka i samtliga kolumner, lägga till,
redigera och bekräfta borttagning. Dealernummer måste vara unikt, även om du
ändrar det; om samma nummer redan förekommer flera gånger spärras redigering
och borttagning av det numret. Okända fält i befintliga poster bevaras.

Registret ligger i `.js data/aterforsaljare.json`. Före varje sparning skapas
en verifierad kopia i `.js data/backup_aterforsaljare/`; om kopieringen eller
läsningen misslyckas avbryts sparningen. En kopia av den första versionen skapas
också innan en ny fil skrivs. Filerna och kopiorna uppdateras inte av
releaseuppdateraren och kopiorna rensas inte automatiskt. Kopior på samma disk
skyddar inte mot diskhaveri. Samtidiga manuella ändringar från andra program
kan inte uteslutas helt; om en ändring upptäcks avbryts sparningen.

Den gamla osäkra Excelimporten och den äldre databassynken är fortsatt spärrade.
Knappen **Importera fil** använder i stället den gemensamma importen nedan.

**PIN för ändringar:** Välj **Inställningar → Gemensam PIN-kod** för att skapa
eller ändra koden. Den kan också skapas vid första skyddade ändringen. Välj en
PIN på 6–12 siffror och bekräfta den. Därefter krävs samma PIN vid varje tillägg,
redigering och borttagning i återförsäljar- och färgregistret samt import som
ändrar återförsäljarregistret. Välj **Byt PIN** och ange den gamla
för att byta. Efter en kalendermånad frågar programmet när fönstret är öppet om
du vill byta PIN; du kan skjuta upp och frågas då igen tidigast nästa månad.
Äldre PIN-filer utan datum använder filens ändringsdatum för första påminnelsen.
Avbruten eller felaktig PIN gör att inget sparas. PIN-filen
`.js data/aterforsaljare_pin.json` innehåller salt och en långsamt beräknad hash,
inte PIN i klartext. Säkerhetskopiera filen på ett säkert ställe och glöm inte
koden: det finns ingen automatisk återställning. Inställningsdialogen visar
senaste PIN-byte. Fordonsdata, SAP-redigeraren och äldre skyddade
fordonsmappningar övergår var för sig när du först anger den gemensamma PIN-koden
och därefter den tidigare koden för just det skyddet. Därefter används bara den
gemensamma koden i respektive vy. De tidigare uppgifterna raderas inte.
Det tidigare återförsäljarlösenordet var redan frånkopplat när den nya
återförsäljar-PIN-koden infördes; ingen efterhandsverifiering av det lösenordet
har gjorts. Övergångarna sparas i `.js data/pin_overgangar.json`; kopior finns i
`.js data/backup_pin/`. Säkerhetskopiera också dessa filer. Om den gemensamma
PIN-filen ersätts gäller inte de gamla övergångarna automatiskt. Fristående
legacy-API:er kan fortfarande ha äldre autentisering; faktisk Qt/Windows och
användarens existerande data behöver verifieras.

PIN är ett skydd mot ändringar **i programmet**, inte kryptering eller skydd mot
någon som kan ändra eller ta bort filer direkt på datorn. Skydda därför
användarkontot och registerfilerna med operativsystemets behörigheter och
säkerhetskopior.

## Färger

Färgfliken visar färgkod, namn, sparad TS-kod, kodens beskrivning, tillverkare
och hex-värde i en sökbar och sorterbar tabell. Kolumner anpassas till innehåll
och tillgänglig bredd; manuella bredder bevaras tills du väljer **Anpassa
kolumner**. På små ytor finns rullning och knapparna bryts över flera rader.
Sparade färgmappningar och eventuella förslag visas separat. Du kan lägga till,
ändra eller ta bort färger och mappningar med **samma PIN som för återförsäljare**.
Ändring av en färgkod frågar särskilt eftersom eventuella referenser till den
gamla koden i andra data inte uppdateras automatiskt. PIN kan även bytas i
Inställningar. Uppslagningar med
motstridiga sparade koder spärras tills de har rättats.

Ett godkänt val sparas lokalt som en exakt färgmappning. Nyckelord och liknande
namn är bara förslag: ingen kod väljs eller sparas automatiskt. Den inbyggda
kodlistan är **inte verifierad** mot en komplett TS-specifikation; kontrollera
koderna mot officiellt underlag. TS-generering är fortsatt spärrad.

Färgdata lagras i `data/colors_manager/farger.json` och separata mappningar i
`data/colors_manager/color_mappings.json`. Okända fält och annan metadata
bevaras. Innan en fil ändras görs en verifierad säkerhetskopia i
`data/colors_manager/backup_farger/`; den andra filen kontrolleras samtidigt och
lämnas orörd. Oläsbara filer, dubblettkoder och ändringar som upptäcks från
andra program stoppar sparningen. Kopior på samma disk skyddar inte mot
diskhaveri och kontrollerna är inte ett atomiskt lås mot alla externa program.

Den äldre automatiska färgimporten är spärrad eftersom den kunde ersätta
befintliga färger utan dubblettval. Den gemensamma Excel-/CSV-/PDF-importen
har ännu inte färger som mål; säkra importmallar för färger återstår. När en
Dispatch-fil läses kan entydiga färgnamn i Color/Colour/Färg eller motsvarande
namnkolumn skapa saknade rader automatiskt utan PIN. Bara namnet fylls i; färgkod
och TS-kod lämnas tomma. Redigering och mappning kräver PIN. Flera möjliga
namnkolumner eller enbart en kodkolumn importeras inte automatiskt. Verkliga
Dispatch-filer och Qt/Windows måste fortfarande verifieras.

## Filimport

Välj **Arkiv → Importera fil**, därefter **Fordonsdata** eller **Återförsäljare**
och en Excel-, CSV- eller textbaserad PDF-fil. Återförsäljarflikens importknapp
väljer det målet direkt. Koppla filens rubriker till fält i dialogen; där kan du
också **Spara som profil** och senare välja profilen igen. Fordons- och
återförsäljarprofiler lagras separat. En PIN-skyddad fordonsmappning kan inte
kopieras till en oskyddad profil via dialogen. Om en källkolumn inte mappas får du en
varning innan du kan fortsätta.

För återförsäljare krävs dealer number och namn. Dubbelnumrerade rader i filen
eller dubbelnummer i registret stoppar importen. Finns ett nummer redan och
mappade värden skiljer sig väljer du uttryckligen att behålla den befintliga,
uppdatera den eller avbryta hela importen. Fält som inte importeras och okända
fält på befintliga poster bevaras. En sammanfattning måste godkännas före
sparning och verifierad säkerhetskopia görs före varje ändring.

CSV måste vara UTF-8 och du väljer själv separator. PDF måste innehålla en enkel,
markerbar **tabell**, antingen avgränsad med separator eller med tydliga
mellanrum mellan kolumnerna. Skannade dokument/OCR, krypterade PDF:er,
svårare layouter och återkommande tabellrubriker stöds inte. Högst 20 sidor,
200 datarader och 50 kolumner tillåts för PDF; hela den tolkade tabellen måste
godkännas mot originalet före import. Saknas Pythonpaketet `pypdf` frågar
programmet om du vill installera det i den befintliga Pythonmiljön. Installationen
kan påverka andra program i miljön och kan misslyckas på systemskyddad Python;
ingen skyddsspärr kringgås. `pypdf` är valfritt och ingår inte i den tidigare
veckokontrollen av de fyra obligatoriska tilläggen.

Felaktiga rader, tomma eller tvetydiga rubriker och olika kolumnantal avvisas;
kontrollera alltid förhandsvisningen eftersom PDF:ers läsordning och Excel:s
nummerformat kan vara svåra att tolka. Vissa numeriska Excel-ID med inledande
nollor i visningsformatet avvisas: spara sådana ID som text. Originalfilerna
ändras inte. Vid CSV/PDF-import till Fordonsdata skapas en tillfällig Excel-fil
med textceller för den befintliga importören; mellanfilen tas bort efteråt.
Excel till Fordonsdata följer befintliga regler för flera blad, år, VIN och
säkerhetskopior. En import som sparar flera år har inte automatisk rollback
om en senare årsfil misslyckas.

## Inlärning

Fordonsreg har ett lokalt inlärningsminne kopplat till kolumnmappningen vid
import till **Fordonsdata och Återförsäljare** från ovanstående format. Det är
inte ett generellt AI som lär sig alla delar av programmet. Mappningarna för de
två målen är åtskilda. Efter en helt lyckad import, där du valt att lära/spara
en oskyddad mappning, räknas godkända kolumnval som exempel. Samma rubrik och
målfält måste ha godkänts i minst två lyckade importer innan det kan förifyllas
för en annan rubrikuppsättning. Motsägande val gör att just den rubriken inte
föreslås. En befintlig fingerprint-mappning för Fordonsdata går före inlärda
förslag. Du ser förifyllda fält och måste fortfarande kontrollera och godkänna
mappningsdialogen. Systemet kan inte avgöra om en rubrik har olika betydelse
hos olika leverantörer, så granskning behövs även efter flera godkännanden.

Inlärningen sparar normaliserade kolumnnamn, valda fältnamn och antal, inte
rader, filnamn eller PIN. Kolumnnamn kan ändå innehålla känslig information.
Minnet finns bara lokalt i `json/mappings/learning.json`, omfattas inte av
programuppdateringar och kan pausas eller rensas under **Verktyg**. Paus och
rensning påverkar inte manuellt sparade profiler eller fingerprint-mappningar.
Om minnet är oläsbart lämnas det orört och importer kan fortsätta utan inlärda
förslag. PIN-skyddade mappningar kopieras inte till inlärningsminnet. Avbrutna,
misslyckade eller delvis överhoppade importer räknas inte som inlärning.

Inlärningen fattar inga beslut om årskonflikter eller dubbletter, ändrar inte
originalfilerna och kan inte häva spärren för TS-generering. Fler delar måste
anslutas och verifieras separat innan de kan lära sig.

## En instans

Vid varje vanlig start visas huvudfönstret minimerat och döljs till systemfältet
när det är tillgängligt. Annars ligger det kvar minimerat i aktivitetsfältet.
Öppna via systemfältsikonen eller menyn på den. Vid vanlig
start tas lås redan före beroendekontrollen. En andra start ber den
befintliga instansen att visa fönstret i stället för att starta en ny kontroll
eller ett nytt GUI. En begäran under uppstart tas om hand när fönstret är klart.
Ett minimerat fönster återställs; operativsystemet kan dock hindra en app från
att stjäla fokus. Låsen släpps vid avslut eller processkrasch. Windowslåset är
per inloggningssession; isolerade användare/miljöer kan ha separata instanser.
Om ett säkert lås inte kan tas avbryts starten i stället för att riskera två
instanser. Uppdateringshjälparen väntar på att startprocessen avslutas och tar
samma lås innan den byter filer.

## Sökning, översikt och skydd

**Global sökning (Ctrl+K)** hittar VIN-kod, godkännandenummer, modellkod, färg,
återförsäljare och menyval. Sökningen går mot ett lokalt index i
`data/search_index.json`, som byggs om automatiskt när en årsfil ändras. Inget
skickas över nätet. Enter på en träff öppnar rätt år och markerar posten.

**Översikt** (Verktyg → Översikt, eller automatiskt första gången fönstret
öppnas efter start) visar antal fordon per år, färger som väntar på koppling,
aktiva felkoder, TS-spärrens läge och om senaste starten bekräftades. Panelen
ändrar ingenting. Starten är fortfarande minimerad; panelen visas först när du
öppnar fönstret.

**Bevakad mapp** (Verktyg → Bevakad mapp) är avstängd som standard. När den är
på kontrolleras mappen var 30:e sekund och en diskret notis visas när en ny
Excel-, CSV- eller PDF-fil har skrivits färdigt. Ingenting importeras
automatiskt: notisen öppnar den vanliga importen där du väljer fil och godkänner
som vanligt. Halvskrivna, tillfälliga och tomma filer hoppas över, och samma fil
rapporteras bara en gång.

**Import i bakgrunden:** filens innehåll läses i en arbetstråd med förlopp och
Avbryt, så fönstret inte fryser vid stora filer. Alla dialoger, all granskning
och all skrivning sker fortfarande på GUI-tråden. Avbryter du läsningen ändras
ingenting. Kan bakgrundskörningen inte startas läses filen i GUI-tråden i
stället.

**TS-verifiering** (Verktyg → Verifiera TS-underlag) läser en riktig TS-fil som
du väljer och sammanfattar teckenkodning, radslut, postlängd, avgränsare och
decimalkomma. Ingenting skrivs eller genereras. Spärren kan bara öppnas med en
felfri rapport, en uttrycklig bekräftelse och en anteckning om vad som
jämförts. Godkännandet sparas i `ts_verification.json` i programmappen och binds
till underlagets SHA-256: ändras filen upphävs godkännandet. Saknas, ändras
eller skadas godkännandet är genereringen spärrad. PT28 och PT99 saknas
fortfarande, så deras format är inte verifierade av det här verktyget.

**Felkodsguide** (Verktyg → Felkodsguide, även från felsökningsloggen) visar
trolig orsak och konkreta steg för varje känd felkod. Guiden ändrar aldrig en
kods status; en kod markeras som åtgärdad först när programmet verifierat det.

**Skydd vid uppdatering:** efter en uppdatering skrivs en markör med filernas
hashvärden och säkerhetskopians plats. Startar programmet och fungerar som det
ska tas markören bort. Bekräftas inte starten återställs säkerhetskopian
automatiskt vid nästa start, och åtgärden loggas i `.health/recovery.jsonl`.
Saknas eller skadas säkerhetskopian återställs ingenting – appen startar och
felet loggas i stället för att data förstörs.

## Förloppsvisning

Excel-importen under Data Mapping och fordonsregistrets textfilexport visar
förlopp under arbetet; de körs i bakgrunden och kan inte avbrytas medan de
skriver. Stapeln lämnar ett sista steg för filskrivning. TS-generatorvyn visar
förlopp från den faktiska generatorn i stället för den tidigare simulerade
förhandsvisningen. Den vanliga Data Mapping-sidans Generera-flik är dock
fortfarande en platshållare och öppnar inte denna TS-generatorvy.
Fordonsregistrets Excel-import visar aktuell fas och antal
bearbetade rader men körs fortfarande i GUI-tråden, liksom TS-generatorn;
stora enskilda läsningar eller skrivningar kan där tillfälligt frysa fönstret.
Andra import- och exportvägar har inte fått någon ny förloppsvisning.

## Loggning

Tekniska loggar skapas i undermappen `logs/` i appens egen mapp, oavsett
vilken arbetskatalog appen startas från, och ignoreras av Git. Startkontroll,
app och uppdaterare använder samma plats. Gamla loggar på andra platser flyttas
eller raderas inte. Om loggmappen inte kan skapas eller skrivas behöver
behörigheterna åtgärdas; loggar omdirigeras inte till en tillfällig mapp.
Tidigare anpassade sökvägar för tekniska loggfiler används inte längre: filnamnen
läggs i appens `logs/`. Separat verksamhetshistorik som genereringslogg i JSON är
användardata och ligger kvar på sin befintliga plats. För snabb felsökning
samlar **`logs/felsokning.log`** nya varningar, fel, kritiska fel och tillhörande
tracebacks från appens vanliga Python-loggning, Qt-loggning, startkontrollen och
uppdaterarens hjälpprocess. Varje post anger tid, nivå, process, logger och
källfil. Filen skapas vid start när det går och kan vara tom tills en varning
eller ett fel inträffar. Den roteras vid 5 MB (tre äldre filer). Olika processer använder ett gemensamt
lås för skrivning och rotation. Den gamla `errors.log` och alla kategoriloggar
behålls; ingen historisk genomsökning av gamla loggfiler görs.

Välj **Verktyg → Visa felsökningslogg** i appen för att öppna en skrivskyddad
vy. Där kan du växla mellan aktuell logg och de tre roterade loggarna, uppdatera
innehållet och kopiera den visade texten. Vyn kan vara öppen medan du använder
appen. För stora filer visas de senaste 2 MB;
hela filen finns kvar på den sökväg som visas. Granska innehållet innan du delar
det, eftersom loggar kan innehålla känsliga uppgifter.

### Dagliga arkiv och programfelkoder

Nya loggposter som når den vanliga logghanteringen sparas även per lokalt
kalenderdatum i `logs/dagliga/ÅÅÅÅ-MM-DD.log`. Från nästa dag flyttas en färdig
dagslogg till `logs/arkiv/`. Kontrollen sker vid start, när poster skrivs och
ungefär varje minut medan appen eller startprocessen körs. Missade dagar tas
vid nästa kontroll. Arkiv raderas inte automatiskt; namn med nummersuffix används
om ett arkiv redan finns. Gamla loggar från före denna funktion byggs inte om
eller raderas, och vanliga kategoriloggar och deras rotation fortsätter som förut.

**`logs/felkoder.json`** innehåller uttryckliga interna programfelkoder som
loggats som varning eller fel, med status `aktiv` eller `åtgärdad`. Det är en
separat fil från dagsarkiven och den kan läsas via **Verktyg → Visa
felsökningslogg → Programfelkoder**. En vanlig feltext är inte automatiskt en
felkod; koder från svarsfiler ingår inte. Filen kan innehålla känsliga uppgifter.
Om samma fel återkommer blir det aktivt igen.

Automatisk verifiering finns för **CONFIG_PARSE_ERROR**: den markeras åtgärdad
först när samma konfigurationsfil har lästs in och parsats utan syntaxfel.
Det bevisar inte att filens övriga innehåll är korrekt. För andra koder finns
ännu ingen tillförlitlig automatisk kontroll, så de ligger kvar som aktiva även
om de inte längre återkommer. Fel som aldrig loggas strukturerat kan inte
läggas till i felkodsregistret.

Vid vanlig GUI-start finns startkontroll och avslutningsstatus i `bootstrap.log` samt
processens tidiga stderr/stdout och Qt-utskrift i `console.log`. Appens vanliga
`debug.log` samlar loggposter, `errors.log` varningar och fel, och övriga filer
används för kategorier. Python-varningar, ohanterade undantag i huvudtråd och
bakgrundstrådar, unraisable-undantag och Qt-meddelanden loggas; eventnamn
loggas utan eventens datainnehåll. Loggar roteras och gamla filer kan skrivas
över. Uppdateraren använder dessutom `auto_update.log`.

Felsökningsfilen samlar loggposter när de skapas, inte genom att läsa alla
andra loggfiler. Den kan därför inte garantera att fånga t.ex. text som skrivs
direkt i en separat fil, native-utskrifter eller en logger som inte skickar
sina poster vidare. En approcess som avslutas med felstatus rapporteras med en
hänvisning till `console.log`. Inga loggsystem kan fånga fel som en plugin tyst
sväljer, avbrott före startfilen körs eller ett plötsligt strömavbrott. Befintliga plugins kan själva
logga personuppgifter, filnamn eller annat känsligt; behandla loggar som
konfidentiella och granska dem innan de delas. Ingen automatisk loggning av
lösenord eller kompletta eventdata har lagts till.

Excel-filerna är lokala användarfiler och behöver inte ligga i Git.
