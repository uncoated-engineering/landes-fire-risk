# Landes Fire-Risk Map

A geospatial wildfire-risk map of the Landes de Gascogne, built entirely from open data — and a sketch of what risk-based insurance premiums could look like parcel by parcel.

The project is the visual companion to an essay arguing that state-flattened risk pricing (regulation, mandatory insurance, reconstruction subsidies) mutes the signals that would otherwise discourage risky land use. If risk is unevenly distributed across the forest, a flat premium is a cross-subsidy. This repo tries to show how uneven.

## Forest history map

[`docs/forest-history/index.html`](docs/forest-history/index.html) is a hexagon map of the massif from 1780 to 2026. Each hexagon is 1,500 ha and shows pine forest, burned or storm-hit land, farmland or moor for 15 snapshot years, across nine zones from the Médoc to Dax. A stacked chart shows the whole massif over time and a table gives forest hectares per zone.

- `scripts/build_forest_history.py` builds it: it selects 277 communes (~1.33 million ha), defines the zones, lays the hexagon grid and allocates the totals.
- `data/reference/forest_history_anchors.csv` holds the massif-wide figures, each marked documented or estimate, with sources.
- The split between zones is an estimate; which hexagons inside a zone are green is illustrative.

Rebuild with `python scripts/build_forest_history.py` (downloads commune boundaries from gregoiredavid/france-geojson on first run). The page is self-contained, with no external map tiles.

## Fire history map

[`docs/fire-history/index.html`](docs/fire-history/index.html) maps every forest fire recorded by BDIFF in the massif from 2006 to 2025: 4,407 fires and 39,064 ha. It uses the same zones and hexagons as the forest map. You can switch between where fires start (starts per 10,000 ha per year) and where land burned (circles drawn to scale), and view any single year. It also has a year-by-year chart, each zone's share of the area burned against its share of the land, the largest fires, a month profile and causes.

What the first 20 years show:
- **Concentration:** 5 fires burned 75% of the area; 80% of fires stay under 1 ha.
- **Season:** July holds 55% of the area burned.
- **Geography:** Landes bordelaises is 12% of the massif but 54% of the area burned (×4.5, driven by Landiras 2022). The southern zones burn 5–10 times less than their size.

Notes:
- `scripts/build_fire_history.py` builds it from `data/reference/bdiff/` (BDIFF export, Licence Ouverte). It reuses `build_massif()` and `base_map()` from the forest script.
- BDIFF locates fires by commune only, and holds these départements only from 2006.
- 2026 fires come from press reports, shown apart and kept out of all totals.

## Exposure map

[`docs/exposure/index.html`](docs/exposure/index.html) counts the houses near the forest. Owners must clear 50 m around any building within 200 m of woods or moorland; the map shows, per hexagon, how many houses stand inside that band and how many within 50 m. It also gives each zone's yearly chance that a hectare of forest burns and what an insurance claim costs, the other two pieces of an expected-loss estimate.

- `scripts/build_exposure.py` builds it. It downloads the OpenStreetMap extract for Aquitaine (release [`data-osm-aquitaine`](https://github.com/uncoated-engineering/landes-fire-risk/releases/tag/data-osm-aquitaine), checked against its SHA-256) and INSEE's 2021 housing counts, reads buildings, land cover and roads with pyosmium and caches them as GeoParquet in `data/processed/osm/`. The first run takes a few minutes, later ones about 20 seconds.
- `data/reference/claims_costs.csv` holds the published insurance totals, with sources.

What it shows:
- **Exposure:** 243,000 of the massif's 372,000 houses (65%) stand within 200 m of the forest, and 96,500 (26%) within 50 m. The share passes 75% in the inland zones (84% in the Grande Lande), but most of these houses are on the coast and around Bordeaux and Arcachon.
- **Hazard:** 0.20% of the forest burned in an average year of 2006–2025, 1 in 490 years for a given hectare. Without 2022 it is 0.05%; with the 2026 fires, 0.42%. By zone it runs from 0.02% to 1% a year, and to 2.6% for the Médoc in the 2026 stress case.
- **Cost:** about €25,000 per claim in 2026 (€563M for 22,500 claims in Gironde, Landes and Var) and €40,000 in 2022 (€80M for 2,000 claims across France).

Notes:
- OSM buildings are not homes: 958,000 buildings for 372,000 houses. Likely homes (solid walls, 40 to 1,000 m², no other use tagged) are weighted in each commune to its INSEE house count. Flats are left out.
- Forest is OSM forest, woodland, heath and scrub: 957,500 ha in the massif, against 987,950 ha in the national inventory. Pines inside housing estates are mapped as residential land, so the coastal towns built under the pines are undercounted.
- Burned area is placed in the commune where each fire started, as on the fire map, so the 2026 Saumos fire counts entirely for the Médoc.

## Questions

1. Where in the Landes massif is fire risk concentrated, and what drives it (fuel, weather, access, wildland-urban interface)?
2. How has risk shifted since the big fires of 1949, 2022 and 2026?
3. If insurers priced fire risk freely, how much would premiums vary between parcels — and who is currently subsidising whom?

## Candidate data sources

To verify licences, coverage and formats before ingesting.

| Layer | Source | Use |
|---|---|---|
| Historical fires | BDIFF (Base de Données sur les Incendies de Forêts en France) | **In use** (2006–2025): fires by commune, area, cause |
| Burned-area perimeters | Copernicus EMS / EFFIS | Fire footprints, esp. 2022 and 2026 |
| Fire weather | Météo-France IFM (Indice Forêt Météo, the French FWI) | Daily danger, seasonal climatology |
| Forest cover & species | IGN BD Forêt v2 | Fuel type (maritime pine monoculture vs. mixed/broadleaf) |
| Tree cover density | Copernicus Land Monitoring Service | Fuel load proxy |
| Buildings & WUI | OpenStreetMap (land registry import), INSEE census 2021 | **In use**: houses within 200 m and 50 m of the forest |
| Roads & tracks (DFCI) | OpenStreetMap | **Extracted**: main roads on the exposure map, forest tracks per zone; access analysis to come |
| Insurance claims | France Assureurs | **In use**: cost per claim, 2022 and 2026 |
| Parcels | Cadastre Etalab | Parcel-level risk and premium sketch |
| Admin boundaries | IGN Admin Express | Communes, départements (Landes, Gironde, Lot-et-Garonne) |

## Stack

- **Python** with GeoPandas, Shapely, rasterio
- **DuckDB + spatial extension** for joins and aggregation
- **H3** hexagons as the common analysis grid
- **Folium / kepler.gl** for interactive maps
- Optional: **dbt-duckdb** for the modelled layers, medallion-style (raw → staged → marts)

## Layout

```
data/raw/         downloaded source files (git-ignored)
data/processed/   cleaned layers (git-ignored)
notebooks/        exploration
src/landes_fire_risk/  ingestion, features, scoring
docs/             method notes and write-up
```

## Roadmap

See [docs/PLAN.md](docs/PLAN.md).

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

The exposure build downloads about 300 MB of OpenStreetMap data on its first run.
