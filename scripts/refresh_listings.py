"""Refresh Headfirst Bristol listings for GatherBristol.

Usage: python -P -E refresh_listings.py <phase> <data_dir> <work_dir> <images_dir>
  discover  find event URLs for the next HORIZON days from public listing and venue pages
  events    fetch each event page and turn its schema.org data into a listing (resumable)
  images    download and resize each new listing's preview image (resumable)
At most 2 requests a second to any site. Anything that fails is logged and skipped.
"""
import datetime as dt, glob, hashlib, html, io, json, os, re, sys, time, urllib.parse, urllib.request

PHASE, DATA, WORK, IMAGES = sys.argv[1:5]
os.makedirs(WORK, exist_ok=True)
BASE = 'https://www.headfirstbristol.co.uk'
UA = 'Mozilla/5.0 (compatible; GatherBristolBot/1.0; daily listings refresh)'
GAP = 0.6
HORIZON = 42
TODAY = dt.date.today()
LAST = TODAY + dt.timedelta(days=HORIZON)
MON = {m: i + 1 for i, m in enumerate('jan feb mar apr may jun jul aug sep oct nov dec'.split())}
DOW = 'mon tue wed thu fri sat sun'.split()

_last = [0.0]
def get(url, limit=3_000_000):
    wait = _last[0] + GAP - time.time()
    if wait > 0: time.sleep(wait)
    _last[0] = time.time()
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'en-GB'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read(limit), r.headers.get_content_charset() or 'utf-8'

def text(url):
    raw, cs = get(url)
    return raw.decode(cs, 'replace')

def path(name): return os.path.join(WORK, name)
def load(name, default):
    return json.load(open(path(name), encoding='utf-8')) if os.path.exists(path(name)) else default
def save(name, obj):
    tmp = path(name + '.tmp')
    json.dump(obj, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    os.replace(tmp, path(name))

def old_items():
    for f in glob.glob(os.path.join(DATA, 'days', '*.json')):
        doc = os.path.splitext(os.path.basename(f))[0]
        for x in json.load(open(f, encoding='utf-8')).get('items', []):
            yield doc, x

def slug_date(url):
    m = re.search(r'/whats-on/[^/]+/([a-z]{3})-(\d{1,2})-([a-z]{3})-', url)
    if not m or m.group(3) not in MON or m.group(1) not in DOW: return None
    for y in (TODAY.year, TODAY.year + 1):
        try: d = dt.date(y, MON[m.group(3)], int(m.group(2)))
        except ValueError: continue
        if d >= TODAY and d.weekday() == DOW.index(m.group(1)): return d
    return None

def discover():
    pages = ['gigs-and-live-music', 'club-listings', 'event-listings', 'whats-on/tonight', 'whats-on/this-weekend', '']
    venues = set()
    for _, x in old_items():
        m = re.match(re.escape(BASE) + r'/whats-on/([^/]+)/', x.get('u', ''))
        if m: venues.add(m.group(1))
    found, seen, fails, tags = set(), set(), [], load('genres.json', {})
    def scan(url):
        if url in seen: return
        seen.add(url)
        try: h = text(url)
        except Exception as e:
            fails.append([url, str(e)[:120]]); print('skip', url, e, flush=True); return
        tags.update(card_genres(h))
        for u in re.findall(r'https://www\.headfirstbristol\.co\.uk/whats-on/[^"\'\s<>#?]+', h):
            parts = u[len(BASE) + 1:].split('/')
            if len(parts) == 3 and re.match(r'[a-z]{3}-\d', parts[2]): found.add(u); venues.add(parts[1])
            elif len(parts) == 2 and parts[1] not in ('tonight', 'this-weekend', 'new-years-eve'): venues.add(parts[1])
    for p in pages: scan(BASE + '/' + p)
    # Headfirst has a listings page for every day; these reach small venues that no listing page links to
    for i in range(HORIZON + 1):
        d = TODAY + dt.timedelta(days=i)
        nth = 'th' if 10 <= d.day % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(d.day % 10, 'th')
        scan(f"{BASE}/whats-on/{d.strftime('%A').lower()}-{d.day}{nth}-{d.strftime('%B').lower()}-{d.year}")
    venues = {v for v in venues if not re.match(r'(?:mon|tues|wednes|thurs|fri|satur|sun)day-\d', v)}   # day pages are not venues
    print('venues to scan', len(venues), flush=True)
    for i, v in enumerate(sorted(venues), 1):
        scan(f'{BASE}/whats-on/{v}')
        if i % 25 == 0: print(i, 'venues,', len(found), 'event links', flush=True)
    keep = sorted(u for u in found if (d := slug_date(u)) and d <= LAST)
    save('event_urls.json', keep); save('discover_fails.json', fails)
    save('genres.json', {u: tags[u] for u in keep if u in tags})
    print(f'{len(found)} event links, {len(keep)} between {TODAY} and {LAST}; {sum(1 for u in keep if u in tags)} with genre tags; {len(fails)} pages skipped')

EVENT_LINK = re.compile(r'https://www\.headfirstbristol\.co\.uk/whats-on/[^"\'\s<>#?/]+/[a-z]{3}-\d[^"\'\s<>#?/]*')
def card_genres(h):
    """The genre tags Headfirst shows on each listing card of a listings page: {event url: [tag, ...]}."""
    out, starts = {}, [m.start() for m in re.finditer(r'class="\s*c-listing\s+c-listing--', h)]
    for a, b in zip(starts, starts[1:] + [len(h)]):
        card = h[a:b]; link = EVENT_LINK.search(card)
        g = [html.unescape(x).strip().lower() for x in re.findall(r'c-listing__genre">([^<]+)<', card)]
        if link and g: out[link.group(0)] = g[:8]
    return out

def has(pat, s): return re.search(r'\b(?:' + pat + r')\b', s, re.I) is not None

# Music genres for the site's Music tile, most specific first. Each: id, label, pattern for Headfirst's own tags,
# and a stricter pattern for free text, where words like "house", "pop" and "party" usually mean something else.
MUSIC_GENRES = [
    ('tribute', 'Tribute acts', r'tribute', None),
    ('openmic', 'Open mic & jams', r'open mic|jam session|jam night|open decks', None),
    ('dnb', 'Drum & bass & jungle', r'drum (?:and|&|n) bass|d ?& ?b|dnb|jungle|neurofunk|jump ?up', None),
    ('bass', 'Garage, dubstep & bass', r'uk garage|speed garage|ukg|garage(?! rock)|dubstep|bassline|140|grime|bass music|breaks|breakbeat|footwork|uk funky', r'uk garage|ukg|dubstep|bassline|grime|breakbeat'),
    ('techno', 'Techno, trance & hard dance', r'techno|trance|hard dance|hardstyle|gabber|acid|rave|psy|industrial|ebm|electro(?!nic| swing)', r'techno|trance|hard dance|hardstyle|gabber|psytrance|acid house|ebm'),
    ('house', 'House & disco', r'house|disco|italo|balearic|boogie', r'house music|tech house|deep house|disco|italo'),
    ('hiphop', 'Hip hop, rap & R&B', r'hip[ -]?hop|rap|r ?& ?b|rnb|trap|drill', r'hip[ -]?hop|rapper|r ?& ?b|rnb'),
    ('reggae', 'Reggae, dub & ska', r'reggae|dub(?!step)|dancehall|ska|sound ?system|roots|soca|bashment', r'reggae|dancehall|ska|sound ?system|dubwise'),
    ('global', 'Latin, Afro & global', r'latin|salsa|cumbia|afro\w*|amapiano|highlife|world|balkan|klezmer|samba|bossa|flamenco|brazil\w*|bhangra|tropical|reggaeton|gqom|arabic|african',
     r'latin|salsa|cumbia|afrobeats?|amapiano|balkan|klezmer|samba|flamenco|bhangra|world music'),
    ('punk', 'Punk, metal & hardcore', r'(?<!post[- ])punk|metal|hardcore|grunge|emo|doom|stoner|thrash|sludge|noise|screamo|grindcore', r'(?<!post[- ])punk|metal|hardcore|grunge|emo|doom|stoner|thrash|sludge'),
    ('rock', 'Rock, indie & alternative', r'rock|indie|alternative|psych\w*|shoegaze|britpop|post[- ]punk|new wave|math', r'rock|indie|shoegaze|psych|post[- ]punk|britpop'),
    ('folk', 'Folk, country & acoustic', r'folk|acoustic|singer[- ]songwriter|country|americana|bluegrass|ceilidh|shanty|celtic|trad\w*', r'folk|acoustic|singer[- ]songwriter|country music|americana|bluegrass|ceilidh|shanty|celtic'),
    ('jazz', 'Jazz, funk & soul', r'jazz|funk|soul|blues|swing|big band|motown|gospel', None),
    ('classical', 'Classical, choral & opera', r'classical|orchestra\w*|choir|choral|opera|symphon\w*|quartet|recital|baroque|chamber', None),
    ('electronic', 'Electronic & experimental', r'electronic\w*|synth\w*|ambient|experimental|modular|idm|downtempo|leftfield', r'electronica?|synth\w*|ambient|experimental|modular'),
    ('pop', 'Pop & party nights', r'pop|80s|90s|00s|2000s|karaoke|sing[- ]?along|party|cheese|student|lgbtq\+?|drag|queer', r'pop music|80s|90s|00s|karaoke|sing[- ]?along'),
]
def music_genre(tags, title, desc, k):
    """One genre id for a gig or club night: Headfirst's tags vote first, then words in the title and description."""
    votes = {}
    for t in tags or []:
        for gid, _, pat, _ in MUSIC_GENRES:
            if re.search(r'(?<![a-z0-9])(?:' + pat + r')(?![a-z])', t, re.I): votes[gid] = votes.get(gid, 0) + 1; break
    if not votes:
        for gid, _, pat, strict in MUSIC_GENRES:
            n = 3 * len(re.findall(r'\b(?:' + (strict or pat) + r')\b', title, re.I)) + len(re.findall(r'\b(?:' + (strict or pat) + r')\b', desc, re.I))
            if n: votes[gid] = n
    if not votes: return 'otherclub' if k == 'club' else 'othergig'
    order = [g[0] for g in MUSIC_GENRES]
    return max(votes, key=lambda g: (votes[g], -order.index(g)))

GENRES = ['drum and bass', 'drum & bass', 'jungle', 'dubstep', 'uk garage', 'garage', 'house', 'tech house', 'techno', 'trance', 'disco', 'funk', 'soul', 'jazz', 'afrobeats', 'amapiano', 'dancehall', 'reggae', 'dub', 'hip hop', 'grime', 'electro', 'breakbeat', 'punk', 'hardcore', 'metal', 'grunge', 'emo', 'indie', 'alt rock', 'rock', 'psych', 'folk', 'ceilidh', 'singer-songwriter', 'tribute', 'world', 'lgbtq+']
def genres(s):
    out = []
    for g in GENRES:
        if re.search(r'(?<![a-z])' + re.escape(g) + r'(?![a-z])', s, re.I) and g not in out: out.append(g)
    return out[:3]

def classify(title, desc, crumb, venue, etype='Event'):
    t, all_ = title, title + ' ' + desc
    g = genres(all_)
    if 'nightlife' in crumb.lower():
        if has('drum (?:and|&) bass|d&b|dnb|jungle|dubstep|140', all_): sub = 'Drum & bass and jungle'
        elif has('techno|trance|hard dance|hardcore|rave|gabber', all_): sub = 'Techno & hard dance'
        elif has('house|disco|garage|funk', all_): sub = 'House, disco & garage'
        elif has('reggae|dub|dancehall|afrobeats?|amapiano|latin|salsa|reggaeton|soca', all_): sub = 'Reggae, Latin & global'
        elif has('indie|pop|rock|emo|2000s|00s|90s|80s', all_): sub = 'Indie, pop & rock'
        else: sub = 'Other'
        return 'club', sub, g
    if has('comedy|stand-?up|comedian', t) or has('stand-?up comedy|comedy night', desc) or has('gaffe comedy', venue): return 'comedy', 'Stand-up', ['stand-up']
    if has('festival of economics|study day|curators?.? tour|walking tour|mansion|upstairs tour|bookshop presents', t): return 'learn', 'Talks & panels', []
    if has('film|screening|cinema', t): return 'film', 'Festival screenings' if has('festival', all_) else 'Screenings', []
    if has('quiz|bingo', t): return 'social', 'Quizzes', []
    if has('market|craft fair|record fair', t): return 'food', 'Markets', []
    if has('supper club|feast|tasting|brunch', t): return 'food', 'Supper clubs & feasts', []
    if has('workshop|masterclass|class|classes|course', t): return 'learn', 'Workshops', ['workshop']
    if has('yoga|sound bath|breathwork|meditation|ecstatic dance', t): return 'learn', 'Movement & wellbeing', []
    if has('talk|panel|lecture|in conversation', t): return 'learn', 'Talks & panels', ['talk']
    if has('exhibition', t): return 'art', 'Exhibitions', []
    if has('drag|cabaret|burlesque', t): return 'stage', 'Cabaret & drag', []
    if has('circus', t): return 'stage', 'Circus', []
    if has('musical|opera|ballet|panto|pantomime|the play', t) or has('wardrobe theatre|tobacco factory theatres?', venue): return 'stage', 'Theatre & dance', []
    if has('for kids|family (?:day|show|fun)|for children|ages \\d+', t): return 'family', 'Family days', []
    if etype != 'MusicEvent' and 'gigs' not in crumb.lower(): return 'social', 'Other', []
    if has('tribute', all_): sub = 'Tribute'
    elif has('punk|metal|hardcore|grunge|emo|stoner|doom', all_): sub = 'Punk & metal'
    elif has('folk|ceilidh|acoustic|singer-songwriter|bluegrass|americana|choir', all_): sub = 'Folk & acoustic'
    elif has('jazz|funk|soul|blues', all_): sub = 'Jazz, funk & soul'
    elif has('reggae|dub|afrobeat|world music|latin|ska', all_): sub = 'Reggae & world'
    elif has('electronic|synth|techno|house', all_): sub = 'Electronic'
    elif has('rock|indie|alt|psych|shoegaze|britpop', all_): sub = 'Rock & indie'
    else: sub = 'Other'
    return 'gig', sub, g

def parse_event(h, url):
    ev, crumb = None, ''
    for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', h, re.S):
        try: data = json.loads(m)
        except ValueError: continue
        for j in (data if isinstance(data, list) else [data]):
            if str(j.get('@type', '')).endswith('Event'): ev = j
            if j.get('@type') == 'BreadcrumbList':
                items = j.get('itemListElement', [])
                if len(items) > 1: crumb = (items[1].get('item') or {}).get('name', '')
    if not ev: raise ValueError('no event data')
    if ev.get('eventStatus', '').rsplit('/', 1)[-1] in ('EventCancelled', 'EventPostponed'): raise ValueError('cancelled or postponed')
    loc = ev.get('location') or {}
    addr = loc.get('address') or {}
    title, desc = html.unescape(ev.get('name', '')).strip(), html.unescape(ev.get('description', '') or '').strip()
    start, end = ev.get('startDate', ''), ev.get('endDate', '')
    if not title or not re.match(r'\d{4}-\d\d-\d\dT\d\d:\d\d', start): raise ValueError('missing title or date')
    offers = ev.get('offers') or []
    prices = [float(o['price']) for o in offers if str(o.get('price', '')).replace('.', '', 1).isdigit() and float(o['price']) > 0]
    sold = bool(offers) and all(o.get('availability', '').endswith(('SoldOut', 'OutOfStock')) for o in offers)
    img = ev.get('image') or []
    return {'url': url, 'etype': ev.get('@type'), 'title': title, 'desc': desc[:600], 'crumb': crumb, 'venue': html.unescape(loc.get('name', '')).strip(),
            'postcode': (addr.get('postalCode') or '').strip(), 'locality': addr.get('addressLocality', ''), 'start': start, 'end': end,
            'min_price': min(prices) if prices else None, 'sold': sold, 'image': img[0] if isinstance(img, list) and img else (img if isinstance(img, str) else '')}

def events():
    urls = load('event_urls.json', [])
    parsed, fails = load('events_raw.json', {}), load('event_fails.json', {})
    for i, u in enumerate(urls, 1):
        if u in parsed or u in fails: continue
        try: parsed[u] = parse_event(text(u), u)
        except Exception as e: fails[u] = str(e)[:160]; print('skip', u, e, flush=True)
        if i % 25 == 0:
            save('events_raw.json', parsed); save('event_fails.json', fails); print(i, '/', len(urls), flush=True)
    save('events_raw.json', parsed); save('event_fails.json', fails)
    print(f'{len(parsed)} events parsed, {len(fails)} skipped')

def images():
    from PIL import Image
    parsed = load('events_raw.json', {})
    done, fails, by_img = load('image_map.json', {}), load('image_fails.json', {}), {}
    for u, f in done.items():
        by_img[parsed.get(u, {}).get('image', '')] = f
    want = {x['u'] for f in glob.glob(path('docs/*.json')) for x in json.load(open(f, encoding='utf-8'))['items']}
    cap = int(sys.argv[5])   # the artifact's file limit: soonest events first until this many new files
    todo = sorted((e for e in parsed.values() if e['url'] in want and e['url'] not in done and e['url'] not in fails), key=lambda e: e['start'])
    for i, e in enumerate(todo, 1):
        if len(set(done.values())) >= cap: print('reached the file cap at', e['start'][:10]); break
        u, src = e['url'], e['image']
        try:
            if not src: raise ValueError('no image')
            if src in by_img: done[u] = by_img[src]; continue
            name = hashlib.sha1(u.encode()).hexdigest()[:12] + '.jpg'
            out = os.path.join(IMAGES, name)
            if not os.path.exists(out):
                raw, _ = get(src, 15_000_000)
                im = Image.open(io.BytesIO(raw)); im.load()
                if im.width < 150: raise ValueError(f'too small ({im.width}px)')
                if im.width > 400: im = im.resize((400, round(im.height * 400 / im.width)), Image.LANCZOS)
                if im.mode != 'RGB':
                    im = im.convert('RGBA'); bg = Image.new('RGB', im.size, (255, 255, 255)); bg.paste(im, mask=im.split()[3]); im = bg
                im.save(out, 'JPEG', quality=78, optimize=True, progressive=True)
            done[u] = by_img[src] = name
        except Exception as x: fails[u] = str(x)[:160]; print('skip', u, x, flush=True)
        if i % 25 == 0:
            save('image_map.json', done); save('image_fails.json', fails); print(i, '/', len(todo), flush=True)
    save('image_map.json', done); save('image_fails.json', fails)
    print(f'{len(done)} listings have images, {len(set(done.values()))} files, {len(fails)} skipped')

{'discover': discover, 'events': events, 'images': images}[PHASE]()
