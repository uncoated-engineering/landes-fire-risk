# Landes Fire-Risk Map

A geospatial wildfire-risk map of the Landes de Gascogne, built entirely from open data — and a sketch of what risk-based insurance premiums could look like parcel by parcel.

The project is the visual companion to an essay arguing that state-flattened risk pricing (regulation, mandatory insurance, reconstruction subsidies) mutes the signals that would otherwise discourage risky land use. If risk is unevenly distributed across the forest, a flat premium is a cross-subsidy. This repo tries to show how uneven.

## Forest history map

[`docs/forest-history/index.html`](docs/forest-history/index.html) is a hexagon map of the massif from 1780 to 2026. Each hexagon is 1,500 ha and shows pine forest, burned or storm-hit land, farmland or moor for 15 snapshot years, across nine zones from the Médoc to Dax. A stacked chart shows the whole massif over time and a table gives forest hectares per zone.

- `scripts/build_forest_history.py` builds it: it selects 277 communes (~1.33 million ha), defines the zones, lays the hexagon grid and allocates the totals.
- `data/reference/forest_history_anchors.csv` holds the massif-wide figures, each marked documented or estimate, with sources.
- The split between zones is an estimate; which hexagons inside a zone are green is illustrative.

Rebuild with `python scripts/build_forest_history.py` (downloads commune boundaries from gregoiredavid/france-geojson on first run). The page is self-contained, with no external map tiles.

## Questions

1. Where in the Landes massif is fire risk concentrated, and what drives it (fuel, weather, access, wildland-urban interface)?
2. How has risk shifted since the big fires of 1949, 2022 and 2026?
3. If insurers priced fire risk freely, how much would premiums vary between parcels — and who is currently subsidising whom?

## Candidate data sources

To verify licences, coverage and formats before ingesting.

| Layer | Source | Use |
|---|---|---|
| Historical fires | BDIFF (Base de Données sur les Incendies de Forêts en France) | Ignition points and burned area by commune |
| Burned-area perimeters | Copernicus EMS / EFFIS | Fire footprints, esp. 2022 and 2026 |
| Fire weather | Météo-France IFM (Indice Forêt Météo, the French FWI) | Daily danger, seasonal climatology |
| Forest cover & species | IGN BD Forêt v2 | Fuel type (maritime pine monoculture vs. mixed/broadleaf) |
| Tree cover density | Copernicus Land Monitoring Service | Fuel load proxy |
| Buildings & WUI | IGN BD TOPO | Wildland-urban interface |
| Roads & tracks (DFCI) | IGN BD TOPO / OpenStreetMap | Firefighting access |
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
