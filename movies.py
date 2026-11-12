"""What's playing in the valley's cinemas, from each cinema's own showtimes page, for the next seven days; posters from TMDB
(The Movie Database) when the TMDB_TOKEN secret is set. Writes movies.json. Run nightly by nightly.yml after fetch.py.
Only names, ratings, running times, showtimes and each cinema's own ticket links are kept; posters are TMDB's (credited on the page).
Standard library only."""
import json, re, os, time, datetime, html, urllib.request, urllib.parse
from zoneinfo import ZoneInfo
TZ = ZoneInfo('America/Detroit'); NOW = datetime.datetime.now(TZ); TODAY = NOW.date()
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36 ProjectScrollValleyLive/1.0 (+https://projectscroll.com/movies/)'
def get(u):
    r = urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': UA, 'Accept': 'text/html,*/*'}), timeout=40)
    return r.read().decode(r.headers.get_content_charset() or 'utf-8', 'replace')
clean = lambda x: re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', x or ''))).strip()
T = json.load(open('movie_sources.json'))['theaters']
try:   # each cinema's position from the OpenStreetMap list (cinemas.json), matched by its distinctive words
    OSM = json.load(open('cinemas.json'))['cinemas']
    for t in T:
        w = [x for x in re.findall(r'[a-z0-9]+', t['name'].lower()) if x not in ('gqt', 'cinema', 'cinemas', 'theatre', 'theater', 'the')]
        hit = [c for c in OSM if all(x in c['name'].lower() for x in w)] or [c for c in OSM if w and w[0] in c['name'].lower() and c['town'] == t['town']]
        if hit and 'll' not in t: t['ll'] = hit[0]['ll']; t['osm'] = hit[0]['id']
except Exception: pass

def cinemaplus(t, day):
    """CinemaPlus sites (KP Cinemas, the GQT cinemas, Linway): one block per film, each showtime a ticket link (or 'Expired')"""
    page = get(t['url'] + ('?date=' + day.isoformat() if day != TODAY else ''))
    out = []
    for b in re.split(r'<h3[^>]*>\s*<a[^>]*href="[^"]*/movie/', page)[1:]:
        m = re.match(r'(\d+)(?:\?[^"]*)?">(.*?)</a>', b, re.S)
        if not m: continue
        mid, title = m.group(1), clean(m.group(2))
        end = b.find('<h3'); b = b if end < 0 else b[:end]
        meta = re.findall(r'<div[^>]*>\s*([A-Z0-9-]{1,6}|NR|Not Rated|\d+h \d+m)\s*</div>', b[:2500])
        rating = next((x for x in meta if not re.match(r'\d+h', x)), ''); run = next((x for x in meta if re.match(r'\d+h', x)), '')
        feats = clean((re.search(r'class="cin-attribute">(.*?)</div>', b, re.S) or [None, ''])[1]).replace(' ,', ',')
        pm = re.search(r'<img[^>]*src="(https://images\.cinemaplus\.com/ticketing/posters/[^"]+)"', page[max(0, page.find('/movie/' + mid) - 1500):page.find('/movie/' + mid) + 600])
        for tk, tm in re.findall(r'<a[^>]*href="([^"]*/tickets/\d+)"[^>]*>\s*([0-9:]+[ap])\b', b, re.S):
            h, mi = (tm[:-1].split(':') + ['0'])[:2]; h = int(h) % 12 + (12 if tm[-1] == 'p' else 0)
            out.append({'cp': pm.group(1) if pm else '', 'title': title, 'mid': mid, 'rating': rating, 'run': run, 'feat': feats if len(feats) < 80 else '',
                        'start': datetime.datetime.combine(day, datetime.time(h, int(mi)), TZ).isoformat(), 'tickets': tk,
                        'page': t['url'].rstrip('/') + '/movie/' + mid if '/movie/' not in t['url'] else t['url']})
    return out

def key(t):
    t = re.sub(r'\(\d{4}\)|\b(3d|imax|screenx|dbox|d-box|4dx|open caption|oc|sensory friendly|fathom|re-release)\b', '', t.lower())
    return re.sub(r'[^a-z0-9]+', '', re.sub(r'^\s*(the|a|an)\s+', '', t))
def nicer(a, b):   # of two spellings of a title, the one not in capitals, with its article
    sa, sb = a.isupper(), b.isupper()
    if sa != sb: return b if sa else a
    return a if len(a) >= len(b) else b

films, shows, status = {}, [], {}
for t in T:
    n = 0
    try:
        for i in range(7):
            day = TODAY + datetime.timedelta(days=i)
            for s in {'cinemaplus': cinemaplus}[t['method']](t, day):
                k = key(s['title']) or s['mid']
                f = films.setdefault(k, {'k': k, 'title': re.sub(r'\s*\((?:3D|IMAX|Open Caption)\)\s*', ' ', s['title']).strip(), 'rating': s['rating'], 'run': s['run']})
                if not f['rating'] and s['rating']: f['rating'] = s['rating']
                if s.get('cp') and not f.get('cp'): f['cp'] = s['cp']; f['cpc'] = t['id']   # the poster the cinema itself shows (used only with the cinema's OK)
                f['title'] = nicer(f['title'], re.sub(r'\s*\((?:3D|IMAX|Open Caption)\)\s*', ' ', s['title']).strip())
                shows.append({'f': k, 'c': t['id'], 's': s['start'], 'u': s['tickets'], 'x': s['feat'], 'v': s['title'] if s['title'] != f['title'] else ''}); n += 1
            time.sleep(1)
        status[t['id']] = {'ok': True, 'shows': n}
    except Exception as e:
        status[t['id']] = {'ok': False, 'error': str(e)[:200], 'shows': n}

# film nights from the venues fetch.py reads (the Browning Cinema at Notre Dame and the like), each with its own page
try:
    for n in json.load(open('nights.json'))['nights']:
        if 'film' not in (n.get('tags') or []) or not re.search(r'(?i)cinema', (n.get('room') or '') + ' ' + n['venue']): continue
        title = re.sub(r'^(?:Film|Screening)\s*:\s*', '', n['title']).strip(); k = key(title)
        films.setdefault(k, {'k': k, 'title': title, 'rating': '', 'run': ''})
        shows.append({'f': k, 'c': 'browning' if 'Browning' in (n.get('room') or '') or 'Notre Dame' in n['town'] else n['venue'], 's': n['start'], 'u': n['url'], 'x': '', 'v': ''})
except Exception as e:
    status['film-nights'] = {'ok': False, 'error': str(e)[:200]}

# posters: TMDB, title by title, kept in tmdb_cache.json so each film is asked for once
TOK = os.environ.get('TMDB_TOKEN', '').strip()
cache = json.load(open('tmdb_cache.json')) if os.path.exists('tmdb_cache.json') else {}
if TOK:
    for k, f in films.items():
        if k in cache: continue
        try:
            q = urllib.parse.urlencode({'query': f['title'], 'include_adult': 'false', 'language': 'en-US', 'region': 'US'})
            r = json.load(urllib.request.urlopen(urllib.request.Request('https://api.themoviedb.org/3/search/movie?' + q, headers={'Authorization': 'Bearer ' + TOK, 'accept': 'application/json'}), timeout=20))
            R = [x for x in r.get('results', []) if x.get('poster_path')]
            # prefer this year's or last year's release with the same title
            R.sort(key=lambda x: (key(x.get('title', '')) != k, abs(int((x.get('release_date') or '1900')[:4]) - TODAY.year), -x.get('popularity', 0)))
            cache[k] = {'p': R[0]['poster_path'], 'id': R[0]['id'], 'y': (R[0].get('release_date') or '')[:4]} if R else {}
            time.sleep(.3)
        except Exception as e:
            status['tmdb'] = {'ok': False, 'error': str(e)[:200]}; break
    json.dump(cache, open('tmdb_cache.json', 'w'), separators=(',', ':'))
for k, f in films.items():
    c = cache.get(k) or {}
    if c.get('p'): f.update(poster=c['p'], tmdb=c['id'], year=c.get('y', ''))

shows.sort(key=lambda s: s['s'])
F = sorted(films.values(), key=lambda f: -sum(1 for s in shows if s['f'] == f['k']))
json.dump({'updated': NOW.isoformat(timespec='minutes'), 'theaters': [{k: t[k] for k in ('id', 'name', 'town', 'll', 'url') if k in t} for t in T],
           'films': F, 'shows': shows, 'status': status, 'posters': 'TMDB' if TOK else ''},
          open('movies.json', 'w'), ensure_ascii=False, separators=(',', ':'))
print(len(F), 'films,', len(shows), 'showtimes'); print(json.dumps(status))
