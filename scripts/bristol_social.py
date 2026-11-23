"""Add group sessions from the Bristol Social directory that source/dir/clubs.json does not have yet.

Usage:  python scripts/bristol_social.py            add the missing sessions
        python scripts/bristol_social.py --dry-run  list what would be added, change nothing
Then run  python scripts/daily_update.py --data-only  to rebuild the file the site reads.

It only ever adds. Listings already in clubs.json, including ones edited by hand, are left exactly as they are.
A session is skipped if the directory gives it no map location or it sits outside the map area.
"""
import datetime as dt, json, os, re, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLUBS = os.path.join(ROOT, 'source', 'dir', 'clubs.json')
SITE = 'https://social-bristol.pages.dev'
DRY = '--dry-run' in sys.argv
DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
# first matching tag decides the category: (tags, category, sub-category)
CATS = [(('running',), 'run', 'Free social runs'),
        (('board games', 'chess', 'D&D'), 'games', 'Board games'), (('gaming', 'console'), 'games', 'Video games'),
        (('languages',), 'lang', 'Language exchange'),
        (('knitting', 'sewing', 'fashion', 'crafts'), 'make', 'Craft'), (('drawing',), 'make', 'Drawing'), (('animation',), 'make', 'Animation'), (('art', 'creative'), 'make', 'Art'),
        (('cycling', 'mountain biking'), 'out', 'Cycling'), (('cold water therapy',), 'out', 'Cold water'), (('walking', 'hiking'), 'out', 'Walking'), (('sports', 'climbing'), 'out', 'Sport'),
        (('books', 'literature', 'writing'), 'books', 'Book club'),
        (('singing',), 'music', 'Singing'),
        (('coding', 'technology', 'electronics', 'development'), 'tech', 'Tech')]

html = urllib.request.urlopen(urllib.request.Request(SITE + '/', headers={'User-Agent': 'GatherBristolBot/1.0'}), timeout=40).read().decode('utf-8', 'replace')
groups = json.loads(re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S).group(1))['props']['pageProps']['groups']

doc = json.load(open(CLUBS, encoding='utf-8'))
have = {}   # directory slug -> weekdays already listed
for x in doc['items']:
    m = re.search(r'/groups/([^/?#]+)', x.get('u', ''))
    if m: have.setdefault(m.group(1), set()).update(x.get('dow') or range(1, 8))   # a listing with no weekdays counts for every day
def norm(s): return re.sub(r'[^a-z0-9]', '', s.lower())
named = [(norm(x['t']), set(x.get('dow') or range(1, 8))) for x in doc['items']]   # groups listed from another source, matched by name

def hhmm(s):
    m = re.search(r'(\d{1,2}):(\d\d)\s*$', s or '')
    return f'{int(m.group(1)):02d}:{m.group(2)}' if m else ''
def when(freq, day):
    f = re.sub(r'^(the|every)\s+', '', (freq or '').strip(), flags=re.I)
    if f.lower() in ('weekly', f'weekly on {day.lower()}s'): return day + 's', True
    if f.lower().startswith('weekly'): return day + 's' + f[len('weekly'):].replace(f' on {day}s', ''), True
    m = re.match(r'fortnightly on (\w+)$', f, re.I)
    if m: return 'Fortnightly ' + m.group(1), False
    if f.lower() == 'monthly': return f'Monthly, on a {day}', False
    return f[:1].upper() + f[1:], False
def category(tags):
    for names, k, sub in CATS:
        if any(t in names for t in tags): return k, sub
    return 'social', 'Social'

new, skipped = [], []
for g in groups:
    events = g.get('events') or []
    for e in events:
        t, loc, day = e.get('time') or {}, e.get('location') or {}, (e.get('time') or {}).get('weekday', '')
        name = g['name'] + (f" ({e['name']})" if e.get('name') and len(events) > 1 else '')
        if day not in DAYS: skipped.append((name, 'no weekday')); continue
        dow = DAYS.index(day) + 1
        if dow in have.get(g['slug'], set()) or any(n.startswith(norm(g['name'])) and dow in d for n, d in named): continue
        try: ll = [round(float(loc['latitude']), 4), round(float(loc['longitude']), 4)]
        except (KeyError, TypeError, ValueError): skipped.append((name, 'no map location')); continue
        if not (51.385 <= ll[0] <= 51.525 and -2.735 <= ll[1] <= -2.495): skipped.append((name, 'outside the map')); continue
        k, sub = category(g.get('tags') or [])
        w, weekly = when(t.get('frequency'), day)
        item = {'t': name, 'v': (loc.get('address') or g['name']).split(',')[0].strip(), 'll': ll, 'k': k, 'sub': sub,
                'u': f"{SITE}/groups/{g['slug']}", 'w': w, 'dow': [dow], 'wk': weekly}
        if hhmm(t.get('start')): item['s'] = hhmm(t.get('start'))
        if hhmm(t.get('end')): item['e'] = hhmm(t.get('end'))
        price = (e.get('cost') or {}).get('sessionPrice')
        if price == 0: item['p'] = 'Free'
        elif isinstance(price, (int, float)): item['p'] = '£' + (f'{price:.0f}' if float(price).is_integer() else f'{price:.2f}')
        if (e.get('booking') or {}).get('required') in (True, 'Required', 'Yes'): item['g'] = 'book ahead'
        new.append(item)

print(f'Bristol Social: {len(groups)} groups, {sum(len(g.get("events") or []) for g in groups)} sessions; {len(new)} to add; skipped {len(skipped)}')
for x in new: print('  +', x['k'], '|', x['sub'], '|', x['t'], '|', x['v'], '|', x['w'], x.get('s', ''), '|', x.get('p', ''))
for n, why in skipped: print('  -', n, '(' + why + ')')
if DRY or not new: sys.exit(0)
doc['items'] += new
with open(CLUBS, 'w', encoding='utf-8', newline='\n') as f:
    json.dump(doc, f, ensure_ascii=False, indent=2, sort_keys=True); f.write('\n')
print('clubs.json written')
