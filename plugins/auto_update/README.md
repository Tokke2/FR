# Automatisk uppdatering och autostart

Pluginen upptäcks automatiskt vid appstart. Den kontrollerar i bakgrunden den
senaste publicerade, stabila releasen i `Tokke2/FR` på GitHub. Den slår upp
releasens tagg till en exakt commit och laddar arkivet för den commiten. Den
jämför SHA-256 för varje tillåten programfil vid varje kontroll, oavsett om
versionsnummer eller taggnamn är oförändrat. Ändrade och nya filer installeras;
likadana filer lämnas orörda. En vanlig commit som inte ingår i den publicerade
releasens tagg installeras inte. Om ingen stabil release har publicerats
händer ingenting. API-fel, inklusive GitHubs begränsning av anonyma anrop,
loggas och kontrollen försöks på nytt vid nästa appstart.

Knappen **Sök efter uppdateringar** i verktygsfältet och motsvarande menyval
visar om kontroll pågår, om ingen release finns, om filerna redan matchar,
om en uppdatering är förberedd eller om ett fel inträffat. Kontrollen körs i
bakgrunden. Om en installation redan väntar på appavslut tillåts inte en andra
konkurrerande hjälpprocess; sök igen efter nästa start för eventuella nya filer.

Om skrivbordsmiljön stöder systemfält visas Fordonsregs ikon där medan appen
körs. Högerklicka på ikonen och välj **Sök efter uppdateringar** för samma
kontroll. Huvudfönstret visas så att resultat och felmeddelanden syns. Menyn
har även **Öppna Fordonsreg** och **Avsluta Fordonsreg**. Om systemfält saknas
finns uppdateringsknappen och den vanliga menyn kvar. Med systemfält döljer
fönstrets stängknapp och minimera programmet till ikonen. Välj **Avsluta
Fordonsreg** för att avsluta på riktigt så att den förberedda uppdateringen
kan installeras. Utan systemfält används vanlig stängning.

Om filer skiljer sig laddas GitHubs källkodsarkiv ned. En hjälpprocess väntar
på att appen avslutas, säkerhetskopierar befintliga filer i `.update-backups/`
och installerar ändringarna. Hjälpprocessen tar appens singelinstanslås; om appen redan startats igen skjuts installationen upp till en senare kontroll. De nya filerna används vid nästa start. Appen startas inte om
automatiskt, så pågående arbete störs inte. Fel loggas och stoppar inte appen;
hjälpprocessens logg finns i `logs/auto_update.log`. Varningar och fel därifrån
skrivs även till `logs/felsokning.log` för gemensam felsökning. Ändringar återställs vid
skrivfel, så långt det är möjligt; behåll backupkatalogen för manuell återställning.

Endast `.py`-filer under `core/`, `plugins/`, `ui/` och `tools/` samt `start.pyw`, `main.pyw` och de namngivna programikonerna (`ikon.ico`, `ikon_16.png`, `ikon_32.png`, `ikon_64.png`, `ikon_256.png`) samt de statiska logotyperna `assets/fordonsreg-logo.svg` och
`assets/fordonsreg-icon.svg` samt `assets/LOGOTYP.md` installeras. De ingår i
releasearkivet tillsammans med programmet, inte som en separat nedladdning.
Data, inställningar, Excel-filer, Git och filer som saknas i releasen rörs
inte. Lokala ändringar i programfiler ersätts men säkerhetskopieras först.
Detta uppdaterar en Python-källkodsinstallation, inte en fryst exe/app-bundle,
och installerar inte Pythonberoenden. Uppdateringen använder GitHub över HTTPS;
den har ingen separat signaturverifiering. Releaser måste komma från ett betrott
konto och innehålla fungerande, kompatibel kod.

En äldre installerad uppdaterare som bara tillåter Pythonfiler kan inte hämta
ikonerna i samma steg som den får den nya uppdaterarkoden. Publicera i så fall
först en release med den nya uppdateraren och därefter en ny release med samma
ikonfiler; ikonerna installeras då efter nästa kontroll och appavslut. På samma
sätt kan äldre uppdaterare som inte tillåter SVG och logotypbeskrivningen behöva
en ytterligare kontroll efter att uppdaterarkoden har installerats.

Menyn **Start och uppdatering** har en kryssruta för valfri OS-autostart.
Inställningen sparas i `settings.json`. Windows använder en genväg med
Fordonsregs ikon i Startup-mappen, Linux XDG-autostart och macOS LaunchAgents.
En tidigare Windows-registrering i Registry eller `.bat` migreras först när
det nya alternativet har skapats och verifierats. Windows-genvägen startar
fortfarande appen via Python och `start.pyw` i en källkodsinstallation; den
ändrar inte filassociationen eller Python-processens inbyggda ikon.
OS-inställningen
synkroniseras från inställningen vid appstart. Menyn kan även skapa en
skrivbordsgenväg med Fordonsregs ikon på Windows och Linux efter bekräftelse;
den skriver inte över en befintlig genväg och ändrar inga filassociationer. Inloggningsstart beror på att
användarens skrivbordsmiljö stöder respektive mekanism.
