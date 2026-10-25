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
- zone figures split each commune between zones by its share of hexagons.

Fires in communes outside the massif are counted but not mapped.

Run:  python scripts/build_fire_history.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

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


def load_bdiff() -> pd.DataFrame:
    df = pd.read_csv(BDIFF, sep=";", skiprows=3, dtype={"Département": str, "Code INSEE": str})
    df["ha"] = df["Surface parcourue (m2)"] / 1e4
    df["date"] = pd.to_datetime(df["Date de première alerte"])
    assert not df.duplicated(["Année", "Numéro", "Département"]).any(), "duplicate fires in export"
    return df


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
    centre = mc.representative_point()
    code_idx = {c: k for k, c in enumerate(mc.code)}
    communes = [[r.nom, sx(centre[k].x), sy(centre[k].y), comm_hexes[r.code]] for k, r in mc.iterrows()]

    cause_idx = {raw: k for k, (raw, _) in enumerate(CAUSES)}
    fires = fires.sort_values("date")
    records = [[code_idx[r["Code INSEE"]], int(r["Année"]), r["date"].strftime("%m-%d"), round(float(r.ha), 2),
                cause_idx.get(r["Nature"] if isinstance(r["Nature"], str) else None, len(CAUSES) - 1)]
               for _, r in fires.iterrows()]

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
        press2026=[[name, code_idx[code], ha, note] for name, code, ha, note in PRESS_2026],
        sources=["https://bdiff.agriculture.gouv.fr/", PRESS_SOURCE, "https://github.com/gregoiredavid/france-geojson"],
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")
    if (OUT_DIR / "template.html").exists():
        fh.render_page(OUT.read_text(), OUT_DIR, "fires.artifact.html")


if __name__ == "__main__":
    main()
