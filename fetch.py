"""Reads every source in sources.json and writes nights.json (the shows ahead) and status.json (what each source gave).
Run nightly by .github/workflows/nightly.yml. Only what a venue publishes itself is kept: name, date, venue, link.
Standard library only."""
import json, re, time, datetime, urllib.request, html, hashlib
from zoneinfo import ZoneInfo
TZ = ZoneInfo('America/Detroit'); NOW = datetime.datetime.now(TZ); TODAY = NOW.date()
UA = 'Mozilla/5.0 (compatible; ProjectScrollValleyLive/1.0; +https://projectscroll.com/)'

def get(url):
    r = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'text/html,text/calendar,*/*'}), timeout=40)
    return r.read().decode(r.headers.get_content_charset() or 'utf-8', 'replace')

def walk(x):
    if isinstance(x, list):
        for y in x: yield from walk(y)
    elif isinstance(x, dict):
        t = x.get('@type'); t = t if isinstance(t, list) else [t]
        if any(isinstance(s, str) and s.endswith('Event') for s in t): yield x
        for k in ('@graph', 'itemListElement', 'item', 'subEvent', 'event', 'events'):
            if k in x: yield from walk(x[k])

def when(s):
    if not s: return None
    s = str(s).strip()
    try:
        d = datetime.datetime.fromisoformat(s.replace('Z', '+00:00'))
        if d.tzinfo: d = d.astimezone(TZ)
        return d
    except ValueError:
        try: return datetime.datetime.combine(datetime.date.fromisoformat(s[:10]), datetime.time())
        except ValueError: return None

def from_jsonld(src, page):
    out = []
    for blk in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try: data = json.loads(html.unescape(blk.strip()))
        except Exception: continue
        for e in walk(data):
            d = when(e.get('startDate'))
            if not d: continue
            loc = e.get('location'); loc = loc[0] if isinstance(loc, list) and loc else loc
            out.append({'title': html.unescape(str(e.get('name', '')).strip()), 'start': d.isoformat(),
                        'url': e.get('url') or src['url'], 'place': (loc or {}).get('name') if isinstance(loc, dict) else None})
    return out

def from_ics(src, page):
    out = []; page = re.sub(r'\r?\n[ \t]', '', page)
    for ev in re.findall(r'BEGIN:VEVENT(.*?)END:VEVENT', page, re.S):
        f = {}
        for line in ev.strip().splitlines():
            if ':' in line:
                k, v = line.split(':', 1); f.setdefault(k.split(';')[0], (k, v))
        k, v = f.get('DTSTART', ('', ''))
        m = re.match(r'(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2}))?', v)
        if not m: continue
        y, mo, da, hh, mi = m.groups()
        d = datetime.datetime(int(y), int(mo), int(da), int(hh or 0), int(mi or 0), tzinfo=ZoneInfo('UTC') if v.endswith('Z') else TZ).astimezone(TZ)
        out.append({'title': f.get('SUMMARY', ('', ''))[1].replace('\\,', ',').strip(), 'start': d.isoformat(),
                    'url': f.get('URL', ('', src['url']))[1], 'place': f.get('LOCATION', ('', ''))[1].replace('\\,', ',') or None})
    return out

def main():
    S = json.load(open('sources.json'))['sources']
    nights, status, seen = [], {}, set()
    for s in S:
        try:
            page = get(s['url'])
            got = (from_ics if s['method'] == 'ics' else from_jsonld)(s, page)
            if not got and s.get('follow'):
                # the list page names the shows; each show's own page carries its date (at most 40 pages, a second apart)
                base = re.match(r'https?://[^/]+', s['url']).group(0)
                links = []
                for h in re.findall(r'href=["\']([^"\'#]+)', page):
                    u = h if h.startswith('http') else base + ('' if h.startswith('/') else '/') + h
                    if re.search(s['follow'], u) and u not in links: links.append(u)
                for u in links[:40]:
                    try: got += from_jsonld(dict(s, url=u), get(u))
                    except Exception: pass
                    time.sleep(1)
            kept = 0
            for g in got:
                d = datetime.datetime.fromisoformat(g['start'])
                if d.date() < TODAY - datetime.timedelta(days=1) or not g['title']: continue
                key = (s.get('name'), d.date().isoformat(), re.sub(r'\W+', '', g['title'].lower())[:40])
                if key in seen: continue
                seen.add(key); kept += 1
                nights.append({'id': hashlib.sha1(repr(key).encode()).hexdigest()[:10], 'title': g['title'], 'start': g['start'],
                               'venue': s['name'], 'room': g['place'] if g['place'] and g['place'] != s['name'] else None,
                               'town': s['town'], 'kind': s['kind'], 'campus': s.get('campus'), 'url': g['url'],
                               'source': s['url'], 'read': TODAY.isoformat()})
            status[s['id']] = {'ok': True, 'found': len(got), 'kept': kept, 'read': NOW.isoformat(timespec='minutes')}
        except Exception as e:
            status[s['id']] = {'ok': False, 'error': str(e)[:200], 'read': NOW.isoformat(timespec='minutes')}
    nights.sort(key=lambda n: n['start'])
    json.dump({'updated': NOW.isoformat(timespec='minutes'), 'nights': nights}, open('nights.json', 'w'), ensure_ascii=False, indent=0)
    json.dump(status, open('status.json', 'w'), ensure_ascii=False, indent=1)
    print(f"{len(nights)} nights from {sum(v['ok'] for v in status.values())} of {len(S)} sources")
    for k, v in status.items(): print(k, v)

if __name__ == '__main__': main()
