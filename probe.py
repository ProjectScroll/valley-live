"""One-off look at each source page: status, size, JSON-LD types, likely event links, date-like text. Writes probe.json."""
import json, re, urllib.request, collections
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36'
URLS = json.load(open('probe_urls.json'))
out = {}
for u in URLS:
    pat = None
    if isinstance(u, list): u, pat = u
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': UA, 'Accept': 'text/html,*/*'}), timeout=40)
        h = r.read().decode('utf-8', 'replace')
        lds = re.findall(r'<script[^>]+ld\+json[^>]*>(.*?)</script>', h, re.S | re.I)
        types = collections.Counter(re.findall(r'"@type"\s*:\s*"([^"]+)"', ' '.join(lds)))
        links = collections.Counter(re.sub(r'\d+', 'N', re.sub(r'[?#].*', '', l)) for l in re.findall(r'href="([^"]+)"', h) if re.search(r'event|show|perform|ticket|concert|calendar', l, re.I))
        out[u] = {'status': r.status, 'final': r.geturl(), 'bytes': len(h), 'ld_types': dict(types), 'links': links.most_common(15),
                  'ics': re.findall(r'href="([^"]+\.ics[^"]*)"', h)[:5], 'feeds': re.findall(r'href="([^"]*(?:feed|rss|ical|json)[^"]*)"', h, re.I)[:8],
                  'dates': re.findall(r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? \d{1,2},? \d{4}', h)[:6],
                  'apis': sorted(set(re.findall(r'https?://[a-z0-9.-]*(?:api|tixr|etix|ticketmaster|eventbrite|localist|ludus|showclix|seatgeek|axs|spektrix|tessitura|ovationtix|audienceview|calendarwiz|trumba)[a-z0-9./-]*', h, re.I)))[:12],
                  'snip': (lambda m: re.sub(r'\s+',' ',h[max(0,m.start()-1500):m.start()+1500]) if m else '')(re.search(pat or r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? \d{1,2},? \d{4}|\d{4}-\d{2}-\d{2}T', h)),
                  'head': h[:2500] if len(h) < 30000 else '',
                  'types_json': (lambda: (list(json.loads(h).keys())[:40] if h.strip().startswith('{') else None))() ,
                  'title': (re.findall(r'<title>(.*?)</title>', h, re.S) or [''])[0].strip()[:100]}
    except Exception as e:
        out[u] = {'error': str(e)[:200]}
json.dump(out, open('probe.json', 'w'), indent=1)
