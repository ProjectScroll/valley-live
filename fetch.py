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
        # a time with no zone is the venue's own clock: the valley's (Eastern)
        return d.astimezone(TZ) if d.tzinfo else (d.replace(tzinfo=TZ) if 'T' in s else d)
    except ValueError:
        try: return datetime.datetime.combine(datetime.date.fromisoformat(s[:10]), datetime.time())
        except ValueError: return None

def sidearm_results(page):
    """a Sidearm schedule page's games and, once finished, the result as its box prints it: [(month, day, opponent, 'W, 3-2' or None), ...]
    only a W, L or T the page prints itself (a tournament game between two other teams has none)"""
    out = []
    for b in re.split(r'<li[^>]+class="sidearm-schedule-game ', page)[1:]:
        r = re.search(r'<div class="sidearm-schedule-game-result[^"]*">(.*?)</div>', b, re.S)
        sp = [clean(x) for x in re.findall(r'<span[^>]*>(.*?)</span>', r.group(1), re.S)] if r else []
        sp = [x for x in sp if x]
        res = sp[0].rstrip(',') + ', ' + ' '.join(sp[1:]) if len(sp) >= 2 and re.fullmatch(r'[WLT],?', sp[0]) and re.fullmatch(r'\d+-\d+', sp[1]) else None
        d = re.search(r'sidearm-schedule-game-opponent-date[^>]*>\s*<span>\s*([A-Z][a-z]{2})[a-z]*\.? (\d{1,2})', b)
        o = re.search(r'sidearm-schedule-game-opponent-name"?[^>]*>(.*?)</(?:span|div)>\s*</div>', b, re.S)
        if not d: continue
        out.append((MON[d.group(1).lower()], int(d.group(2)), re.sub(r'\W+', '', clean(o.group(1)).lower()) if o else '',
                    res))
    return out

def from_jsonld(src, page):
    out = []
    R = sidearm_results(page)
    for blk in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try: data = json.loads(html.unescape(blk.strip()))
        except Exception: continue
        for e in walk(data):
            d = when(e.get('startDate'))
            if not d: continue
            loc = e.get('location'); loc = loc[0] if isinstance(loc, list) and loc else loc
            nm = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', html.unescape(str(e.get('name', ''))))).strip()
            of = e.get('offers'); of = of[0] if isinstance(of, list) and of else of
            free = bool(e.get('isAccessibleForFree')) or (isinstance(of, dict) and str(of.get('price', '')).strip() in ('0', '0.0', '0.00'))
            place = (loc or {}).get('name') if isinstance(loc, dict) else None
            home = None
            if 'Sports' in str(e.get('@type')):
                if re.match(r'(?i)(vs\.?|at)\s', nm): nm = f"{src.get('team', '')} {nm[0].lower()}{nm[1:]}".strip()   # 'Vs Judson' -> 'IU South Bend vs Judson'
                # a home game: 'vs', and (when the source names its grounds) played there, not at a neutral site
                home = bool(re.search(r'(?i)\svs\.?\s', nm)) and (not src.get('home_re') or bool(re.search(src['home_re'], place or '')))
            g = {'title': nm, 'free': free, 'home': home, 'start': d.isoformat(), 'url': e.get('url') or src['url'], 'place': place}
            # its final score, when the page prints one: the game of that day whose opponent the event names (or the day's only game)
            day = [x for x in R if (x[0], x[1]) == (d.month, d.day)]
            hit = [x for x in day if x[2] and x[2] in re.sub(r'\W+', '', nm.lower())] or (day if len(day) == 1 else [])
            if len(hit) == 1 and hit[0][3]: g['result'] = hit[0][3]
            out.append(g)
    return out


MON = {m: i for i, m in enumerate(['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'], 1)}
def pdate(txt):
    """'Thursday, November 12, 2026' or 'Nov 14, 2026' (and an optional '7:30 PM') -> ISO, date only when no time"""
    m = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})(?:,?\s+(\d{4}))?', txt or '', re.I)
    n = None if m else re.search(r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b', txt or '')   # 11/16/2026
    if not m and not n: return None
    if n: m = n; mo, da = int(n.group(1)), int(n.group(2))
    else: mo, da = MON[m.group(1)[:3].lower()], int(m.group(2))
    if m.group(3): yr = int(m.group(3))
    else:   # a card without a year: this year, or next year if that date is more than two months gone
        yr = TODAY.year
        if datetime.date(yr, mo, da) < TODAY - datetime.timedelta(days=60): yr += 1
    d = datetime.date(yr, mo, da)
    t = re.search(r'(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m', (txt or '')[m.end():m.end() + 80], re.I)
    if t and re.match(r'\s*c\.?t\b', (txt or '')[m.end() + t.end():m.end() + t.end() + 4], re.I): t = None   # Central time: a place outside the valley's clock
    if t:
        h = int(t.group(1)) % 12 + (12 if t.group(3).lower() == 'p' else 0)
        return datetime.datetime.combine(d, datetime.time(h, int(t.group(2) or 0)), TZ).isoformat()
    return d.isoformat()
def clean(x): return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', x or ''))).strip()

def from_html(src, page):
    """one event page: its title and date as printed (title_re, date_re, room_re in the source)"""
    t = re.search(src['title_re'], page, re.S | re.I); d = re.search(src['date_re'], page, re.S | re.I)
    if not t or not d: return []
    tm = re.search(src['time_re'], page, re.S | re.I) if src.get('time_re') else None
    st = pdate(clean(d.group(1)) + (' ' + clean(tm.group(1)) if tm else ''))
    if not st: return []
    r = re.search(src['room_re'], page, re.S | re.I) if src.get('room_re') else None
    ti = re.sub(src.get('title_strip', r'$^'), '', clean(t.group(1))).strip()
    return [{'title': ti, 'start': st, 'url': src['url'], 'place': clean(r.group(1)) if r else None}]

def from_cards(src, page):
    """a list page of cards: each block holds a date and a title (block_re splits, title_re/date_re/link_re inside)"""
    out = []
    base = re.match(r'https?://[^/]+', src['url']).group(0)
    for b in re.split(src['block_re'], page)[1:]:
        if src.get('require_re') and not re.search(src['require_re'], b[:src.get('require_len', 400)]): continue
        t = re.search(src['title_re'], b, re.S | re.I); d = re.search(src['date_re'], b, re.S | re.I)
        if not t or not d: continue
        tm = re.search(src['time_re'], b, re.S | re.I) if src.get('time_re') else None
        st = pdate(clean(d.group(1)) + (' ' + clean(tm.group(1)) if tm else ''))
        if not st: continue
        l = re.search(src.get('link_re', r'href="([^"]+)"'), b)
        u = l.group(1) if l else src['url']
        out.append({'title': re.sub(src.get('title_strip', r'$^'), '', clean(t.group(1))).strip(), 'start': st, 'url': u if u.startswith('http') else base + u, 'place': None})
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
            x = {'title': f"{a} at {h}", 'start': when(g['gameDate']).isoformat() if g.get('gameDate') else d['date'],
                 'url': src.get('link') or src['url'], 'place': (g.get('venue') or {}).get('name'), 'home': h == src['name']}
            # a final score, from the club's side: only once MLB calls the game Final (not postponed or cancelled, which MLB also files as Final)
            st = g.get('status') or {}
            us, them = (g['teams']['home'], g['teams']['away']) if x['home'] else (g['teams']['away'], g['teams']['home'])
            if st.get('abstractGameState') == 'Final' and st.get('codedGameState') == 'F' and isinstance(us.get('score'), int) and isinstance(them.get('score'), int):
                w = 'W' if us.get('isWinner') else 'L' if them.get('isWinner') else 'T' if us['score'] == them['score'] else None
                if w: x['result'] = f"{w}, {us['score']}-{them['score']}"
            out.append(x)
    return out

def from_ndapi(src, page):
    """Notre Dame's own schedule service (fightingirish.com/website-api): the sport's current schedule, every game in it"""
    sid = next(x['schedule_id'] for x in json.loads(page)['data'] if x['slug'] == src['slug'])
    out, p = [], 1
    while p and p < 10:
        j = json.loads(get(f'https://fightingirish.com/website-api/schedule-events?filter%5Bschedule_id%5D={sid}&per_page=100&include=scheduleEventResult&page={p}'))
        for g in j['data']:
            if g.get('status') in ('canceled', 'cancelled', 'postponed'): continue
            opp = g.get('opponent_name') or ''
            vt = g.get('venue_type') or ''
            t = f"Notre Dame {'vs' if vt != 'away' else 'at'} {opp}".strip()
            st = g['datetime'][:10] if (g.get('tba') or g.get('is_all_day')) else g['datetime']
            if 'T' in st: st = datetime.datetime.fromisoformat(st.replace('Z', '+00:00').replace('.000000', '')).astimezone(TZ).isoformat()
            else:   # a time to be announced: the valley's own date of the listed moment
                st = datetime.datetime.fromisoformat(g['datetime'].replace('Z', '+00:00').replace('.000000', '')).astimezone(TZ).date().isoformat()
            x = {'title': t, 'start': st, 'url': f"https://fightingirish.com/sports/{src['slug']}/schedule/",
                 'place': g.get('venue') or g.get('location'), 'home': vt == 'home'}
            # the final, as the schedule records it: win, loss or tie and the two scores, Notre Dame's first
            r = g.get('schedule_event_result') or {}
            num = lambda v: re.sub(r'\.0*$|(\.\d*?)0+$', r'\1', str(v).strip()) if v not in (None, '') else None
            hi, lo = num(r.get('winning_score')), num(r.get('losing_score'))
            if g.get('status') == 'completed' and hi and lo and r.get('result') in ('win', 'loss', 'tie'):
                hi, lo = sorted((hi, lo), key=float, reverse=True)   # the two boxes are sometimes filled the other way round: the higher is the winner's
                x['result'] = {'win': f'W, {hi}-{lo}', 'loss': f'L, {lo}-{hi}', 'tie': f'T, {hi}-{lo}'}[r['result']] + (f" ({r['text'].strip()})" if (r.get('text') or '').strip() else '')
            out.append(x)
        p = j['meta']['current_page'] + 1 if j['meta']['current_page'] < j['meta']['last_page'] else None
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

TAGS = [   # what a show is, read from its own title (first match per kind; a show may have several)
    ('comedy',    r'comed|stand-?up|comedian|improv|laugh'),
    ('classical', r'symphon|orchestra|philharmonic|recital|quartet|chamber|sonata|chorale|choral|concerto|organ'),
    ('music',     r'concert|symphon|orchestra|band\b|jazz|choir|chorale|quartet|\btour\b|live music|singer|bluegrass|tribute|recital|ensemble|philharmonic|unplugged|acoustic|blues|rock|country|songwriter|\bdj\b|music'),
    ('theatre',   r'musical|\bplay\b|theat(?:re|er)|broadway|opera|stage|shakespeare'),
    ('dance',     r'ballet|dance|nutcracker'),
    ('film',      r'\bfilm|movie|screening|cinema'),
    ('family',    r'\bkids?\b|family|children|junior|youth|sesame|paw patrol|puppet|storytime'),
    ('holiday',   r'christmas|holiday|nutcracker|santa|noel|messiah|new year'),
    ('talk',      r'lecture|\btalk\b|conversation|author|speaker|podcast|panel'),
    ('trivia',    r'trivia|quiz'),
]
def tags(t):
    t = (t or '').lower()
    return [k for k, r in TAGS if re.search(r, t)]
def flags(g):
    t = (g['title'] or '').lower()
    f = {}
    if g.get('free') or re.search(r'\bfree\b(?! ?(?:will|state))|no cover|no charge', t): f['free'] = True
    if g.get('allages') or re.search(r'all[- ]ages|\bfamily\b|\bkids?\b|children', t): f['allages'] = True
    return f

def ics(items, name, path, desc):
    """a calendar people subscribe to: name, date, place and a link to the venue's own page (no text of theirs)"""
    esc = lambda x: str(x or '').replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n')
    L = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Project Scroll//Valley Live//EN', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH',
         'X-WR-CALNAME:' + esc(name), 'X-WR-TIMEZONE:America/Detroit', 'X-WR-CALDESC:' + esc(desc), 'REFRESH-INTERVAL;VALUE=DURATION:PT12H',
         'BEGIN:VTIMEZONE', 'TZID:America/Detroit', 'BEGIN:STANDARD', 'DTSTART:19701101T020000', 'RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU',
         'TZOFFSETFROM:-0400', 'TZOFFSETTO:-0500', 'TZNAME:EST', 'END:STANDARD', 'BEGIN:DAYLIGHT', 'DTSTART:19700308T020000',
         'RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU', 'TZOFFSETFROM:-0500', 'TZOFFSETTO:-0400', 'TZNAME:EDT', 'END:DAYLIGHT', 'END:VTIMEZONE']
    stamp = NOW.astimezone(ZoneInfo('UTC')).strftime('%Y%m%dT%H%M%SZ')
    for n in items:
        L += ['BEGIN:VEVENT', f"UID:{n['id']}@valley-live.projectscroll.com", 'DTSTAMP:' + stamp]
        if n['allday']:
            d = datetime.date.fromisoformat(n['start'][:10])
            L += ['DTSTART;VALUE=DATE:' + d.strftime('%Y%m%d'), 'DTEND;VALUE=DATE:' + (d + datetime.timedelta(days=1)).strftime('%Y%m%d')]
        else:
            d = datetime.datetime.fromisoformat(n['start']).astimezone(TZ)
            L += ['DTSTART;TZID=America/Detroit:' + d.strftime('%Y%m%dT%H%M%S'), 'DURATION:PT2H' if n['kind'] != 'sports' else 'DURATION:PT3H']
        where = ', '.join(x for x in (n.get('room'), n['venue'] if n['kind'] != 'sports' else None, n['town']) if x)
        L += ['SUMMARY:' + esc(n['title']), 'LOCATION:' + esc(where), 'URL:' + n['url'],
              'DESCRIPTION:' + esc(f"Listed by {n['venue']}. Times and tickets: {n['url']}\nMore nights out in the valley: https://projectscroll.com/{'sports' if n['kind'] == 'sports' else 'scroll-bar'}/?p=feed"),
              'END:VEVENT']
    L.append('END:VCALENDAR')
    out = []
    for line in L:   # folded at 75 octets, as the standard asks
        b = line.encode()
        while len(b) > 74:
            cut = 74
            while (b[cut] & 0xC0) == 0x80: cut -= 1
            out.append(b[:cut].decode()); b = b' ' + b[cut:]
        out.append(b.decode())
    open(path, 'w', newline='').write('\r\n'.join(out) + '\r\n')

def main(SRC='sources.json', OUT='nights.json', KEY='nights', STAT='status.json', KEEP=1):
    """KEEP: how many days back a listing is kept (the games: a week, for the final scores)"""
    S = json.load(open(SRC))['sources']
    nights, status, seen = [], {}, set()
    for s in S:
        try:
            if '__TEAMID__' in s['url']:   # the club's number in MLB's own list, looked up by its name
                T = json.loads(get('https://statsapi.mlb.com/api/v1/teams?sportIds=11,12,13,14,16&season=' + str(TODAY.year)))['teams']
                tm = next(t for t in T if t['name'] == s['name'])
                s = dict(s, url=s['url'].replace('__TEAMID__', str(tm['id'])).replace('__SPORTID__', str(tm['sport']['id'])))
            page = get(s['url'].replace('__TODAY__', (TODAY - datetime.timedelta(days=KEEP)).isoformat()).replace('__PLUS300__', (TODAY + datetime.timedelta(days=300)).isoformat()))
            M = {'ics': from_ics, 'jsonld': from_jsonld, 'html': from_html, 'cards': from_cards, 'tm': from_tm, 'mlb': from_mlb, 'ndapi': from_ndapi}
            got = [] if (s.get('follow') and s['method'] == 'html') else M[s['method']](s, page)   # an html source with follow reads only the shows' own pages
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
                d = d.astimezone(TZ) if d.tzinfo else d
                if d.date() < TODAY - datetime.timedelta(days=KEEP) or not g['title']: continue
                if re.search(r'(?i)\b(?:day )?package\b|gift card|private event|to-go\b', g['title']): continue   # ticket bundles and private bookings are not shows
                key = (s.get('name'), d.date().isoformat(), re.sub(r'\W+', '', g['title'].lower())[:40])
                if key in seen: continue
                seen.add(key); kept += 1
                nights.append({'id': hashlib.sha1(repr(key).encode()).hexdigest()[:10], 'title': g['title'], 'start': g['start'], 'allday': 'T' not in g['start'],
                               'venue': s['name'], 'room': g['place'] if g['place'] and g['place'] != s['name'] else None,
                               'town': s['town'], 'kind': s['kind'], 'campus': s.get('campus'), 'url': g['url'],
                               'source': s['url'], 'read': TODAY.isoformat(), 'tags': (lambda T: T + (['film'] if 'film' not in T and re.search(r'(?i)cinema|movie|film', (g.get('place') or '') + ' ' + (s.get('kind') or '')) else []))(tags(g['title'])) if s['kind'] != 'sports' else [],   # a show in a cinema is a film **flags(g),
                               **({'tickets': s['tickets']} if s.get('tickets') else {}), **({'home': g['home'], 'team': s.get('team'), 'sport': s.get('sport')} if 'home' in g and g['home'] is not None else {}),
                               **({'result': g['result']} if g.get('result') else {})})
            status[s['id']] = {'ok': True, 'found': len(got), 'kept': kept, 'read': NOW.isoformat(timespec='minutes')}
        except Exception as e:
            status[s['id']] = {'ok': False, 'error': str(e)[:200], 'read': NOW.isoformat(timespec='minutes')}
    nights.sort(key=lambda n: n['start'])
    json.dump({'updated': NOW.isoformat(timespec='minutes'), KEY: nights}, open(OUT, 'w'), ensure_ascii=False, indent=0)
    json.dump(status, open(STAT, 'w'), ensure_ascii=False, indent=1)
    if KEY == 'nights': ics(nights, 'The Scroll Bar: shows in the valley', 'nights.ics', 'Concerts, comedy and stage shows in the St. Joseph River valley, from each venue\'s own calendar. Project Scroll.')
    else: ics([n for n in nights if n.get('home')], 'Game Day: home games in the valley', 'games.ics', 'Home games of the valley\'s teams, from each club\'s own schedule. Project Scroll.')
    print(f"{len(nights)} nights from {sum(v['ok'] for v in status.values())} of {len(S)} sources")
    for k, v in status.items(): print(k, v)

if __name__ == '__main__':
    main()
    main('sports_sources.json', 'games.json', 'games', 'sports_status.json', KEEP=7)
    # counts.json: how many shows and home games each day of the next two weeks, for the home page's two buttons (a few hundred bytes)
    def per_day(path, key, home=False):
        c = {}
        for n in json.load(open(path))[key]:
            if home and not n.get('home'): continue
            if not home and len(n['start']) > 10 and datetime.datetime.fromisoformat(n['start']).astimezone(TZ).hour < 16: continue   # shows: the night's only (from 4 pm)
            d = n['start'][:10] if len(n['start']) == 10 else datetime.datetime.fromisoformat(n['start']).astimezone(TZ).date().isoformat()
            if TODAY.isoformat() <= d <= (TODAY + datetime.timedelta(days=14)).isoformat(): c[d] = c.get(d, 0) + 1
        return dict(sorted(c.items()))
    json.dump({'updated': NOW.isoformat(timespec='minutes'), 'shows': per_day('nights.json', 'nights'), 'games': per_day('games.json', 'games', True)},
              open('counts.json', 'w'), separators=(',', ':'))
