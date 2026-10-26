"""Fetch the outlines of the largest fires and the building damage of the 2026 Saumos fire.

Writes two small reference files used by the fire and exposure maps:
- data/reference/fire_outlines.geojson: EFFIS burned-area outlines (European
  Forest Fire Information System, MODIS and Sentinel-2) of the fires listed in
  EFFIS_FIRES, simplified to 10 m.
- data/reference/emsr899_buildings.geojson: buildings graded by Copernicus EMS
  rapid mapping after the 2026 Saumos fire (activation EMSR899, grading
  monitoring 1, version 2, photo-interpretation).

Both are Copernicus data, free to use with attribution: "European Forest Fire
Information System (EFFIS)" and "© European Union, Copernicus Emergency
Management Service". The EMS download is about 130 MB; only the building
points are kept.

Run:  python scripts/fetch_fire_outlines.py
"""
from __future__ import annotations

import json
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "reference" / "fire_outlines.geojson"
OUT_EMS = ROOT / "data" / "reference" / "emsr899_buildings.geojson"

EFFIS_WFS = "https://maps.effis.emergency.copernicus.eu/effis"
BBOX = "43.3,-1.7,45.8,0.5,urn:ogc:def:crs:EPSG::4326"  # lat/lon order for WFS 1.1
# EFFIS layer -> ids of the fires kept, with the name used on the maps
EFFIS_FIRES = {
    "modis.ba.poly.2017": {"12926": "Cissac-Médoc"},
    "modis.ba.poly.2022": {"206257": "Landiras", "208962": "Landiras (August)",
                           "205433": "La Teste-de-Buch", "210476": "Saumos"},
    "modis.ba.poly.season": {"562583": "Saumos", "567357": "Biscarrosse"},  # season = 2026
}
EMS_ZIP = "https://rapidmapping.emergency.copernicus.eu/backend/EMSR899/AOI01/GRA_MONIT01/EMSR899_AOI01_GRA_MONIT01_v2.zip"
EMS_LAYER = "EMSR899_AOI01_GRA_MONIT01_builtUpP_v2.shp"


def effis_layer(layer: str) -> gpd.GeoDataFrame:
    q = urllib.parse.urlencode({"service": "WFS", "version": "1.1.0", "request": "GetFeature", "typename": f"ms:{layer}",
                                "outputformat": "application/json; subtype=geojson",
                                "srsname": "urn:ogc:def:crs:EPSG::4326", "bbox": BBOX})
    with urllib.request.urlopen(f"{EFFIS_WFS}?{q}", timeout=300) as r:
        return gpd.GeoDataFrame.from_features(json.load(r)["features"], crs=4326)


def main():
    frames = []
    for layer, fires in EFFIS_FIRES.items():
        g = effis_layer(layer)
        g = g[g["id"].astype(str).isin(fires)].copy()
        missing = set(fires) - set(g["id"].astype(str))
        if missing:
            raise SystemExit(f"{layer}: EFFIS ids {sorted(missing)} not found")
        g["name"] = g["id"].astype(str).map(fires)
        frames.append(g)
    g = pd.concat(frames, ignore_index=True)
    l93 = g.to_crs(2154)
    l93["geometry"] = shapely.make_valid(shapely.simplify(l93.geometry.values, 10))
    out = l93.to_crs(4326)[["id", "name", "FIREDATE", "COMMUNE", "AREA_HA", "geometry"]]
    out["geometry"] = shapely.set_precision(out.geometry.values, 1e-6)
    out.columns = ["effis_id", "name", "firedate", "effis_commune", "effis_ha", "geometry"]
    out["effis_id"] = out.effis_id.astype(int)
    out["effis_ha"] = out.effis_ha.astype(float).round().astype(int)
    out["firedate"] = out.firedate.str.slice(0, 10)
    OUT.write_text(out.to_json(drop_id=True, to_wgs84=True, ensure_ascii=False))
    print(f"wrote {OUT.relative_to(ROOT)}: {len(out)} outlines, {out.effis_ha.sum():,} ha "
          f"({OUT.stat().st_size / 1024:.0f} KB)")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ems.zip"
        urllib.request.urlretrieve(EMS_ZIP, path)
        b = gpd.read_file(f"/vsizip/{path}/{EMS_LAYER}")
    b = b[["obj_type", "damage_gra", "geometry"]].rename(columns={"damage_gra": "damage"})
    b["obj_type"] = b.obj_type.str.replace(r"^\d+-", "", regex=True)
    b = b.to_crs(4326)
    b["geometry"] = shapely.set_precision(b.geometry.values, 1e-6)
    OUT_EMS.write_text(b.to_json(drop_id=True, ensure_ascii=False))
    print(f"wrote {OUT_EMS.relative_to(ROOT)}: {len(b):,} buildings {b.damage.value_counts().to_dict()}")


if __name__ == "__main__":
    main()
