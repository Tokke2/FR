# Fordonsreg – logotyp och ikon

Trycklogotypen och denna beskrivning ingår i Fordonsregs releasearkiv och
levereras med programmet, utan separat nedladdning. Uppdateraren tar med dessa
namngivna filer och säkerhetskopierar tidigare versioner före byte.

- `fordonsreg-logo.svg` är den frilagda trycklogotypen: ett FR-monogram där
  R:ets ben pekar ner mot en väg. Allt är **fyllda vektorformer** – ingen text,
  ingen rasterbild, inga streck som kan bli olika tjocka i olika program.
  Normal storlek är 112 × 112 mm; proportionerna kan skalas.
- `fordonsreg-logo-tryck.pdf` är tryckoriginalet: en sida på exakt 112 × 112 mm
  med samma vektorbanor (ingen rasterbild inbäddad). Skicka den till tryckeriet
  när PDF efterfrågas.
- Formerna är ritade på ett 280 × 280-rutnät med jämna kanter, så att de är
  skarpa även i 16 px. Varje färg är ett eget namngivet lager:
  `lager-platta` (endast appikonen), `lager-monogram` och `lager-vag`.
  Bokstäverna heter `f` och `r`, vägen `vag-turkos` och `vag-orange`. Ett
  tryckeri kan byta färg per lager utan att röra formen.
- `fordonsreg-icon.svg` har samma motiv på en vit rundad platta för appikonen.
  Programmets `ikon_*.png` och `ikon.ico` är renderade från detta original.
- Färgpaletten är angiven i sRGB: marinblått **#071F40**, turkos **#2DE8F5**
  och orange **#E75E1D**. Plattan i appikonen är vit **#FFFFFF**.
- SVG-färgerna är RGB, inte en CMYK- eller Pantone-master. Be tryckeriet
  konvertera med rätt ICC-profil, material och tryckmetod och godkänn ett
  färgprov. Logotypen har transparent bakgrund och ska i första hand ligga på
  vit eller ljus yta.

## Så återskapas rasterfilerna

Alla PNG- och ICO-filer är renderade från `fordonsreg-icon.svg` med samma
vektorkälla, aldrig uppskalade från en mindre bild:

| Fil | Storlek | Användning |
| --- | --- | --- |
| `ikon_16.png` | 16 × 16 | menyrad, systemfält |
| `ikon_32.png` | 32 × 32 | fönsterikon på äldre skärmar |
| `ikon_64.png` | 64 × 64 | Aktivitetsfältet i Windows |
| `ikon_256.png` | 256 × 256 | aktivitetsfält och aktivitetsvy i hög DPI |
| `ikon.ico` | 16–256 | Windows-ikon med alla storlekar i samma fil |
| `assets/fordonsreg-source.png` | 1024 × 1024 | dokumentation, presentationsbilder |

Renderingen görs med `resvg_py` direkt från `fordonsreg-icon.svg`, i varje
storlek för sig – ingen fil skalas upp i efterhand. Samma vektorkälla används
till alla storlekar, så ikonen är identisk i menyraden och i aktivitetsfältet.

Uppdateraren tar med `fordonsreg-logo.svg`, `fordonsreg-icon.svg`, `ikon*.png`,
`ikon.ico` och den här beskrivningen, och säkerhetskopierar tidigare versioner
före byte.
