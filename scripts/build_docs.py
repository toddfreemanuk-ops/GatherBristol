"""Merge refreshed Headfirst events into day documents, keeping every non-Headfirst listing.

Usage: python -P -E build_docs.py <live_data_dir> <project_data_dir> <work_dir>
Writes <work_dir>/docs/<date>.json and <work_dir>/plan.json. Touches nothing live.
"""
import collections, datetime as dt, glob, json, os, re, sys, time, urllib.parse, urllib.request

LIVE, DATA, WORK = sys.argv[1:4]
TODAY = dt.date.today().isoformat()
HF = 'headfirstbristol.co.uk'
raw = json.load(open(os.path.join(WORK, 'events_raw.json'), encoding='utf-8'))

src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'refresh_listings.py'), encoding='utf-8').read()
g = {'re': re}
exec(src[src.index('def has('):src.index('def parse_event(')], g)
classify = g['classify']

def norm(v): return re.sub(r'[^a-z0-9]', '', re.sub(r'^the\s+', '', v.lower()))
ll = {}
for f in glob.glob(os.path.join(LIVE, 'days', '*.json')) + glob.glob(os.path.join(DATA, 'dir', '*.json')):
    for x in json.load(open(f, encoding='utf-8')).get('items', []):
        if x.get('v') and isinstance(x.get('ll'), list): ll.setdefault(norm(x['v']), x['ll'])

# small venues are typed in by promoters with no address; some carry the postcode in the venue name itself
for e in raw.values():
    if not e['postcode']:
        m = re.search(r'\b(BS\d{1,2})\s*(\d[A-Z]{2})\b', e['venue'].upper())
        if m: e['postcode'] = m.group(1) + ' ' + m.group(2)

missing = sorted({e['postcode'].upper() for e in raw.values() if norm(e['venue']) not in ll and e['postcode']})
cache_p = os.path.join(WORK, 'postcodes.json')
pc = json.load(open(cache_p, encoding='utf-8')) if os.path.exists(cache_p) else {}
todo = [p for p in missing if p not in pc]
for i in range(0, len(todo), 100):
    body = json.dumps({'postcodes': todo[i:i + 100]}).encode()
    req = urllib.request.Request('https://api.postcodes.io/postcodes', data=body, headers={'Content-Type': 'application/json', 'User-Agent': 'GatherBristolBot/1.0'})
    for r in json.load(urllib.request.urlopen(req, timeout=30))['result']:
        pc[r['query']] = [round(r['result']['latitude'], 4), round(r['result']['longitude'], 4)] if r['result'] else None
json.dump(pc, open(cache_p, 'w', encoding='utf-8'))

# venues still unplaced are looked up by name on OpenStreetMap, once each, and kept only on a single exact-name match inside Bristol
geo_p = os.path.join(WORK, 'venues_geo.json')
geo = json.load(open(geo_p, encoding='utf-8')) if os.path.exists(geo_p) else {}
def plain(v): return re.split(r',| - | \(', v)[0].strip()
def hints(v): return [w for w in re.findall(r'[a-z0-9]+', v[len(plain(v)):].lower()) if len(w) >= 3 and w != 'bristol']   # the area or street a promoter added after the name
def fits(v, r):   # the name must match exactly; an added area must appear in the address; a church needs an area, as many share a name
    if r.get('category') not in PLACES or norm(r.get('name') or '') != norm(plain(v)): return False
    where, h = (r.get('display_name') or '').lower(), hints(v)
    return any(w in where for w in h) if h else r.get('type') != 'place_of_worship'
PLACES = {'amenity', 'shop', 'leisure', 'tourism', 'building', 'landuse', 'craft', 'club'}
unplaced = sorted({e['venue'] for e in raw.values() if e['venue'] and e['venue'] not in geo and norm(e['venue']) not in ll and not pc.get(e['postcode'].upper())})
for v in unplaced[:200]:
    q = urllib.parse.urlencode({'q': plain(v) + ', Bristol', 'format': 'jsonv2', 'limit': 5, 'countrycodes': 'gb', 'viewbox': '-2.735,51.525,-2.495,51.385', 'bounded': 1})
    try:
        req = urllib.request.Request('https://nominatim.openstreetmap.org/search?' + q, headers={'User-Agent': 'GatherBristolBot/1.0 (venue lookup for a listings map)'})
        hits = [r for r in json.load(urllib.request.urlopen(req, timeout=30)) if fits(v, r)]
    except Exception as e:
        print('venue lookup failed, will retry next time:', v, e); time.sleep(1.1); continue
    spots = {(round(float(r['lat']), 3), round(float(r['lon']), 3)) for r in hits}
    geo[v] = [round(float(hits[0]['lat']), 4), round(float(hits[0]['lon']), 4)] if len(spots) == 1 else None
    time.sleep(1.1)
json.dump(geo, open(geo_p, 'w', encoding='utf-8'), ensure_ascii=False, indent=0, sort_keys=True)

old_by_url = {}
keep, versions, old_srcs = collections.defaultdict(list), {}, {}
for f in glob.glob(os.path.join(LIVE, 'days', '*.json')):
    d = os.path.splitext(os.path.basename(f))[0]
    if not re.match(r'\d{4}-\d\d-\d\d$', d): continue
    doc = json.load(open(f, encoding='utf-8'))
    old_srcs[d] = doc.get('src', '')
    for x in doc.get('items', []):
        if HF in x.get('u', ''): old_by_url[x['u']] = (d, x)
        if d >= TODAY: keep[d].append(x)

def money(v): return '£' + (f'{v:.0f}' if float(v).is_integer() else f'{v:.2f}')
new, skipped = collections.defaultdict(list), collections.Counter()
skip_venues = collections.Counter()
for u, e in raw.items():
    d = e['start'][:10]
    if d < TODAY: skipped['past'] += 1; continue
    p = ll.get(norm(e['venue'])) or pc.get(e['postcode'].upper()) or geo.get(e['venue'])
    if not p: skipped['no location'] += 1; skip_venues[e['venue']] += 1; continue
    if not (51.38 <= p[0] <= 51.56 and -2.76 <= p[1] <= -2.44): skipped['outside Bristol'] += 1; skip_venues[e['venue']] += 1; continue
    k, sub, gs = classify(e['title'], e['desc'], e['crumb'], e['venue'], e.get('etype', 'Event'))
    item = {'t': e['title'], 'v': e['venue'], 'll': p, 'u': u, 'k': k, 'sub': sub}
    s, en = e['start'][11:16], e['end'][11:16] if e['end'] else ''
    if s != '00:00': item['s'] = s
    if en and en != s: item['e'] = en
    if e['min_price'] is not None: item['p'] = money(e['min_price'])
    if e['sold']: item['x'] = 'Sold out'
    if gs: item['g'] = ', '.join(gs)
    prev = old_by_url.get(u)
    if prev:  # keep the categories and flags already set by hand
        for f in ('k', 'sub', 'g', 'f', 'area'):
            if f in prev[1]: item[f] = prev[1][f]
            elif f == 'g': item.pop('g', None)
    new[d].append(item)

out = os.path.join(WORK, 'docs'); os.makedirs(out, exist_ok=True)
for f in glob.glob(os.path.join(out, '*.json')): os.remove(f)
plan, total = [], 0
for d in sorted(set(new) | {k for k in keep}):
    fresh = {x['u'] for x in new.get(d, [])}
    others = [x for x in keep.get(d, []) if HF not in x.get('u', '')]   # Headfirst events come only from today's scrape, so cancelled ones drop out
    items = others + sorted(new.get(d, []), key=lambda x: (x.get('s', '99'), x['t']))
    names = [s.strip() for s in old_srcs.get(d, '').split(',') if s.strip()]
    if new.get(d) and 'Headfirst Bristol' not in names: names.insert(0, 'Headfirst Bristol')
    doc = {'date': d, 'items': items, 'pulled': dt.date.today().isoformat(), 'src': ', '.join(names) or 'Headfirst Bristol'}
    json.dump(doc, open(os.path.join(out, d + '.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    plan.append(d); total += len(items)
json.dump(plan, open(os.path.join(WORK, 'plan.json'), 'w'))

all_new = [x for v in new.values() for x in v]
print('dates', len(plan), 'listings', total, 'refreshed', len(all_new), 'kept from before', total - len(all_new))
print('skipped', dict(skipped), skip_venues.most_common(30))
print('by type', collections.Counter(x['k'] for x in all_new).most_common())
print('by sub', collections.Counter((x['k'], x['sub']) for x in all_new).most_common(40))
print('per day', [(d, len(new.get(d, []))) for d in plan][:45])
print('largest doc KB', max(os.path.getsize(os.path.join(out, d + '.json')) for d in plan) // 1024)
print('--- non-gig/club sample')
for x in [x for x in all_new if x['k'] not in ('gig', 'club')][:60]: print(x['k'], '|', x['sub'], '|', x['t'][:60], '|', x['v'][:28])
print('--- social Other sample')
for x in [x for x in all_new if x['k'] == 'social' and x['sub'] == 'Other'][:40]: print(x['t'][:60], '|', x['v'][:28])
print('--- gig Other sample')
for x in [x for x in all_new if x['k'] == 'gig' and x['sub'] == 'Other'][:25]: print(x['t'][:60], '|', x['v'][:28])
print('etypes', collections.Counter((e.get('etype'), e['crumb']) for e in raw.values()).most_common(12))
