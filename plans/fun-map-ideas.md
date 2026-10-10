# Plan: fun map ideas from the content we have

Scope: **fun, general-audience maps, built as QGIS 3.x projects**, from what is already on disk plus sources that are one registered fetch away. This is not the production Spanish-losses timelapse; it is a menu of one-message maps, each with one fun element, ranked by fun-per-effort. All data facts below were verified against `data/raw/` and `fetch/manifest.yaml` on this machine.

All endpoint/manifest facts were checked on 2026-10-09. On-disk means present in `data/raw/`; one-fetch means a source in `fetch/manifest.yaml` fetched with `just download <id>` (add `--large` for STRO).

---

## 1. What we actually have

**On disk (extractors exist in `analyses/01-ship-losses/`):**

| Source | Content | Licence | Publish? |
|---|---|---|---|
| `ireland-wiid` | 17,981 wreck records; 3,153 rows carry decimal DD_Lat/DD_Long (`0` means "no location") | CC-BY-4.0 | Yes |
| `novascotia-shipwrecks` | 4,939 wrecks with cause of event, cargo, voyage from/to, lives lost, date built (text locations) | NS Open Government Licence | Yes |
| `wa-shipwrecks` | 305 GeoJSON points from 1629, with port_from/port_to | CC-BY-4.0 | Yes |
| `zenodo-shipwrecks` | 4,463 rows with FLAG, sunk date, vessel type, coordinates | CC-BY-4.0 (T3, Wikipedia-derived) | Yes, with caveat |
| `hawaii-wrecks` | 37 charted wrecks | none provided | No |
| `prize-papers` | Query dumps: ~4,215 ships, 2,857 captures; index has `MD_GEO_POINT`, `MD_SHIP_FLAG`, `MD_CAPTURE_PLACE` | metadata terms unstated | **No — personal use only** |
| `todo-a-babor` | 2 HTML articles: Spanish losses 1796-1808, British prizes of Spain | none stated | **No** |
| `coldat` + OWID | Colony counts by colonizer by year (195 countries) | CC0 | Yes |
| `hgis-indias/ports` | 6-feature ports shapefile | CC-BY-NC-SA-4.0 | Non-commercial |

**One fetch away** (`just download <id>`): `cliwoc-gpkg` (190 MB, 287,114 daily logbook positions; licence "None stated" — personal use), `cliopatria` (CC-BY-4.0 polity polygons, FromYear/ToYear per feature), `manila-galleon` (~1 MB NOAA PDF tables, "cite DOI"), `stro-sound-toll` (~1.6 GB, needs `--large`, CC-BY-4.0), `historical-basemaps`, `naturalearth` (ne_50m_land + marine polys), `geonames` (country dumps).

**Ready-made layer:** `just ship-losses` writes `analyses/01-ship-losses/outputs/losses_all.csv` and `per-source/*.csv` with `lat`, `lon`, `cause_class`, `loss_year`, `source` — geocoded, deduped, cause-normalized. QGIS loads these directly; use them wherever a map wants point layers with clean classes.

**Projects live in** `analyses/02-fun-maps/` (README + one `.qgz` per map + exported layouts), following the repo's analyses convention. Every map: title states the finding, plain-words legend with units, source + date at 8 pt in a corner, basemap lighter than data, one fun element in text or margin only.

---

## 2. The menu, ranked

### Map A — "Ireland's seabed: 3,000 ships and counting" (hex-bin density)

- **Message:** Ireland's coast is a two-millennium ships' graveyard with one extreme hotspot.
- **Data:** on-disk `ireland-wiid`; 3,153 geolocated rows (filter `DD_Lat=0`/`DD_Long=0` and out-of-bounds at build).
- **Spec:** hex-bin density; EPSG:2157 (Irish Transverse Mercator); 10 km hexagons; graduated renderer on points-per-cell, **quantiles, 5 classes**, `viridis` (light = few, dark = packed); data layer is the only saturated colour; `ne_50m_land` in #E6E6E6 underneath.
- **QGIS:** Add Delimited Text (X=`DD_Long`, Y=`DD_Lat`, EPSG:4326) → Create Grid (hexagonal, layer extent, 10 km) → Count Points in Polygon → graduated, quantile, 5 → Print Layout, 300 DPI PNG.
- **Fun element:** annotation with a leader line on the densest cell: "This cell alone holds N wrecks." Fill N from the built layer; do not guess.
- **Caveat:** WIID dates span prehistoric to WWII; state the span in the subtitle, or filter to 1500-1860 for the project window (subtitle then says so).

### Map B — "What sank them: Nova Scotia's bad days, classified" (categorical causes)

- **Message:** stranding dominates; the weird causes are the fun.
- **Data:** on-disk; run `just ship-losses --source novascotia-shipwrecks` and load `outputs/per-source/novascotia-shipwrecks.csv` (already geocoded within Nova Scotia with `cause_class`). Raw text locations cannot be plotted directly.
- **Spec:** categorical points; EPSG:26920 (NAD83 / UTM 20N); **Okabe-Ito 8-hue palette**, top 7 causes + "Other"; point size 2.5 mm, no border; rare causes folded into Other at build time.
- **QGIS:** categorized renderer on `cause_class`; rule-based labels off (too dense); Layout A3 landscape.
- **Fun element:** legend copy in plain words, e.g. "Stranded, foundered, burned, and other bad days." Optionally one annotation quoting the strangest actual `Cause of Event` string found while building.
- **Caveat:** NS licence requires attribution; put it in the corner.

### Map C — "Caught! Where Britain filed the paperwork" (Prize Papers captures)

- **Message:** the seizures cluster in European waters and the Caribbean.
- **Data:** on-disk `prize-papers` JSON; extract `MD_GEO_POINT` + `MD_SHIP_FLAG` + `MD_CAPTURE_PLACE` from the capture docs into a CSV (one small script, no network).
- **Spec:** categorical points by ship flag, Okabe-Ito + grey "Unknown"; EPSG:8857 (Equal Earth); 2 mm points, 60% transparency for overplotting.
- **Fun element:** title hook only: "Caught! 2,857 seizures, one filing cabinet." Verify the count from the built table before printing it.
- **Caveats:** **licence: metadata terms unstated, `redistribute=false` — do not publish or export the image publicly.** Ship-to-capture linking events need the Phase 0.2 harvester extension, so map capture-place points as-is and say "places of seizure, not linked ships" in the subtitle.

### Map D — "'Enemy in sight': where the logs recorded fights" (CLIWOC)

- **Message:** fights cluster on the known lanes, told by the sailors themselves.
- **Data:** one-fetch `just download cliwoc-gpkg`; filter rows where the WarsAndFights field is non-empty [verify the field exists in the Ottens GPKG columns before committing to the idea].
- **Spec:** points coloured by Nationality (Okabe-Ito + "Other"); EPSG:8857; 2.5 mm, 70% transparency; `ne_50m_land` grey underneath.
- **Fun element:** one annotation quoting an actual `WarsAndFightsMemo` log entry from the built subset, with its date.
- **Caveat:** GPKG copy's licence is "None stated", `redistribute=false` — personal use. For a publishable version, switch to the PANGAEA CC-BY-3.0 copy (`cliwoc-pangaea`, large).

### Map E — "Empires rise; ships sink" (Cliopatria + loss points, 4 snapshots)

- **Message:** the empires the ships died under, at four instants.
- **Data:** one-fetch `cliopatria` + `naturalearth`; plus `just ship-losses` outputs (points). Cliopatria features carry FromYear/ToYear; filter to snapshots 1500 / 1600 / 1700 / 1800 (13,765 features total — pre-filter per snapshot).
- **Spec:** small multiples, four Equal Earth panels in one Print Layout; ≤8 named polities with Okabe-Ito hues muted to 60% lightness + "Other" in light grey #D9D9D9; loss points in full-saturation Okabe-Ito orange #D95F02, 1.2 mm, so the data layer outranks the muted backdrop.
- **Palette:** polities categorical (Okabe-Ito muted, 8 + grey "Other"; a sequential ramp would be wrong here); ship points a single accent hue already in the Okabe-Ito set at full saturation.
- **Fun element:** subtitle: "The maps a shipwrecked sailor would have been shown, four centuries running."
- **Caveat:** Cliopatria CC-BY-4.0; publishable. Ship points restricted to years present in losses_all; state row counts per panel.

### Map F — "Whose flag rests on the seabed" (zenodo world flags)

- **Message:** most named wrecks in this Wikipedia-derived set fly two or three flags.
- **Data:** on-disk `zenodo-shipwrecks` (4,463 rows, FLAG, coordinates; strip the U+FEFF on load); optionally add WA (305, from 1629 — annotate the Batavia, the oldest) and Hawaii (37) as a Pacific inset.
- **Spec:** density of wrecks per 5° equal-area grid cell (Create Grid on the Equal Earth reprojection, Count Points in Polygon); graduated `viridis`, quantiles, 5 classes — counts per equal-area cell, never raw counts by country; EPSG:8857. Inset panel: WA oldest wrecks, 1.5 mm points, grey basemap, one orange #D95F02 dot on the Batavia.
- **Fun element:** margin note: "The Batavia has been waiting off Western Australia since 1629."
- **Caveat:** T3 community dataset, Wikipedia-derived — subtitle must say "Wikipedia-derived, not a census."

### Map G — "262 years of the same commute" (Manila galleon)

- **Message:** two centuries of Spain's Pacific lifeline ran on one corridor.
- **Data:** one-fetch `manila-galleon` (NOAA PDF tables); extract voyages with a small `pdfplumber` pass into a CSV of year + direction; draw the corridor as generalized great-circle lines in QGIS (Acapulco, Manila waypoints), one line per decade, colour by century (Okabe-Ito ≤4 centuries + "Before 1591" grey).
- **Spec:** Pacific-centred; EPSG:8857 with a Pacific-centred extent or Lambert azimuthal centred 180°; 0.6 mm lines, 80% transparency stacked per decade.
- **Fun element:** annotation on the return leg: "North to 40°N to catch the westerlies home."
- **Caveat:** "Cite DOI" licence — cite the NOAA DOI on the map. PDF extraction is a pre-QGIS step; if the tables parse badly, drop the idea rather than hand-place ships.

### Map H (stretch) — "The world's oldest traffic counter" (Sound Toll)

- **Message:** the Øresund counted the world's shipping for 360 years.
- **Data:** one-fetch `just download stro-sound-toll --large` (18 CSVs, ~1.6 GB) + `geonames` for departure ports.
- **Spec:** flow lines from departure ports to the Sound, line width ∝ sqrt(passages per port), per-decade small multiples or a Temporal Controller animation; EPSG:8857; Baltic extent.
- **Fun element:** subtitle: "Ships paid a toll to Denmark 427 years before E-ZPass."
- **Caveat:** 1.6 GB + port geocoding; do this last, only if A-G were fun.

---

## 3. Rules that bind every map

1. **Palette:** sequential = one lightness-ordered ramp (viridis/cividis); categorical = Okabe-Ito, ≤8 classes, rest "Other"; never rainbow; every ramp must survive deuteranopia.
2. **No choropleth of raw counts.** Hex/grid bins are counts per equal-area cell (density) — allowed; radius always ∝ sqrt(value).
3. **Projection:** national CRS for single-country maps (A: EPSG:2157; B: EPSG:26920); Equal Earth (EPSG:8857) for everything multi-country.
4. **Figure-ground:** `ne_50m_land` in #E6E6E6, no edge stroke; data layer is the only saturated element; labels ≥8 pt with white 1.5 mm halo where over data.
5. **Every exported map carries** title = finding, subtitle = what/where/when, plain-words legend with units, source + licence + date in a corner. No field names in legends.
6. **Fun lives only in title, subtitle, annotations, legend copy and margin notes.** One per map. No distorted geometry, no joke at a place's residents.

## 4. Build order and validation

First batch (highest fun-per-effort, all publishable): **A, B, E**. Then C and D (personal-use caveats), then F, G, H.

- 1. `just download naturalearth` (needed by A, D, E).
- 2. Create `analyses/02-fun-maps/` with README listing each map's inputs; one `.qgz` per idea, relative layer paths where possible.
- 3. For B and E, run `just ship-losses` first; record the commit + date in each map's corner.
- 4. Per map: rebuild both the CSV layer and the QGIS project from scratch once (delete and re-add layers) to prove it is reproducible; screenshot the 5-second test — a stranger must state the message unprompted.
- 5. Export Print Layouts at 300 DPI PNG + PDF into `analyses/02-fun-maps/outputs/`.
- 6. Licence gate before any public use: A, B, E, F, H publishable with attribution; **C, D (Ottens copy), todo-a-babor-derived content: personal use only.** G cites the NOAA DOI.

## 5. Known risks

- Prize Papers capture points lack the ship link (Phase 0.2 pending) — Map C stays a place-of-seizure map.
- CLIWOC GPKG may lack the WarsAndFights columns in the Ottens copy — verify before building Map D; fallback is nationality-coloured positions of voyages that later lost the ship [verify].
- zenodo dataset is Wikipedia-derived T3 — never present as authoritative.
- WIID `0/0` coordinates and out-of-bounds points must be filtered, or Map A gets a wreck at Null Island.
- Cliopatria is 13,765 features; unfiltered temporal rendering will choke QGIS — pre-filter to the snapshot year.

## 6. Out of scope

Three Decks data (another agent owns it), Lloyd's List OCR NLP pass, Spanish-losses timelapse production work, and any new harvester ( Prize Papers Phase 0.2, NOAA EIC landing pages).
