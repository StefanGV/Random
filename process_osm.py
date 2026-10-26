"""Turn osmium GeoJSON exports for Bucharest into the compact layers used by the home map."""
import json, os, sys
from shapely.geometry import shape, LineString, Polygon, MultiPolygon, Point
R = lambda x: round(x, 5)

def feats(name):
    p = f"tmp/{name}.geojsonseq"
    if not os.path.exists(p): return []
    out = []
    for ln in open(p, encoding="utf-8"):
        ln = ln.strip().lstrip("\x1e")
        if ln: out.append(json.loads(ln))
    return out

def center(f):
    g = shape(f["geometry"]); c = g.representative_point() if g.geom_type != "Point" else g
    return R(c.y), R(c.x)
def line(g, tol):
    g = g.simplify(tol)
    if g.geom_type == "LineString": return [[[R(y), R(x)] for x, y in g.coords]]
    if g.geom_type == "MultiLineString": return [[[R(y), R(x)] for x, y in p.coords] for p in g.geoms]
    return []
def rings(g, tol):
    g = g.simplify(tol)
    polys = list(g.geoms) if g.geom_type == "MultiPolygon" else [g] if g.geom_type == "Polygon" else []
    return [[[R(y), R(x)] for x, y in p.exterior.coords] for p in polys if not p.is_empty]
M2 = lambda g: g.area * 111320 * 0.7145 * 110574   # m² at 44.4°N
os.makedirs("osm", exist_ok=True)
T = lambda f: f.get("properties", {})

# metro
seen = {}
for f in feats("metro_st"):
    n = T(f).get("name")
    if n and n not in seen: seen[n] = [n, *center(f)]
planned = []
for f in feats("metro_plan"):
    t = T(f); kind = t.get("railway", "")
    if t.get("station") == "subway" or t.get("construction") in ("subway", "station") or t.get("construction:railway") == "station" or t.get("proposed:railway") == "station" or t.get("proposed") in ("station", "subway"):
        if f["geometry"]["type"] in ("Point", "Polygon", "MultiPolygon") or "station" in str(t):
            planned.append([t.get("name", ""), *center(f), kind or "construction"])
lines = []
for f in feats("metro_lines"):
    for g in line(shape(f["geometry"]), 0.0001): lines.append({"ref": "", "g": g})
con = []
for f in feats("metro_con"):
    t = T(f)
    if f["geometry"]["type"].endswith("LineString"):
        for g in line(shape(f["geometry"]), 0.0001): con.append({"t": t.get("railway"), "n": t.get("name", ""), "g": g})
json.dump({"metro": list(seen.values()), "metro_planned_pts": [p for p in planned if p[0]], "metro_lines": lines, "metro_line_rels": [], "metro_construction": con},
          open("osm/metro.json", "w"), ensure_ascii=False, separators=(",", ":"))
# hospitals
hs = {}
for f in feats("hospitals"):
    n = T(f).get("name", ""); la, lo = center(f)
    hs[(n, round(la, 3), round(lo, 3))] = [n, la, lo]
json.dump({"hospitals": list(hs.values())}, open("osm/hospitals.json", "w"), ensure_ascii=False, separators=(",", ":"))
# parks
parks = []
for f in feats("parks"):
    if not f["geometry"]["type"].endswith("Polygon"): continue
    g = shape(f["geometry"]);
    if not g.is_valid: g = g.buffer(0)
    a = M2(g)
    if a < 3000: continue
    parks.append({"n": T(f).get("name", ""), "a": round(a), "r": rings(g, 0.00008)})
json.dump({"parks": parks}, open("osm/parks.json", "w"), ensure_ascii=False, separators=(",", ":"))
# roads, tram, rail
roads = []
for f in feats("roads"):
    if not f["geometry"]["type"].endswith("LineString"): continue
    c = T(f).get("highway", "").replace("_link", "")[:1]
    for g in line(shape(f["geometry"]), 0.00006): roads.append({"c": c, "g": g})
tram = [g for f in feats("tram") if f["geometry"]["type"].endswith("LineString") for g in line(shape(f["geometry"]), 0.00006)]
rail = [g for f in feats("rail") if f["geometry"]["type"].endswith("LineString") and not T(f).get("service") for g in line(shape(f["geometry"]), 0.0001)]
json.dump({"roads": roads, "tram": tram, "rail": rail}, open("osm/roads.json", "w"), ensure_ascii=False, separators=(",", ":"))
# water
water = []
for f in feats("water"):
    t = T(f); g = shape(f["geometry"])
    if t.get("waterway") == "river" and f["geometry"]["type"].endswith("LineString"):
        water += [{"k": "l", "g": x} for x in line(g, 0.0001)]
    elif f["geometry"]["type"].endswith("Polygon"):
        if not g.is_valid: g = g.buffer(0)
        if M2(g) < 8000: continue
        water += [{"k": "p", "n": t.get("name", ""), "g": r} for r in rings(g, 0.0001)]
json.dump({"water": water}, open("osm/water.json", "w"), ensure_ascii=False, separators=(",", ":"))
# supermarkets
sm = [[T(f).get("name", ""), *center(f)] for f in feats("shops")]
json.dump({"supermarkets": sm}, open("osm/shops.json", "w"), ensure_ascii=False, separators=(",", ":"))
print({"metro": len(seen), "planned": len(planned), "lines": len(lines), "con": len(con), "hosp": len(hs), "parks": len(parks), "roads": len(roads), "tram": len(tram), "rail": len(rail), "water": len(water), "shops": len(sm)})
