"""Build the data behind the exposure map (docs/exposure).

Inputs
- OpenStreetMap extract for Aquitaine (Geofabrik, 25 Oct 2026), published as
  the release asset data-osm-aquitaine of this repository and downloaded to
  data/raw/osm/ on first run.
- INSEE census 2021, dwellings per commune (houses, flats, second homes).
- The BDIFF export used by the fire history map.
- Published insurance figures in data/reference/claims_costs.csv.

Pipeline
1. Buildings, land cover and roads are read from the PBF (pyosmium), kept if
   inside the massif's bounding box and cached as GeoParquet in
   data/processed/osm/.
2. Forest is OSM forest, woods, heath and scrub: the clearing rules apply
   within 200 m of "bois, forêts, landes, plantations, reboisements". For each
   building in the massif, the distance from its footprint to the nearest
   forest (0 when it stands in the forest), flagged within 200 m (the band
   where the clearing duty applies) and within 50 m (the clearing radius).
3. Homes. OSM buildings come from the land registry and include sheds, barns
   and garages: 958,000 buildings for 372,000 houses (INSEE). Likely homes are
   solid buildings (not wall=no, the registry's light structures) of 40 to
   1,000 m² not tagged as a non-residential use. Each commune's likely homes
   are then weighted to add up to its INSEE house count, so a farming commune
   full of barns is not over-counted. Flats are left out.
4. Counts per hexagon, commune and zone.
5. Hazard: the yearly chance that a hectare of forest in each zone burns, from
   BDIFF, in three cases: all years 2006-2025, without 2022, and with the 2026
   press figures added as a stress case. Burned area is placed as on the fire
   map (the largest fires by their EFFIS outline); the forest area per zone
   comes from OSM.
6. Cost of a claim from published insurance totals, and per house near the
   area burned in 2022 and 2026 (EFFIS outlines), with the buildings Copernicus
   EMS graded as damaged by the 2026 Saumos fire.

The massif, zones and hexagons come from build_forest_history.py, as for the
other maps.

Run:  python scripts/build_exposure.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_fire_history as fhist  # noqa: E402
import build_forest_history as fh  # noqa: E402

ROOT = fh.ROOT
PBF = ROOT / "data" / "raw" / "osm" / "aquitaine-261025.osm.pbf"
OSM_URL = ("https://github.com/uncoated-engineering/landes-fire-risk/releases/download/"
           "data-osm-aquitaine/aquitaine-261025.osm.pbf")
OSM_SHA256 = "ddd4ee61d75074f74eb75075d2bc48d5fc2150fd2f29d3f99dfb9ace277ccba2"
INSEE = ROOT / "data" / "raw" / "insee" / "base-cc-logement-2021_csv.zip"
INSEE_URL = "https://www.insee.fr/fr/statistiques/fichier/8202349/base-cc-logement-2021_csv.zip"
CLAIMS = ROOT / "data" / "reference" / "claims_costs.csv"
EMS_BUILDINGS = ROOT / "data" / "reference" / "emsr899_buildings.geojson"
CACHE = ROOT / "data" / "processed" / "osm"
OUT_DIR = ROOT / "docs" / "exposure"
OUT = OUT_DIR / "data.json"

# Land cover kept from OSM (key, value) -> class; built-up land is cached for later steps, not used yet
LANDCOVER = {("landuse", "forest"): "forest", ("natural", "wood"): "forest",
             ("natural", "heath"): "moor", ("natural", "scrub"): "moor",
             ("landuse", "residential"): "built", ("landuse", "farmyard"): "built",
             ("landuse", "industrial"): "built", ("landuse", "commercial"): "built",
             ("landuse", "retail"): "built"}
FOREST = ("forest", "moor")
ROADS = ["motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link", "secondary",
         "secondary_link", "tertiary", "tertiary_link", "unclassified", "residential", "living_street",
         "service", "track", "road"]
MAIN_ROADS = ["motorway", "trunk", "primary"]
BBOX_PAD = 2000  # metres around the massif kept from the extract
TILE = 1000  # forest is cut into tiles of this size (metres) for distance queries
MAX_D = 1000  # distances are measured up to this (metres)
BANDS = [0, 50, 100, 200, 500]  # distance bands for the histogram; 50 and 200 are the flags
HOME_M2 = (40, 1000)
NON_HOME = {"church", "chapel", "school", "retail", "service", "shed", "industrial", "garage", "garages",
            "farm_auxiliary", "ruins", "civic", "commercial", "office", "warehouse", "hangar", "barn", "public",
            "construction", "greenhouse", "roof", "bunker", "static_caravan", "carport", "kiosk", "toilets",
            "transformer_tower", "water_tower", "hospital", "university", "college", "kindergarten",
            "sports_hall", "stadium", "train_station", "transportation", "parking", "supermarket", "government",
            "fire_station", "townhall", "religious", "silo", "storage_tank", "tower", "stable", "cowshed", "sty",
            "boathouse", "pavilion", "grandstand", "manufacture"}
# Communes merged since the boundary file was made: INSEE counts them under the new code
MERGED = {"40009": "40197", "40107": "40197", "40302": "40197"}  # Arjuzanx, Garrosse, Sindères -> Morcenx-la-Nouvelle

wgs_to_l93 = Transformer.from_crs(4326, 2154, always_xy=True)


# ------------------------------------------------------------------- inputs
def fetch_pbf() -> Path:
    if not PBF.exists():
        PBF.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {OSM_URL}")
        urllib.request.urlretrieve(OSM_URL, PBF)
    h = hashlib.sha256()
    with PBF.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != OSM_SHA256:
        raise SystemExit(f"{PBF} does not match the release checksum")
    return PBF


def fetch_insee() -> pd.DataFrame:
    if not INSEE.exists():
        INSEE.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(INSEE_URL, INSEE)
    with zipfile.ZipFile(INSEE) as z:
        return pd.read_csv(z.open("base-cc-logement-2021.CSV"), sep=";", dtype={"CODGEO": str},
                           usecols=["CODGEO", "P21_LOG", "P21_MAISON", "P21_APPART", "P21_RSECOCC"])


def to_l93(hex_wkb: list[str]) -> np.ndarray:
    geoms = shapely.from_wkb(hex_wkb)
    return shapely.transform(geoms, lambda xy: np.column_stack(wgs_to_l93.transform(xy[:, 0], xy[:, 1])))


def extract_osm(bounds) -> dict[str, gpd.GeoDataFrame]:
    """Buildings, land cover and roads inside the massif's bounding box (Lambert-93), cached."""
    paths = {k: CACHE / f"{k}.parquet" for k in ("buildings", "landcover", "roads")}
    if all(p.exists() for p in paths.values()):
        return {k: gpd.read_parquet(p) for k, p in paths.items()}
    import osmium
    import osmium.filter

    pbf = fetch_pbf()
    box = shapely.box(bounds[0] - BBOX_PAD, bounds[1] - BBOX_PAD, bounds[2] + BBOX_PAD, bounds[3] + BBOX_PAD)
    shapely.prepare(box)
    wkb = osmium.geom.WKBFactory()
    out = {k: [] for k in paths}

    def flush(kind, rows):
        if not rows:
            return
        cols = list(zip(*rows))
        g = to_l93(list(cols[-1]))
        keep = shapely.intersects(box, g)
        out[kind].append(gpd.GeoDataFrame({f"c{k}": np.asarray(c, dtype=object)[keep] for k, c in enumerate(cols[:-1])},
                                          geometry=g[keep], crs=2154))
        rows.clear()

    # areas: buildings and land cover (closed ways and multipolygon relations)
    t0 = time.time()
    keys = ("building", "landuse", "natural")
    fp = (osmium.FileProcessor(str(pbf))
          .with_areas(osmium.filter.KeyFilter(*keys))
          .with_filter(osmium.filter.EntityFilter(osmium.osm.AREA))
          .with_filter(osmium.filter.KeyFilter(*keys)))
    bld, lc, bad = [], [], 0
    for a in fp:
        t = a.tags
        is_bld = t.get("building", "no") != "no"
        kv = None if is_bld else next(((k, t[k]) for k in ("landuse", "natural") if (k, t.get(k)) in LANDCOVER), None)
        if not is_bld and kv is None:
            continue
        try:
            g = wkb.create_multipolygon(a)
        except RuntimeError:
            bad += 1
            continue
        if is_bld:
            bld.append((a.id, t["building"], t.get("wall", ""), g))
            if len(bld) >= 200_000:
                flush("buildings", bld)
        else:
            lc.append((a.id, LANDCOVER[kv], kv[1], g))
            if len(lc) >= 20_000:
                flush("landcover", lc)
    flush("buildings", bld)
    flush("landcover", lc)
    print(f"areas read in {time.time() - t0:.0f}s ({bad} invalid skipped)")

    # roads: highway ways
    t0 = time.time()
    fp = (osmium.FileProcessor(str(pbf))
          .with_locations()
          .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY))
          .with_filter(osmium.filter.TagFilter(*[("highway", c) for c in ROADS])))
    rd = []
    for w in fp:
        try:
            g = wkb.create_linestring(w)
        except RuntimeError:
            continue
        rd.append((w.id, w.tags["highway"], g))
        if len(rd) >= 100_000:
            flush("roads", rd)
    flush("roads", rd)
    print(f"roads read in {time.time() - t0:.0f}s")

    names = {"buildings": ["osm_id", "building", "wall"], "landcover": ["osm_id", "cls", "tag"], "roads": ["osm_id", "highway"]}
    CACHE.mkdir(parents=True, exist_ok=True)
    res = {}
    for k, frames in out.items():
        g = pd.concat(frames, ignore_index=True)
        g.columns = names[k] + ["geometry"]
        g = gpd.GeoDataFrame(g, geometry="geometry", crs=2154)
        g["osm_id"] = g.osm_id.astype("int64")
        g.to_parquet(paths[k])
        res[k] = g
        print(f"{k}: {len(g):,} kept")
    return res


# ----------------------------------------------------------------- geometry
def polygons(geoms) -> np.ndarray:
    """Valid polygon parts of any geometries."""
    parts = shapely.get_parts(shapely.get_parts(shapely.make_valid(np.asarray(geoms))))
    return parts[shapely.get_type_id(parts) == 3]


def forest_tiles(forest: np.ndarray, bounds) -> np.ndarray:
    """Forest dissolved inside a grid of TILE x TILE squares: small polygons that never overlap,
    fast to query for distances and safe to sum for areas."""
    x0, y0, x1, y1 = bounds
    xs, ys = np.meshgrid(np.arange(x0, x1, TILE), np.arange(y0, y1, TILE))
    xs, ys = xs.ravel(), ys.ravel()
    cells = shapely.box(xs, ys, xs + TILE, ys + TILE)
    ci, fi = shapely.STRtree(forest).query(cells, predicate="intersects")
    pieces = shapely.intersection(forest[fi], cells[ci])
    keep = shapely.area(pieces) > 0
    df = gpd.GeoDataFrame({"cell": ci[keep]}, geometry=pieces[keep], crs=2154).dissolve("cell")
    return polygons(df.geometry.values)


def hex_cells(m) -> np.ndarray:
    """The massif split between hexagons, so that each point goes to its nearest hexagon centre (as buildings do):
    the grid hexagons clipped to the outline, plus the slivers of the outline that no hexagon covers."""
    hexes = np.array([fh.hexagon(x, y) for x, y in zip(m.hexes.x, m.hexes.y)])
    shapely.prepare(m.massif)
    edge = ~shapely.contains_properly(m.massif, hexes)
    cells = hexes.copy()
    cells[edge] = [shapely.intersection(h, shapely.make_valid(shapely.clip_by_rect(m.massif, *h.bounds))) for h in hexes[edge]]
    slivers = polygons(shapely.difference(m.massif, shapely.union_all(hexes)))
    near = cKDTree(np.column_stack([m.hexes.x, m.hexes.y])).query(shapely.get_coordinates(shapely.point_on_surface(slivers)))[1]
    for k in np.unique(near):
        cells[k] = shapely.union_all([cells[k], *slivers[near == k]])
    return cells


def area_by(pieces: np.ndarray, zones: np.ndarray) -> np.ndarray:
    """Area (m²) of `pieces`, which must not overlap, inside each polygon of `zones`."""
    zi, pi = shapely.STRtree(pieces).query(zones, predicate="intersects")
    a = shapely.area(shapely.intersection(pieces[pi], zones[zi]))
    return np.bincount(zi, weights=a, minlength=len(zones))


# ----------------------------------------------------------------- exposure
def measure_buildings(m, osm, mc) -> tuple[pd.DataFrame, np.ndarray]:
    """One row per building in the massif (tags, footprint m², commune, hexagon, distance to forest),
    and the forest as tiles. Both cached."""
    path, tpath = CACHE / "buildings_massif.parquet", CACHE / "forest_tiles.parquet"
    if path.exists() and tpath.exists():
        return pd.read_parquet(path), gpd.read_parquet(tpath).geometry.values
    t0 = time.time()
    lc = osm["landcover"]
    minx, miny, maxx, maxy = m.bounds
    tiles = forest_tiles(polygons(lc.geometry.values[lc.cls.isin(FOREST)]),
                         (minx - BBOX_PAD, miny - BBOX_PAD, maxx + BBOX_PAD, maxy + BBOX_PAD))
    print(f"forest tiles: {len(tiles):,} ({time.time() - t0:.0f}s)")

    b = osm["buildings"]
    fp = b.geometry.values
    pt = shapely.point_on_surface(fp)
    x, y = shapely.get_x(pt), shapely.get_y(pt)
    shapely.prepare(m.massif)
    inside = shapely.contains_xy(m.massif, x, y)
    fp, x, y = fp[inside], x[inside], y[inside]
    df = pd.DataFrame({"osm_id": b.osm_id.values[inside], "building": b.building.values[inside],
                       "wall": b.wall.values[inside], "m2": shapely.area(fp).round(1), "x": x.round(1), "y": y.round(1)})
    df["hex"] = cKDTree(np.column_stack([m.hexes.x, m.hexes.y])).query(np.column_stack([x, y]))[1]
    pts = gpd.GeoDataFrame(geometry=shapely.points(x, y), crs=2154)
    j = gpd.sjoin(pts, mc[["code", "geometry"]], how="left", predicate="within")
    df["code"] = j[~j.index.duplicated()]["code"].values
    if df.code.isna().any():  # on a boundary: nearest commune
        miss = df.code.isna().values
        near = gpd.sjoin_nearest(pts[miss], mc[["code", "geometry"]], how="left")
        df.loc[miss, "code"] = near[~near.index.duplicated()]["code"].values

    t0 = time.time()
    (bi, _), d = shapely.STRtree(tiles).query_nearest(fp, max_distance=MAX_D, return_distance=True, all_matches=False)
    dist = np.full(len(fp), np.inf)
    dist[bi] = d
    df["d"] = dist.round(1)
    print(f"distances for {len(df):,} buildings ({time.time() - t0:.0f}s)")
    df.to_parquet(path)
    gpd.GeoDataFrame(geometry=tiles, crs=2154).to_parquet(tpath)
    return df, tiles


def weight_homes(df: pd.DataFrame, mc) -> tuple[pd.Series, dict]:
    """Weight of each building as a home: likely homes get their commune's INSEE houses / likely homes."""
    likely = (df.wall != "no") & ~df.building.isin(NON_HOME) & df.m2.between(*HOME_M2)
    group = df.code.replace(MERGED)
    codes = sorted(set(mc.code.replace(MERGED)))
    ins = fetch_insee().set_index("CODGEO").reindex(codes)
    if ins.P21_MAISON.isna().any():
        raise SystemExit(f"no INSEE row for {ins.index[ins.P21_MAISON.isna()].tolist()}: add them to MERGED")
    n_likely = likely.groupby(group).sum().reindex(codes).fillna(0)
    ratio = ins.P21_MAISON / n_likely
    w = np.where(likely, group.map(ratio).values, 0.0)
    info = dict(buildings=len(df), light=int((df.wall == "no").sum()), likely=int(likely.sum()),
                maxRatio=round(float((n_likely / ins.P21_MAISON).replace(np.inf, np.nan).max()), 1),
                houses=round(float(ins.P21_MAISON.sum())), flats=round(float(ins.P21_APPART.sum())),
                dwellings=round(float(ins.P21_LOG.sum())), second=round(float(ins.P21_RSECOCC.sum())))
    print(f"homes: {info['likely']:,} likely homes among {len(df):,} buildings, weighted to {w.sum():,.0f} "
          f"of {info['houses']:,} INSEE houses ({info['likely'] / info['houses']:.2f} likely homes per house; "
          f"{(ratio > 1).sum()} communes with more houses than likely homes)")
    return pd.Series(w, index=df.index), info


def hazard(m, mc, comm_hexes, outlines, forest_ha: np.ndarray) -> dict:
    """Yearly chance that a hectare of forest burns, per zone, in three cases."""
    df = fhist.load_bdiff()
    fires = df[df["Code INSEE"].isin(set(mc.code))]
    nz = len(m.zone_ids)
    hz = np.array([m.zone_ids.index(m.zone_of[h]) for h in m.hexes.index])
    wz = {c: np.bincount(hz[h], minlength=nz) / len(h) for c, h in comm_hexes.items()}
    wo = [np.bincount(hz, weights=s, minlength=nz) for s in outlines.hexShare]  # by outline, for the largest fires

    def weights(code, key):
        k = fhist.outline_index(outlines, code, key)
        return wo[k] if k >= 0 else wz[code]
    y0, y1 = int(fires["Année"].min()), int(fires["Année"].max())
    burned = {y: np.zeros(nz) for y in range(y0, y1 + 2)}
    for code, date, year, ha in zip(fires["Code INSEE"], fires.date, fires["Année"], fires.ha):
        burned[int(year)] += ha * weights(code, date.strftime("%Y-%m-%d"))
    for _, code, ha, _ in fhist.PRESS_2026:
        burned[y1 + 1] += ha * weights(code, str(y1 + 1))
    cases = [("all", f"{y0}–{y1}", [y for y in range(y0, y1 + 1)]),
             ("no2022", f"{y0}–{y1} without 2022", [y for y in range(y0, y1 + 1) if y != 2022]),
             ("with2026", f"{y0}–{y1 + 1}, 2026 from press figures", [y for y in range(y0, y1 + 2)])]
    out = []
    for cid, label, years in cases:
        tot = sum(burned[y] for y in years)
        out.append(dict(id=cid, label=label, years=len(years), burnedHa=[round(v) for v in tot],
                        p=[round(float(v), 7) for v in tot / len(years) / forest_ha],
                        pMassif=round(float(tot.sum() / len(years) / forest_ha.sum()), 7)))
        print(f"hazard {cid:9s} massif {100 * out[-1]['pMassif']:.3f}%/yr  zones " +
              " ".join(f"{z}:{100 * p:.3f}" for z, p in zip(m.zone_ids, out[-1]['p'])))
    return dict(years=[y0, y1], cases=out, byYear={str(y): [round(v, 1) for v in burned[y]] for y in burned})


def claims() -> list[dict]:
    rows = list(csv.DictReader(CLAIMS.open()))
    for r in rows:
        r["year"], r["claims"], r["cost_eur"] = int(r["year"]), int(r["claims"]), int(r["cost_eur"])
        r["per_claim"] = round(r["cost_eur"] / r["claims"])
        print(f"claims {r['year']} {r['scope']}: {r['claims']:,} claims, EUR {r['cost_eur'] / 1e6:,.0f}M, "
              f"EUR {r['per_claim']:,} per claim")
    return rows


def near_fires(df: pd.DataFrame, w: pd.Series, outlines, tiles: np.ndarray, rows: list[dict]) -> dict:
    """Houses near the area burned in 2022 and 2026, and what the fires cost per house near them;
    buildings Copernicus EMS graded after the 2026 Saumos fire, by distance to the forest."""
    pts = shapely.points(df.x.values, df.y.values)
    paid = {2022: next(r for r in rows if r["year"] == 2022),
            2026: next(r for r in rows if r["year"] == 2026 and "Var" not in r["scope"])}
    out = {}
    for year, r in paid.items():
        burned = shapely.union_all(outlines.geometry.values[outlines.year.values == year])
        shapely.prepare(burned)
        near = {k: shapely.dwithin(burned, pts, d) if d else shapely.contains(burned, pts) for k, d in
                (("in", 0), ("d200", 200), ("d1000", 1000))}
        out[str(year)] = dict(burnedHa=round(shapely.area(burned) / 1e4), **{k: round(float(w[v].sum())) for k, v in near.items()},
                              claims=r["claims"], cost=r["cost_eur"], scope=r["scope"])
        print(f"near fires {year}: {out[str(year)]}")
    ems = gpd.read_file(EMS_BUILDINGS).to_crs(2154)
    (bi, _), d = shapely.STRtree(tiles).query_nearest(ems.geometry.values, max_distance=MAX_D, return_distance=True,
                                                         all_matches=False)
    dist = np.full(len(ems), np.inf)
    dist[bi] = d
    saumos = outlines.geometry.values[(outlines.year.values == 2026) & (outlines.name.values == "Saumos")][0]
    near = shapely.dwithin(saumos, pts, 200) & (df.wall != "no").values  # solid buildings near the graded fire
    grades = {}
    for g in ("Destroyed", "Damaged", "Possibly damaged"):
        k = (ems.damage == g).values
        grades[g] = dict(n=int(k.sum()), d50=round(float(np.mean(dist[k] <= 50)), 3), d200=round(float(np.mean(dist[k] <= 200)), 3))
    out["ems"] = dict(grades=grades, base50=round(float(np.mean(df.d.values[near] <= 50)), 3))
    print(f"EMS graded buildings: {grades}; solid buildings within 200 m of the Saumos fire: {out['ems']['base50']:.0%} within 50 m of forest")
    return out


def roads_in_massif(m, roads: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Road segments whose midpoint lies in the massif, with their hexagon. Cached."""
    path = CACHE / "roads_massif.parquet"
    if path.exists():
        return gpd.read_parquet(path)
    mid = shapely.line_interpolate_point(roads.geometry.values, 0.5, normalized=True)
    x, y = shapely.get_x(mid), shapely.get_y(mid)
    shapely.prepare(m.massif)
    keep = shapely.contains_xy(m.massif, x, y)
    r = roads[keep].copy()
    r["hex"] = cKDTree(np.column_stack([m.hexes.x, m.hexes.y])).query(np.column_stack([x[keep], y[keep]]))[1]
    r.to_parquet(path)
    return r


def svg_lines(geom, sx, sy, tol=300) -> str:
    geom = shapely.simplify(geom, tol)
    parts = shapely.get_parts(geom)
    return "".join("M" + "L".join(f"{sx(x)},{sy(y)}" for x, y in shapely.get_coordinates(p)) for p in parts
                   if shapely.get_type_id(p) == 1)


def main():
    m = fh.build_massif()
    bdiff = fhist.load_bdiff()
    mc, hex_code, comm_hexes = fhist.commune_hexes(m, bdiff)
    osm = extract_osm(m.bounds)
    df, tiles = measure_buildings(m, osm, mc)
    w, info = weight_homes(df, mc)

    near200, near50 = df.d <= 200, df.d <= 50
    nh, nzn = len(m.hexes), len(m.zone_ids)
    hexzone = np.array([m.zone_ids.index(m.zone_of[h]) for h in m.hexes.index])

    def by(key, n, weights=None):
        return np.bincount(key, weights=weights, minlength=n)
    hexstat = {k: by(df.hex.values, nh, v) for k, v in [("homes", w), ("h200", w * near200), ("h50", w * near50),
                                                         ("bld", None), ("b200", near200), ("b50", near50)]}
    cells = hex_cells(m)
    forest_hex = area_by(tiles, cells) / 1e4
    cell_ha = shapely.area(cells) / 1e4
    zone = {k: by(hexzone, nzn, v) for k, v in hexstat.items()}
    zone["forest"] = by(hexzone, nzn, forest_hex)
    roads = roads_in_massif(m, osm["roads"])
    km = shapely.length(roads.geometry.values) / 1000
    track = (roads.highway == "track").values
    zone["trackKm"] = by(hexzone[roads.hex.values], nzn, km * track)
    zone["roadKm"] = by(hexzone[roads.hex.values], nzn, km * ~track)
    print(f"forest in massif: {forest_hex.sum():,.0f} ha (IFN: 987,950 ha); roads {zone['roadKm'].sum():,.0f} km, "
          f"tracks {zone['trackKm'].sum():,.0f} km")
    tot = {k: v.sum() for k, v in zone.items()}
    print(f"homes {tot['homes']:,.0f}: within 200 m {tot['h200']:,.0f} ({tot['h200'] / tot['homes']:.0%}), "
          f"within 50 m {tot['h50']:,.0f} ({tot['h50'] / tot['homes']:.0%})")
    print(f"buildings {tot['bld']:,.0f}: within 200 m {tot['b200']:,.0f}, within 50 m {tot['b50']:,.0f}")
    for z, zid in enumerate(m.zone_ids):
        print(f"  {zid:9s} homes {zone['homes'][z]:8,.0f}  ≤200 m {zone['h200'][z]:8,.0f} ({zone['h200'][z] / zone['homes'][z]:4.0%})"
              f"  ≤50 m {zone['h50'][z]:8,.0f}  forest {zone['forest'][z]:9,.0f} ha")
    edges = BANDS + [MAX_D]
    band = np.searchsorted(np.array(edges[1:]), df.d.values, side="left") + 1  # 1: up to 50 m ... last: beyond MAX_D
    band[df.d.values == 0] = 0  # in the forest
    hist = by(band, len(edges) + 1, w)
    print("homes by distance band:", hist.round(0).tolist())

    outlines = fhist.fire_outlines(m)
    hz = hazard(m, mc, comm_hexes, outlines, zone["forest"])
    cl = claims()
    calib = near_fires(df, w, outlines, tiles, cl)

    # page data
    bm = fh.base_map(m)
    sx, sy, b = bm.sx, bm.sy, bm.data
    code_idx = {c: k for k, c in enumerate(mc.code)}
    centre = mc.representative_point()
    cstat = pd.DataFrame({"homes": w, "h200": w * near200, "h50": w * near50}).groupby(df.code.values).sum()
    communes = [[r.nom, sx(centre[k].x), sy(centre[k].y), *[round(float(cstat.at[r.code, c])) if r.code in cstat.index else 0
                                                           for c in ("homes", "h200", "h50")]] for k, r in mc.iterrows()]
    # the largest fires, drawn by their outline and labelled with their official area (BDIFF, or press for 2026)
    ha_of = np.zeros(len(outlines))
    for code, date, ha in zip(bdiff["Code INSEE"], bdiff.date, bdiff.ha):
        k = fhist.outline_index(outlines, code, date.strftime("%Y-%m-%d"))
        if k >= 0:
            ha_of[k] += ha
    for _, code, ha, _ in fhist.PRESS_2026:
        ha_of[fhist.outline_index(outlines, code, "2026")] += ha
    fires = []
    for k, r in outlines.iterrows():
        x0, y0, x1, y1 = r.geometry.bounds
        fires.append([r["name"], int(r.year), round(ha_of[k]), int(r.year == 2026), bm.path(r.geometry, 120),
                      [sx(x0), sy(y1), sx(x1), sy(y0)]])
    main_roads = shapely.line_merge(shapely.union_all(roads.geometry.values[roads.highway.isin(MAIN_ROADS).values]))
    zones = [{**zp, **{k: round(float(zone[k][z])) for k in zone}} for z, zp in enumerate(b["zones"])]
    data = dict(
        meta={**b["meta"], "osmDate": "25 October 2026", "maxD": MAX_D, "bands": BANDS, "homeM2": list(HOME_M2), **info},
        hexes=b["hexes"], zones=zones, land=b["land"], massif=b["massif"], depts=b["depts"], labels=b["labels"],
        towns=b["towns"], roads=svg_lines(main_roads, sx, sy),
        hexStats=dict(homes=hexstat["homes"].round().astype(int).tolist(), h200=hexstat["h200"].round().astype(int).tolist(),
                      h50=hexstat["h50"].round().astype(int).tolist(),
                      forestPct=np.clip(100 * forest_hex / cell_ha, 0, 100).round().astype(int).tolist()),
        hexComm=[code_idx[hex_code[h]] for h in m.hexes.index],
        communes=communes, hist=hist.round().astype(int).tolist(), hazard=hz, claims=cl, fires=fires, calib=calib,
        sources=["https://download.geofabrik.de/europe/france/aquitaine.html",
                 "https://www.insee.fr/fr/statistiques/8202349",
                 "https://bdiff.agriculture.gouv.fr/",
                 "https://www.franceassureurs.fr/press-en/press-releases/wildfires-gironde-landes-var-25000claims-losses-estimated-nearly-500million/",
                 cl[0]["source"],
                 fhist.PRESS_SOURCE,
                 fhist.EFFIS_SOURCE,
                 "https://rapidmapping.emergency.copernicus.eu/EMSR899/",
                 "https://www.prefectures-regions.gouv.fr/nouvelle-aquitaine/content/download/95578/610660/file/Plaquette%20-%20Le%20d%C3%A9broussaillement.pdf",
                 "https://github.com/gregoiredavid/france-geojson"],
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")
    if (OUT_DIR / "template.html").exists():
        fh.render_page(OUT.read_text(), OUT_DIR, "exposure.artifact.html")


if __name__ == "__main__":
    main()
