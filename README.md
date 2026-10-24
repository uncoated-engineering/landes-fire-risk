# Landes Fire-Risk Map

A geospatial wildfire-risk map of the Landes de Gascogne, built entirely from open data — and a sketch of what risk-based insurance premiums could look like parcel by parcel.

The project is the visual companion to an essay arguing that state-flattened risk pricing (regulation, mandatory insurance, reconstruction subsidies) mutes the signals that would otherwise discourage risky land use. If risk is unevenly distributed across the forest, a flat premium is a cross-subsidy. This repo tries to show how uneven.

## Forest history map

[`docs/forest-history/index.html`](docs/forest-history/index.html) is an interactive timeline of the massif from the 18th century to 2026. Drag the slider to step through the Cassini map, the état-major map, the 1950 map, IGN aerial photos (1950–65, 2000–05, today) and Sentinel-2 mosaics (2021, 2023). Major fires appear as circles of equal area, and a second slider blends in today's aerial photo for comparison.

It is a single static page (Leaflet from cdnjs, tiles from IGN Géoplateforme and EOX), so it runs from GitHub Pages or straight from a local file.

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
