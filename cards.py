"""Draws the two share cards that change every day (cards/scroll-bar.png, cards/sports.png) from nights.json and games.json.
Run nightly after fetch.py. Our own artwork only: neon lettering, a scoreboard, and the names of the shows and games.
Fonts in fonts/ are under the SIL Open Font License (Monoton, Bebas Neue, Inter)."""
import json, datetime, os
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont, ImageFilter
TZ = ZoneInfo('America/Detroit'); NOW = datetime.datetime.now(TZ); TODAY = NOW.date()
W, H = 1200, 630
os.makedirs('cards', exist_ok=True)
def inter(size, w='Regular'):
    f = ImageFont.truetype('fonts/Inter.ttf', size)
    try: f.set_variation_by_name(w)
    except Exception: pass
    return f
MONO = lambda s: ImageFont.truetype('fonts/Monoton-Regular.ttf', s)
BEBAS = lambda s: ImageFont.truetype('fonts/BebasNeue-Regular.ttf', s)
def start(n):
    s = n['start']
    if len(s) == 10: return datetime.datetime.combine(datetime.date.fromisoformat(s), datetime.time(12), TZ), True
    return datetime.datetime.fromisoformat(s).astimezone(TZ), n.get('allday', False)
def fit(d, text, font, maxw):
    if d.textlength(text, font=font) <= maxw: return text
    while text and d.textlength(text + '…', font=font) > maxw: text = text[:-1]
    return text.rstrip() + '…'
def glow(img, draw_fn, color, radius=14, times=2):
    layer = Image.new('RGBA', img.size, (0, 0, 0, 0)); draw_fn(ImageDraw.Draw(layer), color)
    for _ in range(times): img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(radius)))
    img.alpha_composite(layer)
def hm(dt, allday): return 'All day' if allday else dt.strftime('%-I:%M %p').replace(':00 ', ' ').lower().replace(' pm', ' pm').replace(' am', ' am')

def pick(items, home=False):
    """tonight's, else the next days' (up to the weekend), soonest first"""
    L = []
    for n in items:
        if home and not n.get('home'): continue
        dt, ad = start(n)
        if dt.date() < TODAY or (not ad and dt < NOW - datetime.timedelta(hours=1)): continue
        L.append((dt, ad, n))
    L.sort(key=lambda x: x[0])
    tn = [x for x in L if x[0].date() == TODAY]
    return ('Tonight', tn) if tn else (('Coming up', L))

# ---- the Scroll Bar: a neon sign on a dark brick wall
def scroll_bar():
    N = json.load(open('nights.json'))['nights']
    lab, L = pick(N)
    img = Image.new('RGBA', (W, H), (11, 9, 18, 255)); d = ImageDraw.Draw(img)
    for y in range(0, H, 34):   # bricks
        off = 0 if (y // 34) % 2 else 46
        for x in range(-off, W, 92): d.rectangle([x + 2, y + 2, x + 90, y + 32], fill=(22, 16, 30, 255))
    shade = Image.new('RGBA', (W, H), (0, 0, 0, 0)); sd = ImageDraw.Draw(shade)
    for i in range(60): sd.rectangle([0, 0, W, H], outline=(0, 0, 0, 4 * i), width=1); 
    img.alpha_composite(Image.new('RGBA', (W, H), (11, 9, 18, 120)))
    t1 = MONO(92)
    glow(img, lambda g, c: g.text((70, 52), 'The Scroll Bar', font=t1, fill=c), (255, 62, 165, 255), 18, 3)
    d = ImageDraw.Draw(img)
    d.text((76, 178), (lab + ' in the valley · ' + TODAY.strftime('%A, %B %-d')).upper(), font=inter(24, 'Bold'), fill=(56, 217, 255, 255))
    y = 232
    for dt, ad, n in L[:4]:
        when = hm(dt, ad) if lab == 'Tonight' else dt.strftime('%a %b %-d')
        d.rounded_rectangle([70, y, W - 70, y + 74], 14, fill=(21, 17, 31, 255), outline=(255, 255, 255, 22))
        d.rounded_rectangle([70, y, 76, y + 74], 3, fill=(255, 62, 165, 255))
        d.text((96, y + 12), when, font=inter(22, 'Bold'), fill=(255, 179, 64, 255))
        d.text((96, y + 39), fit(d, n['venue'] + ' · ' + n['town'], inter(20), 370), font=inter(20), fill=(171, 159, 196, 255))
        d.text((490, y + 20), fit(d, n['title'], inter(30, 'Bold'), W - 70 - 490 - 24), font=inter(30, 'Bold'), fill=(243, 238, 252, 255))
        y += 86
    if not L: d.text((76, 260), 'The venues’ calendars are read every night.', font=inter(30), fill=(243, 238, 252, 255))
    more = len(L) - 4
    d.text((72, H - 52), 'projectscroll.com/scroll-bar' + (f'   ·   {more} more {"show" if more == 1 else "shows"} ahead' if more > 0 else ''), font=inter(22, 'SemiBold'), fill=(171, 159, 196, 255))
    img.convert('RGB').save('cards/scroll-bar.png', optimize=True)

# ---- Game Day: a scoreboard over a mown field
def sports():
    G = json.load(open('games.json'))['games']
    lab, L = pick(G, home=True)
    img = Image.new('RGBA', (W, H), (10, 18, 13, 255)); d = ImageDraw.Draw(img)
    for x in range(0, W, 140): d.rectangle([x, 0, x + 69, H], fill=(29, 107, 52, 255)); d.rectangle([x + 70, 0, x + 139, H], fill=(35, 122, 61, 255))
    img.alpha_composite(Image.new('RGBA', (W, H), (6, 14, 9, 150)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([50, 36, W - 50, H - 36], 18, fill=(11, 11, 11, 255), outline=(42, 42, 42, 255), width=8)
    glow(img, lambda g, c: g.text((92, 58), 'GAME DAY', font=BEBAS(120), fill=c), (255, 176, 46, 255), 10, 2)
    d = ImageDraw.Draw(img)
    for yy in range(58, 180, 5): d.line([(92, yy), (560, yy)], fill=(11, 11, 11, 120))   # the board's dot rows
    d.text((96, 186), (lab + ' · home games in the valley').upper(), font=inter(22, 'Bold'), fill=(125, 211, 252, 255))
    y = 232
    for dt, ad, n in L[:4]:
        when = ('TBA' if ad else hm(dt, ad)) if lab == 'Tonight' else dt.strftime('%a %b %-d').upper()
        d.text((96, y + 4), when, font=BEBAS(40), fill=(255, 176, 46, 255))
        t = n['title'].replace('Western Michigan University', 'Western Michigan').replace(' Vs ', ' vs. ').replace(' At ', ' at ').replace('Bethel University (Ind)', 'Bethel').replace("Saint Mary's College", "Saint Mary's")
        d.text((330, y), fit(d, t, inter(30, 'Bold'), W - 96 - 330), font=inter(30, 'Bold'), fill=(238, 247, 239, 255))
        d.text((330, y + 38), fit(d, ' · '.join(x for x in (n.get('sport'), n.get('room')) if x), inter(20), W - 96 - 330), font=inter(20), fill=(166, 188, 170, 255))
        y += 78
    if not L: d.text((96, 260), 'The teams’ schedules are read every night.', font=inter(30), fill=(238, 247, 239, 255))
    d.text((96, H - 92), 'projectscroll.com/sports', font=inter(22, 'SemiBold'), fill=(166, 188, 170, 255))
    img.convert('RGB').save('cards/sports.png', optimize=True)

scroll_bar(); sports(); print('cards drawn')
