"""Fetch OpenStreetMap layers for Bucharest via Overpass and save compact JSON."""
import json, time, urllib.request, urllib.parse
from shapely.geometry import LineString, Polygon, MultiPolygon, shape
from shapely.ops import unary_union

EPS = ["https://overpass-api.de/api/interpreter",
       "https://overpass.kumi.systems/api/interpreter",
       "https://overpass.private.coffee/api/interpreter",
       "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
AREA = 'area["name"="București"]["admin_level"="4"]->.a;'

def q(body):
    data = urllib.parse.urlencode({"data": "[out:json][timeout:300];" + AREA + body}).encode()
    for attempt in range(3):
        for ep in EPS:
            try:
                req = urllib.request.Request(ep, data=data, headers={"User-Agent": "bucharest-home-map/1.0 (personal research)"})
                with urllib.request.urlopen(req, timeout=360) as r:
                    els = json.load(r)["elements"]
                    print(ep, len(els)); return els
            except Exception as e:
                print("fail", ep, e)
        time.sleep(30)
    raise SystemExit("all endpoints failed")

R = lambda x: round(x, 5)
def line(g): return [[R(p["lat"]), R(p["lon"])] for p in g]
def simp(coords, tol):
    if len(coords) < 3: return coords
    ls = LineString([(c[1], c[0]) for c in coords]).simplify(tol)
    return [[R(y), R(x)] for x, y in ls.coords]
def center(e):
    return (e.get("lat") or e["center"]["lat"], e.get("lon") or e["center"]["lon"])

out = {}
# Metro stations (existing) and anything under construction / proposed
st = q('(node["railway"="station"]["station"="subway"](area.a);node["public_transport"="station"]["subway"="yes"](area.a););out;')
seen = {}
for e in st:
    n = e.get("tags", {}).get("name", "")
    if n and n not in seen: seen[n] = [n, R(e["lat"]), R(e["lon"])]
out["metro"] = list(seen.values())
pl = q('(nwr["construction:railway"="station"](area.a);nwr["railway"="construction"]["construction"="station"](area.a);nwr["railway"="proposed"]["proposed"="station"](area.a);nwr["proposed:railway"="station"](area.a);nwr["railway"="construction"]["station"="subway"](area.a););out center tags;')
out["metro_planned_pts"] = [[e.get("tags", {}).get("name", ""), R(center(e)[0]), R(center(e)[1]), e.get("tags", {}).get("railway", "")] for e in pl]
lines = q('rel["route"="subway"](area.a);out tags;way(r)["railway"="subway"];out geom;')
out["metro_lines"] = [{"ref": "", "g": simp(line(e["geometry"]), 0.0001)} for e in lines if e["type"] == "way"]
out["metro_line_rels"] = [[e["tags"].get("ref", ""), e["tags"].get("colour", ""), e["tags"].get("name", "")] for e in lines if e["type"] == "relation"]
con = q('(way["railway"="construction"]["construction"="subway"](area.a);way["railway"="proposed"]["proposed"="subway"](area.a););out geom tags;')
out["metro_construction"] = [{"t": e["tags"].get("railway"), "n": e["tags"].get("name", ""), "g": simp(line(e["geometry"]), 0.0001)} for e in con]
# Hospitals
hs = q('nwr["amenity"="hospital"](area.a);out center tags;')
out["hospitals"] = [[e.get("tags", {}).get("name", ""), R(center(e)[0]), R(center(e)[1])] for e in hs]
# Parks (polygons), with area
pk = q('(way["leisure"="park"](area.a);rel["leisure"="park"](area.a);way["landuse"="forest"](area.a););out geom tags;')
parks = []
for e in pk:
    try:
        if e["type"] == "way":
            g = e["geometry"]
            if len(g) < 4: continue
            poly = Polygon([(p["lon"], p["lat"]) for p in g])
        else:
            outers = [m for m in e.get("members", []) if m.get("role") == "outer" and "geometry" in m]
            from shapely.ops import polygonize
            poly = unary_union(list(polygonize([LineString([(p["lon"], p["lat"]) for p in m["geometry"]]) for m in outers])))
        if not poly.is_valid: poly = poly.buffer(0)
        a = poly.area * 111000 * 79000  # m2 approx at 44.4N
        if a < 3000: continue
        poly = poly.simplify(0.00008)
        polys = list(poly.geoms) if isinstance(poly, MultiPolygon) else [poly]
        rings = [[[R(y), R(x)] for x, y in p.exterior.coords] for p in polys if p.area > 0]
        parks.append({"n": e.get("tags", {}).get("name", ""), "a": round(a), "r": rings})
    except Exception as ex:
        print("park skip", ex)
out["parks"] = parks
# Main roads and tram lines (noise proxy + basemap)
rd = q('way["highway"~"^(motorway|trunk|primary|secondary)(_link)?$"](area.a);out geom tags;')
out["roads"] = [{"c": e["tags"]["highway"].replace("_link", "")[0], "g": simp(line(e["geometry"]), 0.00006)} for e in rd]
tr = q('way["railway"="tram"](area.a);out geom;')
out["tram"] = [simp(line(e["geometry"]), 0.00006) for e in tr]
rl = q('way["railway"="rail"]["service"!~"."](area.a);out geom;')
out["rail"] = [simp(line(e["geometry"]), 0.0001) for e in rl]
# Water
wt = q('(way["natural"="water"](area.a);rel["natural"="water"](area.a);way["waterway"="river"](area.a););out geom tags;')
water = []
for e in wt:
    if e["type"] == "way" and e["tags"].get("waterway") == "river":
        water.append({"k": "l", "g": simp(line(e["geometry"]), 0.0001)})
    elif e["type"] == "way" and len(e["geometry"]) > 3:
        p = Polygon([(x["lon"], x["lat"]) for x in e["geometry"]])
        if p.area * 111000 * 79000 < 8000: continue
        p = p.simplify(0.0001)
        water.append({"k": "p", "n": e["tags"].get("name", ""), "g": [[R(y), R(x)] for x, y in p.exterior.coords]})
out["water"] = water
# Kindergartens and primary-only schools are skipped; supermarkets as everyday-convenience layer
sm = q('nwr["shop"="supermarket"](area.a);out center tags;')
out["supermarkets"] = [[e.get("tags", {}).get("name", ""), R(center(e)[0]), R(center(e)[1])] for e in sm]
for k, v in out.items(): print(k, len(v))
json.dump(out, open("osm/bucharest_osm.json", "w"), ensure_ascii=False, separators=(",", ":"))
