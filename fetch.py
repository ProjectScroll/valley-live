"""Reads every source in sources.json and writes nights.json (the shows ahead) and status.json (what each source gave).
Run nightly by .github/workflows/nightly.yml. Only what a venue publishes itself is kept: name, date, venue, link.
Standard library only."""
import json, re, time, datetime, urllib.request, html, hashlib
from zoneinfo import ZoneInfo
TZ = ZoneInfo('America/Detroit'); NOW = datetime.datetime.now(TZ); TODAY = NOW.date()
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36 ProjectScrollValleyLive/1.0 (+https://projectscroll.com/scroll-bar/)'

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
            nm = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', html.unescape(str(e.get('name', ''))))).strip()
            out.append({'title': nm, 'home': (' Vs ' in nm or ' vs. ' in nm) if 'Sports' in str(e.get('@type')) else None, 'start': d.isoformat(),
                        'url': e.get('url') or src['url'], 'place': (loc or {}).get('name') if isinstance(loc, dict) else None})
    return out


MON = {m: i for i, m in enumerate(['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'], 1)}
def pdate(txt):
    """'Thursday, November 12, 2026' or 'Nov 14, 2026' (and an optional '7:30 PM') -> ISO, date only when no time"""
    m = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})(?:,?\s+(\d{4}))?', txt or '', re.I)
    if not m: return None
    mo, da = MON[m.group(1)[:3].lower()], int(m.group(2))
    if m.group(3): yr = int(m.group(3))
    else:   # a card without a year: this year, or next year if that date is more than two months gone
        yr = TODAY.year
        if datetime.date(yr, mo, da) < TODAY - datetime.timedelta(days=60): yr += 1
    d = datetime.date(yr, mo, da)
    t = re.search(r'(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m', (txt or '')[m.end():m.end() + 80], re.I)
    if t:
        h = int(t.group(1)) % 12 + (12 if t.group(3).lower() == 'p' else 0)
        return datetime.datetime.combine(d, datetime.time(h, int(t.group(2) or 0)), TZ).isoformat()
    return d.isoformat()
def clean(x): return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', x or ''))).strip()

def from_html(src, page):
    """one event page: its title and date as printed (title_re, date_re, room_re in the source)"""
    t = re.search(src['title_re'], page, re.S | re.I); d = re.search(src['date_re'], page, re.S | re.I)
    if not t or not d: return []
    st = pdate(clean(d.group(1)))
    if not st: return []
    r = re.search(src['room_re'], page, re.S | re.I) if src.get('room_re') else None
    return [{'title': clean(t.group(1)), 'start': st, 'url': src['url'], 'place': clean(r.group(1)) if r else None}]

def from_cards(src, page):
    """a list page of cards: each block holds a date and a title (block_re splits, title_re/date_re/link_re inside)"""
    out = []
    base = re.match(r'https?://[^/]+', src['url']).group(0)
    for b in re.split(src['block_re'], page)[1:]:
        if src.get('require_re') and not re.search(src['require_re'], b[:400]): continue
        t = re.search(src['title_re'], b, re.S | re.I); d = re.search(src['date_re'], b, re.S | re.I)
        if not t or not d: continue
        st = pdate(clean(d.group(1)))
        if not st: continue
        l = re.search(src.get('link_re', r'href="([^"]+)"'), b)
        u = l.group(1) if l else src['url']
        out.append({'title': clean(t.group(1)), 'start': st, 'url': u if u.startswith('http') else base + u, 'place': None})
    return out

def from_tm(src, page):
    """Ticketmaster links on the venue's own calendar carry the show and its date: /<show>-<town>-<mm>-<dd>-<yyyy>/event/<id>"""
    out, seen = [], set()
    for u, slug, mm, dd, yy in re.findall(r'(https://www\.ticketmaster\.com/([a-z0-9-]+?)-(\d{2})-(\d{2})-(\d{4})/event/[0-9A-F]+)', page):
        if u in seen: continue
        seen.add(u)
        slug = re.sub(src.get('strip_re', r'-new-buffalo-michigan$'), '', slug)
        out.append({'title': slug.replace('-', ' ').title(), 'start': f'{yy}-{mm}-{dd}', 'url': u, 'place': None})
    return out

def from_mlb(src, page):
    """MLB's own schedule service (statsapi.mlb.com) for the valley's minor-league clubs"""
    out = []
    for d in json.loads(page).get('dates', []):
        for g in d.get('games', []):
            h, a = g['teams']['home']['team']['name'], g['teams']['away']['team']['name']
            out.append({'title': f"{a} at {h}", 'start': g['gameDate'] if g.get('gameDate') else d['date'],
                        'url': src.get('link') or src['url'], 'place': (g.get('venue') or {}).get('name'), 'home': h == src['name']})
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

def main(SRC='sources.json', OUT='nights.json', KEY='nights', STAT='status.json'):
    S = json.load(open(SRC))['sources']
    nights, status, seen = [], {}, set()
    for s in S:
        try:
            if '__TEAMID__' in s['url']:   # the club's number in MLB's own list, looked up by its name
                T = json.loads(get('https://statsapi.mlb.com/api/v1/teams?sportIds=11,12,13,14,16&season=' + str(TODAY.year)))['teams']
                tm = next(t for t in T if t['name'] == s['name'])
                s = dict(s, url=s['url'].replace('__TEAMID__', str(tm['id'])).replace('__SPORTID__', str(tm['sport']['id'])))
            page = get(s['url'].replace('__TODAY__', TODAY.isoformat()).replace('__PLUS300__', (TODAY + datetime.timedelta(days=300)).isoformat()))
            M = {'ics': from_ics, 'jsonld': from_jsonld, 'html': from_html, 'cards': from_cards, 'tm': from_tm, 'mlb': from_mlb}
            got = M[s['method']](s, page)
            if not got and s.get('follow'):
                # the list page names the shows; each show's own page carries its date (at most 40 pages, a second apart)
                base = re.match(r'https?://[^/]+', s['url']).group(0)
                links = []
                for h in re.findall(r'href=["\']([^"\'#]+)', page):
                    u = h if h.startswith('http') else base + ('' if h.startswith('/') else '/') + h
                    if re.search(s['follow'], u) and u not in links: links.append(u)
                for u in links[:40]:
                    try: got += (from_html if s.get('title_re') else from_jsonld)(dict(s, url=u), get(u))
                    except Exception: pass
                    time.sleep(1)
            kept = 0
            for g in got:
                d = datetime.datetime.fromisoformat(g['start'] if 'T' in g['start'] else g['start'] + 'T00:00')
                if d.date() < TODAY - datetime.timedelta(days=1) or not g['title']: continue
                key = (s.get('name'), d.date().isoformat(), re.sub(r'\W+', '', g['title'].lower())[:40])
                if key in seen: continue
                seen.add(key); kept += 1
                nights.append({'id': hashlib.sha1(repr(key).encode()).hexdigest()[:10], 'title': g['title'], 'start': g['start'], 'allday': 'T' not in g['start'],
                               'venue': s['name'], 'room': g['place'] if g['place'] and g['place'] != s['name'] else None,
                               'town': s['town'], 'kind': s['kind'], 'campus': s.get('campus'), 'url': g['url'],
                               'source': s['url'], 'read': TODAY.isoformat(), **({'home': g['home'], 'team': s.get('team'), 'sport': s.get('sport')} if 'home' in g and g['home'] is not None else {})})
            status[s['id']] = {'ok': True, 'found': len(got), 'kept': kept, 'read': NOW.isoformat(timespec='minutes')}
        except Exception as e:
            status[s['id']] = {'ok': False, 'error': str(e)[:200], 'read': NOW.isoformat(timespec='minutes')}
    nights.sort(key=lambda n: n['start'])
    json.dump({'updated': NOW.isoformat(timespec='minutes'), KEY: nights}, open(OUT, 'w'), ensure_ascii=False, indent=0)
    json.dump(status, open(STAT, 'w'), ensure_ascii=False, indent=1)
    print(f"{len(nights)} nights from {sum(v['ok'] for v in status.values())} of {len(S)} sources")
    for k, v in status.items(): print(k, v)

if __name__ == '__main__':
    main()
    main('sports_sources.json', 'games.json', 'games', 'sports_status.json')
