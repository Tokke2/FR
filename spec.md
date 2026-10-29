FILREGISTRERING — FORDONSFILREGISTRERINGSSYSTEM

# ═══════════════════════════════════════════════════════════════════════
# FILREGISTRERING — FORDONSFILREGISTRERINGSSYSTEM
# MODULÄRT PLUGIN-BASERAT SYSTEM (PYTHON + PYSIDE6)
# CONSOLIDATED MASTER SPEC / AI-KONTEXT / SYSTEMKRAV
# VERSION: 1.4
# Copyright © 2026 Rickard Längkvist
# ═══════════════════════════════════════════════════════════════════════

# STATUS:
# Source-of-truth. Version 1.4.
# Konsoliderad från: v1.3 (Filregistrering, baserad på Transportstyrelsen
# Fordonsregistreringssystem v7.2; generella mekanismer från
# Intygsgenerator v10.7 och Email & Template Manager v4.9 — sådant som
# passar fordonsfilregistrering; inga mallar/intyg/e-postspecifika flöden)
# + spec-ändring v7.3 (rad 1 = titlar vid fordonsimport + ny json/-katalog)
# + Session 10-arbete (ikonfiler genererade i assets/).
# Renskriven och sammanslagen i EN spec.
# ERSÄTTER ALLA tidigare versioner. Inga konflikter. Inga dubbletter.
# Full detaljnivå bevarad: Sektion D (funktionsöversikt), Q (importkrav
# 30–42), R (utvecklingsplan), S (UI/tema), T (loggning), U (cache),
# V (testchecklista), W (tillägg efter kodfil 10–12), X (ts_schema_manager),
# Y (tillägg efter kodfil 20–25), Z (json/-katalogen, NY).

# RENSKRIVNING v1.3 → v1.4 (genomgående):
# - Markdown-artefakter borttagna: [fil](url) → fil,
#   &gt;/&lt;/&amp; → >/</&, *log =* → _log =, **init** → __init__,
#   **getattr** → __getattr__, **eq** → __eq__, *activate*time →
#   _activate_time, **meta → _meta, *last*stats → _last_stats osv.
# - Versionsharmonisering (var felaktigt blandat):
#   ts_schema_manager = v3.5.0 (10 filer) ÖVERALLT
#     (X.2/X.5/Sektion N sa 3.4.0; C/X.1 sa 3.5.0 → 3.5.0 gäller).
#   ts_spec_import = v4.0.1.
#   ts_spec_viewer plugin.py = v1.0.0 (övriga filer saknas).
#   vehicle_registration_post = v3.1.0 (dokumenterad i W.5, EJ GRANSKAD).
# - "OGRANSKADE plugins" = 11 st (ts_spec_viewer har nu plugin.py v1.0.0).
# - Mappstrukturen (Sektion C) kompletterad med verkliga kataloger:
#   dispatch/, In/, xlsx/, config.json (rot), readme.txt samt
#   data/end_post, data/registration_post, data/transportstyrelsen,
#   data/ts_excel_importer, data/ts_file_generator, data/ts_specs.
# - Loggsektionen (T) noterar att äldre loggnamn (app.log, core.log,
#   plugin_*.log, ts_file.log, app_YYYYMMDD.log) fasas ut vid rotation.

# INARBETAT FRÅN SPEC-ÄNDRING v7.3:
# - KRAV 40: rad 1 i ALLA blad = kolumnrubriker vid fordonsimport.
# - KRAV 41: mappning + rubrik-fingerprint → JSON under json/mappings/.
# - KRAV 42: DEFAULT_COLUMN_MAPPING vs dialogresultat (dialog vinner).
# - NY SEKTION Z: json/-katalogen (alla data-JSON:er; settings.json +
#   ALLA config.json LIGGER KVAR; PROTECTED_DIRS + json).
# - Persistens-sökvägar uppdaterade till json/ med fallback till gamla.
# - Sektion Q: KRAV 30–42 + 5-stegsflöde med rad 1-regeln.

# SESSION 10 (DENNA):
# - Spec-ändring v7.3 skriven (rad 1 + json/) — inarbetad här.
# - Ikonfiler genererade: assets/ikon.ico (16–256 px, 7 storlekar),
#   ikon_16/32/64/256.png. Används av ui/tray_icon.py och
#   ui/main_window.py (fönsterikon) när de skrivs.
# - KVAR: ui/ (4 filer) → main (3 filer) → tests/ (7 filer) →
#   11 ogranskade plugins → Sektion Q-koden → rotation. Se Sektion K.

# ═══════════════════════════════════════════════════════════════════════
# SEKTION A — AI ENGINE MODE v2.5
# ═══════════════════════════════════════════════════════════════════════

# DU ÄR EN SENIOR CROSS-PLATFORM SOFTWARE ARCHITECT (AI ENGINE MODE v2.5)

# META:
# VERSION: 2.5 (uppgraderad från 2.4 med skarpare leveransregler)
# MODUS:   Iterativ generering (modul för modul)
# SPRÅK:   Python 3.12.x (senaste stabila LTS)
# UI:      PySide6 (senaste stabila LTS) — INGET annat GUI-ramverk
# OUTPUT:  En modul per svar (inkrementell byggnad)
# START:   main.pyw (ingen terminal)

# ANTAGANDE:
# Om applikationstyp saknas → generera "Shell App"
# (minimal app med komplett core + plugin-system redo)

# SPRÅKVAL (HÅRD REGEL):
# - Användaren BESTÄMMER språk, AI FÅR ALDRIG byta. Svenska gäller.
# - ALL output konsistent, ALLTID senaste stabila LTS
# - Dependencies == pinnade (använd == i requirements.txt, inga >= eller ~=)
# - Om orealistiskt språkval → föreslå närmaste LTS med motivering

# HÅRDA KODREGLER FÖR AI (v2.5):
# - AI SKRIVER ABSOLUT INGEN KOD UTAN UTTRYCKLIG ORDER
# - AI INVÄNTAR ALLTID INKLISTRAD KOD innan ändring görs.
#   Användaren har koden lokalt. Gissa ALDRIG. Skriv ALDRIG om
#   filer som inte bifogats. UNDANTAG: fil som enligt spec SAKNAS
#   får skrivas från grunden på uttrycklig order ("X — denna").
# - AI UPPDATERAR ALLTID KOD HELT, ALDRIG DELVIS.
#   Varje uppdaterad fil skrivs ut KOMPLETT från första till sista
#   rad, körbar direkt. Aldrig "ändra bara denna del", aldrig
#   diff-snuttar, aldrig "resten oförändrat".
# - AI FÅR ALDRIG korta ner kod eller spec. Inga "...", inga TODOs,
#   inga placeholders, inga förkortade rader.
# - Uppdatera BARA den fil som skickats in — ingen annan.
# - Uppdelning av svar i delar görs ENDAST när innehållet inte
#   ryms i ett svar (aldrig annars); hjälpfil föreslås endast
#   vid >1800 rader.
# - ALLA filer i samma mapp INNAN nästa mapp
# - Fråga ALLTID: "Vilken fil vill du börja med?"

# PRIORITY ORDER:
# P0 — CRITICAL: settings, logging, single instance lock
# P1 — REQUIRED: event bus, plugin loader, theme engine
# P2 — IMPORTANT: main window, tray, autostart, cache manager
# P3 — POLISH: tests, DPI fine-tuning, hot reload

# SMART RUNTIME MODE:
# DEV:  cache behålls, debug aktivt, snabb iteration
# PROD: full cleanup vid exit, deterministisk
# settings.json: "mode": "dev"|"prod", "smart_cache": true
# smart_cache=false → tvingar PROD cleanup

# GLOBAL CACHE POLICY (SMART CACHE — uppdaterad v1.4):
# RENSA vid exit (PROD): cache-filer, runtime cache, temp-artefakter,
# __pycache__ rekursivt, lösa .pyc/.pyo.
# SMART CACHE ska AKTIVT rensa bort __pycache__-mappar:
#   - Rekursiv skanning av projektroten (core/, ui/, plugins/, tests/)
#   - Alla __pycache__-kataloger tas bort (shutil.rmtree,
#     kraschsäkert, varje rmtree i egen try/except, loggas per mapp)
#   - Lösa .pyc/.pyo-filer utanför __pycache__ tas också bort
#   - Körs vid exit i PROD mode (smart_cache styr beteendet:
#     true = smart läge enligt mode, false = tvingad PROD-cleanup)
#   - I DEV mode behålls __pycache__ (snabb iteration)
#   - Hoppar ALLTID över: data/, logs/, settings.json, ut/, sap/,
#     In/, json/, .git/, venv/ och alla användarfiler (PROTECTED_DIRS)
#   - Symlänkar följs ALDRIG; radering ENDAST under projektroten
# RENSA ALDRIG: user data, settings, plugin data, logs
# PROTECTED_DIRS (komplett, v1.4): data, logs, ut, sap, In, json, .git,
#   .venv, venv, env, .idea, .vscode, node_modules
# PROTECTED_FILES: settings.json

# EVENT SYSTEM (OBLIGATORISKT):
# publish(event, data), subscribe(event, handler),
#   unsubscribe(event, handler)
# Implementation (core/event_bus.py v2.1.0): emit/on/off/clear_all
# plugins kommunicerar ENDAST via events
# unsubscribe KRÄVS vid cleanup

# FAIL-SAFE:
# varje modul wrappas i felhantering, fel → loggat + disabled
# UI visar ⚠ modul inaktiv vid fel
# ERROR RECOVERY: 3 failures → permanent disabled tills manuellt
#   återaktiverat

# SETTINGS: settings.json, atomic write, schema validation,
#   auto-repair (core/settings_manager.py v1.0.0, SCHEMA v1)

# AUTOSTART: Windows Registry (+.bat fallback), Linux .desktop,
#   macOS .plist (core/autostart.py v1.0.0)
# verify paths, auto-repair, no duplicates, sync vid startup
# settings.json "startup" är source of truth för sync()
# UI: Settings-dialog → autostart.set_enabled(checked)

# SINGLE INSTANCE: Windows Mutex, Linux/macOS flock, PID fallback
# max 1 instans, second → focus existing (trigger-fil + check_show_request())
# cleanup vid exit+crash (core/single_instance.py v1.0.0)

# PLUGIN CONTRACT: init(), register_ui(parent), shutdown(), config_schema()
# isolerade, failure→disable, lazy loading, ENBART EventBus
# HOT RELOAD: shutdown → clear subs → remove tab → reimport → init
#   → register_ui. STATE bevaras EJ vid reload.

# THEME ENGINE: get(key), apply(widget), set_mode(mode)
# 3 MODES: light, dark, auto (EXAKT 3 teman)
# Ljust: mörkgrå knappar + svart fet text
# Mörkt: ljusgrå knappar + vit fet text
# INGA hårdkodade färger i Python-kod
# KEYS: background, text, accent, surface, border, error, warning,
#   success, text_secondary, button_bg, button_text, tab_bg, tab_text
#   (samt utökade StyleEngine-nycklar, se Sektion S)
# IKON (v1.4): assets/ikon.ico (16–256 px) för tray + fönster,
#   assets/ikon_16/32/64/256.png som reserv.

# SYSTEM TRAY: ALLTID starta minimerat, enkelklick=öppna
# X=minimize to tray, exit=full shutdown via meny
# MENU: Show/Hide, Settings, Exit (+ Tema-undermeny, se W.3)

# UI:
# DPI aware, responsive, mushjul ÖVERALLT (ScrollPerPixel), scroll
# word wrap via Python (setWordWrap(True), ALDRIG i stylesheet)
# Visa/dölj tabbar var för sig via Visa-meny + högerklick på tabb
#   (sparas i settings.json, anpassas dynamiskt för alla
#   fönster/skärmar)
# QTableView + QAbstractTableModel (EJ QTableWidget >100 poster)
# QSortFilterProxyModel för sökning, dubbelklick=redigera
# Dialoger: BÅDE skapa+redigera (existing_data parameter)
# setObjectName() för alla widgets (theme engine)
# UI-tråden FÅR ALDRIG blockeras
# Progress indicator / progressbar vid >500ms tasks

# LOGGNING ("LOGGA VARJE SAK"):
# rotating 5MB×3, UTF-8, timestamp+module+level
# ALLA exceptions loggas, INGA silent exceptions
# Separata loggar: schema, import, export, gui, response, errors,
#   audit, vehicle, plugins, events, data_mapping, ts_file_generator
# + debug.log (catch-all DEBUG+, 10MB×5)
# sys.excepthook + threading.excepthook → errors.log
# logging.captureWarnings(True) → errors.log
# @log_call-dekorator (entry/argument/resultat/tid/exception)
# LogContext context manager (▶ START / ✔ KLART / ✗ FEL + ms)
# SESSION_ID i startbanner i alla kategoriloggar
# enable/disable_debug_mode() runtime

# OUTPUT-REGLER:
# full kod, körbar direkt, inga placeholders, inga TODOs
# Om fil >1800 rader → föreslå hjälpfil (max 1200 rader)
# Om kod ej ryms i ett svar → 2+ delar med användarkommando
#   emellan (ALDRIG uppdelning annars)

# ROTATION: När en mapp är komplett → hamnar SIST i priolistan.
# Alla andra mappar uppdateras innan samma mapp körs igen.

# ═══════════════════════════════════════════════════════════════════════
# SEKTION B — PROJEKTSPECIFIK SYSTEMSPEC
# ═══════════════════════════════════════════════════════════════════════

# 1. ÖVERGRIPANDE MÅL
# ─────────────────────────────────────────────────────────────────────
# Modernt, modulärt, plugin-baserat desktopsystem (Python + PySide6)
# för fordonsfilregistrering (Transportstyrelsen-filer).
# Systemet ersätter ett äldre Microsoft Access-baserat system
# ("Registrera nya fordonstyper – Vägverket registrering ver:6.12")
# som var formulärbaserat med VBA och .accdb/.mdb backend.

# Systemet ska vara:
# • Datadrivet
# • Schema-styrt
# • Plugin-baserat
# • Framtidssäkert
# • Kraschsäkert
# • Event-driven
# • Dynamiskt
# • Samarbetsvänligt mellan plugins
# • Anpassat för framtida okända posttyper och regeländringar
# • Modernt och färgglatt GUI
# • Alltid startande minimerat i systray
# • Alltid utan terminal (main.pyw; även .py ska köra tyst)

# Systemet ska kunna:
# • Importera TS-specifikationer från Excel (versionerade scheman)
# • Hantera schema-versioner (diff, backup, restore)
# • Importera Dispatch-data
# • Importera SAP-data
# • Importera Fordonsdata via Excel (med manuell mappningsdialog)
# • Matcha VIN mellan flera datakällor (VINCODE: tecken 2–4)
# • Mappa data automatiskt + manuellt via dialog
# • Validera fordonsdata (ISO 3779)
# • Generera Transportstyrelsefiler (PT28/PT45/PT99)
# • Läsa svarsfiler (TAD)
# • Hantera status och felkoder
# • Stödja Fix & Resend
# • Logga ALLT som sker i systemet
# • Hantera återförsäljare (CRUD, Excel-import, lösenordsskydd)
# • Hantera fordonsimport med förhandsgranskning och dubbletthantering
# • Hantera central konfiguration, FileID, backups
# • Redigera SAP-data via lösenordsskyddad editor
# • Spåra VIN per år/månad + årsrapporter
# • Importera färgdata + PDF-export
# • Hantera fordonsregister med VIN-validering och index
# • Visa systemdokumentation, hälsa och diagnostik
# • Batchhantering och massimport
# • Historik och loggning av alla operationer

# 2. ORIGINALSYSTEMET (VÄGVERKET ver:6.12) — DOKUMENTATION
# ─────────────────────────────────────────────────────────────────────
# Det befintliga systemet som ersätts:
# • Titel: "Registrera nya fordonstyper – Vägverket registrering ver:6.12"
# • Plattform: Microsoft Access (formulärbaserat)
# • Backend: .accdb/.mdb databas
# • UI: Ribbon/verktygsfält + 3-kolumns formulär
# • Funktioner: postnavigering, filter, sök, CRUD
# • Brister: ingen Excel-import, ingen batchhantering,
#   gammal design, ingen inline-validering

# FÄLT SOM ORIGINALSYSTEMET HANTERAR:
# ─── Identifiering ───
# Namn (BF), Fabrikat, Fabrikatskod, Gruppnr, Typ, Variant,
# Version, Handelsbeteckning, Fordonskategori,
# Godkännandenr, Godkännandedatum
# ─── Dimensioner & Vikt ───
# Antal axlar, Antal hjul, Längd, Bredd, Höjd,
# Vikt körklar, Totalvikt
# ─── Motor & Prestanda ───
# Slagvolym, Effekt (kW), Varvtal maxeffekt,
# Maxhastighet, Drivmedel
# ─── Chassi ───
# Bromssystem, Däck axel 1, Däck axel 2
# ─── Miljö ───
# Euroklass, Ljudnivå stillastående, Ljudnivå körning,
# CO2-utsläpp, Avgasdirektiv
# ─── Administration ───
# Tillverkningsår-månad, Kommissionsspärr,
# Beställ vid kommissionsspärr, Skyltformat

# 3. VIKTIGA UTVECKLINGSREGLER
# ─────────────────────────────────────────────────────────────────────
# core/, main.py, main.pyw FÅR EJ ÄNDRAS utan explicit godkännande
# (inskickad fil eller uttrycklig order räknas som godkännande).
# ALL ny funktionalitet via plugins.
# INGEN affärslogik hårdkodar fasta positioner om schema kan styra.
# Kommunikation: event_bus, get_plugin(), events.
# Direkta hårdkopplingar mellan plugins undviks.

# 4. TS-FILER
# ─────────────────────────────────────────────────────────────────────
# 2500 tecken/rad, ISO-8859-1 (Latin-1), atomisk skrivning,
# schema-styrd formatering.
# PT28, PT45, PT99 + framtida posttyper.

# 5. ARKITEKTUR
# ─────────────────────────────────────────────────────────────────────
# Core: plugin loading, event bus, lifecycle.
# Affärslogik i plugins, kraschsäkra, lazy, event-drivna.
# REGISTRERADE EVENT-NAMN: se komplett lista i Sektion P.

# 6. SCHEMA-ARKITEKTUR
# ─────────────────────────────────────────────────────────────────────
# Excel → JSON (source of truth), styr: positioner, fältlängder,
# typer, padding, validering, obligatoriska fält, konstanter,
# formatregler.
# Synonym-filer del av schemasystemet, utökningsbara via JSON.

# 7. TS_SCHEMA_MANAGER
# ─────────────────────────────────────────────────────────────────────
# Source of truth för schemasystemet.
# API: get_schema(), get_all_schemas(), list_versions(),
#   set_active_version(), get_active_version(), compare_versions()
# VIKTIGT: PluginBase.logger har INGEN setter.
# FÖRBJUDET: self.logger = ...
# KORREKT: module-level _log = get_logger()
# Lagring: json/schemas/ (versionerade), fallback data/schemas/
#   och legacy data/ts_specs/ (se Sektion Z + X.6).

# 8. TS_SPEC_IMPORT
# ─────────────────────────────────────────────────────────────────────
# STATUS: 100% KOMPLETT v4.0.1. SKA INTE GÖRAS OM utan uttrycklig
# begäran.
# Excel-import, versionshantering, Latin-1, GUI, events,
# export/import, diff, statistik, mapping suggestions, validation.

# 9. DATAIMPORT
# ─────────────────────────────────────────────────────────────────────
# Källor: Dispatch Excel, SAP Excel, JSON, Återförsäljar-Excel,
# fordonsdata Excel (modellimport), TAD-svarsfiler.
# Auto-detektering via prioritetsordnade synonym-listor
# (specifika termer först, generella sist).
# Excel-import 4-stegs header-detektering:
#   header=4 → header=0 → skanning rad 0-20 → fallback.
#   Poängsystem: DN=2, Namn=2, T6=1, minimum 3 för accept.
# Excel fordonsdata: ett blad per årsmodell.
#   '25Kw'-blad (och liknande, kw/kwh-suffix) ignoreras automatiskt.

# FORDONSDATAIMPORT — KÄLLKATALOGER:
# - SAP-modellimport: approtens undermapp sap/ (v7.0)
# - Standard fordonsdata: data/vehicles/ → json/vehicles/ (v1.4)
# - Fallback: data/
# - Endast Excel-filer; .json-filer ignoreras av importflödet

# MODELLIMPORT — MANUELL KOLUMNMAPPNING (KRAV v7.0):
# Excel-importen vid modellimport fungerar, MEN innan systemet
# matchar någonting ska användaren via ett AUTOGENERERAT FORMULÄR
# (dialog) ange vilken excelkolumn som ska kopplas till vilket
# målfält, t.ex.:
#   COMNAME = ?   (dropdown med upptäckta excelkolumner)
# - Vid import från sap/-mappen: kolumn 1 (rubrikraden/titlarna)
#   sparas som JSON-fil, och en dialog visas för koppling
#   kolumn ↔ målfält.
# - Mappningen sparas i json/mappings/vehicle_import_mapping.json
#   (atomisk skrivning) och återanvänds automatiskt vid nästa
#   import (rubrik-fingerprint, KRAV 35/41).
# - Ändring av sparad mappning kräver lösenord (lösenordsskydd).
# - VINCODE: matchning ska använda tecken 2–4 ur VIN
#   (positionerna 2, 3 och 4 — slice [1:4]).
# - Import skriver ALDRIG över befintlig fordonsdata utan att
#   användaren uttryckligen valt det (se dubbletthantering).

# MODELLIMPORT — RAD 1 I ALLA BLAD ÄR TITLAR (KRAV 40, v1.4):
# - Vid import av fordonsdata från Excel-fil är rad 1 i varje
#   blad titlar/rubriker.
# - Systemet läser rad 1 i varje blad och presenterar samtliga
#   unika rubriker för användaren i mappningsdialogen.
# - Rubrikerna från varje blad sparas tillsammans med ett
#   fingerprint (json/mappings/) så att samma filtyp kan
#   återanvända mappningen.
# - Om olika blad har olika rubriker visas alla rubriker; de blad
#   som inte har någon mappad användbar kolumn rapporteras som
#   hoppade (aldrig tyst, aldrig gissning).

# MODELLDATA-IMPORT — KOMPLETT IMPORTKEDJA:
#   1. Användaren klickar "📥 Importera Excel" i Fordonsdata-sidan
#   2. QFileDialog öppnas → välj .xlsx/.xls/.xlsm
#   3. Rad 1 (rubrikerna) läses i varje blad → sparas till JSON
#      (json/mappings/) + mappningsdialog visas (KRAV 31–32, 40)
#   4. vehicle_registry.import_from_excel() → ExcelModelImporter
#      (rad 1 = header direkt, VIN3 tecken 2–4, merge/upsert
#      per vin_kod)
#   5. VehicleDataPage refreshar alla tabs
#   6. QMessageBox visar resultat (nya/uppdaterade/överhoppade/fel)
# Backend: pandas + openpyxl
# Progress: QProgressDialog under import

# 10. FORDONSDATA & MAPPNING
# ─────────────────────────────────────────────────────────────────────
# VIN-matchning, saknade fält, mapping-kvalitet, validering.
# Färgkodsmappning, återförsäljare, typgodkännanden.
# Sparade mappings återanvänds automatiskt.
# VIN-registry: persistent lagring, ISO 3779 validering
#   (format + kontrollsiffra), modellårsutvinning.

# VIN-BEGREPP (FORMALISERAT — se även Sektion P/R):
#   Full VIN  = 17 tecken (ISO 3779, ej I/O/Q)
#   VIN-kod   = position 4-11 (vin_code i VinValidator)
#   VIN3      = TECKEN 2-4 (slice [1:4]) — SPEC v7.0-regeln,
#               implementerad i vehicle_registry v4.5.0.
#               Lagras som "vin_kod" i fordonsdata (3 tecken).
#   OBS: Äldre kod använde pos 5-7 — index/årsfiler byggda med
#   gamla regeln kräver rebuild_index() + ev. ommappning.
#   KONSISTENSKONTROLL KRÄVS vid rotation av: data_mapping
#   (extract_wmi/vin_registry), sap_import (data_normalizer),
#   main_gui (vehicle_registry_page).

# PERSISTENS (v1.4 — alla data-JSON:er under json/, se Sektion Z):
# - json/mappings/imported_headers.json
# - json/mappings/column_mappings.json
# - json/mappings/vin_registry.json
# - json/mappings/vehicle_import_mapping.json (dialog, KRAV 34/41)
# - json/mappings/column_mapping.json (excel_importer fältmappning)
# - json/vehicle_registry/registered_vins.json
# - json/vehicle_registry/index.json
# - json/vehicles/{YYYY}.json
# - json/schemas/ (ts_schema_manager, versionerade scheman)
# - json/vin_register/{YYYY}/{MM}.json (vin_tracking)
# - json/rapporter/vin_rapport_{YYYY}.json (vin_tracking)
# - json/sap_cache/ (sap_import)
# GAMLA SÖKVÄGAR (data/mappings/, data/vehicle_registry/,
# data/vehicles/, data/schemas/, data/ts_specs/, data/vin_register/,
# ut/rapporter/): läses som fallback tills migrerade (Sektion Z).

# GÄLLANDE TARGET FIELDS FÖR FORDONSDATA (32 st):
# MODELYEAR, VINCODE, TYPE, VARIANTE, VERSION, MODELNAME, COMNAME,
# CLASS, VEHCAT2, APPROVAL, DATEAPP, NUMAXLE, NUMWHEEL, ANTILBS,
# LENGTH, WIDTH, HEIGHT, MASS, LADENMASS, CYLCAPACITY, MAXPOWER,
# MAXNET, SPEED, TYRESIZE1, TYRESIZE2, SEATS, EMISLVL, STATIONARY,
# STATENG, DRIVEBY, EMSTAGE, EECO2E
# (vehicle_registry MODEL_COLUMNS innehåller även WORK_PR, FUEL)

# 11. GUI-KRAV
# ─────────────────────────────────────────────────────────────────────
# PySide6, modernt och färgglatt, senaste stabila Python.
# ALLA plugins lägger till egna flikar (eller integreras via
# meny/dialog där lämpligt).

# TABB-HANTERING:
# • Visa/dölj individuellt via 'Visa'-menyn
# • Högerklicka på tabb → dölj
# • Dynamiskt anpassat alla fönster/skärmar
# • Tillstånd sparas i settings.json

# TABELLER:
# • QTableView + QAbstractTableModel (aldrig QTableWidget >100 poster)
# • QSortFilterProxyModel för sökning
# • Dubbelklick = redigera

# DIALOGER:
# • Stöder BÅDE skapa och redigera (existing_data parameter)
# • Validering innan accept

# WIDGETS (setObjectName() för tema-styling):
# • PrimaryButton, SecondaryButton, DangerButton, SuccessButton
# • PageTitle, SearchGroup, ActionGroup, StatusLabel, CountLabel

# FORDONSIMPORT UI:
# • QPushButton("📥 Importera Excel") placerad bredvid "Lägg till fordon"
# • QFileDialog.getOpenFileName() för filväljare
# • Mappningsdialog (kolumn ↔ målfält) FÖRE matchning (v7.0)
# • QTableView med förhandsgranskning (antal, fel, dubletter)
# • Tydliga felmeddelanden med radnummer
# • Progress indicator under import

# PERFORMANCE:
# • UI-tråden FÅR ALDRIG blockeras
# • async/thread för tung logik
# • progress indicator vid >500ms tasks

# 12. TEMASYSTEM
# ─────────────────────────────────────────────────────────────────────
# EXAKT 3 TEMAN: Mörkt (dark), Ljust (light), System (auto).
# Krav:
# • Tydliga knappar, hög kontrast, läsbar text
# • Inga hårdkodade färger i Python-kod, konsekvent spacing
# • Fet text på knappar/tabbar, färgglatt och modernt
# • Ljust: mörkgrå knappar/tabbar + svart fet text
# • Mörkt: ljusgrå knappar/tabbar + vit fet text
# • System: synkar till OS automatiskt
# • Alla knappar/tabbar ALLTID tydligt synliga oavsett tema
# • Qt stylesheet: "word-wrap" FÖRBJUDET → setWordWrap(True)
# • settings.json theme-värden: ENDAST "light"/"dark"/"auto"
#   (legacy ttk-teman som "clam" migreras till "auto")
# StyleEngine-nycklar (minimalt):
# background, surface, surface_alt, bg_secondary, panel_bg,
# card_bg, input_bg, text, text_secondary, muted, disabled_fg,
# disabled_bg, button_bg, button_fg, button_hover, button_active,
# tab_bg, tab_fg, tab_active_bg, tab_active_fg, accent,
# accent_hover, accent_active, border, border_soft, success,
# warning, error, info, link, selection_bg, selection_fg,
# tooltip_bg, tooltip_fg
# (komplett lista i Sektion S.3)

# 13. LOGGNING
# ─────────────────────────────────────────────────────────────────────
# ALLT loggas ("LOGGA VARJE SAK").
# Separata loggar:
# schema, import, export, gui, response, errors, audit, vehicle,
# plugins, events, data_mapping, ts_file_generator
# + debug.log (catch-all DEBUG+, 10MB×5)
# Dealer CRUD-operationer loggas.
# Excel-import loggar per blad (bearbetat/hoppat).
# Matchade kolumnnamn loggas med synonym-info.
# Fordonsimport loggar: antal importerade, fel, dubletter,
#   validering per rad, kolumnmappning som användes, tid.
# Färgimport, VIN-spårning, fordonsregister och SAP-redigering
#   loggas.
# Ohanterade exceptions (även trådar) loggas via excepthooks.
# Python-warnings fångas till errors.log.
# Rotating 5MB × 3 filer (debug 10MB × 5). UTF-8.
# Inga silent exceptions.
# Module-level _log (EJ self.logger, EJ print()).
# SESSION_ID i startbanner i alla kategoriloggar.
# @log_call / LogContext för funktionsanrop där så är motiverat.
# Äldre loggnamn (app.log, app_YYYYMMDD.log, core.log,
# plugin_*.log, ts_file.log) fasas ut vid respektive rotation.

# 14. KRASCHSÄKERHET
# ─────────────────────────────────────────────────────────────────────
# ALLA publika plugin-metoder kraschsäkra.
# ALLA operationer: exception-hantering, loggning, säkra fallbacks.
# Plugin loading kraschar ALDRIG hela systemet.
# Excel-import returnerar ALLTID resultat (även vid total krasch).
# cleanup/cache-rensning FÅR ALDRIG krascha appen.
# settings-load FÅR ALDRIG krascha (korrupt → .corrupt-backup + defaults).

# 15. LATIN-1 / TRANSPORTSTYRELSEN
# ─────────────────────────────────────────────────────────────────────
# validate_latin1(), sanitize_for_ts(), ensure_latin1().
# Synonymer med svenska tecken (å, ä, ö) fungerar vid matchning
# men behöver ej vara Latin-1-säkra (skrivs ej till TS-filer).

# 16. ATOMISK FILSKRIVNING
# ─────────────────────────────────────────────────────────────────────
# ALL skrivning av kritiska filer:
#   tempfile.mkstemp → os.fdopen → fsync → os.replace
# ALDRIG Path.replace() — använd ALLTID os.replace().
# ALDRIG open(fd, closefd=False) i atomic-write (fd-läcka +
#   PermissionError på Windows).
# Gäller: TS-filer, JSON-scheman, versionsdata, mapping-data,
#   exportfiler, lösenordsfiler, ÅF-JSON, export-JSON,
#   fordonsdata-JSON, VIN-register, VIN tracking-register,
#   årsrapporter, vehicle_import_mapping.json, settings.json,
#   config-save, autostart .bat/.desktop/.plist,
#   single_instance trigger-/PID-filer,
#   vehicle_registry column_mapping.json.
# ALLT under json/ skrivs ALLTID atomiskt (Sektion Z, regel 2).

# ═══════════════════════════════════════════════════════════════════════
# SEKTION C — MAPPSTRUKTUR (uppdaterad v1.4)
# ═══════════════════════════════════════════════════════════════════════

# projektrot/
# ├── main.py                          # Dev entry      ⬜ SAKNAS
# ├── main.pyw                         # Prod entry     ⬜ SAKNAS
# ├── requirements.txt                 # Pinnade ==     ⬜ SAKNAS
# ├── settings.json                    # ✅ SCHEMA v1 — LIGGER KVAR
# ├── config.json                      # ✅ rot-konfig — LIGGER KVAR
# ├── readme.txt                       # ✅ LIGGER KVAR
# ├── assets/                          # ✅ NY v1.4 (Session 10)
# │   ├── ikon.ico                     #   fönster/tray-ikon (16–256 px)
# │   └── ikon_16/32/64/256.png        #   reserv-PNG:er
# │
# ├── core/                            # ✅ KOMPLETT (Session 9)
# │   ├── __init__.py                  # v3.1.0 — lazy-importtabell
# │   ├── application.py               # v1.1.0
# │   ├── config.py                    # v1.1.0 (atomisk save)
# │   ├── exceptions.py                # v1.1.0
# │   ├── event_bus.py                 # v2.1.0
# │   ├── plugin_base.py               # v3.3.0 (komplett kontrakt)
# │   ├── plugin_loader.py             # v2.3.0
# │   ├── settings_manager.py          # v1.0.0 (SCHEMA v1)
# │   ├── logger_setup.py              # v2.0.0
# │   ├── single_instance.py           # v1.0.0
# │   ├── cache_manager.py             # v1.0.0 (SPEC v7.1/v1.4:
# │   │                                #   PROTECTED_DIRS + json)
# │   ├── autostart.py                 # v1.0.0
# │   └── config.json                  # LIGGER KVAR (undantag v1.4)
# │
# ├── ui/                              # ⬜ ALLA 4 SAKNAS ← NÄST PÅ TUR
# │   ├── __init__.py
# │   ├── theme_engine.py              # dark/light/auto, StyleEngine
# │   ├── main_window.py               # tabbar, visa/dölj, X=tray,
# │   │                                # QTimer → single_instance.
# │   │                                # check_show_request(), ikon,
# │   │                                # geometri ↔ settings,
# │   │                                # Settings-dialog → autostart
# │   ├── tray_icon.py                 # systray, enkelklick=öppna,
# │   │                                # ikon från assets/ikon.ico
# │   └── tab_manager.py               # högerklick, Visa-meny, mushjul
# │
# ├── json/                            # ✅ NY v1.4 — ALLA data-JSON:er
# │   ├── mappings/                    #   kolumn-/importmappningar
# │   │   ├── column_mappings.json     #   (data_mapping)
# │   │   ├── imported_headers.json    #   (data_mapping)
# │   │   ├── vin_registry.json        #   (data_mapping)
# │   │   ├── vehicle_import_mapping.json  # (Q, KRAV 34/41)
# │   │   └── column_mapping.json      #   (vehicle_registry
# │   │                                #    excel_importer v1.2.0)
# │   ├── schemas/                     #   versionerade TS-scheman
# │   │   └── backup/                  #   (ts_schema_manager)
# │   ├── vehicles/                    #   {YYYY}.json per år
# │   ├── vehicle_registry/            #   registered_vins.json,
# │   │                                #   index.json
# │   ├── sap_cache/                   #   SAP-cache (JSON)
# │   ├── vin_register/                #   {YYYY}/{MM}.json
# │   │                                #   (vin_tracking)
# │   └── rapporter/                   #   vin_rapport_{YYYY}.json
# │                                    #   (vin_tracking)
# │
# ├── plugins/
# │   ├── about/                       # ✅ v3.0.0 (2 filer)
# │   ├── buntpost/                    # ⬜ EJ GRANSKAD
# │   ├── color_import/                # ✅ v3.0.0 (2 filer)
# │   ├── colors_manager/              # ⬜ EJ GRANSKAD
# │   ├── core_auth/                   # ⬜ EJ GRANSKAD
# │   ├── core_config/                 # ✅ v4.0.0 (2 filer)
# │   ├── core_logger/                 # ⬜ EJ GRANSKAD
# │   ├── data_mapping/                # ✅ v5.0.0 (5 filer)
# │   │   # ⚠ VIN3-konsistenskontroll (tecken 2-4) vid rotation
# │   ├── data_viewer/                 # ⬜ EJ GRANSKAD
# │   ├── dealers_manager/             # ✅ v2.2.1 (5 filer)
# │   ├── dispatch_viewer/             # ✅ v3.1.0 (2 filer)
# │   ├── end_post/                    # ⬜ EJ GRANSKAD
# │   ├── ereko/                       # ⬜ EJ GRANSKAD
# │   ├── gui_helpers/                 # ⬜ EJ GRANSKAD
# │   ├── identity_post/               # ✅ v3.2.0 (2 filer)
# │   ├── main_gui/                    # ✅ (delvis)
# │   │   ├── plugin.py                # v6.0.1
# │   │   └── vehicle_registry_page.py # v5.4.0
# │   │   # ⚠ VIN3-konsistenskontroll vid rotation
# │   ├── post_format/                 # ⬜ EJ GRANSKAD
# │   ├── reports/                     # ⬜ EJ GRANSKAD
# │   ├── response_viewer/             # ✅ v2.0.0 (2 filer)
# │   ├── sap_editor/                  # ✅ v2.0.0 (4 filer)
# │   ├── sap_import/                  # ✅ v4.1.0 (11 filer)
# │   │   # ⚠ VIN3-konsistenskontroll vid rotation
# │   ├── ts_excel_importer/           # ⬜ EJ GRANSKAD
# │   ├── ts_file_generator/           # ✅ v6.0.0 (5 filer)
# │   ├── ts_schema_manager/           # ✅ v3.5.0 (10 filer)
# │   │   # __init__, plugin.py, constants.py, models.py,
# │   │   # version_manager.py, schema_diff.py, widget_utils.py,
# │   │   # widget_models.py, widget_dialogs.py, widget.py
# │   │   # Lagring: json/schemas/ (se X.6 + Z)
# │   ├── ts_spec_import/              # ✅ v4.0.1 (3 filer)
# │   ├── ts_spec_viewer/              # ✅ plugin.py v1.0.0
# │   │   # ⬜ övriga filer saknas (widget.py, __init__.py)
# │   ├── vehicle_registration_post/   # ⬜ EJ GRANSKAD
# │   │   # v3.1.0 dokumenterad i W.5
# │   ├── vehicle_registry/            # ✅ v4.5.0 (3 filer)
# │   │   ├── __init__.py              # v4.5.0
# │   │   ├── plugin.py                # v4.5.0
# │   │   └── excel_importer.py        # v1.1.0 (→ v1.2.0 planerad:
# │   │                                #   rad 1 = header direkt,
# │   │                                #   json/mappings/)
# │   └── vin_tracking/                # ✅ v1.1.0 (2 filer)
# │       # registry_dir/report_dir via config →
# │       # json/vin_register, json/rapporter (v1.4)
# │
# ├── sap/                             # Excel-filer för SAP-modellimport
# ├── dispatch/                        # Dispatch-data (verklig katalog)
# ├── In/                              # In-katalog (verklig katalog)
# ├── xlsx/                            # Excel-källa (verklig katalog)
# │
# ├── data/                            # ⚠ UNDER MIGRERING (v1.4)
# │   │                                #   JSON-filer flyttas till json/
# │   │                                #   vid respektive fils rotation;
# │   │                                #   läses som fallback tills dess.
# │   ├── schemas/                     #   → json/schemas/
# │   ├── mappings/                    #   → json/mappings/
# │   ├── vehicles/                    #   → json/vehicles/
# │   ├── sap_cache/                   #   JSON → json/sap_cache/
# │   ├── vehicle_registry/            #   → json/vehicle_registry/
# │   │                                #   (+ column_mapping.json →
# │   │                                #     json/mappings/)
# │   ├── vin_register/                #   → json/vin_register/
# │   ├── exports/                     #   ligger kvar
# │   ├── end_post/config.json         #   LIGGER KVAR (config.json)
# │   ├── registration_post/config.json#   LIGGER KVAR (config.json)
# │   ├── transportstyrelsen/          #   LIGGER KVAR (config.json +
# │   │                                #   backup/status/)
# │   ├── ts_excel_importer/           #   LIGGER KVAR (import_history
# │   │                                #   → json/mappings/ vid rotation)
# │   ├── ts_file_generator/           #   LIGGER KVAR (config.json +
# │   │                                #   file_id_series.json → json/)
# │   └── ts_specs/                    #   legacy (→ json/schemas/)
# │
# ├── ut/                              # TS-filer + rapporter (oförändrad)
# │   └── rapporter/                   #   TS-rapportfiler ligger kvar;
# │                                    #   JSON-rapporten → json/rapporter/
# │
# ├── logs/                            # Rotationsvänliga loggar
# │   ├── schema.log, import.log, export.log, gui.log
# │   ├── response.log, errors.log, audit.log
# │   ├── vehicle.log, plugins.log, events.log
# │   ├── data_mapping.log, ts_file_generator.log
# │   └── debug.log                    # catch-all DEBUG+ (10MB × 5)
# │
# ├── cache/                           # RENSAS i PROD mode
# │
# └── tests/                           # ⬜ SAKNAS
#     ├── test_import.py
#     ├── test_startup.py
#     ├── test_plugin_load.py
#     ├── test_settings.py
#     ├── test_event_bus.py
#     ├── test_theme.py
#     └── test_single_instance.py

# NOTERA: struktur.txt-filer ignoreras och räknas INTE som styrande.
# settings.json + ALLA config.json ligger kvar (undantag v1.4, Sektion Z).

# ═══════════════════════════════════════════════════════════════════════
# SEKTION D — FUNKTIONS- OCH IMPORTÖVERSIKT (SAMMANFATTAD, v1.4)
# ═══════════════════════════════════════════════════════════════════════

# core/ — 12 filer kompletta (full detalj i föregående v7.2 Sektion D):
#   __init__.py v3.1.0, application.py v1.1.0, config.py v1.1.0,
#   exceptions.py v1.1.0, event_bus.py v2.1.0, plugin_base.py v3.3.0,
#   plugin_loader.py v2.3.0, settings_manager.py v1.0.0,
#   logger_setup.py v2.0.0, single_instance.py v1.0.0,
#   cache_manager.py v1.0.0, autostart.py v1.0.0
#   + settings.json SCHEMA v1.

# ui/ — 4 filer saknas (se Sektion S för detaljerade krav):
#   theme_engine.py   — StyleEngine, get/apply/set_mode, 3 teman,
#                       generera QSS, läsa/skriva theme via
#                       SettingsManager.
#   main_window.py    — QMainWindow, Visa-meny, tabbar, geometri ↔
#                       settings, QTimer → single_instance.
#                       check_show_request(),
#                       set_show_callback(show_window), fönsterikon
#                       från assets/ikon.ico, Settings-dialog →
#                       autostart.set_enabled.
#   tray_icon.py      — QSystemTrayIcon med ikon från assets/ikon.ico,
#                       enkelklick/dubbelklick=show, meny:
#                       Visa/Dölj, Inställningar, Avsluta (+ Tema, W.3).
#   tab_manager.py    — TabBar med contextMenuEvent, add/show/hide/
#                       toggle_tab, restore/save visible_tabs,
#                       ScrollPerPixel.

# plugins/ — kompletta mappar (16 st) + delvis:
#   dealers_manager 2.2.1 (5) · ts_schema_manager 3.5.0 (10) ·
#   data_mapping 5.0.0 (5) · ts_file_generator 6.0.0 (5) ·
#   response_viewer 2.0.0 (2) · ts_spec_import 4.0.1 (3, EJ GÖRA OM) ·
#   core_config 4.0.0 (2) · about 3.0.0 (2) · sap_editor 2.0.0 (4) ·
#   vin_tracking 1.1.0 (2) · color_import 3.0.0 (2) ·
#   vehicle_registry 4.5.0 (3) · sap_import 4.1.0 (11) ·
#   dispatch_viewer 3.1.0 (2) · identity_post 3.2.0 (2) ·
#   main_gui plugin.py 6.0.1 + vehicle_registry_page.py 5.4.0 ·
#   ts_spec_viewer plugin.py 1.0.0 (övriga filer saknas).

# PLANERADE VERSIONER VID NÄSTA ROTATION (v1.4):
# - vehicle_registry/excel_importer.py v1.1.0 → v1.2.0:
#   * _read_sheet: RAD 1 = header direkt; fallback-skanning rad 1–9
#     ENDAST om rad 1 tom/oläsbar (loggas); blad utan användbar
#     header → skipped med rapport (KRAV 40).
#   * get/set_column_mapping: persistent → json/mappings/
#     column_mapping.json (atomisk).
# - vehicle_registry/plugin.py v4.5.0 → v4.6.0:
#   * init(): ExcelModelImporter(mapping_dir=json/mappings).
#   * __init__.py synkas till v4.6.0.
# - main_gui/vehicle_registry_page.py v5.4.0 → v5.5.0:
#   * Importflöde enligt Sektion Q (rad 1 → dialog → json/mappings/
#     → import → sammanfattning).
# - vin_tracking: ingen kodändring; config-defaults uppdateras:
#   registry_dir=json/vin_register, report_dir=json/rapporter.
# - ts_schema_manager: lagring → json/schemas/ (fallback data/schemas/
#   och legacy data/ts_specs/).
# - data_mapping: mappings → json/mappings/ (+ VIN3-kontroll, G6).
# - sap_import: sap_cache-JSON → json/sap_cache/.
# - core_config/settings_manager: oförändrade (config.json/
#   settings.json ligger kvar).

# ═══════════════════════════════════════════════════════════════════════
# SEKTION E — ALLA KÄNDA BUGGAR (17 st — SAMTLIGA ÅTGÄRDADE)
# ═══════════════════════════════════════════════════════════════════════

# Dessa buggar är dokumenterade så att de ALDRIG återinförs. Vid varje
# kodrotation: kontrollera att fixarna fortfarande är på plats.

# BUGG #1  — logger-setter (ts_schema_manager): self.logger = ...
#            → module-level _log. Regel: ALDRIG self.logger = .
# BUGG #2  — ColumnMappingService (data_mapping): tjänster registreras
#            i activate(), avregistreras i deactivate().
# BUGG #3  — word-wrap i stylesheet (main_gui): setWordWrap(True) i
#            Python-kod. Regel: word-wrap ALDRIG i .qss/stylesheet.
# BUGG #4  — get_all saknades (response_viewer): get_all() implementerad
#            publikt. Regel: publika API:n som andra anropar måste finnas.
# BUGG #5  — TADEGA-copyright: AUTHOR = "Rickard Längkvist" överallt,
#            dynamisk copyright (aldrig hårdkodat årtal).
# BUGG #6  — change() returnerade fel typ: Tuple korrekt i signatur +
#            alla returvägar.
# BUGG #7  — "nan"-strängar från pandas: NaN → "" (pd.isna()-kontroll).
# BUGG #8  — AUTHOR-konstant saknades/fel: VERSION + AUTHOR per fil.
# BUGG #9  — get_active_version (ts_schema_manager): korrekt uppslag +
#            definierad fallback.
# BUGG #10 — dealers importvägar: konsekventa absoluta paketimporter
#            (inga cwd-beroenden).
# BUGG #11 — excel_reader synonyms-väg: sökväg via config, ej hårdkodad.
# BUGG #12 — fd-läcka i atomic_write_text (vin_tracking): os.fdopen i
#            with-block. Regel: closefd=False FÖRBJUDET.
# BUGG #13 — tempfile utan import (logger_setup): import tempfile på
#            modulnivå. Regel: print() förbjudet, stderr via
#            _bootstrap_report.
# BUGG #14 — core/__init__.py korrupt dubbel-fil: konsoliderad lazy-modul.
#            Regel: kontrollera alltid efter hopklistrade dubbletter.
# BUGG #15 — kontraktslucka i PluginBase: register_ui() + config_schema()
#            tillagda; _activate_time sätts (uptime fungerar).
# BUGG #16 — config.save() icke-atomisk: mkstemp → fdopen → fsync →
#            os.replace. Regel: Path.replace FÖRBJUDET.
# BUGG #17 — VIN3 fel teckenposition (pos 5–7): VIN3 = tecken 2–4
#            (slice [1:4]) i VinValidator, extract_vin3,
#            extract_vin3_from_full, get_vehicle()-logik (3 tecken =
#            VIN3 direkt, 4+ tecken = slice [1:4]) samt
#            excel_importer._extract_vin3_from_value.
#            ⚠ Gamla index-/årsfiler byggda med pos 5–7 kräver
#            rebuild_index() vid första körning efter uppdateringen!

# ═══════════════════════════════════════════════════════════════════════
# SEKTION F — SESSIONSCHECKLISTA
# ═══════════════════════════════════════════════════════════════════════

# [x] Session 1–3 : Grundsystem, plugin-arkitektur, första spec-versionerna.
# [x] Session 4–5 : Spec v5.0, dealers/schema/data_mapping/file_generator.
# [x] Session 6   : sap_import v4.1.0.
# [x] Session 7   : main_gui v6.0.1 + vehicle_registry_page v5.1.0,
#                   dispatch_viewer v3.1.0, identity_post v3.2.0.
# [x] Session 8   : Spec v7.0 konsoliderad; VINCODE tecken 2–4.
# [x] Session 9   : vin_tracking v1.1.0, vehicle_registry v4.5.0,
#                   core/ komplett (12 filer), settings SCHEMA v1.
# [x] Session 10  : Spec-ändring v7.3 (rad 1 = titlar + json/-katalog),
#                   ikonfiler genererade (assets/), konsolidering till
#                   FILREGISTRERING MASTER SPEC v1.4 (denna).
# [ ] Session 11+ : ui/ (NÄST PÅ TUR) → main → tests → ogranskade
#                   plugins → Sektion Q-importflödet → VIN3-konsistens
#                   → json/-migrering → rotation.

# ═══════════════════════════════════════════════════════════════════════
# SEKTION G — KVARVARANDE ARBETE
# ═══════════════════════════════════════════════════════════════════════

# G1. ui/ — 4 filer saknas: theme_engine.py, main_window.py,
#     tray_icon.py, tab_manager.py (skrivs på order "X — denna").
#     Ikon finns: assets/ikon.ico (tray + fönster).
# G2. main — 3 filer: main.pyw, main.py, requirements.txt (pinnade ==).
#     main.pyw-integrationer: SingleInstance.acquire() → vid upptaget:
#     focus_existing() + sys.exit(0); CacheManager.install_exit_hook();
#     AutostartManager.sync(); shutdown_logging().
# G3. tests/ — 7 filer.
# G4. 11 OGRANSKADE plugins: buntpost, colors_manager, core_auth (först —
#     sap_editor beror på den), core_logger, data_viewer, end_post,
#     ereko, gui_helpers, reports, ts_excel_importer,
#     vehicle_registration_post. (ts_spec_viewer har plugin.py v1.0.0,
#     övriga filer saknas.)
# G5. Sektion Q-kraven 30–42: mappningsdialog (rad 1 = titlar), sap/-
#     import, JSON-mappningsfiler under json/mappings/, lösenordsskydd,
#     återanvändning (fingerprint).
# G6. VIN3-konsistenskontroll (tecken 2–4) vid rotation av: data_mapping
#     (vin_registry extract_wmi pos 1–3 är OK men VERIFIERA), sap_import
#     (data_normalizer), main_gui (vehicle_registry_page).
# G7. rebuild_index() för gamla index-/årsfiler byggda med pos 5–7.
# G8. Slutverifiering: full uppstart, alla plugins, alla events, atomisk
#     skrivning överallt, inga print(), inga f-string-loggar.
# G9. json/-migrering — befintliga data-JSON:er flyttas vid respektive
#     fils rotation enligt Sektion Z; gamla sökvägar läses som fallback
#     (loggas) tills första skrivning skett till ny path.

# ═══════════════════════════════════════════════════════════════════════
# SEKTION H — FRAMTIDSPLAN (FASER)
# ═══════════════════════════════════════════════════════════════════════

# FAS 1 ✅ KLAR  : Stabil kärna — core/ komplett (12 filer), settings
#                  SCHEMA v1, single instance, smart cache, autostart,
#                  avancerad loggning, alla 17 buggar fixade.
# FAS 2 ▶ NÄST   : ui/ — 4 filer (theme_engine, main_window, tray_icon,
#                  tab_manager) + main.pyw/main.py/requirements.txt.
#                  Ikonfiler klara (assets/).
# FAS 3          : tests/ + ogranskade plugins + Sektion Q-importflödet
#                  (rad 1 → dialog → json/mappings/).
# FAS 4          : vehicle_registry-utvecklingsplanen (Sektion R) +
#                  json/-migrering (Sektion Z) + rotation/underhåll.

# ═══════════════════════════════════════════════════════════════════════
# SEKTION I — ARBETSFLÖDEN
# ═══════════════════════════════════════════════════════════════════════

#  1. Registrera ny fordonstyp manuellt (vehicle_registry → formulär → spara).
#  2. Modellimport från Excel MED mappningsdialog FÖRE matchning
#     ("COMNAME = ?" per kolumn; rad 1 i alla blad läses som titlar).
#  3. Import av fordonsdata från sap/-mappen (kolumn 1/rubriker → JSON-
#     mappningsfil json/mappings/ + dialog).
#  4. VIN-sökning: 3 tecken = VIN3 direkt; 4+ tecken = slice [1:4];
#     17 tecken = full VIN-validering.
#  5. Skapa TS-fil (ts_file_generator) → validate_latin1 → ut/.
#  6. Läs in svarsfil (response_viewer → get_all).
#  7. Schemahantering (ts_schema_manager → aktiv version + fallback;
#     lagring json/schemas/).
#  8. Kolumnmappning (data_mapping → ColumnMappingService;
#     json/mappings/).
#  9. Återförsäljare (dealers_manager CRUD).
# 10. SAP-redigering (sap_editor, kräver core_auth).
# 11. VIN-spårning/rapport (vin_tracking; json/vin_register,
#     json/rapporter).
# 12. Tema-byte (light/dark/auto → SettingsManager → theme_engine;
#     även via tray-meny, W.3).
# 13. Autostart på/av (Settings-dialog → autostart.set_enabled → sync();
#     Windows Registry, .bat-fallback, Linux .desktop, macOS .plist).
# 14. Andra instans startas → trigger-fil → befintligt fönster fokuseras
#     (QTimer-poll ~1000 ms).
# 15. Avslut: shutdown_logging() + cache-rensning (__pycache__) via
#     install_exit_hook om should_cleanup(); json/ rörs ALDRIG.

# ═══════════════════════════════════════════════════════════════════════
# SEKTION J — ABSOLUT FÖRBJUDET
# ═══════════════════════════════════════════════════════════════════════

# ✗ tkinter / ttk / Tkinter-widgets
# ✗ print() (alltid _log; bootstrap-fel → stderr)
# ✗ self.logger = ... (alltid module-level _log)
# ✗ f-strings i logganrop (alltid lazy %s)
# ✗ Path.replace (alltid os.replace)
# ✗ closefd=False (alltid os.fdopen i with)
# ✗ Icke-atomisk skrivning av JSON/register/settings
# ✗ word-wrap i stylesheets (alltid setWordWrap(True))
# ✗ Hårdkodade paths, färger, årtal
# ✗ >= eller ~= i requirements (alltid ==)
# ✗ TODO/placeholder/förkortad kod
# ✗ Delvis uppdaterad fil — ALLTID hela filen
# ✗ Automatiskt skapade profiler
# ✗ Att skriva kod utan uttrycklig order
# ✗ QTableWidget för >100 rader
# ✗ struktur.txt som styrande källa
# ✗ NY KOD skriver data-JSON utanför json/ (undantag: settings.json
#   och config.json-filer per spec — dessa ligger kvar)
# ✗ Icke-atomisk skrivning i json/ (samma atomiska mönster)
# ✗ Cache-/cleanup-logik som rör json/ (PROTECTED_DIRS)

# ═══════════════════════════════════════════════════════════════════════
# SEKTION K — ROTATIONSORDNING
# ═══════════════════════════════════════════════════════════════════════

# STEG 1  ▶ NÄST PÅ TUR: ui/ (theme_engine.py, main_window.py,
#          tray_icon.py, tab_manager.py) — alla 4 SAKNAS.
#          Ikon finns i assets/.
# STEG 2  : main (main.pyw, main.py, requirements.txt).
# STEG 3  : tests/ (7 filer).
# STEG 4  : 11 ogranskade plugins (core_auth först — sap_editor beror
#          på den; ts_spec_viewer: resterande filer).
# STEG 5  : Sektion Q-kraven 30–42 (importflödet med mappningsdialog;
#          rad 1 = titlar; JSON under json/mappings/).
# STEG 5b : json/-migrering (G9/Sektion Z) — görs vid respektive fils
#          rotation, INTE som separat steg.
# STEG 6+ : Rotation — komplett mapp läggs SIST i listan:
#          core/ → vin_tracking → vehicle_registry → dealers_manager →
#          ts_schema_manager → data_mapping → ts_file_generator →
#          response_viewer → ts_spec_import (EJ GÖRA OM) → core_config →
#          about → sap_editor → color_import → sap_import →
#          dispatch_viewer → identity_post → main_gui → ts_spec_viewer.

# REGEL: ALLA filer i samma mapp blir klara INNAN nästa mapp påbörjas.
#        Efter avslutad mapp/fil frågas ALLTID: "Vilken fil vill du börja med?"

# ═══════════════════════════════════════════════════════════════════════
# SEKTION L — HÅRDA KRAV
# ═══════════════════════════════════════════════════════════════════════

# L1.  Språk: Svenska. ALLTID. Byt aldrig.
# L2.  Python 3.12 + PySide6. Inga andra GUI-ramverk.
# L3.  Kod skrivs ENDAST på uttrycklig order. Inklistrad kod inväntas
#      alltid. UNDANTAG: fil som enligt spec SAKNAS får skrivas på
#      order "X — denna".
# L4.  Filer uppdateras ALLTID komplett — hela filen, körbar, inga delar.
# L5.  Uppdatera BARA den fil som skickats in.
# L6.  Uppdelning av svar ENDAST om det inte ryms; hjälpfil endast vid
#      >1800 rader (hjälpfil max 1200 rader).
# L7.  Atomisk skrivning: tempfile.mkstemp → os.fdopen → fsync → os.replace.
# L8.  Module-level _log, lazy %s-loggning.
# L9.  VERSION + AUTHOR ("Rickard Längkvist") i varje fil; dynamisk copyright.
# L10. setObjectName() för all tema-styling.
# L11. Dependencies pinnade med ==.
# L12. VIN3 = tecken 2–4 (slice [1:4]) — ÖVERALLT.
# L13. Import skriver ALDRIG över befintliga data utan användarens val.
# L14. Dokumentation per fil: vad den gör, funktioner, importer.
# L15. Spec levereras i markdown-kodruta, appnamn överst.
# L16. All ny data-JSON skrivs under json/ (atomiskt); settings.json +
#      alla config.json ligger kvar (Sektion Z).

# ═══════════════════════════════════════════════════════════════════════
# SEKTION M — ARBETSINSTRUKTION
# ═══════════════════════════════════════════════════════════════════════

#  1. Läs användarens order. Ingen order = ingen kod.
#  2. Inklistrad kod = den filen ska uppdateras. ENDAST den.
#  3. Saknad fil enligt spec + order "X — denna" = skriv från grunden.
#  4. Kontrollera filen mot Sektion E (alla 17 buggar) innan leverans.
#  5. Kontrollera mot Sektion J (förbjudet-listan).
#  6. VIN3-logik? Verifiera tecken 2–4 (slice [1:4]).
#  7. Persistens? Verifiera atomiskt mönster (L7) + json/-regeln (L16).
#  8. Loggning? _log + lazy %s, inga print().
#  9. GUI? PySide6, setWordWrap(True), setObjectName, QTableView >100 rader.
# 10. Versionsbump + ändringslogg överst i svaret.
# 11. HELA filen i ETT svar om den ryms; annars delar med "fortsätt".
# 12. Dokumentationstabell efter koden (funktioner, importer).
# 13. Synka __init__.py-version om pluginversion ändras.
# 14. Efter klar mapp: mappen läggs SIST i rotationen (Sektion K).
# 15. Avsluta ALLTID med: "Vilken fil vill du börja med?"

# ═══════════════════════════════════════════════════════════════════════
# SEKTION N — KORT FILÖVERSIKT
# ═══════════════════════════════════════════════════════════════════════

# core/ (KLAR, 12 filer): __init__ 3.1.0 · application 1.1.0 · config 1.1.0 ·
# exceptions 1.1.0 · event_bus 2.1.0 · plugin_base 3.3.0 · plugin_loader
# 2.3.0 · settings_manager 1.0.0 · logger_setup 2.0.0 · single_instance
# 1.0.0 · cache_manager 1.0.0 · autostart 1.0.0 + settings.json SCHEMA v1.

# plugins/ (16 kompletta + 1 delvis): dealers_manager 2.2.1 (5) ·
# ts_schema_manager 3.5.0 (10) · data_mapping 5.0.0 (5) ·
# ts_file_generator 6.0.0 (5) · response_viewer 2.0.0 (2) ·
# ts_spec_import 4.0.1 (3, EJ GÖRA OM) · core_config 4.0.0 (2) ·
# about 3.0.0 (2) · sap_editor 2.0.0 (4) · vin_tracking 1.1.0 (2) ·
# color_import 3.0.0 (2) · vehicle_registry 4.5.0 (3) ·
# sap_import 4.1.0 (11) · dispatch_viewer 3.1.0 (2) ·
# identity_post 3.2.0 (2) · main_gui plugin.py 6.0.1 +
# vehicle_registry_page.py 5.4.0 · ts_spec_viewer plugin.py 1.0.0 (delvis).

# SAKNAS: ui/ (4) · main.pyw/main.py/requirements.txt · tests/ (7) ·
# assets/ ✅ finns (ikon.ico + PNG).

# OGRANSKADE (11): buntpost, colors_manager, core_auth, core_logger,
# data_viewer, end_post, ereko, gui_helpers, reports, ts_excel_importer,
# vehicle_registration_post (v3.1.0 dokumenterad i W.5).

# ═══════════════════════════════════════════════════════════════════════
# SEKTION O — KVAR-REFERENS
# ═══════════════════════════════════════════════════════════════════════

# [ ] ui/theme_engine.py        [ ] ui/main_window.py
# [ ] ui/tray_icon.py           [ ] ui/tab_manager.py
# [ ] main.pyw                  [ ] main.py
# [ ] requirements.txt          [ ] tests/ (7 filer)
# [ ] 11 ogranskade plugins     [ ] Sektion Q (krav 30–42)
# [ ] VIN3-konsistens (G6)      [ ] rebuild_index gamla filer (G7)
# [ ] json/-migrering (G9/Z)    [ ] Slutverifiering (G8)

# ═══════════════════════════════════════════════════════════════════════
# SEKTION P — TEKNISKA NOTER
# ═══════════════════════════════════════════════════════════════════════

# P1. validate_latin1: stränggränssnitt mot ts_file_generator — all
#     utdata till ut/ ska klara latin-1-kodning; ogiltiga tecken
#     rapporteras med position, ersätts ALDRIG tyst.
# P2. mandatory/required: schemafält märkta mandatory blockerar spara;
#     required varnar men tillåter spara med bekräftelse.
# P3. Atomisk skrivning förekommer i: config.save, settings_manager,
#     cache_manager (skyddslista), vin_tracking, vehicle_registry
#     storage, data_mapping mappningsfiler, sap_import,
#     vehicle_import_mapping.json, column_mapping.json — ALLA under
#     json/ för data-JSON:er, via mkstemp → fdopen → fsync → os.replace.
# P4. SKIP_SHEETS: blad som hoppas över vid Excel-import
#     (25kw/25kwh/kw/kwh/info/mall/template/instruktioner +
#     endswith kw/kwh) — definieras i excel_importer.
# P5. VIN-REGLER: Full VIN = 17 tecken; VIN-kod = position 4–11;
#     VIN3 = tecken 2–4 = slice [1:4]; get_vehicle(): 3 tecken → VIN3
#     direkt; 4+ tecken → slice [1:4]. Gamla index kräver rebuild_index().
# P6. COLUMN_SYNONYMS: synonymtabell för rubrikigenkänning vid import,
#     läses via config-sökväg (BUGG #11).
# P7. 32 headers: standardrubrikuppsättningen för modellimport;
#     DEFAULT_COLUMN_MAPPING (33 fält) finns komplett i Sektion D
#     (föregående v7.2).
# P8. Modellimportflöde: fil väljs → rubriker läses (rad 1 alla blad) →
#     mappningsdialog → mappning sparas (json/mappings/, atomiskt) →
#     förhandsvisning → användarval vid konflikt → import → event
#     vehicle_registry:excel_imported.
# P9. KOMPLETT EVENTLISTA: app:initialized · app:shutdown · plugins:loaded ·
#     plugins:all_activated · plugin:activated · plugin:deactivated ·
#     config:changed · theme:changed · vehicle_registry:vehicle_added ·
#     vehicle_registry:vehicle_updated · vehicle_registry:vehicle_deleted ·
#     vehicle_registry:excel_imported · vin_tracking:report_generated ·
#     schema:version_changed · mapping:updated · tsfile:generated ·
#     response:loaded · dealers:changed.
#     (ts_schema_manager utökar med ts:schema:* — se X.7.)
# P10. Loggning v2.0.0: debug.log catch-all (10 MB × 5), errors.log
#      excepthooks (sys + threading), captureWarnings(True), @log_call,
#      LogContext, SESSION_ID = uuid[:12], enable/disable_debug_mode,
#      get_log_stats, shutdown_logging, LOGGER_MAPPINGS 70+ namn.
# P11. Smart cache v1.4: PROTECTED_DIRS = {data, logs, ut, sap, In,
#      json, .git, .venv, venv, env, .idea, .vscode, node_modules},
#      PROTECTED_FILES = {settings.json}; find_pycache_dirs (os.walk
#      topdown, followlinks=False, beskär skyddade) → purge_pycache
#      (rmtree per mapp i egen try/except) + purge_loose_pyc;
#      is_under_base-spärr; should_cleanup: smart_cache=False → True
#      (tvingad), annars mode == "prod".
# P12. Single instance: Windows CreateMutexW Global\ → Local\-fallback
#      (ERROR_ALREADY_EXISTS=183), POSIX flock LOCK_EX|LOCK_NB, PID-stale-
#      detektering (Windows OpenProcess + GetExitCodeProcess,
#      STILL_ACTIVE=259); fokus via trigger-fil <lockname>.show;
#      DEFAULT_LOCK_NAME = "ts_fordonsregistreringssystem".
# P13. Autostart: HKCU\...\CurrentVersion\Run (REG_SZ) med .bat-fallback i
#      Startup ('start "" <cmd>'); Linux ~/.config/autostart/.desktop
#      (Terminal=false); macOS ~/Library/LaunchAgents/<bundle>.plist;
#      settings["startup"] = source of truth via sync(); build_command =
#      pythonw.exe + main.pyw; DEFAULT_BUNDLE_ID =
#      "se.langkvist.ts_fordonsregistreringssystem".
# P14. Rubrik-fingerprint (NY v1.4): md5 över normaliserad rad 1 (alla
#      blad, i ordning) → används för återanvändning av sparad mappning
#      (KRAV 35/41). Fingerprintet lagras i samma JSON-fil
#      (json/mappings/vehicle_import_mapping.json).

# ═══════════════════════════════════════════════════════════════════════
# SEKTION Q — FORDONSDATAIMPORT FRÅN EXCEL (KRAV 30–42, UPPDATERAD v1.4)
# ═══════════════════════════════════════════════════════════════════════

# KRAV 30: Excel-fil med fordonsdata läggs i approtens undermapp sap/
#          eller väljs via QFileDialog.
# KRAV 31: Vid import läses RAD 1 i ALLA blad in som titlar/rubriker.
#          Samtliga unika rubriker samlas och visas i mappningsdialogen.
# KRAV 32: En DIALOG visas där användaren kopplar varje rubrik till ett
#          systemfält i formulärsform: "COMNAME = ?", "VINCODE = ?", osv.
# KRAV 33: VINCODE-matchning använder ALLTID tecken 2–4 ur VIN (slice [1:4]).
# KRAV 34: Mappningen sparas som json/mappings/vehicle_import_mapping.json
#          (atomisk skrivning). (Tidigare: data/mappings/...)
# KRAV 35: Sparad mappning ÅTERANVÄNDS automatiskt vid nästa import av
#          samma filtyp (rubrik-fingerprint, P14).
# KRAV 36: Ändring av sparad mappning kräver LÖSENORD.
# KRAV 37: Import skriver ALDRIG över befintliga poster utan användarens
#          aktiva val (dialog: hoppa över / skriv över / behåll båda).
# KRAV 38: Ogiltiga VINCODE-värden → skipped-lista, rapporteras efter import.
# KRAV 39: Efter import: event vehicle_registry:excel_imported +
#          sammanfattningsdialog (importerade / uppdaterade / skippade).
# KRAV 40: RAD 1 i ALLA blad är ALLTID kolumnrubrikerna (titlarna) vid
#          fordonsdataimport. Rad 1 läses direkt som header. Rad 1
#          tom/oläsbar → fallback-skanning rad 1–9 (loggas); hittas
#          ingen användbar header → bladet skippas och rapporteras
#          (aldrig tyst, aldrig gissning).
# KRAV 41: Dialogresultatet (rubrik ↔ målfält) sparas som JSON under
#          json/mappings/ med rubrik-fingerprint (P14) för automatisk
#          återanvändning vid nästa import av samma filtyp.
# KRAV 42: excel_importer-standarden DEFAULT_COLUMN_MAPPING + sparad
#          kopia ligger under json/mappings/column_mapping.json;
#          dialogens användarmappning under
#          json/mappings/vehicle_import_mapping.json. Vid konflikt
#          mellan dialogresultat och standard VINNER dialogresultatet.

# 5-STEGSFLÖDE:
#   STEG 1: Välj fil i sap/ eller via dialog → rubriker läses
#           (rad 1 i varje blad).
#   STEG 2: Finns sparad mappning som matchar rubrikerna (fingerprint)?
#           JA → STEG 4 (med möjlighet att redigera, lösenordsskyddat).
#           NEJ → STEG 3.
#   STEG 3: Mappningsdialog "RUBRIK = ?" per kolumn → spara JSON till
#           json/mappings/ (atomiskt, inkl. fingerprint).
#   STEG 4: Förhandsvisning + konfliktkontroll (VIN3 tecken 2–4) →
#           användarval per konflikt enligt KRAV 37.
#   STEG 5: Import → skipped-rapport → event
#           vehicle_registry:excel_imported → sammanfattning.

# ═══════════════════════════════════════════════════════════════════════
# SEKTION R — VEHICLE_REGISTRY UTVECKLINGSPLAN (15 PUNKTER, 4 FASER)
# ═══════════════════════════════════════════════════════════════════════

# R1.  MODULUPPDELNING: plugin.py delas upp i validators.py,
#      vin_history.py, storage.py, cache.py, schema_bridge.py,
#      exports.py, gui_bridge.py.
# R2.  VIN-FORMALISERING: Full VIN / VIN-kod / VIN3 dokumenteras och
#      formaliseras i kod; fältet vin_kod döps på sikt om till vin3
#      med versionerad datamigrering.
# R3.  DATAMODELLER: dataclasses VehicleRecord, VinHistoryEntry,
#      ExportBundle, SearchResult ersätter lösa dicts.
# R4.  VERSIONERAD DATAMIGRERING: _meta.version i datafiler; backup tas
#      ALLTID före migrering.
# R5.  SCHEMA-DRIVEN FÄLTHANTERING: FIELD_GROUPS / VALIDATION / DROPDOWNS /
#      MODEL_COLUMNS hämtas från ts_schema_manager med inbyggd fallback.
# R6.  GUI HELT SEPARERAT: ingen GUI-kod i registry-logiken; all
#      presentation via gui_bridge.py / main_gui.
# R7.  UTÖKAD SÖKNING: filter, fuzzy-matchning, ranking, pagination.
# R8.  UTÖKAD STATISTIK: per tillverkare / kategori / bränsle, dubbletter,
#      datakvalitetsmått.
# R9.  EVENTKONTRAKT: alla events dokumenteras med payload-format
#      (se Sektion P9).
# R10. IMPORTFLÖDEN: JSON / Excel / CSV med preview + diff; merge-
#      strategier: replace, update-if-newer, insert-only, manual.
# R11. CACHE-POLICY: metrics, selective invalidation, warmup vid aktivering.
# R12. TESTER: validator, normalize_model_year, load/save, index-rebuild,
#      CRUD, events, schema-fallback, export.
# R13. DATAKVALITET: dubbletter (VIN3 mellan år), required-fält,
#      dropdown-värden, orimliga tal (vikter, effekt, mått).
# R14. SKALNING: SQLite-option bakom ett storage-interface — JSON kvar
#      som default (json/vehicles/), bytbart utan API-ändring.
# R15. PUBLIKT API: klassificering av varje metod som stabilt / internt /
#      legacy; legacy får deprecation-logg.

# FASER:
#   FAS 1 — STABILISERING : API-dokumentation, eventkontrakt (R9),
#                            tester (R12), VIN-dokumentation (R2),
#                            datakvalitet (R13).
#   FAS 2 — STRUKTURERING : moduluppdelning (R1), GUI-brygga (R6),
#                            datamodeller (R3), migrering (R4).
#   FAS 3 — SCHEMA-FIRST  : schema-driven fälthantering (R5),
#                            importflöden (R10), sökning/statistik
#                            (R7, R8), cache (R11).
#   FAS 4 — SKALNING      : SQLite-option (R14), API-klassificering (R15).

# SLUTSATS: Vehicle Registry är systemets centrala tjänst för fordons-
# masterdata, VIN-validering och registreringshistorik, och bör vidare-
# utvecklas mot en modulär, schema-driven och testbar kärnkomponent.

# ═══════════════════════════════════════════════════════════════════════
# SEKTION S — UI- OCH TEMASYSTEM
# ═══════════════════════════════════════════════════════════════════════

# S.1 Generella UI-krav
# - PySide6-only; DPI-aware; responsiv layout med QLayout (inga fasta
#   pixelvärden).
# - ScrollArea med setWidgetResizable(True) där innehållet kan bli stort.
# - Mushjul fungerar överallt (ScrollPerPixel).
# - Word wrap via Python: setWordWrap(True), ALDRIG i stylesheet.
# - Dialoger centrerade över huvudfönster, skalar med innehåll.
# - setObjectName() på alla widgets som ska stylas.
# - Progress indicator / progressbar vid uppgifter >500 ms.
# - UI-tråden blockeras ALDRIG; tungt arbete i QThread/QRunnable.

# S.2 Tab-system
# - Standardtabbar via TabManager.
# - Visa-meny med checkbox per tab.
# - Högerklick på tabb → "Dölj denna tab".
# - "Visa alla" återställer alla tabbar.
# - Minst en tab synlig.
# - Event ui.tab_visibility_changed {tab_key, visible} publiceras.

# S.3 Tema — exakt 3 lägen
# light, dark, auto (synkar med OS).
# ### Light theme
# - Bakgrund: #F5F5F5
# - Text: #111111 (bold)
# - Knappar: #555555 bakgrund, #FFFFFF text
# - Hover: #444444, Active/Focus: accent #1565C0
# - Disabled: #CCCCCC / #888888
# ### Dark theme
# - Bakgrund: #1E1E2E
# - Text: #FFFFFF (bold)
# - Knappar: #5A5A7A bakgrund, #FFFFFF text
# - Hover: #6A6A8A, Active/Focus: accent #5C9EFF
# - Disabled: #2E2E40 / #666677
# ### StyleEngine-kontrakt
# - get_theme() → str
# - get_colors() → dict[str, str]
# - get_color(key) → str
# - apply(widget) → None
# - set_mode(mode) → None
# - generate_stylesheet() → str
# - Publicerar ui.theme_changed {theme, was}
# ### Obligatoriska färgnycklar
# background, surface, surface_alt, bg_secondary, panel_bg,
# card_bg, card_hover, input_bg, text, text_secondary, muted,
# disabled_fg, disabled_bg, inverse_text, button_bg, button_fg,
# button_hover, button_active, tab_bg, tab_fg, tab_active_bg,
# tab_active_fg, accent, accent_hover, accent_active, accent_soft,
# link, border, border_soft, success, warning, error, info,
# selection_bg, selection_fg, tooltip_bg, tooltip_fg

# S.4 QSS
# - Stylesheet genereras centralt av StyleEngine.
# - Inga hårdkodade hex-färger i UI-kod (undantag: QPainter-fallbackikoner).
# - Semantiska klasser: PrimaryButton, DangerButton, SuccessButton,
#   PageTitle, SearchGroup, ActionGroup, StatusLabel, CountLabel.

# S.5 Ikon (NY v1.4)
# - assets/ikon.ico (16, 24, 32, 48, 64, 128, 256 px) — fönster- och
#   tray-ikon (QSystemTrayIcon.setIcon + QWindowIcon).
# - assets/ikon_16/32/64/256.png som reserv (t.ex. Linux-tray).
# - Sökväg via Path bredvid applikationen, aldrig hårdkodad absolut.

# S.6 Autostart-UI (NY v1.4)
# - Settings-dialog (via tray-meny "Inställningar" eller Visa-meny)
#   innehåller checkbox "Starta med Windows" (settings["startup"]).
# - On/off → core/autostart.py set_enabled(checked) → sync().
# - Status visas (registrerat kommando, verify-resultat).

# ═══════════════════════════════════════════════════════════════════════
# SEKTION T — LOGGNINGSSYSTEM
# ═══════════════════════════════════════════════════════════════════════

# - Module-level _log = logging.getLogger(name) i varje fil.
# - Lazy %s-loggning; inga f-strings i logganrop.
# - Roterande filer: 5 MB × 3 för kategorier, 10 MB × 5 för debug.log.
# - UTF-8, format: timestamp | level | module | message.
# - Separata loggar: schema, import, export, gui, response, errors,
#   audit, vehicle, plugins, events, data_mapping, ts_file_generator.
# - debug.log: catch-all DEBUG+ från HELA systemet.
# - errors.log: sys.excepthook + threading.excepthook.
# - logging.captureWarnings(True) → errors.log.
# - @log_call-dekorator: entry/argument/resultat/tid/exception.
# - LogContext: ▶ START / ✔ KLART / ✗ FEL + ms.
# - SESSION_ID i startbanner i alla kategoriloggar.
# - enable/disable_debug_mode() runtime.
# - shutdown_logging() vid app-avslut.
# - Inga silent exceptions.
# - Äldre loggnamn (app.log, app_YYYYMMDD.log, core.log,
#   plugin_*.log, ts_file.log) fasas ut vid respektive rotation —
#   kanoniska namnen ovan gäller.

# ═══════════════════════════════════════════════════════════════════════
# SEKTION U — SMART RUNTIME & CACHE
# ═══════════════════════════════════════════════════════════════════════

# - settings.json: "mode": "dev"|"prod", "smart_cache": true.
# - DEV: cache behålls, debug aktivt.
# - PROD (eller smart_cache=false): full cleanup vid exit.
# - CacheManager:
#   * register_cache_dir(path)
#   * cleanup() — töm registrerade cache-kataloger + __pycache__ +
#     lösa .pyc/.pyo
#   * purge_pycache(root) → int
#   * install_exit_hook()
#   * should_cleanup() → bool
# - PROTECTED_DIRS (v1.4): data, logs, ut, sap, In, json, .git,
#   .venv, venv, env, .idea, .vscode, node_modules.
# - PROTECTED_FILES: settings.json.
# - Symlänkar följs aldrig.
# - Cache-rensning får ALDRIG krascha appen.
# - json/ rörs ALDRIG av cleanup (PROTECTED_DIRS).

# ═══════════════════════════════════════════════════════════════════════
# SEKTION V — LEVERANS- OCH TESTCHECKLISTA
# ═══════════════════════════════════════════════════════════════════════

# Innan en release/fil anses klar:
# □ Inga syntaktiska fel i samtliga uppdaterade filer (python -m py_compile).
# □ PySide6-miljö kan ladda alla plugins.
# □ Logger har exakt en controller och inga dubblade handlers.
# □ Tray har exakt en QSystemTrayIcon med ikon från assets/ikon.ico.
# □ Atomisk skrivning verifierad (mkstemp → os.fdopen → fsync → os.replace).
# □ Inga print(), inga f-string-loggar, inga hårdkodade färger/paths/årtal.
# □ VIN3 = tecken 2–4 överallt.
# □ Tema byte dark→light→auto fungerar utan omstart.
# □ Tray: start minimerat, enkelklick öppnar, [X]=minimize, Avsluta=full shutdown.
# □ Fordonsdata kan matas in manuellt per år och kopieras mellan år.
# □ Excel-import: rad 1 = titlar läses i alla blad; mappningsdialog
#   visas; mappning sparas i json/mappings/ (atomiskt); fingerprint
#   återanvänder sparad mappning.
# □ Generera textfil med manuellt radurval fungerar.
# □ settings.json valideras och auto-repareras.
# □ Smart cache rensar __pycache__ i PROD men bevarar user data och
#   rör ALDRIG json/.
# □ Single instance: andra instans fokuserar befintlig.
# □ Autostart syncas med settings (Registry/.bat/.desktop/.plist).
# □ Start utan terminal: main.pyw (pythonw), även .py kör tyst.

# ═══════════════════════════════════════════════════════════════════════
# SEKTION W — TILLÄGG EFTER KODFIL 10–12 (AUTO-UPPDATERING)
# ═══════════════════════════════════════════════════════════════════════

# Specen uppdateras automatiskt efter var 10:e kodfil. Nedan tillägg
# ingår efter fil 10–12 och ska betraktas som en förlängning av
# Sektion A–V ovan.

# W.1 Central config-schema-validering
# En central config-schema-validering ska säkerställa att settings.json
# och andra konfigurationsfiler alltid följer ett definierat schema.
# Krav:
# - JSON Schema-baserad validering (sparat i config/schema/ eller motsv.).
# - Validering körs vid:
#   * Applikationsstart.
#   * Innan varje sparande av config/settings.
#   * Efter manuell redigering via Settings-dialog.
# - Vid valideringsfel:
#   * Loggas tydligt i errors.log.
#   * Försök auto-repair om möjligt (t.ex. saknade fält sätts till default).
#   * Om auto-repair misslyckas → spara .corrupt-backup + ladda default.
# - Migrationsstöd: config har _meta.schema_version; vid versionsskillnad
#   körs registrerade migrationsfunktioner i ordning.
# - API: ConfigValidator.validate(data) -> (ok, errors, repaired).
# - Event: config:validated publiceras med resultat.

# W.2 Plugin health monitor
# Ett plugin health-monitor ska övervaka alla laddade plugins livscykel,
# hälsostatus och felhistorik.
# Krav:
# - PluginHealthMonitor i core (eller som egen modul) som registreras av
#   Application vid uppstart.
# - Hälsostatus per plugin: ok, warning, error, disabled.
# - Heartbeat: plugins kan pinga via event plugin:heartbeat {name, timestamp}.
# - Räknare: 3 fel inom 60 s → plugin markeras error och inaktiveras.
# - API:
#   * get_health(name) -> dict
#   * get_all_health() -> dict[name, dict]
#   * reset(name)
# - Event: plugins:health_changed {name, status, reason}.
# - UI: statusindikator i statusrad och/eller systemmeny.

# W.3 Tema-växling via systemmeny
# Användaren ska kunna byta tema direkt från system tray-menyn.
# Krav:
# - System tray-menyn innehåller undermenyn "Tema" med alternativen:
#   * Ljust
#   * Mörkt
#   * System (följer OS)
# - Vid val:
#   * Uppdatera settings.json (atomisk skrivning).
#   * Anropa StyleEngine.set_mode(mode).
#   * Publicera event theme:changed {theme, was}.
#   * Återanvänd befintlig logik i ui/theme_engine.py.
# - Inställningen återställs vid nästa uppstart.
# - Ingen omstart krävs.

# W.4 VIN3-konsistensverktyg
# Ett verktyg för att upptäcka och rätta VIN3-inkonsistenser efter
# övergången från gamla pos 5–7 till nya tecken 2–4 (slice [1:4]).
# Krav:
# - VIN3ConsistencyChecker som skannar relevanta datakällor:
#   * json/mappings/vin_registry.json
#   * json/vehicle_registry/index.json
#   * json/vehicles/{YYYY}.json
#   * VIN3-användning i kodmoduler: data_mapping, sap_import, main_gui.
# - Rapport innehåller:
#   * Antal poster som använder gammal regel.
#   * Antal poster som redan följer nya regeln.
#   * Kollisionsrisker (samma VIN3 från olika källor).
# - rebuild_index() som migrerar gamla index/årsfiler till ny VIN3-regel
#   med backup före ändring.
# - UI-kommando under Arkiv/Verktyg eller motsvarande.
# - Event: vin3:consistency_checked {ok_count, old_count, collisions}.

# W.5 Dokumentation/arkitektur — vehicle_registration_post
# ### Översikt
# Plugin:et vehicle_registration_post genererar registreringsposter
# (PT45) för Transportstyrelsen. Det är schema-drivet där ts_spec_import
# är primär källa för PT45-fältdefinitioner.
# Filer:
# - plugins/vehicle_registration_post/plugin.py — v3.1.0
# - plugins/vehicle_registration_post/__init__.py — v3.1.0
# ### Komponenter
# - RegistrationConfig — dataclass med konfiguration för dispatch/SAP-
#   kolumner, matchningsstrategi, utdatakatalog, schema-användning m.m.
# - MatchStatistics — samlar matchningsstatistik (VIN+år, VIN, ETG+år,
#   ETG, omatchade, ogiltiga VIN).
# - FieldFormatter — formaterar fält enligt TS-spec: text (vänster-
#   justerat), numeriskt (högerjusterat), datum (YYMMDD/YYYYMMDD),
#   boolean.
# - VehicleDataNormalizer — normaliserar VIN, ETG, modellår, färg,
#   återförsäljarkod samt validerar VIN-format.
# - DataMatcher — matchar dispatch-rader mot SAP-data med prioriterade
#   strategier: VIN+år → VIN → ETG+år → ETG.
# - PostGenerator — genererar 2500-teckens PT45-poster, antingen via
#   ts_spec_import-schema eller en hårdkodad fallback om schema saknas.
# - Plugin — PluginBase-klass som exponerar publik API, hanterar events
#   och konfiguration.
# ### Integrationer
# - ts_spec_import — hämtar PT45-schema (get_schema("45")).
# - sap_import — hämtar SAP-data och kan använda DateConverter.
# - core_config — läser/skriver konfiguration.
# - core_logger — loggning via module-level _log.
# ### Events
# Lyssnar:
# - registration_post:generate — triggar generering.
# - ts_spec:version_changed — invaliderar cachat schema.
# - ts_spec:imported — invaliderar cachat schema.
# Publicerar:
# - vehicle_registration_post:activated
# - registration_post:generated
# ### Publik API (Plugin)
# - initialize() -> bool
# - activate() -> bool
# - deactivate() -> bool
# - generate_posts(dispatch_file, output_file=None, sap_df=None) -> dict
# - generate_posts_from_matched(vehicles) -> dict
# - match_data(dispatch_df, sap_df) -> (matches, statistics)
# - get_config() -> dict
# - update_config(updates) -> dict
# - config_schema() -> dict
# ### Konstanter
# - POSTTYP_FORDON = "45"
# - RECORD_LENGTH = 2500
# - TS_ENCODING = "iso-8859-1"
# - VIN_LENGTH = 17

# W.6 Dokumentation — ts_spec_viewer
# ### Översikt
# Plugin:et ts_spec_viewer visualiserar, jämför och inspekterar
# Transportstyrelsens schema/specifikationer. Det är en viewer, inte
# source of truth, och använder ts_schema_manager som källa.
# Filer:
# - plugins/ts_spec_viewer/plugin.py — v1.0.0 (övriga filer saknas)
# ### Huvudfunktioner
# - Visa aktiv schema-version.
# - Lista posttyper med fältantal och total längd.
# - Detaljerad fältvy per posttyp (position, längd, typ, obligatorisk,
#   beskrivning).
# - Jämföra två versioner och visa tillagda/borttagna/ändrade posttyper.
# - Exportera schemaöversikt till JSON.
# ### Komponenter
# - Plugin(PluginBase) — public API och lifecycle.
# - TSSpecViewerWidget(QWidget) — GUI med tre flikar:
#   1. Översikt
#   2. Fältdetaljer
#   3. Jämför versioner
# ### Integrationer
# - ts_schema_manager — source of truth.
# - ts_excel_importer — valfri.
# - main_gui eller annat GUI-lager via create_widget().
# ### Events
# - Ingen egen event-lyssning.
# - Kan utökas att publicera ts_spec:viewer_refreshed om behov uppstår.
# ### Publik API
# - create_widget(parent=None) -> QWidget|None
# - compare_versions(version1, version2) -> dict
# - get_schema_info(post_type, version=None) -> dict
# - get_active_version() -> str|None
# - list_versions() -> list[str]
# - refresh()
# ### Begränsningar
# - Ändrar inte schema.
# - Importerar inte schema själv.
# - Fallback-diff på modifierade posttyper är grov (checksum eller
#   fältantal).

# W.7 Uppdaterad filöversikt
# Följande kodfiler har skapats/uppdaterats sedan senaste spec-baseline:
# - plugins/ts_spec_viewer/plugin.py — v1.0.0 (skapad)
# - plugins/ts_spec_import/plugin.py — v4.0.1 (uppdaterad från v4.0.0)
# Sektion C mappstruktur justeras härmed:
# - ts_spec_viewer — EJ GRANSKAD → plugin.py ✅ v1.0.0, övriga filer
#   (widget.py, __init__.py) saknas fortfarande.
# - ts_spec_import — v4.0.0 → v4.0.1.

# ═══════════════════════════════════════════════════════════════════════
# SEKTION X — TS_SCHEMA_MANAGER DOKUMENTATION
# ═══════════════════════════════════════════════════════════════════════

# X.1 Översikt
# ts_schema_manager är source of truth för TS-scheman i Filregistrering.
# Det hanterar schemaåtkomst, versioner, validering, export/import, diff,
# backup, restore, samarbete och rapportering. Pluginet exponerar ett
# robust API för andra plugins, samt en valfri administrativ GUI-widget
# via create_widget().
# Filer (10 st, v3.5.0):
# - plugins/ts_schema_manager/__init__.py — v3.5.0
# - plugins/ts_schema_manager/constants.py — v2.1.0
# - plugins/ts_schema_manager/models.py — v2.1.0
# - plugins/ts_schema_manager/plugin.py — v3.5.0
# - plugins/ts_schema_manager/version_manager.py — v2.1.0
# - plugins/ts_schema_manager/schema_diff.py — v2.1.0
# - plugins/ts_schema_manager/widget_utils.py — v1.0.0
# - plugins/ts_schema_manager/widget_models.py — v1.0.0
# - plugins/ts_schema_manager/widget_dialogs.py — v1.0.0
# - plugins/ts_schema_manager/widget.py — v1.0.0
# Lagring: json/schemas/<version>/ (v1.4), fallback data/schemas/ och
# legacy data/ts_specs/.

# X.2 __init__.py — Paket-entrypoint v3.5.0
# Syfte: lazy entrypoint och metadataåtkomst utan cirkulära imports.
# Metadata:
# - __plugin_name__ = "TS Schema Manager"
# - __plugin_version__ = "3.5.0"
# - __plugin_author__ = "Rickard Längkvist"
# - __plugin_description__ = "Hanterar TS-scheman och versioner (source of truth, 30 funktioner)"
# - __plugin_dependencies__ = []
# - __plugin_copyright__ = "Copyright © <år> Rickard Längkvist" (dynamiskt år)
# Lazy loading cache:
# - cached_plugin_class
# - cached_models
# - cached_constants
# Publika accessors:
# - get_plugin_class() -> Type[Plugin] — laddar .plugin.Plugin lazy.
# - get_plugin_info() -> Dict — metadata utan att ladda klassen.
# - get_models() -> Dict[str, Any] — returnerar PostSpec, FieldSpec, SpecVersion.
# - get_PostSpec(), get_FieldSpec(), get_SpecVersion() — typ-accessorer.
# - get_version_manager_class() -> Type — laddar SpecVersionManager.
# - get_constants() -> Dict[str, Any] — TS_POST_LENGTH, TS_ENCODING,
#   KNOWN_POST_TYPES.
# - get_helpers() -> Dict[str, Any] — ensure_latin1, validate_latin1,
#   sanitize_for_ts, emit_event_safe, get_plugin_safe, get_config_manager.
# - get_events() -> Type — laddar SchemaEvents.
# Dynamisk attributåtkomst (__getattr__):
# - "Plugin" → get_plugin_class()
# - "PostSpec"/"FieldSpec"/"SpecVersion" → get_models()[name]
# - "SpecVersionManager" → get_version_manager_class()
# - "SchemaEvents" → get_events()
# - "TS_POST_LENGTH"/"TS_ENCODING"/"KNOWN_POST_TYPES" → get_constants()[name]
# - helper-namn och metadata-alias VERSION, AUTHOR, NAME, DESCRIPTION,
#   COPYRIGHT
# - annars AttributeError
# __all__ exporterar metadata, accessors och lazy loaders.

# X.3 constants.py — Konstanter och hjälpfunktioner v2.1.0
# Syfte: central definitionsfil för schema-konstanter, posttypsmetadata,
# typmappningar, Latin-1-regler, kolumnmönster och eventnamn.
# Metadata:
# - VERSION = "2.1.0"
# - AUTHOR = "Rickard Längkvist"
# - dynamisk copyright
# Kärnkonstanter:
# - TS_POST_LENGTH = 2500
# - TS_ENCODING = "iso-8859-1"
# - TS_ENCODING_ALIASES = {"iso-8859-1", "iso_8859_1", "latin-1",
#   "latin1", "l1", "8859", "cp819", "ibm819"}
# - SPEC_DIR_NAME = "ts_specs" (legacy; ny: json/schemas, se Z)
# - BACKUP_DIR_NAME = "backup"
# - ACTIVE_VERSION_KEY = "ts_schema_active_version"
# - CACHE_TTL_SECONDS = 300
# Latin-1-ersättningar:
# - LATIN1_REPLACEMENTS — stor mappning från Unicode till TS-kompatibel
#   Latin-1-text (citationstecken, dash-varianter, NBSP, BOM, ellipsis,
#   bullets, euro, TM, copyright, matematiska symboler, pilar, fractions m.m.)
# - LATIN1_QUICK_REPLACE — frozenset av alla ersättbara Unicode-tecken.
# Posttyper:
# - _KNOWN_POST_TYPES (muterbar) innehåller:
#   * PT28: Identitetspost, required, position="first", count="one",
#     order=0, source="builtin"
#   * PT45: Registreringspost, required, position="middle", count="many",
#     order=50, source="builtin"
#   * PT99: Slutpost, required, position="last", count="one",
#     order=100, source="builtin"
# - KNOWN_POST_TYPES — bakåtkompatibel export.
# - _POST_TYPE_LISTENERS = [] — callbacks för posttyp-ändringar.
# Typmappningar:
# - TS_TYPE_MAPPING — normaliserar många varianter till
#   numeric/alphanumeric/date/constant.
# - FIELD_TYPE_CODES — numeric→N, alphanumeric→AN, date→D, constant→K.
# - FIELD_TYPE_FROM_CODE — omvänd mappning.
# - FIELD_PADDING_RULES — padding/justify per typ.
# Schemadefaults:
# - SCHEMA_DEFAULTS — total_length, encoding, field_type, required,
#   position, length, description, valid_values, default, source_mapping,
#   constant_value.
# - TYPICALLY_REQUIRED_FIELDS — POSTTYP, PT, VIN, CHASSINR, ORGNR, FILID,
#   ANTALPOSTER m.fl.
# - TYPICALLY_CONSTANT_FIELDS — POSTTYP, PT, FILLER, BLANK, RESERV,
#   RESERVED m.fl.
# Kolumnmönster för import:
# - COLUMN_PATTERNS — regex för name, position, length, type, mandatory,
#   description, valid_values, default.
# - detect_column_type(column_name) -> Optional[str]
# - get_column_patterns() -> Dict[str, List[str]]
# Eventnamn (SchemaEventNames):
# - LOADED = "ts:schema:loaded"
# - VERSION_CHANGED = "ts:schema:version_changed"
# - CREATED = "ts:schema:created"
# - DELETED = "ts:schema:deleted"
# - EXPORTED = "ts:schema:exported"
# - IMPORTED = "ts:schema:imported"
# - VALIDATED = "ts:schema:validated"
# - MERGED = "ts:schema:merged"
# - CLONED = "ts:schema:cloned"
# - UPGRADED = "ts:schema:upgraded"
# - BACKUP = "ts:schema:backup"
# - RESTORED = "ts:schema:restored"
# - SYNCED = "ts:schema:synced"
# - POST_TYPE_REGISTERED = "ts:schema:post_type_registered"
# - legacy: LEGACY_LOADED = "schema:loaded",
#   LEGACY_VERSION_CHANGED = "schema:version_changed"
# Hjälpfunktioner 1–10:
# 1. get_post_type_info(post_type) -> Optional[Dict]
# 2. is_known_post_type(post_type) -> bool
# 3. get_post_type_position(post_type) -> str — first/middle/last/unknown
# 4. normalize_field_type(type_str) -> str
# 5. get_field_type_code(field_type) -> str
# 6. register_post_type(...) — lägger till/uppdaterar posttyp dynamiskt
# 7. unregister_post_type(post_type) -> bool — tar bort icke-builtin
# 8. get_all_post_types() -> List[Dict]
# 9. validate_post_length(length) -> (bool, str)
# 10. get_encoding_errors(text) -> List[Dict]
# Hjälpfunktioner 11–20:
# 11. get_schema_defaults() -> Dict
# 12. sanitize_for_encoding(text, replacement='?') -> str
# 13. ensure_latin1(text) -> str
# 14. validate_latin1(text) -> (bool, invalid_positions, invalid_chars)
# 15. get_post_types_by_position(position) -> List[str]
# 16. get_required_post_types() -> List[str]
# 17. get_padding_rule(field_type) -> Dict
# 18. is_typically_required(field_name) -> bool
# 19. is_typically_constant(field_name) -> bool
# 20. add_post_type_listener(callback) -> bool /
#     remove_post_type_listener(callback) -> bool
# Diagnostic:
# - get_constants_info() -> Dict — version, author, copyright,
#   ts_post_length, ts_encoding, known_post_types, field_types,
#   latin1_replacements_count, column_pattern_types, post_type_listeners.

# X.4 models.py — Datamodeller v2.1.0
# Syfte: definiera source of truth för hur TS-poster modelleras,
# formateras, valideras och serialiseras.
# Logger:
# - Module-level _log = logging.getLogger(__name__) (eller fallback).
# Konstanter:
# - TS_POST_LENGTH = 2500
# - TS_ENCODING = "iso-8859-1"
# Latin-1 utilities:
# - ensure_latin1(text, log_warnings=False) -> str
# - validate_latin1(text) -> (bool, List[str])
# - sanitize_for_ts(text) -> str
# Enum:
# - FieldType(str, Enum) — NUMERIC, ALPHANUMERIC, DATE, CONSTANT
#   med padding_char, alignment, code och from_string(value).
# FieldSpec (dataclass):
# - Fält: name, position, length, field_type, mandatory, description,
#   valid_values, default, source_mapping, constant_value.
# - Validering i __post_init__: position >= 1, length >= 1,
#   normaliserad field_type.
# - Properties: end_position, required (alias mandatory),
#   field_type_enum, type_code, position_range.
# - Metoder:
#   * clone(*overrides) -> FieldSpec
#   * shift_position(delta) -> FieldSpec
#   * overlaps_with(other) -> bool
#   * contains_position(position) -> bool
#   * format_value(value) -> str — exakt length, Latin-1-safe
#   * validate_value(value) -> (bool, error)
#   * to_dict(), from_dict(data)
# PostSpec (dataclass):
# - Fält: post_type, name, total_length, fields, description, version,
#   source_file, created_at, checksum.
# - __post_init__: sätter created_at, sorterar fields, beräknar checksum.
# - calculate_checksum() — md5 av fältdefinitioner, 12 tecken.
# - Properties: is_valid, calculated_length, coverage, field_count,
#   required_field_count, optional_field_count.
# - Fältåtkomst:
#   * get_field(name), get_field_at(position),
#     get_fields_in_range(start, end), get_fields_by_type(field_type),
#     get_required_fields(), get_optional_fields(),
#     has_field(name), find_fields(pattern)
# - Modifiering:
#   * clone(*overrides), add_field(...), remove_field(name),
#     update_field(name, ...), merge_fields(other)
# - Analys:
#   * get_position_map(), find_gaps(), find_overlaps(),
#     get_gaps(), get_overlaps()
# - Formatering/validering:
#   * format_record(data) -> str — huvudmetod, exakt total_length,
#     Latin-1-safe, använder field.name eller source_mapping.
#   * validate_record(data) -> (bool, List[str])
#   * validate_structure() -> List[str]
# - Serialisering: to_dict(), from_dict(), to_json(indent=2),
#   from_json(json_str).
# - Dunder: __iter__, __len__, __getitem__, __contains__, __repr__.
# SpecVersion (dataclass):
# - Fält: version, created_at, source_file, post_types, description,
#   is_active.
# - Properties: age_days, post_type_count.
# - Metoder: to_dict(), from_dict(), __repr__().
# Factory-funktioner:
# - create_empty_post_spec(post_type, name=None, total_length=2500,
#   version="")
# - create_field_for_gap(gap, name=None, field_type="alphanumeric",
#   mandatory=False)
# - create_minimal_spec(post_type) — alias för ovan.

# X.5 plugin.py — TS Schema Manager Plugin v3.5.0
# Syfte: central source of truth, 30 publika funktioner.
# Metadata:
# - VERSION = "3.5.0", AUTHOR = "Rickard Längkvist",
#   NAME = "TS Schema Manager",
#   DESCRIPTION = "Hanterar TS-scheman och versioner (source of truth, 30 funktioner)",
#   DEPENDENCIES = [].
# Konstanter:
# - TS_POST_LENGTH, TS_ENCODING, SPEC_DIR_NAME, BACKUP_DIR_NAME,
#   ACTIVE_VERSION_KEY, CACHE_TTL_SECONDS.
# - KNOWN_POST_TYPES — PT28, PT45, PT99.
# Logger:
# - Module-level _log.
# Events (SchemaEvents):
# - SCHEMA_LOADED, VERSION_CHANGED, SCHEMA_CREATED, SCHEMA_DELETED,
#   SCHEMA_EXPORTED, SCHEMA_IMPORTED, SCHEMA_VALIDATED, SCHEMA_MERGED,
#   SCHEMA_CLONED, SCHEMA_UPGRADED, SCHEMA_BACKUP, SCHEMA_RESTORED,
#   SCHEMA_SYNCED, plus legacy-alias.
# Helpers:
# - emit_event_safe(app, event_name, data=None)
# - get_plugin_safe(app, name)
# - get_config_manager(app)
# - ensure_latin1(text), validate_latin1(text), sanitize_for_ts(text)
# Data models:
# - FieldSpec, PostSpec, SpecVersion (se X.4).
# SpecVersionManager (lokal i plugin.py):
# - Ansvar: lista/ladda/spara versioner, aktiv version, backup/restore,
#   historik, atomisk skrivning.
# - __init__(specs_dir, config_manager=None)
# - active_version property med cache/config/fallback.
# - list_versions(), list_backups(), version_exists()
# - get_spec(post_type, version=None), load_version(version, use_cache=True)
# - create_version(version, specs, source_file="", description="", set_active=True)
# - save_spec(post_type, spec, version), delete_version(version)
# - compare_versions(version1, version2), get_stats(), clear_cache()
# - _write_json_atomic(path, data), _add_to_history(...),
#   get_history(post_type)
# Plugin-klass (PluginBase):
# - Lifecycle:
#   * initialize() — loggar banner, skapar SpecVersionManager,
#     registrerar app.ts_schema_manager = self.
#   * activate() — sätter is_active, detekterar collaborators,
#     emitterar ts:schema:loaded och schema:loaded.
#   * deactivate() — rensar cache.
# - Internal:
#   * _resolve_specs_dir() — config/core_config → json/schemas
#     (fallback data/schemas, legacy data/ts_specs)
#   * _detect_collaborators() — ts_spec_import, ts_excel_importer
#   * _ensure_version_manager(), _clear_cache(version=None),
#     _notify_subscribers(event_type, data)
# Public API — schema access:
# - get_schema(post_type, version=None) -> Optional[PostSpec]
# - get_schema_safe(...) — alias
# - get_all_schemas(version=None, use_cache=True) -> Dict[str, PostSpec]
# - has_schema(post_type, version=None) -> bool
# Public API — version management:
# - get_active_version() -> Optional[str]
# - set_active_version(version) -> bool — emit event + notify subscribers
# - list_versions() -> List[SpecVersion]
# - version_exists(version) -> bool
# - delete_version(version) -> bool — emit event
# - compare_versions(version1, version2) -> Dict[str, List[str]]
# Public API — create/save:
# - create_version(version, specs, source_file="", source="",
#   description="", set_active=True) -> bool
# - save_schema(post_type, spec, version=None) -> bool
# Public API — formatting & validation:
# - format_record(post_type, data, version=None) -> Optional[str]
# - validate_record(post_type, data, version=None) -> (bool, List[str])
# Funktioner 1–10:
# 1. export_schema_to_json(post_type, output_path, version=None,
#    pretty=True) -> bool
# 2. import_schema_from_json(input_path, version=None,
#    set_active=False) -> Optional[PostSpec]
# 3. validate_schema_structure(post_type, version=None) -> Dict
# 4. get_schema_diff(post_type, version1, version2) -> Dict
# 5. merge_schemas(version1, version2, target_version,
#    conflict_resolution="version2") -> bool
# 6. get_field_by_position(post_type, position, version=None) -> Optional[FieldSpec]
# 7. get_coverage_map(post_type, version=None) -> Dict
# 8. clone_version(source_version, target_version,
#    modifications=None) -> bool
# 9. auto_upgrade_schema(post_type, from_version, to_version) -> Optional[PostSpec]
# 10. get_schema_metadata(post_type, version=None) -> Dict
# Funktioner 11–20:
# 11. subscribe_to_changes(callback) / unsubscribe_from_changes(callback)
# 12. get_field_mapping(post_type, version=None) -> Dict
# 13. create_empty_schema(post_type, name=None, total_length=2500) -> PostSpec
# 14. get_schema_history(post_type) -> List[Dict]
# 15. validate_data_batch(post_type, data_list, version=None) -> Dict
# 16. get_required_fields(post_type, version=None) -> List[str]
# 17. find_field_by_name(post_type, pattern, version=None) -> List[Dict]
# 18. get_schema_checksum(post_type, version=None) -> Optional[str]
# 19. backup_all_schemas(backup_name=None) -> Dict
# 20. restore_from_backup(backup_name, overwrite=False) -> Dict
# Funktioner 21–30:
# 21. sync_with_ts_spec_import(direction="from") -> Dict
# 22. get_collaboration_status() -> Dict
# 23. validate_ts_output(line) -> Dict
# 24. get_field_statistics(version=None) -> Dict
# 25. export_all_versions(output_dir) -> Dict
# 26. import_from_excel_spec(filepath, version=None,
#     set_active=True) -> Dict
# 27. get_schema_as_dataframe(post_type, version=None) -> Optional[pandas.DataFrame]
# 28. suggest_field_mapping(post_type, data_columns, version=None) -> Dict
# 29. validate_latin1_compatibility(post_type, data, version=None) -> Dict
# 30. get_comprehensive_report() -> Dict
# Compatibility & utility:
# - get_post_types(version=None) -> List[str]
# - is_known_post_type(post_type) -> bool
# - get_known_post_type_info(post_type) -> Optional[Dict]
# - refresh() — cache refresh + återdetektering av collaborators
# - get_diagnostics() -> Dict

# X.6 version_manager.py — Versionshantering v2.1.0
# Syfte: hantera lagring, laddning, aktiv version, historik, jämförelse,
# export/import, backup, integritetskontroll och metadata för
# schema-versioner.
# Lagring (v1.4):
# json/schemas/<version>/
# ├── manifest.json
# ├── PT28.json
# ├── PT45.json
# └── PT99.json
# (fallback: data/schemas/<version>/, legacy: data/ts_specs/<version>/)
# Lazy imports:
# - _models_cache = {}, _get_FieldSpec(), _get_PostSpec(),
#   _get_SpecVersion(), _get_models() — undviker cirkulära imports.
# Konstanter:
# - TS_POST_LENGTH, TS_ENCODING, ACTIVE_VERSION_KEY,
#   BACKUP_DIR_NAME = "backup", HISTORY_FILE_NAME = "history.json",
#   MAX_HISTORY_ENTRIES = 500, CACHE_TTL_SECONDS = 300.
# VersionHistoryEntry (dataclass):
# - timestamp, action, version, details={}
# - to_dict(), from_dict(), __repr__().
# SpecVersionManager:
# - __init__(specs_dir, config_manager=None) — skapar kataloger,
#   initierar cache, historik och callbacks.
# - Properties:
#   * active_version — cache → config → senaste version
#   * active_version setter — sparar, loggar, notifierar
#   * backup_dir, history_file
# - Versionslistning:
#   * list_versions() -> List[SpecVersion]
#   * list_backups() -> List[Dict]
#   * get_version_dir(version) -> Path
#   * version_exists(version) -> bool
# - Laddning:
#   * load_version(version, use_cache=True) -> Dict[str, PostSpec]
#   * get_spec(post_type, version=None) -> Optional[PostSpec]
# - Skapa/spara:
#   * create_version(version, specs, source_file="", description="",
#     set_active=True)
#   * save_spec(post_type, spec, version)
#   * _write_json_atomic(path, data)
# - Borttagning:
#   * delete_version(version) — förbjuder borttagning av aktiv version
# - Jämförelse:
#   * compare_versions(version1, version2) -> Dict[post_type, List[str]]
#   * _compare_specs(spec1, spec2) -> List[str]
# - Nya funktioner 1–10:
#   1. export_version_to_dir(version, output_dir) -> Dict
#   2. import_version_from_dir(input_dir, version=None, set_active=False) -> Dict
#   3. get_version_metadata(version) -> Dict
#   4. rename_version(old_name, new_name) -> bool
#   5. duplicate_version(source_version, new_version) -> bool
#   6. get_all_post_types() -> Dict[post_type, List[version]]
#   7. find_spec_by_field(field_name, version=None) -> List[Dict]
#   8. validate_version_integrity(version) -> Dict
#   9. compact_version(version) -> Dict
#   10. get_version_timeline() -> List[Dict]
# - Historik:
#   * _load_history(), _save_history(), _add_history(action, version, details)
#   * get_history(post_type=None, limit=50) -> List[Dict]
# - Callbacks:
#   * subscribe(callback), unsubscribe(callback), _notify_change(event_type, data)
# - Utilities:
#   * clear_cache(version=None)
#   * get_stats() -> Dict
#   * __repr__()
# Exporteras (__all__):
# - SpecVersionManager, VersionHistoryEntry, VERSION, AUTHOR,
#   TS_POST_LENGTH, TS_ENCODING, ACTIVE_VERSION_KEY,
#   BACKUP_DIR_NAME, get_copyright_string

# X.7 Händelser (ts_schema_manager)
# Primära event-namn:
# - ts:schema:loaded
# - ts:schema:version_changed
# - ts:schema:created
# - ts:schema:deleted
# - ts:schema:exported
# - ts:schema:imported
# - ts:schema:validated
# - ts:schema:merged
# - ts:schema:cloned
# - ts:schema:upgraded
# - ts:schema:backup
# - ts:schema:restored
# - ts:schema:synced
# - ts:schema:post_type_registered
# Legacy-alias (för bakåtkompatibilitet):
# - schema:loaded
# - schema:version_changed

# X.8 Roll i systemet
# ts_schema_manager är primärt schema-API för:
# - ts_spec_import
# - ts_excel_importer
# - ts_file_generator
# - identity_post
# - vehicle_registration_post
# - end_post
# - main_gui
# - data_viewer
# Alla schema-konsumerande plugins ska hämta fältdefinitioner,
# formatteringsregler och versioner via detta plugin.

# ═══════════════════════════════════════════════════════════════════════
# SEKTION Y — TILLÄGG EFTER KODFIL 20–25 (AUTO-UPPDATERING)
# ═══════════════════════════════════════════════════════════════════════

# Specen uppdateras automatiskt efter var 10:e kodfil. Denna sektion
# dokumenterar filer 16–25: komplett implementation av ts_schema_manager
# inklusive GUI-widget.

# Y.1 Widget-arkitektur
# ts_schema_manager tillhandahåller en administrativ widget som kan
# skapas via Plugin.create_widget(parent=None). Widgeten registreras
# INTE automatiskt som en flik; det är upp till main_gui eller annan
# plugin att integrera den.
# Filer:
# - plugins/ts_schema_manager/widget_utils.py — v1.0.0
# - plugins/ts_schema_manager/widget_models.py — v1.0.0
# - plugins/ts_schema_manager/widget_dialogs.py — v1.0.0
# - plugins/ts_schema_manager/widget.py — v1.0.0

# Y.2 widget_utils.py
# Gemensamma GUI-hjälpmedel:
# - make_button, make_label, make_line_edit, build_button_row
# - Informations-/varnings-/fel-/frågedialoger
# - Latin-1-validering av inmatningsfält
# - Tema-färgaccess via QApplication.instance().theme_engine
# - Statusfärgning och fältsammanfattning

# Y.3 widget_models.py
# QAbstractTableModel-implementationer:
# - PostTypesTableModel — posttyper med fältantal, täckning, version
# - FieldsTableModel — fält med position, längd, typ, obligatorisk-flagga
# - VersionsTableModel — versioner med aktiv-markerare
# - HistoryTableModel — historikposter
# Alla modeller stödjer QSortFilterProxyModel för sökning.

# Y.4 widget_dialogs.py
# Dialoger för CRUD av schemadata:
# - VersionDialog — skapa/redigera version
# - PostTypeDialog — skapa/redigera posttyp
# - FieldDialog — skapa/redigera fält med typ-validering
# - DiffDialog — HTML-visning av versionsdiff
# - ImportDialog — importera schema från JSON
# Basklass BaseDialog ger gemensam konfiguration och validering.

# Y.5 widget.py
# TSSchemaManagerWidget är huvudwidget med sex flikar:
# 1. Översikt — lista posttyper, sök, ny posttyp, import JSON
# 2. Fält — redigera fält för vald posttyp
# 3. Versioner — hantera versioner, sätt aktiv, backup
# 4. Jämför — diff mellan två versioner
# 5. Historik — versionshistorik
# 6. Diagnostik — komplett diagnostikrapport
# Widgeten använder schema_diff.diff_versions() för jämförelser och
# plugin.create_version()/save_schema() för persistens.

# Y.6 Uppdaterad filöversikt
# Följande kodfiler har skapats/uppdaterats sedan senaste spec-baseline:
# - plugins/ts_schema_manager/constants.py — v2.1.0 (skapad)
# - plugins/ts_schema_manager/models.py — v2.1.0 (skapad)
# - plugins/ts_schema_manager/version_manager.py — v2.1.0 (skapad)
# - plugins/ts_schema_manager/schema_diff.py — v2.1.0 (skapad)
# - plugins/ts_schema_manager/plugin.py — v3.5.0 (skapad)
# - plugins/ts_schema_manager/__init__.py — v3.5.0 (skapad)
# - plugins/ts_schema_manager/widget_utils.py — v1.0.0 (skapad)
# - plugins/ts_schema_manager/widget_models.py — v1.0.0 (skapad)
# - plugins/ts_schema_manager/widget_dialogs.py — v1.0.0 (skapad)
# - plugins/ts_schema_manager/widget.py — v1.0.0 (skapad)
# Sektion C mappstruktur justeras härmed:
# - ts_schema_manager — EJ GRANSKAD → ✅ v3.5.0 med widget (10 filer).

# ═══════════════════════════════════════════════════════════════════════
# SEKTION Z — JSON-KATALOGEN (json/) — NY v1.4
# ═══════════════════════════════════════════════════════════════════════

# SYFTE:
# En enda katalog (projektrot/json/) för ALLA data-JSON:er i systemet.
# Ger enhetliga sökvägar, enkel backup och tydlig gräns mot cache/temp
# (cache_manager skyddar json/).

# STRUKTUR:
# json/
# ├── mappings/      kolumn-/importmappningar + vin_registry
# ├── schemas/       versionerade TS-scheman (+ backup/)
# ├── vehicles/      fordonsdata per år {YYYY}.json
# ├── vehicle_registry/  registered_vins.json, index.json
# ├── sap_cache/     SAP-cache (JSON-filer)
# ├── vin_register/  {YYYY}/{MM}.json (vin_tracking)
# └── rapporter/     vin_rapport_{YYYY}.json (vin_tracking)

# REGLER:
# 1. All ny kod skriver data-JSON endast under json/.
# 2. Skrivning sker ALLTID atomiskt (mkstemp → fdopen → fsync →
#    os.replace) — samma mönster som övriga kritiska filer.
# 3. json/ ingår i cache_manager PROTECTED_DIRS — rörs ALDRIG av
#    cleanup, __pycache__-rensning eller annan städning.
# 4. UNDANTAG — ligger kvar på nuvarande plats:
#    settings.json (rot), config.json (rot), core/config.json,
#    data/*/config.json och alla övriga config.json-filer i projektet.
# 5. Icke-JSON-filer i data/-mappar (t.ex. exports/, binärt innehåll)
#    flyttas INTE.

# MIGRERING (vid respektive fils rotation, G9):
#   Gammal sökväg                            → Ny sökväg
#   data/mappings/column_mappings.json       → json/mappings/column_mappings.json
#   data/mappings/imported_headers.json      → json/mappings/imported_headers.json
#   data/mappings/vin_registry.json          → json/mappings/vin_registry.json
#   data/mappings/vehicle_import_mapping.json→ json/mappings/vehicle_import_mapping.json
#   data/vehicle_registry/column_mapping.json→ json/mappings/column_mapping.json
#   data/vehicle_registry/registered_vins.json → json/vehicle_registry/registered_vins.json
#   data/vehicle_registry/index.json         → json/vehicle_registry/index.json
#   data/vehicles/{YYYY}.json                → json/vehicles/{YYYY}.json
#   data/schemas/** (legacy data/ts_specs/**) → json/schemas/**
#   data/sap_cache/*.json                    → json/sap_cache/
#   data/vin_register/{YYYY}/{MM}.json       → json/vin_register/{YYYY}/{MM}.json
#   ut/rapporter/vin_rapport_{YYYY}.json     → json/rapporter/vin_rapport_{YYYY}.json
#   data/ts_excel_importer/import_history.json → json/mappings/import_history.json
#   data/ts_file_generator/file_id_series.json → json/mappings/ (vid rotation)

# FALLBACK-REGEL:
# Efter migrering av en fil läses den gamla sökvägen som fallback OM
# den nya saknas (loggas som INFO, en gång). Skrivning sker ALLTID
# till den nya sökvägen. Ingen data kopieras automatiskt — filen
# flyttas (os.replace) vid första migrerande skrivningstillfälle om
# den gamla finns och den nya saknas.

# ANSVAR:
# Varje plugin migrerar sina egna filer vid sin rotation. Inga
# korsberoenden: data_mapping rör bara json/mappings/, ts_schema_manager
# bara json/schemas/, osv. vehicle_registry excel_importer äger
# json/mappings/column_mapping.json; Sektion Q-flödet (dialog) äger
# json/mappings/vehicle_import_mapping.json.

# ═══════════════════════════════════════════════════════════════════════
# SLUT PÅ CONSOLIDATED MASTER SPEC v1.4 (ERSÄTTER v1.3 + v7.2 + v7.3)
# ═══════════════════════════════════════════════════════════════════════
# Nästa steg (inväntar order): ui/theme_engine.py — denna, eller annan
# fil enligt Sektion K ("X — denna").
