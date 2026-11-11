"""Every cinema in the valley's fourteen counties, from OpenStreetMap (amenity=cinema, drive-ins included), and the ZIP codes'
centre points from the Census Bureau's gazetteer, for the Scroll Bar's cinema finder. Writes cinemas.json and zips.json.
Run weekly by .github/workflows/cinemas.yml. Standard library only."""
import json, urllib.request, urllib.parse, io, zipfile, datetime, re
UA = 'ProjectScrollValleyLive/1.0 (+https://projectscroll.com/scroll-bar/)'
C = json.load(open('counties.json'))['counties']
def inside(lo, la, ring):
    k = False; j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]; xj, yj = ring[j][0], ring[j][1]
        if ((yi > la) != (yj > la)) and lo < (xj - xi) * (la - yi) / (yj - yi) + xi: k = not k
        j = i
    return k
def county(lo, la):
    for c in C:
        if any(inside(lo, la, r) for r in c['rings']): return c['name']
xs = [p[0] for c in C for r in c['rings'] for p in r]; ys = [p[1] for c in C for r in c['rings'] for p in r]
S, W, N, E = min(ys), min(xs), max(ys), max(xs)

# ---- cinemas
q = f'[out:json][timeout:90];(nwr["amenity"="cinema"]({S},{W},{N},{E}););out center tags;'
import socket, time
_gai = socket.getaddrinfo   # IPv4 only: the runners have no IPv6 route
socket.getaddrinfo = lambda *a, **k: [x for x in _gai(*a, **k) if x[0] == socket.AF_INET] or _gai(*a, **k)
els = None
for ep in ('https://overpass-api.de/api/interpreter', 'https://overpass.private.coffee/api/interpreter', 'https://maps.mail.ru/osm/tools/overpass/api/interpreter', 'https://overpass.kumi.systems/api/interpreter'):
    try:
        r = urllib.request.urlopen(urllib.request.Request(ep, data=urllib.parse.urlencode({'data': q}).encode(), headers={'User-Agent': UA}), timeout=100)
        els = json.load(r)['elements']; print('overpass', ep, len(els)); break
    except Exception as e:
        print('overpass', ep, e); time.sleep(3)
if els is None: raise SystemExit('no answer from Overpass')
out = []
for e in els:
    t = e.get('tags', {}); la = e.get('lat') or e.get('center', {}).get('lat'); lo = e.get('lon') or e.get('center', {}).get('lon')
    if la is None or not t.get('name'): continue
    cn = county(lo, la)
    if not cn: continue
    addr = ' '.join(x for x in (t.get('addr:housenumber'), t.get('addr:street')) if x)
    out.append({'id': f"{e['type'][0]}{e['id']}", 'name': t['name'], 'll': [round(la, 5), round(lo, 5)], 'county': cn,
                'town': t.get('addr:city') or '', 'address': addr, 'zip': t.get('addr:postcode', '')[:5],
                'url': t.get('website') or t.get('contact:website') or t.get('url') or '', 'drive_in': t.get('drive_in') == 'yes' or 'drive' in t['name'].lower(),
                'brand': t.get('brand') or t.get('operator') or '', 'screens': t.get('screen') or t.get('screens') or ''})
out.sort(key=lambda c: (c['county'], c['name']))
json.dump({'updated': datetime.datetime.utcnow().isoformat(timespec='minutes') + 'Z', 'source': 'OpenStreetMap contributors (ODbL), amenity=cinema',
           'cinemas': out}, open('cinemas.json', 'w'), ensure_ascii=False, indent=0)
print(len(out), 'cinemas')
for c in out: print(' ', c['county'], '|', c['name'], '|', c['town'], '|', c['url'])

# ---- ZIP code centres (Census Bureau ZCTA gazetteer), the counties' box and a little beyond
try:
    raw = urllib.request.urlopen(urllib.request.Request('https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_Gaz_zcta_national.zip', headers={'User-Agent': UA}), timeout=120).read()
    z = zipfile.ZipFile(io.BytesIO(raw)); txt = z.read(z.namelist()[0]).decode('latin-1').splitlines()
    hd = [h.strip() for h in txt[0].split('\t')]; iz, ila, ilo = hd.index('GEOID'), hd.index('INTPTLAT'), hd.index('INTPTLONG')
    Z = {}
    for line in txt[1:]:
        f = line.split('\t'); la, lo = float(f[ila]), float(f[ilo].strip())
        if S - .5 <= la <= N + .5 and W - .6 <= lo <= E + .6: Z[f[iz]] = [round(la, 3), round(lo, 3)]
    json.dump(Z, open('zips.json', 'w'), separators=(',', ':')); print(len(Z), 'ZIP codes')
except Exception as e:
    print('zips not refreshed:', e)
