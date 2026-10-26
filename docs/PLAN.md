# Plan

## Next steps

Recommended after the exposure map (October 2026), most useful first.

1. [x] Fire outlines for the seven largest fires, which hold 88% of the area burned since 2006: burned area placed where it burned, the cost per house near a fire, and real shapes on the maps.
2. [ ] Expected-loss and premium sketch per hexagon (Weekend 3): houses within 200 m × yearly chance a fire reaches them × cost per house near a fire (about €42,000 in 2022 and €98,000 in 2026). Most hexagons have never burned, so smooth the hazard, for example fire starts per hexagon from BDIFF times the massif-wide chance that a start becomes a large fire. Then set a risk-based premium per house beside a flat one, which gives the cross-subsidy map.
3. [ ] Houses under the pines: OSM maps the pines inside coastal towns as housing, not forest, so Hossegor shows only 36% of houses within 200 m. Copernicus tree-cover density (10 m) would let dense trees inside towns count as fuel. The 2026 fire hit this kind of place: 183 homes burned in Le Porge.
4. [ ] Add the 2026 fires that EFFIS maps but the press list misses (Luglon, 1,800 ha; two at Callen, 880 ha; smaller ones) to the fire map's 2026 view and the stress case.
5. Smaller fixes:
   - [ ] Link the three pages (forest, fires, homes) to each other.
   - [ ] Tidy the README and this plan: the maps use their own 1,500 ha hexagons, not H3; `h3` and `folium` are unused dependencies; the Weekend 1 items are done.
   - [ ] Add sensitivity checks to the exposure method note: 40 vs 50 m² as the smallest home, and forest with and without heath and scrub.
   - [ ] Refresh when final figures come out: BDIFF's 2026 records, France Assureurs' final 2026 cost (€563M is an upper estimate), and a 2022 claims figure for Gironde alone if one exists.
6. [ ] Later: the Weekend 2 drivers (fuel from BD Forêt, fire weather from Météo-France's fire danger index, access from the roads already extracted, such as houses reachable only by forest tracks or dead ends). They help explain the hazard but matter less for the premium sketch.

## Weekend 1 — minimal map

Goal: one honest map of historical fire density over the massif.

- [ ] Define the study area (Landes de Gascogne massif across Landes, Gironde, Lot-et-Garonne)
- [ ] Ingest BDIFF fire records and commune boundaries
- [x] Ingest burned-area outlines of the largest fires: EFFIS for 2017, 2022 and 2026, and the Copernicus EMS building damage of the 2026 Saumos fire (`data/reference/`, `scripts/fetch_fire_outlines.py`)
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
