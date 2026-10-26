# Plan

## Weekend 1 — minimal map

Goal: one honest map of historical fire density over the massif.

- [ ] Define the study area (Landes de Gascogne massif across Landes, Gironde, Lot-et-Garonne)
- [ ] Ingest BDIFF fire records and commune boundaries
- [ ] Ingest 2022 burned-area perimeters (Landiras, La Teste-de-Buch)
- [ ] Aggregate to an H3 grid (resolution 7 to start)
- [ ] Publish a first interactive map

## Weekend 2 — drivers

- [ ] Fuel: BD Forêt species + tree cover density per cell
- [ ] Weather: IFM climatology (days above high-danger threshold per season)
- [ ] Access: distance to roads / DFCI tracks
- [x] Exposure: houses within 200 m and 50 m of the forest, per hexagon and zone (OpenStreetMap + INSEE) → `docs/exposure/`
- [ ] Composite risk score; validate against held-out fire years (e.g. train ≤2021, test 2022 and 2026)

## Weekend 3 — the pricing sketch

- [ ] Join risk score to cadastral parcels
- [x] Hazard per zone from BDIFF: yearly chance a hectare of forest burns, in three cases (all years, without 2022, with 2026)
- [x] Cost per claim from published insurance figures (`data/reference/claims_costs.csv`)
- [ ] Simple expected-loss model: P(fire) × exposed value
- [ ] Compare a risk-based premium with a flat premium across the massif
- [ ] Map the implied cross-subsidy: who pays more than their risk, who pays less

## Write-up

- [ ] Method note in `docs/`
- [ ] Short post tying the maps back to the essay's argument
- [ ] State the limits plainly (data gaps, ignition causes, model simplicity)
