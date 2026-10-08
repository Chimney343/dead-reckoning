# Ship losses map: extraction and visualisation plan

Status: draft, 2026-10-04. Hand-off plan for the implementing agent.

The source review below was run on 2026-10-04 against the files `python -m fetch get` downloaded that day. The Wikimedia harvesters (Wikipedia, Wikidata) did not run because `DR_CONTACT` was unset; their sections rely on the harvester code and one live page check. Every column name quoted here was read from the real file unless marked otherwise.

## 1. Goal and scope

Build one table of ship losses from every downloaded source **except Three Decks**, then plot it on an interactive world map. For each lost ship the table holds, where the source has it:

1. **Where it was lost.** Coordinates, or a place name that can be geocoded, even roughly.
2. **Country of origin.** The polity where it was built or registered, or whose flag it first flew.
3. **Owner at loss.** If the ship changed hands (captured, condemned, sold, renamed), the polity, and the owner where known, that held it when it was lost.
4. **Cause of loss.** Wrecked, foundered, burnt, sunk in action, scuttled, and so on.

Every derived value keeps its raw source text and the id of the source record.

**Where it lives:** `analyses/01-ship-losses/`, following [analyses/README.md](../../analyses/README.md). Code and small curated tables sit there; generated tables and maps go to its `outputs/`. Nothing is written into `data/`.

**Out of scope:**
- Three Decks: another agent owns it, and `data/raw/threedecks/` is reserved. Section 11 leaves a join hook.
- New scraping. The only network work is Phase 0: running existing harvesters, one harvester extension, and two small gazetteer downloads.
- Lloyd's List OCR (see §2.5).

## 2. Source review

### 2.1 Coverage at a glance

"≤1860" counts rows whose loss year is 1860 or earlier, the project's Age of Sail window. Owner and origin columns say which field carries the information; "–" means the source has none.

| Source (manifest id) | Records | ≤1860 | Location | Origin | Owner at loss / change | Cause | Verdict |
|---|---|---|---|---|---|---|---|
| UKHO wrecks (`ukho-wrecks-extra`) | 102,625 | 275 | coords, surveyed | text ("BUILT IN … BY …") | `flag` + text "OWNED AT TIME OF LOSS BY …" (7,414 rows) | text | core |
| Western Australia (`wa-shipwrecks`) | 305 | 41 | coords | `country_bu`, `port_built`, `port_regis` | `owner` | `sunk_code` + `sinking` | core |
| Zenodo shipWrecks (`zenodo-shipwrecks`) | 4,463 | 529 | coords on 2,282 + region text | – | `FLAG` (flag at loss) | `NOTES` text | core |
| Wikipedia shipwreck lists (`wp-en-shipwrecks`) | not fetched; ~200 pages | nearly all | text, some `{{coord}}` | – | State column + capture sentences | description text | core, largest pre-1860 source |
| SlaveVoyages (`slavevoyages`) | 36,108 voyages | nearly all | voyage-stage place codes | `NATIONAL`, `PLACCONS`, `PLACREG` | `OWNERA`–`OWNERP`; captor in `FATE`/`FATE3` | `FATE` codes | core |
| Prize Papers (`prize-papers`) | 4,215 ships, 2,857 captures | all | capture place + polygon | `MD_SHIP_RULING_AUTHORITY` | capture events | – (captures, not sinkings) | core for ownership |
| Ireland WIID (`ireland-wiid`) | 17,981 | 7,714 | coords on 3,564 (146 ≤1860); `Place of Loss` text | text only ("Brig of Greenock") | – | `Description` text (3,728 useful) | secondary |
| INFOMAR (`ireland-infomar`) | 608 | few | coords, surveyed | – | – | – | coordinates for WIID |
| EMODnet (`emodnet-shipwrecks`) | 7,073 | 157 | coords | – | – | `sink_context` (2,046) | secondary |
| Nova Scotia (`novascotia-shipwrecks`) | 4,939 | 621 | `Location of wreck` text | – | – | `Event` (controlled) | secondary |
| Dutch-Asiatic Shipping (`dutch-asiatic-shipping`) | 8,194 voyages | all | text in `Particulars` | Dutch Republic (implied) | VOC + `Chamber` | text in `Particulars` (~909 loss mentions) | secondary |
| Todo a Babor (`todo-a-babor`) | 2 pages, ~100 list items | all | battle or place name | Spain / Great Britain | captures listed | section heading | secondary |
| IBM maritime archives (`ibm-maritime-archives`) | 710 + 120 curated | all | coords + `uncertainty_km` | implied by archive | – | `loss_cause` | cross-check + T3 extras |
| Wikidata (`wikidata`) | not fetched | – | P625, battle coords | P17, P8047 | P137, P793 events | P793 events | optional + battle gazetteer |

### 2.2 Core sources

**UKHO wrecks and obstructions.** Read `data/raw/ukho-wrecks/extra/ukho-wrecks-extra.zip` → `Wrecks.txt`: a quoted, tab-separated UTF-8 file. Use it rather than the shapefile, because the DBF cuts text at 254 characters and `circumstances_of_loss` runs to 2,205. `ukho-wrecks.xlsx` holds only the field dictionary; use it for the code lists.
- Location: `latitude`/`longitude` in degrees and decimal minutes, e.g. `5 33.535 S` / `110 57.76 E`, on WGS84. Precision is `surveyed`.
- Flag at loss: `flag`, an ISO 3166-1 alpha-2 code, set on 20,190 rows (GB 8,461, DE 1,081, FR 980, …).
- Owner and cause: `circumstances_of_loss`, upper-case free text such as `MINED.`, `SCUTTLED.`, `SANK, CAUSE NOT REPORTED.` or `BUILT IN 1853 BY BANK-QUAY FOUNDRY LTD. OWNED AT TIME OF LOSS BY …`. Prefixes like `EX-SEA TRANSPORTER '86` record former names.
- Date: `date_sunk` as `YYYYMMDD`, `YYYYMM` or `YYYY`; 21k rows have one.
- Filter: drop rows where `obstruction_category` is set and `wreck_category` is empty (foul ground, snags, diffusers, anchors). `general_comments` and `surveying_details` are extra text.
- Licence OGL.

**Western Australia (WAM-002).** `wa-shipwrecks.geojson`, 305 point features. Location: `lat`/`long`, with `position_i` (GPS, Chart, SkyView2004) giving the fix method. Origin: `country_bu`, `port_built`, `port_regis`. Owner: `owner` (161 rows), plus `master`. Cause: `sunk_code`, a controlled list (Wrecked and sunk 102, Scuttled 23, Abandoned 14, Foundered 14, Burnt 8, …), and `sinking`, free text such as "Struck reef". Route: `port_from`/`port_to`. Drop `Refloated` and `Brought on dry land for display`. CC-BY-4.0.

**Zenodo shipWrecks.csv.** 4,463 rows.
- Location: `COORDINATES` as `lat;lon` with a trailing U+FEFF on 2,151 rows. `ZONA1`–`ZONA4` give a region path (country → state → locality) for geocoding the rest.
- Flag: `FLAG` (2,281 rows; Royal Navy, United Kingdom, French Navy, …).
- Cause: `NOTES`, e.g. "A ship of the line wrecked off Le Croisic."
- Date: `SUNK DATE` as `dd/mm/yyyy`. 460 rows read `01/01/YYYY`; treat those as year precision.
- It looks scraped from Wikipedia lists, so expect overlap with them (§6.2). CC-BY-4.0.

**Wikipedia shipwreck lists.** These are not on disk yet (Phase 0.1). The harvester saves one JSON file per page at `data/raw/wikipedia/en-shipwrecks/<title>.json`, with keys `title`, `revid`, `wikitext`, `html` and `url`. The page layout was checked on "List of shipwrecks in 1805":
- Layout: an h2 per month, an h3 per day, and "Unknown date" sections. Each section holds a wikitable with the columns `Ship | State | Description`.
- `State`: a flag icon plus linked polity text (Royal Navy, United Kingdom, Portugal). That is the **flag at loss**.
- `Description`: cause, place and route ("The ship was wrecked near Barmouth, Caernarvonshire, United Kingdom. She was on a voyage from Porto to London"). Some rows carry a `{{coord}}`, rendered in the HTML as `span.geo` decimals. Capture-then-loss sequences also appear ("captured off Berbice by a French privateer. She was plundered and sunk."), which give both an ownership change and a cause.
- Parse the HTML with lxml (already a dependency), and fall back to the wikitext for coordinates.
- Licence CC-BY-SA-4.0.

**SlaveVoyages.** `tastdb-exp-2019.csv`: 36,108 voyages, `YEARAM` 1514–1866, with upper-case column names.
- Fate: `FATE` codes. About 1,079 voyages ended wrecked or destroyed (codes 2–5, 39, 66, 75, 96, 99). About 1,509 were captured or condemned (codes 6–31, 42–53, 56, 74), plus the Vice-Admiralty court codes 102 and up. `FATE3` gives the captor: 1 natural hazard, 2 pirate/privateer, 3 British, 4 Spanish, 5 Dutch, 6 Portuguese, 8 French, 9 US, 10 African, …
- Flag: `NATIONAL` (26,570 rows; 1 Spain, 4 Portugal, 7 Great Britain, 8 Netherlands, 9 U.S.A., 10 France, …) and `NATINIMP`, which is imputed. Construction and registration places: `PLACCONS`, `PLACREG`. Owners: `OWNERA`–`OWNERP` (Royal African Company, West-Indische Compagnie, …).
- Location: there are no loss coordinates. The FATE label names the voyage stage, and the stage picks a place code:
  - before slaves embarked → `MJBYPTIMP`, else `PLAC1TRA`, at place precision;
  - after embarkation → `MJBYPTIMP` at region precision (Middle Passage);
  - after disembarkation → `SLA1PORT`, else `MJSLPTIMP`;
  - unspecified → none.
- Place codes: 5-digit codes (10432 Liverpool, 34299 Barbados, place unspecified, 60799 West Central Africa and St. Helena, port unspecified). Codes ending in 99 are regions.
- Labels for every code are in `SPSS_Codebook_2023-11-06.pdf` (108 pages), whose text extracts cleanly with pypdf. Generate `fate.csv`, `nation.csv` and `places.csv` from it once, review them, and commit them (§4).
- Licence: public domain, but the imputed variables (`*IMP`) are CC-BY-NC. Rows that use them get `redistribute=false`.

**Prize Papers.** These records are **captures, not sinkings**, so their value is ownership change. The harvest on disk holds 4,215 ships and 2,857 captures in `ship_*.json` and `capture_*.json`, each a page with a `docs` list.
- Ships: `MD_SHIP_ALL_NAMES`, `MD_SHIP_FORMER_NAMES` (139), `MD_SHIP_RULING_AUTHORITY` (2,384; Great Britain 957, USA 676, France 346, Denmark 225, Spain 108, …), `MD_SHIP_FLAG` (273).
- Captures: `MD_CAPTURE_PLACE` (2,771; mostly sea areas such as North Atlantic Ocean 881), `MD_ALL_COORDS_FOR_SPATIALSEARCH` (2,755; a GeoJSON FeatureCollection string with Polygon geometry, sometimes a single vertex), `MD_CAPTURE_DATE_CREATED_START`, `MD_CAPTURE_TYPE` (mostly "Seized at sea") and `MD_CAPTURE_DESCRIPTION`. Some dates run to 2026; reject capture years after 1860.
- **The ship-to-capture link is missing from the harvest.** It lives on event docs (`DOCTYPE:EVENT`; 9,355 in the index, 5,767 with a capture link). Each event carries:
  - `PI_TOPSTRUCT`: the ship PI;
  - `MD_EVENT_CAPTURE_LINK`: the capture PI;
  - `MD_EVENT_RULING_AUTHORITY`: the flag on that journey;
  - `MD_EVENT_JOURNEY_TYPE`: "Journey interrupted by capture" or "Forced journey";
  - also `MD_EVENT_CAPTAIN`, `MD_EVENT_PLACE` and `MD_EVENTDATECREATEDSTART`/`END`.

  Phase 0.2 harvests these.
- Only 9 capture descriptions mention destruction ("sunk by the capturer because it was considered not seaworthy"). Those become loss rows; everything else goes to `ownership_events`.
- Licence: metadata terms unstated, so `redistribute=false`.

### 2.3 Secondary sources

**Ireland WIID.** `wiid.csv`, UTF-8 with a BOM (read with `encoding="utf-8-sig"`).
- Location: `DD_Lat`/`DD_Long`, where 0 means no location. Only 146 of the 7,714 losses up to 1860 have coordinates, so geocoding `Place of Loss` decides this source's value. The text looks like "Carlingford Bar, outside, on a rock, Carlingford Lough".
- Cause: `Description`, but only 3,728 rows hold real text; the rest is "We regret that we are unable to supply descriptive details…" boilerplate. Some name a home port ("Brig of Greenock, en route to Dublin").
- Flag: no field.
- Date: `Date of Loss` (`dd/mm/yyyy`) and `Date_of_Loss_Year_Only`.
- Join key: `Wreck No` (W00001) matches INFOMAR `nms_ref` and EMODnet's Irish `source_id`.

**INFOMAR.** A shapefile inside the zip with 608 surveyed wrecks: `latitude`, `longitude`, `vesselname` (213), `date_loss` (198), `nms_ref` (97, → WIID). Use it only to give WIID rows surveyed coordinates.

**EMODnet.** `emodnet-shipwrecks.geojson`, 7,073 points: France 4,844 (SHOM) and Ireland 1,974. The Irish rows duplicate WIID (`source_id` = `Wreck No`). Cause: `sink_context` (2,046 rows), e.g. "Sank at the anchorage of St Pierre as a result of the fiery cloud of 05/08/1902". Date: `sink_yr`. The string `"n/a"` means null in every column. No flag.

**Nova Scotia.** 4,939 rows. Cause: `Event` (Stranded 2,463, Wrecked 1,063, Foundered 468, Collision 148, Sank 146, Missing 134, Burnt 130, …). The values Damaged, Dismasted, Loss of spars, Strained and Serious damage are not losses. Location: `Location of wreck` text, geocoded within Nova Scotia. `Vessel Name` carries a " - 1875" suffix to strip. The other 25 columns hold 6 values or fewer. No flag.

**Dutch-Asiatic Shipping.** `voyages_with_details.csv`: semicolon-delimited, quoted, UTF-8; 8,194 VOC voyages of 1,406 ships. Fate appears only inside `Particulars` ("The ship was wrecked near Cape Agulhas on 08-01-1730", "set on fire near Bawean, 11-01-1597", "lost between Coromandel and Ceylon"); about 909 rows mention a loss word. Flag: Dutch Republic. Owner: VOC, chamber in `Chamber`. Geocode with GLOBALISE VOC places and the IBM gazetteer. Licence: none stated.

**Todo a Babor.** Two HTML pages:
- `article_01.html`: Spanish ships of the line and frigates lost 1793–1815.
- `article_02.html`: British warships captured by Spain.

Neither page uses tables. A `<p>` heading names each event and cause ("En la batalla del Cabo de San Vicente el 14 de febrero de 1797:", "Incendiados por sus propias tripulaciones para evitar su apresamiento…"), followed by `<li>` ship entries. Filter `<li>` to the article body. Location comes from a battle or place name (§5.6).

**IBM chuk-mcp-maritime-archives.** Code is Apache-2.0; the underlying sources are mostly unspecified. Tier T3.
- `data/wrecks.json` holds 710 VOC losses re-extracted from DAS (`wreck_id` `maarer:<DAS Number>`), with `loss_cause`, `loss_location` and `loss_date`. Its dates are not reliable: MEERHUIZEN's `loss_date` 1724-07-14 is a port call, while the text says she was wrecked in 1730. Use it **only to cross-check** our DAS extraction.
- `carreira_wrecks.json` (100), `eic_wrecks.json` (35), `galleon_wrecks.json` (42) and `soic_wrecks.json` (20) carry `position {lat, lon, uncertainty_km}`, `loss_cause` and `is_curated`. Rows with `is_curated: false` look synthetic: Cinco Chagas is dated 1529 with cause "storm" but a fire narrative. Keep only `is_curated == true` (40 + 35 + 25 + 20 = 120 rows).
- `gazetteer.json` lists 157 historical places with aliases (Texel/Tessel, Point de Galle/Galle). Use it as a geocoding aid.

**Wikidata.** The harvester queries only Three Decks-linked items (P11085), Spanish ships and battles. The battles query (Q178561 subclasses with P625, 1492–1860) provides the **battle gazetteer** for "sunk at the Battle of X". A ship-loss query is optional (Phase 0.4).

### 2.4 Gazetteers (inputs to geocoding, not loss sources)

| Gazetteer | Status | Use |
|---|---|---|
| GeoNames country dumps + `cities1000` | **add** (Phase 0.3); CC-BY-4.0 | coastal features and ports. All URLs checked live (`IE.zip` 0.8 MB, `cities1000.zip` 11 MB) |
| Natural Earth `ne_10m_geography_marine_polys`, `ne_50m_land` | **add** (Phase 0.3); public domain | sea-area names → region points; land for the static map. Both URLs were checked live |
| GLOBALISE VOC places (`globalise-voc-places`) | in manifest | DAS places in Asia; check columns on first use |
| HGIS ports 1701–1808 (`hgis-ports`) | in manifest | Spanish American ports; check columns on first use |
| IBM `gazetteer.json` | in the IBM zip | historical names with aliases |
| Wikidata battles | Phase 0.1 | battle sites |
| SlaveVoyages ports with lat/long (`sv-ports`) | manual, optional | SlaveVoyages place codes |

### 2.5 Excluded, and why

| Source | Reason |
|---|---|
| Canmore points | 314,214 heritage points, but only 202 "MARITIME CRAFT" and no flag, cause or date fields; the detail lives on trove.scot pages |
| Hawaii wrecks | 37 chart hazards with no names or dates |
| CDB90 | land battles |
| CLIWOC, ICOADS, STRO, TOFLIT18, RICardo, Manila galleon PDF, Historical_Sea_Routing, ReShare ports/routes | voyages, logbooks and trade; no loss records |
| Cliopatria, historical-basemaps, HGIS jurisdictions, COLDAT, Newberry | polities and boundaries; possible context layers later |
| Lloyd's List 1741–1800 OCR | loss notices exist, but as noisy OCR prose; needs its own NLP pass (§11) |
| HE protected wrecks, NI wrecks, NOAA wrecks and obstructions | manual and not on disk; add an extractor if a human downloads them |

## 3. Data model

### 3.1 `losses_all`: one row per source record describing a loss

| Column | Type | Notes |
|---|---|---|
| `loss_id` | str | `<source>:<source_record_id>` |
| `source`, `source_record_id`, `source_url`, `tier` | str | `tier` from the manifest |
| `ship_name`, `ship_name_norm`, `former_names`, `ship_type` | str / list | norm: lower case, Unidecode, prefixes (HMS, SS, MV, USS…), quotes, "(PROBABLY)" and " - 1875" suffixes removed |
| `loss_date`, `loss_year`, `date_precision` | str / Int16 / enum | ISO partial date (`1797`, `1797-02`, `1797-02-14`); precision day, month, year, decade or none |
| `lat`, `lon` | float | WGS84 |
| `location_text` | str | raw place phrase |
| `location_precision` | enum | `surveyed`, `reported`, `place`, `region`, `none` |
| `uncertainty_km` | float | from the source, else the default per precision (§5.6) |
| `geocode_method` | str | `source_coords`, `override`, `gazetteer:<name>`, `marine_area`, `none` |
| `origin_raw`, `origin_polity`, `origin_basis` | str / enum | basis: `built`, `registered`, `flag_before_change`, `flag_assumed` |
| `flag_at_loss_raw`, `flag_at_loss_polity` | str | |
| `owner_at_loss` | str | person, company or navy, when named |
| `ownership_changed` | boolean, nullable | NA means unknown, not "no" |
| `ownership_change`, `ownership_event_ids` | str / list | e.g. "captured by Great Britain, 1797-02-14 (Prize Papers)" |
| `cause_raw`, `cause_class`, `weather_related`, `is_total_loss` | str / enum / bool / bool | §5.4 |
| `route_from`, `route_to` | str | |
| `licence`, `redistribute` | str / bool | copied from the source's `_provenance.json` |
| `cluster_id`, `is_primary`, `<field>_from` | | set by dedupe (§6.2) |
| `raw` | JSON str | source fields used, for re-parsing |

**Origin is not owner-at-loss.** Most sources record a single flag, and that flag is the flag at loss. Set `origin_polity` from build or registry evidence, or from a recorded pre-change flag. Otherwise copy the flag at loss and mark it `origin_basis=flag_assumed`. Never infer a change of hands from two sources disagreeing on the flag; list the conflict in the QA report instead.

### 3.2 `ownership_events`

`event_id, source, source_record_id, ship_name, ship_name_norm, date, date_precision, from_polity, to_polity, mechanism (captured | condemned | sold | renamed), captor, place_text, lat, lon, location_precision`

Fed by:
- Prize Papers events and captures;
- SlaveVoyages captured codes;
- Wikipedia capture sentences;
- Todo a Babor (`apresado` entries and the whole of `article_02`);
- UKHO `EX-` names (renamed only, with no polity);
- Wikidata, if harvested.

### 3.3 Map layer

`losses_map.geojson` holds one feature per cluster primary at `surveyed`, `reported` or `place` precision, plus one aggregate feature per (region, decade) for region-only rows. Properties are compact: short keys, enums as integers, strings in lookup tables.

## 4. Code layout

```
analyses/01-ship-losses/
  README.md                question, input source ids, method, status
  build.py                 CLI: --source ID (repeatable), --stage extract|geocode|ownership|dedupe|map|all,
                           --online-geocode, --redistributable-only
  shiplosses/
    schema.py              columns, enums, dtypes, validate(df)
    registry.py            SOURCES list; each module exposes ID and extract(raw_root: Path) -> Extract(losses, events)
    sources/               ukho.py wa.py zenodo.py wikipedia.py slavevoyages.py prizepapers.py wiid.py
                           infomar.py emodnet.py novascotia.py das.py todoababor.py ibm.py wikidata.py
    normalize/
      dates.py  coords.py  names.py  polities.py  causes.py  places.py
    geocode.py             offline gazetteer lookup, overrides, optional cached Nominatim
    ownership.py           links ownership_events to losses
    dedupe.py              deterministic links, then fuzzy clusters
    qa.py                  writes outputs/qa_report.md
    mapping/
      interactive.py       fills template.html -> outputs/map.html
      template.html        Leaflet page (§7)
      static.py            outputs/map_<period>.png
  scripts/
    sv_codebook.py         SlaveVoyages codebook PDF -> data/sv/{fate,nation,places}.csv (run once, then review)
  data/                    committed, small, hand-reviewed
    polities.csv           raw_value, source (or *), polity, polity_group, notes
    cause_rules.csv        priority, regex, lang, cause_class, weather_related, is_total_loss, sources
    sv/fate.csv            code, label, is_loss, is_capture, captor_polity, stage
    sv/nation.csv          code, label, polity
    sv/places.csv          code, label, is_region
    place_overrides.csv    location_text, source, lat, lon, precision, note
    battles.csv            battle, date, lat, lon, source (only where Wikidata lacks coords)
  outputs/                 gitignored (§8)
    per-source/<id>.parquet  losses_all.parquet/.csv  ownership_events.parquet  losses_map.geojson
    unresolved_places.csv  unmapped_values.csv  conflicts.csv  qa_report.md  map.html  map_*.png
tests/shiplosses/          offline tests; synthetic fixtures in tests/fixtures/shiplosses/
```

**Wiring:**
- `pyproject.toml`:
  - add `"analyses/01-ship-losses"` to `[tool.pytest.ini_options] pythonpath`;
  - add an optional extra `analysis = ["geopandas>=1.0", "pyogrio>=0.7", "shapely>=2.0", "rapidfuzz>=3.0", "Unidecode>=1.3", "matplotlib>=3.8", "pypdf>=4.0"]`;
  - register a `real_data` marker: tests that need `data/raw/`, skipped when it is absent.

  `openpyxl` is not needed, because UKHO is read from the TSV.
- `justfile`: add `ship-losses *args` → `uv run --extra analysis python analyses/01-ship-losses/build.py {{ args }}`.
- `.gitignore`: add `analyses/*/outputs/*` and `!analyses/*/outputs/.gitkeep`.

**Extractor contract:** a pure function over local files, with no network access. It returns DataFrames in the shared schema and keeps the source fields it used in `raw`. Unknown coded values are counted in `unmapped_values.csv`, never silently dropped. Extraction is separate from geocoding, so geocoder fixes replay without re-extracting.

## 5. Normalisation rules

### 5.1 Dates
- Parse `YYYYMMDD`/`YYYYMM`/`YYYY` (UKHO), `dd/mm/yyyy` (WIID, Zenodo), `YYYY/MM/DD` (WA), ISO (Nova Scotia, Prize Papers) and `dd-mm-yyyy` inside DAS text. Spanish month names apply to Todo a Babor.
- Zenodo `01/01/YYYY` → year precision.
- Reject years outside 1400–2030. Prize Papers capture years after 1860 count as invalid.

### 5.2 Coordinates
- UKHO degrees and decimal minutes: `^(\d+) (\d+(?:\.\d+)?) ([NSEW])$` → degrees + minutes/60, negative for S and W. Test case: `5 33.535 S` → −5.558917.
- Zenodo: strip U+FEFF, then split on `;`.
- WIID: (0, 0) → null.
- Prize Papers: parse the JSON string; use the shapely centroid. A one-vertex polygon gives that vertex.
- Wikipedia: `span.geo` holds decimal "lat; lon" in the HTML; fall back to `{{coord|…}}` in the wikitext.
- Reject |lat| > 90 or |lon| > 180. QA reports points more than 5 km inland on Natural Earth land but keeps them: rivers and lakes are real loss sites (Great Lakes, Thames).

### 5.3 Polities
- `polities.csv` maps each raw value, per source or for all, to a `polity` and a `polity_group` used for colouring.
- Navies map to their state: Royal Navy → Great Britain, French Navy → France, Spanish Navy/Armada → Spain, VOC/United Provinces → Dutch Republic.
- UKHO ISO-2 codes and SlaveVoyages `NATIONAL` codes go through the same table.
- Keep the source's era wording (Great Britain vs United Kingdom) in `polity`, and group them in `polity_group`.
- Target: at least 95% of non-empty flag values per source map to a polity. Unmapped values and their counts go to `unmapped_values.csv`.

### 5.4 Causes
`cause_class` has eight values, which caps the map at eight colours:

| Class | Examples |
|---|---|
| `stranded` | wrecked, stranded, ran aground, driven ashore, struck a reef or rock; WA "Wrecked and sunk"; NS Stranded/Grounded/Ashore/Beached |
| `foundered` | foundered, sank, capsized, sprang a leak, swamped |
| `weather` | lost in a storm, hurricane, typhoon or gale, crushed by ice, when no mechanism is stated |
| `fire_explosion` | accidental fire, burnt, exploded, blew up |
| `collision` | collision, run down by |
| `enemy_action` | sunk or destroyed in action, captured then burnt or sunk by the captor, mined, torpedoed, bombed |
| `scuttled` | scuttled, burnt by her own crew, set on fire to avoid capture, sunk as a blockship or breakwater |
| `unknown` | missing, lost (unspecified), abandoned, cause not reported |

- **Priority** when several patterns match: enemy_action > scuttled > fire_explosion > collision > stranded > foundered > weather > unknown.
- `weather_related` is set separately whenever weather words appear.
- **Non-losses** get `is_total_loss=false` and are left off the map: refloated, salvaged, damaged, dismasted, condemned, sold, broken up, and captured without destruction. Captures go to `ownership_events`.
- Rules are data in `cause_rules.csv`, including Spanish patterns:
  - `apresado` → ownership event;
  - `incendiado`/`quemado` → fire, or scuttled when to avoid capture;
  - `naufragio`/`naufragó` → stranded;
  - `volado` → fire_explosion;
  - `hundido` → by context.
- SlaveVoyages and Nova Scotia map their codes through the same table.

### 5.5 Location phrases from text
For Wikipedia, Zenodo `NOTES`, WIID, DAS and UKHO text, take the first phrase that follows a loss verb (wrecked, lost, stranded, driven ashore, foundered, sank, burnt, captured, ran aground) plus `at|on|near|off|in`, up to the next `.`, `;` or `(`. Handle "N nautical miles south of X" by taking X. Keep the whole comma chain ("near Barmouth, Caernarvonshire, United Kingdom"), because its last part narrows the gazetteer search. Store the phrase in `location_text`, even when geocoding fails.

### 5.6 Geocoding, offline first
Per row, stop at the first hit:
1. Source coordinates.
2. Exact match in `place_overrides.csv`.
3. Source-specific gazetteers:
   - DAS → GLOBALISE VOC places, then IBM `gazetteer.json`;
   - SlaveVoyages → `sv/places.csv` names (plus `sv-ports` coordinates when present);
   - battle phrases and Todo a Babor → Wikidata battles, then `battles.csv`;
   - Prize Papers sea names → Natural Earth marine areas.
4. GeoNames, restricted by context:
   - WIID → IE and Northern Ireland;
   - Nova Scotia → CA, Nova Scotia admin1;
   - WA → AU;
   - Zenodo → country and state from `ZONA1`/`ZONA2`;
   - Wikipedia → the trailing country in the phrase.

   Match on the normalised name plus alternate names, preferring feature classes H (water), T (capes, islands, reefs), then P (places). If more than one candidate in scope lies over 50 km apart, mark the row unresolved; don't guess.
5. Natural Earth marine area name match → label point, `region` precision.
6. Otherwise `none`. Write the phrase to `unresolved_places.csv` with counts, so a human can extend the overrides.

Default `uncertainty_km`: surveyed 0.1, reported 5 (or the source's value), place 10, region 250.

Optional `--online-geocode`: Nominatim at ≤1 request per second with `DR_CONTACT` in the User-Agent, cached in `outputs/geocode_cache.csv`. It is never used for region phrases and is off by default.

## 6. Ownership resolution and de-duplication

### 6.1 Owner at loss
For each loss row, in order:
1. **Explicit owner:** WA `owner`, SlaveVoyages `OWNERA`, and UKHO "OWNED AT TIME OF LOSS BY X" fill `owner_at_loss`.
2. **Change within one record:**
   - A Wikipedia description with a capture followed by destruction: the origin is the State-column polity, the owner at loss is the captor, and the cause is `enemy_action`.
   - A Prize Papers capture with a destruction description.
   - A SlaveVoyages code that combines capture and loss (e.g. 99, "Taken by slaves, recaptured, then ship lost").
3. **Change across sources:** match a loss row to `ownership_events` when all of these hold:
   - `ship_name_norm` similarity (rapidfuzz `token_sort_ratio`) is at least 90;
   - the event comes before the loss and no more than 30 years earlier;
   - the event's `to_polity` equals the flag at loss, or its `from_polity` equals the origin.

   **Common-name guard:** names that occur more than 3 times in the ±5-year window (Mary, Nancy and Betsey top SlaveVoyages) also need one more matching attribute: master, tonnage within ±15%, or ship type. Record the score.
4. Otherwise leave `ownership_changed` as NA.

### 6.2 De-duplication
1. Deterministic links:
   - WIID `Wreck No` = INFOMAR `nms_ref` = EMODnet Irish `source_id`;
   - IBM `maarer:<n>` = DAS `Number`;
   - Zenodo ↔ Wikipedia on name + date + flag.
2. Fuzzy clusters: block on `loss_year` ±1. Link two rows when name similarity is at least 90 and either they lie within 50 km, or one has no coordinates and their `location_text` token overlap is at least 0.5. Join links with union-find.
3. Primary row per cluster: best `location_precision`, then source priority (surveyed registries > Wikipedia > SlaveVoyages > the rest > T3), then the most non-null target fields. The primary fills its missing target fields from other members and records the donor in `<field>_from`.
4. `losses_all` keeps every row; the map uses primaries only.

## 7. Map

**Interactive** (`outputs/map.html`): one self-contained file with the data inlined. Leaflet 1.9 loads from cdnjs. Use the canvas renderer (`L.canvas()`) with circle markers, because tens of thousands of SVG markers stall.

- **Basemap:** CARTO Positron without labels (`https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png` [verify]) at 60% opacity, attributed to OSM and CARTO. Modern labels and borders would mislead over historical data.
- **Projection:** Web Mercator suits an interactive point map. The extent spans every latitude, so the static maps use Equal Earth (EPSG:8857 [verify]).
- **Colour = `cause_class`**, from CARTOColors "Safe", a colourblind-safe qualitative palette:

  | Class | Colour |
  |---|---|
  | stranded | `#88CCEE` |
  | foundered | `#332288` |
  | weather | `#44AA99` |
  | fire_explosion | `#CC6677` |
  | collision | `#DDCC77` |
  | enemy_action | `#882255` |
  | scuttled | `#117733` |
  | unknown | `#888888` |

  Verify the hexes against the CARTOColors source. The legend doubles as a filter: click a class to toggle it.
- **"Colour by" switch:** flag at loss, using the 7 largest `polity_group`s in the current window plus Other in `#888888`, with the same palette.
- **Location precision:**
  - `surveyed` and `reported`: filled circle, radius 4 px, fill opacity 0.85, 0.5 px white stroke.
  - `place`: ring, radius 5 px, 1.5 px stroke in the class colour, fill opacity 0.15.
  - `region`: hidden by default, because the points would stack on ocean centroids. The toggle "Show losses known only by sea area" draws one grey circle per region in the window, radius 4 + 2·√n px (capped at 30), with a count label.
- **Filters:**
  - year range: two sliders, default 1500–1860, full range available;
  - Play: a 10-year window advancing 1 year every 300 ms;
  - flag-at-loss and origin multi-selects;
  - "Only ships that changed hands";
  - precision and source checkboxes.
- **Tooltip:** ship, year, cause in words. **Popup:**
  - ship (former names);
  - date lost;
  - where: location text plus a plain-words precision note ("surveyed wreck site", "position reported at the time", "approximate: near <place>", "sea area only");
  - origin with its basis in words;
  - owner at loss and the change text;
  - cause in words plus the raw text;
  - a link to each source record in the cluster.
- **Layout:**
  - Title: one sentence stating a finding, written after reading `qa_report.md`, never a placeholder.
  - Subtitle: "N ship losses, YYYY–YYYY, from K sources".
  - Legend top right; sources, licences and build date bottom left.
  - At 375 px wide, the filter panel collapses behind a button.
- **Budget:** `map.html` stays under 15 MB.
- `--redistributable-only` drops rows with `redistribute=false` (Prize Papers, DAS, Todo a Babor, rows that use SlaveVoyages imputed variables) to make a shareable build.

**Static** (`outputs/map_<period>.png`): four small multiples for 1500–1699, 1700–1763, 1764–1815 and 1816–1860. Equal Earth projection, Natural Earth 50 m land filled `#E6E6E6` with no stroke, 2 px points coloured by cause, 2,000 px wide at 150 DPI.

## 8. Licences and git

- `outputs/` is gitignored. Several inputs are non-commercial or carry no stated licence (Prize Papers, DAS, Todo a Babor, the SlaveVoyages imputed variables), and the repo has a public remote. Commit code, the curated `data/` tables and synthetic fixtures only.
- Every row carries `licence` and `redistribute`, and the map footer lists sources with their licences. Wikipedia-derived rows are CC-BY-SA-4.0, so any published derivative needs attribution and share-alike.

## 9. Phases and exit criteria

**Phase 0: inputs.** Needs network, about 20 minutes.
- 0.1 A human sets `DR_CONTACT`, then runs `uv run python -m fetch get --id wp-en-shipwrecks --id wp-en-lists --id wikidata`. Check that one JSON per list page from 1650–1860 is present, and spot-check 1805 against §2.2.
- 0.2 Extend `fetch/harvesters/prizepapers.py`:
  - replace `DOCSTRCTS` with named queries `[("ship", "DOCSTRCT:ship"), ("capture", "DOCSTRCT:capture"), ("event", "DOCTYPE:EVENT")]`;
  - add `PI_TOPSTRUCT`, `IDDOC_OWNER`, `DOCTYPE` and `MD_EVENTDATE*` to `RESULT_FIELDS`.

  Existing pages are reused, so this costs about 94 requests at 1 per second. Add an event-page fixture to `tests/test_harvesters.py`. Check: `summary.json` reports about 9,355 events.
- 0.3 Add the `gazetteer` group to `VALID_GROUPS` in `fetch/manifest.py` and to the CLI help, with a test. Then add two manifest entries:
  - `geonames` (direct): `https://download.geonames.org/export/dump/{IE,GB,CA,AU,US,ZA,ES,FR,NL,PT}.zip` and `cities1000.zip`, CC-BY-4.0.
  - `naturalearth` (direct): `https://naciscdn.org/naturalearth/10m/physical/ne_10m_geography_marine_polys.zip` and `https://naciscdn.org/naturalearth/50m/physical/ne_50m_land.zip`, public domain.

  Every URL above returned 200 on 2026-10-04.
- 0.4 Optional: a Wikidata query for ship items with loss events (P793). Resolve the event QIDs (shipwreck, scuttling, …) by label at runtime and record them in provenance, as the download plan requires.
- **Exit:** `python -m fetch validate` lists the new files, and nothing else under `data/raw/` changes.

**Phase 1: skeleton and coordinate-rich sources.**
- Build the schema, the normalisers (dates, coords, names, polities, causes), and the UKHO, WA and Zenodo extractors.
- `build.py` writes the per-source parquet files, `losses_all` and a `qa_report.md` coverage matrix: rows × the four target fields × precision, per source.
- Map v0: cause colours and the year filter.
- **Exit:** offline tests pass; `just ship-losses` runs from empty outputs in under 5 minutes; `map.html` opens and filters.

**Phase 2: Wikipedia and geocoder v1.**
- The Wikipedia extractor, phrase extraction, GeoNames and Natural Earth lookups, and overrides.
- **Exit:** the QA report records the share of Wikipedia rows at `place` precision or better (target 50% or more). Review the 50 most frequent unresolved phrases and add overrides for the top 20.

**Phase 3: ownership.**
- Extractors: Prize Papers (ships + captures + events), SlaveVoyages (run `sv_codebook.py`, review the CSVs), Todo a Babor, and optionally Wikidata. Then `ownership.py`.
- **Exit:**
  - SlaveVoyages loss and capture counts match the reviewed `fate.csv`;
  - the ~130 Spanish ships of the Prize Papers "Spanish Ships" case study (War of the Austrian Succession) appear with ruling authority Spain;
  - `conflicts.csv` lists flag disagreements.

**Phase 4: text-location sources.**
- WIID with INFOMAR and EMODnet, Nova Scotia, DAS (cross-checked against IBM `wrecks.json`), and the IBM curated lists.
- **Exit:** DAS and IBM agree on `cause_class` for at least 80% of matched voyages. Disagreements are listed; IBM is not ground truth.

**Phase 5: de-duplication and final outputs.**
- Clustering, the final interactive map, the static maps, and the analysis README with inputs, method, status and known gaps.
- **Exit:** the definition of done (§12).

## 10. Tests

- **Table-driven unit tests:**
  - coordinates: UKHO minutes format, BOM, (0, 0), polygon centroid;
  - dates: every format, plus the `01/01` placeholder;
  - polity mapping;
  - cause rules: at least 40 real-shaped phrases across sources, including Spanish;
  - phrase extraction and name normalisation.
- **Extractors:** each runs against a synthetic fixture of 5–20 rows that reproduces the real quirks: WIID's BOM, DAS semicolons, UKHO's quoted TSV, EMODnet's `"n/a"`, and the Prize Papers page JSON. Real data is never committed.
- **Golden counts** (`@pytest.mark.real_data`, skipped when the data is absent): UKHO 102,625; WA 305; Zenodo 4,463; WIID 17,981; Nova Scotia 4,939; EMODnet 7,073; SlaveVoyages 36,108; Prize Papers 4,215 ships and 2,857 captures. These pin today's snapshot; update them on purpose when a source is refetched.
- **De-duplication:** one wreck recorded in WIID, INFOMAR and EMODnet merges into one cluster. Two different "Mary" losses in consecutive years at different places do not merge.
- **Map:** build from a 50-row fixture. Assert that the HTML embeds the data, stays under the size budget, shows every cause class in the legend, and has no NaN properties.

## 11. Decisions taken (change them if you disagree)

1. **Period.** Extract every year; the map opens on 1500–1860 with the full range available. Most UKHO, EMODnet and Nova Scotia rows are after 1860 and stay in the data.
2. **Captures that were not sunk** are not plotted as losses. They live in `ownership_events`; a capture layer can come later.
3. **Region-only losses** are hidden by default and shown aggregated on request.
4. **Online geocoding** is off by default.
5. **Lloyd's List OCR** is deferred to a later NLP pass.
6. **Three Decks join.** When its export exists, add `sources/threedecks.py` and join through `data/raw/wikidata/p11085.csv` or name + year. Its one-record-per-ownership-period model is the best ownership source; expect it to supersede Todo a Babor and much of Wikipedia for warships.
7. **`DR_CONTACT`** must be set by a human before Phase 0.1. Don't hard-code a contact.

## 12. Definition of done

- `just ship-losses` rebuilds every output from `data/raw/` offline. A second run produces identical tables.
- `qa_report.md` shows, per source:
  - rows extracted;
  - the share with a location at each precision;
  - the share with origin, owner at loss and cause;
  - unmapped values;
  - unresolved places;
  - cluster counts.
- `map.html` works offline apart from tiles and the Leaflet CDN. It filters by year, cause, flag and changed hands, plays the timelapse, and passes a 375 px width check.
- Offline `pytest` passes; `pytest -m real_data` passes on a machine with the data.
- `analyses/01-ship-losses/README.md` lists inputs, licences, method, known gaps and how to rebuild.
