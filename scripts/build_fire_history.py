"""Build the data behind the fire history map (docs/fire-history).

Input: a BDIFF export (bdiff.agriculture.gouv.fr, forest fires, départements
33, 40 and 47) saved in data/reference/bdiff/. For these départements BDIFF starts
in 2006.

Each fire is located by its commune only (BDIFF gives no coordinates). The
massif, its zones and the hexagon grid come from build_forest_history.py, so
both maps share one geography:
- fire starts are spread evenly over the hexagons of the fire's commune;
- a fire's area is credited to its commune (BDIFF puts the whole area on the
  commune where the fire started, even when it spread further);
- zone figures split each commune between zones by its share of hexagons;
- the largest fires are the exception: they are drawn with their EFFIS
  burned-area outline (data/reference/fire_outlines.geojson, from
  scripts/fetch_fire_outlines.py) and their area is split between zones by it.

Fires in communes outside the massif are counted but not mapped.

Run:  python scripts/build_fire_history.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_forest_history as fh  # noqa: E402

ROOT = fh.ROOT
BDIFF = ROOT / "data" / "reference" / "bdiff" / "bdiff_incendies_33_40_47_1973-2025.csv"
OUT_DIR = ROOT / "docs" / "fire-history"
OUT = OUT_DIR / "data.json"

CAUSES = [  # BDIFF "Nature" → label shown on the page
    ("Malveillance", "Arson"),
    ("Involontaire (particulier)", "Carelessness by individuals"),
    ("Involontaire (travaux)", "Carelessness during work"),
    ("Accidentelle", "Accident (power lines, vehicles, rail)"),
    ("Naturelle", "Lightning"),
    (None, "Not recorded"),
]

# 2026 fires are not in BDIFF yet: press figures, shown apart and never mixed into totals
PRESS_2026 = [
    ("Saumos", "33503", 42000, "Saumos fire, from 22 July 2026"),
    ("Biscarrosse", "40046", 3600, "Biscarrosse fire, from 23 July 2026"),
]
PRESS_SOURCE = "https://www.notre-planete.info/actualites/506-feux-foret-incendie-Gironde-juillet-2026"

OUTLINES = ROOT / "data" / "reference" / "fire_outlines.geojson"
# Fires placed by their EFFIS outline: BDIFF (commune code, date of first alert) or press 2026 (commune code, "2026")
OUTLINE_OF = {("33225", "2022-07-12"): 206257, ("33225", "2022-08-12"): 208962,
              ("40200", "2022-08-09"): 208962,  # Moustey: the August Landiras fire spreading into Landes
              ("33529", "2022-07-12"): 205433, ("33503", "2022-09-12"): 210476, ("33125", "2017-04-20"): 12926,
              ("33503", "2026"): 562583, ("40046", "2026"): 567357}
EFFIS_SOURCE = "https://forest-fire.emergency.copernicus.eu/"


def load_bdiff() -> pd.DataFrame:
    df = pd.read_csv(BDIFF, sep=";", skiprows=3, dtype={"Département": str, "Code INSEE": str})
    df["ha"] = df["Surface parcourue (m2)"] / 1e4
    df["date"] = pd.to_datetime(df["Date de première alerte"])
    assert not df.duplicated(["Année", "Numéro", "Département"]).any(), "duplicate fires in export"
    return df


def fire_outlines(m) -> gpd.GeoDataFrame:
    """EFFIS outlines of the largest fires (Lambert-93), with the share of each one's area that lies in each
    hexagon of the massif (`hexShare`, rows sum to 1)."""
    o = gpd.read_file(OUTLINES).to_crs(2154)
    o["year"] = o.firedate.astype(str).str.slice(0, 4).astype(int)
    hexes = np.array([fh.hexagon(x, y) for x, y in zip(m.hexes.x, m.hexes.y)])
    inside = shapely.intersection(o.geometry.values, m.massif)
    oi, hi = shapely.STRtree(hexes).query(inside, predicate="intersects")
    share = np.zeros((len(o), len(hexes)))
    np.add.at(share, (oi, hi), shapely.area(shapely.intersection(inside[oi], hexes[hi])))
    o["hexShare"] = list(share / share.sum(axis=1, keepdims=True))
    return o


def outline_index(o: gpd.GeoDataFrame, code: str, key: str) -> int:
    """Row of `o` holding the outline of a fire (see OUTLINE_OF), or -1."""
    eid = OUTLINE_OF.get((code, key))
    return int(np.flatnonzero(o.effis_id.values == eid)[0]) if eid else -1


def commune_hexes(m, df: pd.DataFrame):
    """Communes of the massif (BDIFF names), the commune of each hexagon and the hexagons of each commune."""
    mc = m.massif_c.reset_index(drop=True)
    hexes = m.hexes
    j = gpd.sjoin(hexes[["geometry"]], mc[["code", "geometry"]], how="left", predicate="within")
    j = j[~j.index.duplicated()]
    hex_code = j["code"].to_dict()
    pos = {h: k for k, h in enumerate(hexes.index)}
    comm_hexes = {c: [] for c in mc.code}
    for h, c in hex_code.items():
        comm_hexes[c].append(pos[h])
    for _, r in mc.iterrows():  # small communes without a hexagon centre: use the nearest hexagon
        if not comm_hexes[r.code]:
            comm_hexes[r.code] = [pos[hexes.distance(r.geometry.representative_point()).idxmin()]]
    # BDIFF names keep the article ("La Teste-de-Buch"); the boundary file drops it ("Teste-de-Buch")
    bdiff_name = df.drop_duplicates("Code INSEE").set_index("Code INSEE")["Nom de la commune"].to_dict()
    mc["nom"] = [bdiff_name.get(c, n) for c, n in zip(mc.code, mc.nom)]
    return mc, hex_code, comm_hexes


def main():
    m = fh.build_massif()
    bm = fh.base_map(m)
    sx, sy = bm.sx, bm.sy
    df = load_bdiff()

    known = set(m.communes.code)
    massif_codes = list(m.massif_c.code)
    unmatched = df[~df["Code INSEE"].isin(known)]
    outside = df[df["Code INSEE"].isin(known) & ~df["Code INSEE"].isin(massif_codes)]
    fires = df[df["Code INSEE"].isin(massif_codes)].copy()
    print(f"fires: {len(df)} in export, {len(fires)} in massif ({fires.ha.sum():,.0f} ha), "
          f"{len(outside)} outside ({outside.ha.sum():,.0f} ha), {len(unmatched)} unmatched ({unmatched.ha.sum():,.1f} ha)")

    # communes of the massif and the hexagons inside each
    mc, hex_code, comm_hexes = commune_hexes(m, df)
    hexes = m.hexes
    centre = mc.representative_point()
    code_idx = {c: k for k, c in enumerate(mc.code)}
    communes = [[r.nom, sx(centre[k].x), sy(centre[k].y), comm_hexes[r.code]] for k, r in mc.iterrows()]

    cause_idx = {raw: k for k, (raw, _) in enumerate(CAUSES)}
    fires = fires.sort_values("date")
    o = fire_outlines(m)
    records = [[code_idx[r["Code INSEE"]], int(r["Année"]), r["date"].strftime("%m-%d"), round(float(r.ha), 2),
                cause_idx.get(r["Nature"] if isinstance(r["Nature"], str) else None, len(CAUSES) - 1),
                outline_index(o, r["Code INSEE"], r["date"].strftime("%Y-%m-%d"))]
               for _, r in fires.iterrows()]
    matched = sorted({rec[5] for rec in records if rec[5] >= 0} | {outline_index(o, c, "2026") for _, c, _, _ in PRESS_2026})
    assert matched == list(range(len(o))), "every outline must match a fire"
    hz = np.array([m.zone_ids.index(m.zone_of[h]) for h in hexes.index])
    outlines = []
    for _, r in o.iterrows():
        x0, y0, x1, y1 = r.geometry.bounds
        outlines.append([r["name"], int(r.year), bm.path(r.geometry, 120), [sx(x0), sy(y1), sx(x1), sy(y0)],
                         [round(float(v), 4) for v in np.bincount(hz, weights=r.hexShare, minlength=len(m.zone_ids))]])

    # sanity checks against known fires
    by_year = fires.groupby("Année").ha.sum()
    print("2022 burned in massif:", round(by_year.get(2022, 0)), "ha")
    landiras = fires[(fires["Code INSEE"] == "33225") & (fires["Année"] == 2022)].ha.sum()
    print("Landiras 2022:", round(landiras), "ha (press: ~19,300)")

    data = dict(
        meta={**bm.data["meta"], "years": [int(fires["Année"].min()), int(fires["Année"].max())],
              "exportFires": len(df), "outside": [len(outside), round(float(outside.ha.sum()))],
              "unmatched": [len(unmatched), round(float(unmatched.ha.sum()), 1)]},
        hexes=bm.data["hexes"], zones=bm.data["zones"], land=bm.data["land"], massif=bm.data["massif"],
        depts=bm.data["depts"], labels=bm.data["labels"], towns=bm.data["towns"],
        communes=communes,
        hexComm=[code_idx[hex_code[h]] for h in hexes.index],
        causes=[label for _, label in CAUSES],
        fires=records,
        press2026=[[name, code_idx[code], ha, note, outline_index(o, code, "2026")] for name, code, ha, note in PRESS_2026],
        outlines=outlines,
        sources=["https://bdiff.agriculture.gouv.fr/", PRESS_SOURCE, EFFIS_SOURCE, "https://github.com/gregoiredavid/france-geojson"],
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")
    if (OUT_DIR / "template.html").exists():
        fh.render_page(OUT.read_text(), OUT_DIR, "fires.artifact.html")


if __name__ == "__main__":
    main()
