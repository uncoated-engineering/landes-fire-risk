"""Build the data behind the forest history map (docs/forest-history).

Pipeline
1. Communes of Gironde, Landes and Lot-et-Garonne (gregoiredavid/france-geojson)
   are filtered to the Landes de Gascogne massif (~1.33 million ha, which
   matches the IFN figure of 987,950 ha of forest at 74.3% cover).
2. The massif is split into eight natural zones ("pays").
3. A hexagon grid (1 hexagon = 1,500 ha) is laid over the massif.
4. For each snapshot year, massif-wide totals from
   data/reference/forest_history_anchors.csv are split between zones
   (zone parameters below are estimates) and then between hexagons.

Which hexagon inside a zone is forest is illustrative; the count per zone is
what the model says. Fire hexagons are placed around the real fire locations.

Run:  python scripts/build_forest_history.py
"""
from __future__ import annotations

import csv
import json
import math
import random
import urllib.request
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "geo"
ANCHORS = ROOT / "data" / "reference" / "forest_history_anchors.csv"
OUT = ROOT / "docs" / "forest-history" / "data.json"

GEOJSON = "https://raw.githubusercontent.com/gregoiredavid/france-geojson/master"
DEPTS = ["33-gironde", "40-landes", "47-lot-et-garonne"]

HEX_HA = 1500
HEX_R = math.sqrt(2 * HEX_HA * 1e4 / (3 * math.sqrt(3)))  # metres, centre to corner

to_l93 = Transformer.from_crs(4326, 2154, always_xy=True).transform

# ---------------------------------------------------------------- geography
# Inland limit of the massif (lon, lat). The ocean side is left open and the
# real coastline comes from the commune polygons.
MASSIF_LIMIT = [(-1.6, 45.62), (-1.08, 45.58), (-0.98, 45.47), (-0.96, 45.36), (-0.90, 45.22), (-0.83, 45.12),
                (-0.79, 45.02), (-0.73, 44.93), (-0.71, 44.86), (-0.68, 44.79), (-0.62, 44.75), (-0.55, 44.68),
                (-0.47, 44.60), (-0.38, 44.50), (-0.25, 44.44), (-0.10, 44.40), (0.06, 44.36), (0.20, 44.25),
                (0.30, 44.12), (0.22, 44.00), (0.02, 43.95), (-0.22, 43.94), (-0.36, 43.90), (-0.52, 43.91),
                (-0.68, 43.88), (-0.85, 43.81), (-1.02, 43.74), (-1.20, 43.68), (-1.35, 43.60), (-1.45, 43.52),
                (-1.7, 43.5)]
# Edge communes whose centroid falls just outside the line but belong to the massif
EDGE_COMMUNES = {
    "Landiras", "Budos", "Bazas", "Saint-Selve", "Saint-Michel-de-Rieufret", "Mérignac", "Haillan", "Taillan-Médoc",
    "Avensan", "Moulis-en-Médoc", "Arsac", "Pian-Médoc", "Pujols-sur-Ciron", "Léogeats", "Gans", "Cauvignac",
    "Grignols", "Lados", "Bouglon", "Ruffiac", "Poussignac", "Labastide-Castel-Amouroux", "Tartas", "Mont-de-Marsan",
    "Saint-Pierre-du-Mont", "Bretagne-de-Marsan", "Saint-Perdon", "Campagne", "Saugnac-et-Cambran", "Dax", "Téthieu",
    "Yzosse", "Saint-Martin-de-Seignanx", "Saint-André-de-Seignanx", "Biarrotte", "Biaudos", "Saint-Martin-de-Hinx",
    "Saint-Jean-de-Marsacq", "Saubrigues", "Saubusse", "Villeneuve-de-Marsan", "Cissac-Médoc",
}
# Ocean shoreline used for the coastal dune belt (lon, lat)
COAST = [(-1.06, 45.57), (-1.13, 45.51), (-1.16, 45.38), (-1.17, 45.22), (-1.20, 45.00), (-1.22, 44.89),
         (-1.25, 44.63), (-1.26, 44.45), (-1.30, 44.21), (-1.32, 44.09), (-1.36, 43.95), (-1.39, 43.85),
         (-1.44, 43.66), (-1.45, 43.64), (-1.50, 43.54)]
DUNE_BELT_KM = 6.5

LAKES = [("Hourtin-Carcans", 45.17, -1.08, 4), ("Lacanau", 45.00, -1.11, 1),
         ("Cazaux-Sanguinet", 44.49, -1.17, 4), ("Parentis-Biscarrosse", 44.35, -1.17, 2)]

TOWNS = [("Soulac", 45.51, -1.12), ("Lesparre", 45.31, -0.94), ("Lacanau", 44.98, -1.08), ("Bordeaux", 44.84, -0.58),
         ("Arcachon", 44.66, -1.17), ("Belin-Béliet", 44.50, -0.79), ("Bazas", 44.43, -0.21),
         ("Biscarrosse", 44.39, -1.16), ("Casteljaloux", 44.31, 0.09), ("Mimizan", 44.20, -1.23),
         ("Sabres", 44.15, -0.74), ("Roquefort", 44.03, -0.32), ("Castets", 43.88, -1.15),
         ("Mont-de-Marsan", 43.89, -0.50), ("Dax", 43.71, -1.05), ("Hossegor", 43.66, -1.42)]

# Zone seeds (lon, lat): each commune joins the zone of its nearest seed.
# Zone parameters are estimates:
#   h      forest share of the zone around 1780 (old coastal and riverside woods)
#   P      forest share at the pre-war peak
#   mid    year by which half the planting was done; tau = spread in years
#   farm   share of the post-1950 farm clearings (maize) that fell in the zone
#   burn40 share of the 1940s burned area
#   martin / klaus  share of storm damage in 1999 / 2009
ZONES = [
    dict(id="dunes", name="Coastal dunes", seeds=[], h=.32, P=.92, mid=1835, tau=14, farm=.00, burn40=.04, martin=.03, klaus=.06,
         blurb="State forests planted on the moving dunes between 1801 and 1876."),
    dict(id="medoc", name="Médoc", seeds=[(-1.0, 45.42), (-0.97, 45.22), (-0.92, 45.06)], h=.12, P=.88, mid=1875, tau=14,
         farm=.10, burn40=.11, martin=.26, klaus=.07, blurb="Moors west of the Médoc vineyards, Hourtin to Saumos."),
    dict(id="buch", name="Pays de Buch", seeds=[(-1.05, 44.68), (-0.98, 44.58), (-0.85, 44.52), (-1.12, 44.60)], h=.30, P=.86,
         mid=1865, tau=14, farm=.05, burn40=.12, martin=.14, klaus=.07,
         blurb="Around the Arcachon basin, home of the old La Teste pine forest."),
    dict(id="bordeaux", name="Landes bordelaises", seeds=[(-0.75, 44.84), (-0.70, 44.70), (-0.55, 44.62), (-0.45, 44.50)], h=.12,
         P=.85, mid=1868, tau=14, farm=.12, burn40=.22, martin=.20, klaus=.10,
         blurb="The moors south and west of Bordeaux: Cestas, Saucats, Landiras. Chambrelent's trials began here."),
    dict(id="born", name="Born", seeds=[(-1.15, 44.42), (-1.17, 44.22), (-1.05, 44.35)], h=.22, P=.88, mid=1870, tau=14,
         farm=.07, burn40=.10, martin=.08, klaus=.15, blurb="Lakes and forest behind the dunes: Biscarrosse, Parentis, Mimizan."),
    dict(id="grande", name="Grande Lande", seeds=[(-0.85, 44.30), (-0.80, 44.13), (-0.62, 44.18), (-0.72, 44.42)], h=.06, P=.92,
         mid=1882, tau=14, farm=.26, burn40=.23, martin=.15, klaus=.25,
         blurb="The heart of the old moorland: Sabres, Pissos, Solférino, Luxey."),
    dict(id="marensin", name="Marensin & Maremne", seeds=[(-1.25, 43.95), (-1.10, 43.85), (-1.30, 43.70), (-0.98, 43.75), (-0.85, 43.88)],
         h=.24, P=.86, mid=1872, tau=14, farm=.16, burn40=.08, martin=.04, klaus=.15,
         blurb="The southern massif from Lit-et-Mixe and Castets down to Dax and the Adour."),
    dict(id="bazadais", name="Bazadais & Albret", seeds=[(-0.26, 44.29), (0.08, 44.20), (-0.30, 44.42), (0.15, 44.08)],
         h=.18, P=.80, mid=1888, tau=14, farm=.12, burn40=.05, martin=.06, klaus=.07,
         blurb="The north-eastern edge: Bazas, Captieux, Casteljaloux, Houeillès. Old oak woods and more farmland."),
    dict(id="petites", name="Petites Landes", seeds=[(-0.32, 44.03), (-0.10, 43.97), (-0.50, 43.95)],
         h=.14, P=.80, mid=1892, tau=14, farm=.12, burn40=.05, martin=.04, klaus=.08,
         blurb="Roquefort, Gabarret and the sands north of Mont-de-Marsan, where the forest meets Armagnac."),
]

LABELS = [("GIRONDE", 44.88, -0.22, 0), ("LANDES", 43.62, -0.62, 0), ("LOT-ET-GARONNE", 44.62, 0.42, 0),
          ("Atlantic Ocean", 44.55, -1.62, -78)]

SNAPSHOTS = [1780, 1817, 1857, 1876, 1890, 1910, 1940, 1950, 1965, 1980, 2000, 2009, 2021, 2022, 2026]

FIRES = {  # year: [(name, lat, lon, hectares)]
    1950: [("Cestas–Saucats fire, Aug 1949", 44.68, -0.66, 50000)],
    2022: [("Landiras fires", 44.52, -0.55, 23000), ("La Teste-de-Buch fire", 44.56, -1.17, 7000)],
    2026: [("Saumos fire", 44.86, -1.08, 42000), ("Biscarrosse fire", 44.37, -1.13, 3600)],
}


def fetch_communes() -> gpd.GeoDataFrame:
    RAW.mkdir(parents=True, exist_ok=True)
    frames = []
    for d in DEPTS:
        path = RAW / f"communes-{d}.geojson"
        if not path.exists():
            urllib.request.urlretrieve(f"{GEOJSON}/departements/{d}/communes-{d}.geojson", path)
        frames.append(gpd.read_file(path))
    g = pd.concat(frames, ignore_index=True).set_crs(4326, allow_override=True).to_crs(2154)
    g["ha"] = g.area / 1e4
    return g


def fetch_departements() -> gpd.GeoDataFrame:
    path = RAW / "departements-simplifie.geojson"
    if not path.exists():
        urllib.request.urlretrieve(f"{GEOJSON}/departements-version-simplifiee.geojson", path)
    return gpd.read_file(path).set_crs(4326, allow_override=True).to_crs(2154)


def value_noise(seed: int, cell_m: float):
    rng = np.random.default_rng(seed)
    grid = rng.random((80, 80))

    def f(x, y):
        gx, gy = x / cell_m, y / cell_m
        i, j = int(math.floor(gx)) % 79, int(math.floor(gy)) % 79
        fx, fy = gx - math.floor(gx), gy - math.floor(gy)
        sx, sy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
        a = grid[i, j] * (1 - sx) + grid[i + 1, j] * sx
        b = grid[i, j + 1] * (1 - sx) + grid[i + 1, j + 1] * sx
        return a * (1 - sy) + b * sy
    return f


def hexagon(cx, cy, r=HEX_R):
    return Polygon([(cx + r * math.cos(math.radians(60 * k + 30)), cy + r * math.sin(math.radians(60 * k + 30))) for k in range(6)])


def allocate(total: int, raw: dict, cap: dict) -> dict:
    """Split `total` units across zones proportionally to `raw`, never above `cap`."""
    total = min(total, sum(cap.values()))
    lo, hi = 0.0, 1e6
    for _ in range(200):
        s = (lo + hi) / 2
        if sum(min(s * raw[z], cap[z]) for z in raw) < total:
            lo = s
        else:
            hi = s
    share = {z: min(hi * raw[z], cap[z]) for z in raw}
    out = {z: int(math.floor(v)) for z, v in share.items()}
    rest = total - sum(out.values())
    for z in sorted(share, key=lambda z: share[z] - out[z], reverse=True):
        if rest <= 0:
            break
        if out[z] < cap[z]:
            out[z] += 1
            rest -= 1
    return out


def main():
    random.seed(7)
    communes = fetch_communes()
    reps = communes.representative_point().to_crs(4326)
    inside = reps.within(Polygon(MASSIF_LIMIT)) | communes["nom"].isin(EDGE_COMMUNES)
    massif_c = communes[inside].copy()
    massif = unary_union(massif_c.geometry.buffer(1)).buffer(-1)
    print(f"massif: {len(massif_c)} communes, {massif_c.ha.sum():,.0f} ha")

    # zone of each commune by nearest seed
    seed_pts = [(z["id"], Point(to_l93(lon, lat))) for z in ZONES for lon, lat in z["seeds"]]
    massif_c["zone"] = [min(seed_pts, key=lambda s: s[1].distance(p))[0] for p in massif_c.representative_point()]

    coast = LineString([to_l93(lon, lat) for lon, lat in COAST])

    # hexagon grid (pointy-top) over the massif
    minx, miny, maxx, maxy = massif.bounds
    w, h = math.sqrt(3) * HEX_R, 1.5 * HEX_R
    centres = []
    row = 0
    y = miny
    while y <= maxy + h:
        x = minx + (w / 2 if row % 2 else 0)
        while x <= maxx + w:
            if massif.contains(Point(x, y)):
                centres.append((x, y))
            x += w
        y += h
        row += 1
    hexes = gpd.GeoDataFrame({"x": [c[0] for c in centres], "y": [c[1] for c in centres]},
                             geometry=[Point(c) for c in centres], crs=2154)
    joined = gpd.sjoin(hexes, massif_c[["zone", "geometry"]], how="left", predicate="within")
    joined = joined[~joined.index.duplicated()]
    hexes["zone"] = joined["zone"]
    for i in hexes.index[hexes.zone.isna()]:
        p = hexes.geometry[i]
        hexes.loc[i, "zone"] = massif_c.loc[massif_c.distance(p).idxmin(), "zone"]
    hexes["coast_km"] = [coast.distance(p) / 1000 for p in hexes.geometry]
    hexes.loc[hexes.coast_km <= DUNE_BELT_KM, "zone"] = "dunes"
    n = len(hexes)
    print(f"hexagons: {n} x {HEX_HA} ha = {n * HEX_HA:,} ha")

    # lakes
    water = set()
    for _, lat, lon, k in LAKES:
        p = Point(to_l93(lon, lat))
        d = hexes.distance(p).sort_values()
        water.update(d.index[:k])

    # rankings (higher = earlier / more likely)
    nf1, nf2 = value_noise(1, 22000), value_noise(2, 7000)
    na1, na2 = value_noise(3, 16000), value_noise(4, 6000)
    nb, ns = value_noise(5, 14000), value_noise(6, 18000)
    early_spots = [Point(to_l93(-0.75, 44.74)), Point(to_l93(-0.88, 44.13))]  # Pierroton (Chambrelent), Solférino
    pf, pa, pb, ps = {}, {}, {}, {}
    for i, r in hexes.iterrows():
        x, y = r.x, r.y
        base = .65 * nf1(x, y) + .35 * nf2(x, y)
        if r.zone == "dunes":
            base += .09 * r.coast_km  # old woods sat on the inland side of the moving dunes
        else:
            base -= .004 * r.coast_km
        base += sum(.45 * math.exp(-Point(x, y).distance(s) / 9000) for s in early_spots)
        pf[i] = base
        pa[i] = .7 * na1(x, y) + .3 * na2(x, y)
        pb[i] = nb(x, y) + .2 * random.random()
        ps[i] = ns(x, y) + .2 * random.random()

    zone_ids = [z["id"] for z in ZONES]
    zone_of = hexes.zone.to_dict()
    members = {z: [i for i in hexes.index if zone_of[i] == z] for z in zone_ids}
    nz = {z: len(members[z]) for z in zone_ids}
    land = {z: [i for i in members[z] if i not in water] for z in zone_ids}

    anchors = {int(r["year"]): r for r in csv.DictReader(ANCHORS.open())}

    def nearest_forest(lat, lon, k, forest, exclude):
        p = Point(to_l93(lon, lat))
        cand = [i for i in forest if i not in exclude]
        cand.sort(key=lambda i: hexes.geometry[i].distance(p))
        return cand[:k]

    states, zone_stats, burned_1950 = {}, {}, []
    prev_fire_2022 = []
    for year in SNAPSHOTS:
        a = anchors[year]
        F = round(float(a["forest_land_ha"]) / HEX_HA)
        D = round(float(a["damaged_ha"]) / HEX_HA)
        A = round(float(a["farmland_ha"]) / HEX_HA)
        # farmland: pre-war share proportional to land area (none on dunes), post-war clearings by weight
        base_A = round(62000 / HEX_HA)
        pre = allocate(min(A, base_A), {z: (0 if z == "dunes" else len(land[z])) for z in zone_ids},
                       {z: len(land[z]) for z in zone_ids})
        extra = allocate(max(0, A - base_A), {z: next(Z["farm"] for Z in ZONES if Z["id"] == z) + 1e-9 for z in zone_ids},
                         {z: len(land[z]) - pre[z] for z in zone_ids})
        farm_n = {z: pre[z] + extra[z] for z in zone_ids}
        farm = set()
        for z in zone_ids:
            farm.update(sorted(land[z], key=lambda i: pa[i], reverse=True)[:farm_n[z]])
        # forest land by zone
        raw = {}
        for Z in ZONES:
            g = Z["h"] + (Z["P"] - Z["h"]) / (1 + math.exp(-(year - Z["mid"]) / Z["tau"]))
            raw[Z["id"]] = nz[Z["id"]] * g
        cap = {z: len([i for i in land[z] if i not in farm]) for z in zone_ids}
        forest_n = allocate(F, raw, cap)
        forest = []
        for z in zone_ids:
            free = [i for i in land[z] if i not in farm]
            forest += sorted(free, key=lambda i: pf[i], reverse=True)[:forest_n[z]]
        fset = set(forest)
        # damage
        damaged = []
        if year == 1950:
            for _, lat, lon, ha in FIRES[1950]:
                damaged += nearest_forest(lat, lon, round(ha / HEX_HA), forest, set(damaged))
            rest = D - len(damaged)
            by_zone = allocate(rest, {Z["id"]: Z["burn40"] for Z in ZONES},
                               {z: len([i for i in members[z] if i in fset]) for z in zone_ids})
            for z in zone_ids:
                cand = [i for i in members[z] if i in fset and i not in damaged]
                damaged += sorted(cand, key=lambda i: pb[i], reverse=True)[:by_zone[z]]
            burned_1950 = list(damaged)
        elif year == 1965:
            damaged = [i for i in sorted(burned_1950, key=lambda i: pb[i]) if i in fset][:D]
        elif year in (2000, 2009):
            key = "martin" if year == 2000 else "klaus"
            by_zone = allocate(D, {Z["id"]: Z[key] for Z in ZONES},
                               {z: len([i for i in members[z] if i in fset]) for z in zone_ids})
            for z in zone_ids:
                cand = [i for i in members[z] if i in fset]
                damaged += sorted(cand, key=lambda i: ps[i] + (0.6 if year == 2009 else -0.6) * (hexes.y[i] < 6350000), reverse=True)[:by_zone[z]]
        elif year in (2022, 2026):
            if year == 2026:
                damaged += [i for i in prev_fire_2022 if i in fset]
            for _, lat, lon, ha in FIRES[year]:
                damaged += nearest_forest(lat, lon, round(ha / HEX_HA), forest, set(damaged))
            if year == 2022:
                prev_fire_2022 = list(damaged)
        dset = set(damaged)
        s = []
        for i in hexes.index:
            if i in water:
                s.append("W")
            elif i in dset:
                s.append("D")
            elif i in fset:
                s.append("F")
            elif i in farm:
                s.append("A")
            else:
                s.append("M")
        states[year] = "".join(s)
        zone_stats[year] = [[sum(1 for i in members[z] if s[hexes.index.get_loc(i)] == k) for k in "FDAMW"] for z in zone_ids]
        tot = [sum(zs[k] for zs in zone_stats[year]) * HEX_HA for k in range(5)]
        print(year, "forest", tot[0] + tot[1], "damaged", tot[1], "farm", tot[2], "moor", tot[3])

    # -------- SVG geometry (1 unit = 1 km, north up)
    deps = fetch_departements()
    pad = 14000
    bx0, by0, bx1, by1 = minx - pad, miny - pad, maxx + pad, maxy + pad
    bbox = Polygon([(bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)])

    def sx(x):
        return round((x - bx0) / 1000, 2)

    def sy(y):
        return round((by1 - y) / 1000, 2)

    def path(geom, tol=300):
        geom = geom.simplify(tol)
        polys = [geom] if geom.geom_type == "Polygon" else list(getattr(geom, "geoms", []))
        out = []
        for p in polys:
            if p.geom_type != "Polygon" or p.is_empty:
                continue
            for ring in [p.exterior, *p.interiors]:
                pts = list(ring.coords)
                out.append("M" + "L".join(f"{sx(x)},{sy(y)}" for x, y in pts) + "Z")
        return "".join(out)

    def lines(geom, tol=300):
        geom = geom.simplify(tol)
        parts = [geom] if geom.geom_type == "LineString" else list(getattr(geom, "geoms", []))
        return "".join("M" + "L".join(f"{sx(x)},{sy(y)}" for x, y in p.coords) for p in parts if p.geom_type == "LineString")

    land_ctx = unary_union([gm.intersection(bbox) for gm in deps.geometry if gm.intersects(bbox)])
    dept_lines = unary_union([gm.boundary.intersection(bbox.buffer(-1)) for gm in deps.geometry if gm.intersects(bbox)])
    dept_lines = dept_lines.intersection(land_ctx.buffer(-800))
    zone_paths = []
    for Z in ZONES:
        ids = members[Z["id"]]
        shape = unary_union([hexagon(hexes.x[i], hexes.y[i], HEX_R + 2) for i in ids]).intersection(massif.buffer(50))
        lab = shape.representative_point()
        zone_paths.append(dict(id=Z["id"], name=Z["name"], blurb=Z["blurb"], hexes=nz[Z["id"]],
                               ha=nz[Z["id"]] * HEX_HA, path=path(shape, 200), label=[sx(lab.x), sy(lab.y)]))

    data = dict(
        meta=dict(hexHa=HEX_HA, hexR=round(HEX_R / 1000, 3), width=sx(bx1), height=sy(by0), massifHa=n * HEX_HA,
                  communes=len(massif_c), snapshots=SNAPSHOTS),
        hexes=[[sx(hexes.x[i]), sy(hexes.y[i]), zone_ids.index(zone_of[i])] for i in hexes.index],
        states={str(k): v for k, v in states.items()},
        zoneStats={str(k): v for k, v in zone_stats.items()},
        zones=zone_paths,
        land=path(land_ctx, 400),
        massif=path(massif, 250),
        depts=lines(dept_lines, 400),
        labels=[[t, sx(to_l93(lon, lat)[0]), sy(to_l93(lon, lat)[1]), rot] for t, lat, lon, rot in LABELS],
        towns=[[nm, sx(to_l93(lon, lat)[0]), sy(to_l93(lon, lat)[1])] for nm, lat, lon in TOWNS],
        fires={str(y): [[nm, sx(to_l93(lon, lat)[0]), sy(to_l93(lon, lat)[1]), ha] for nm, lat, lon, ha in v] for y, v in FIRES.items()},
        anchors=[{k: (int(float(v)) if k in ("year", "forest_land_ha", "damaged_ha", "farmland_ha") else v)
                  for k, v in r.items()} for r in anchors.values()],
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")
    render_page(OUT.read_text())


def render_page(data_json: str):
    """Inline the data into the page template; writes a standalone index.html."""
    tpl = (OUT.parent / "template.html").read_text()
    body = tpl.replace("/*DATA*/null", data_json)
    head, _, rest = body.partition("<style>")
    page = ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
            + head + "<style>" + rest.replace("</style>", "</style>\n</head>\n<body>", 1) + "\n</body>\n</html>\n")
    (OUT.parent / "index.html").write_text(page)
    (OUT.parent / "atlas.artifact.html").write_text(body)
    print("wrote docs/forest-history/index.html")


if __name__ == "__main__":
    main()
