"""Daily refresh for GatherBristol: find new events, merge them, rebuild the file the site reads.

Usage (from anywhere):  python scripts/daily_update.py            full refresh
                        python scripts/daily_update.py --data-only  rebuild site/data/listings.json from source/ only
Set NO_IMAGES=1 to publish without scraped images.
If the scrape looks broken (far fewer events than last time) it stops before touching the site.
"""
import datetime as dt, glob, json, os, re, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC, WORK, SITE, S = (os.path.join(ROOT, x) for x in ('source', 'work', 'site', 'scripts'))
IMG = os.path.join(SITE, 'img')
TODAY = dt.date.today()
NO_IMAGES = os.environ.get('NO_IMAGES') == '1'
REFETCH_DAYS = 2    # events this close are fetched again each day, so sold-out and price stay current
NEWS_DAYS = 7       # headlines older than this are left off the site
DATED = re.compile(r'^\d{4}-\d\d-\d\d$')

def load(p, default):
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else default
def save(p, obj, **kw):
    json.dump(obj, open(p, 'w', encoding='utf-8'), ensure_ascii=False, **kw)
def run(script, *args):
    subprocess.run([sys.executable, '-P', os.path.join(S, script), *args], check=True)

def refresh():
    urls_p, raw_p = os.path.join(WORK, 'event_urls.json'), os.path.join(WORK, 'events_raw.json')
    before = len(load(urls_p, []))
    run('refresh_listings.py', 'discover', SRC, WORK, IMG)
    urls = set(load(urls_p, []))
    if len(urls) < max(40, before // 2):
        sys.exit(f'Only {len(urls)} events found (last time {before}). Leaving the site as it is.')
    soon = (TODAY + dt.timedelta(days=REFETCH_DAYS)).isoformat()
    raw = {u: e for u, e in load(raw_p, {}).items() if u in urls and e['start'][:10] > soon}
    save(raw_p, raw)
    fails_p = os.path.join(WORK, 'event_fails.json')
    if os.path.exists(fails_p): os.remove(fails_p)
    run('refresh_listings.py', 'events', SRC, WORK, IMG)
    run('build_docs.py', SRC, SRC, WORK)
    docs = glob.glob(os.path.join(WORK, 'docs', '*.json'))
    if not docs: sys.exit('No day documents were built. Leaving the site as it is.')
    for f in glob.glob(os.path.join(SRC, 'days', '*.json')):
        if DATED.match(os.path.splitext(os.path.basename(f))[0]): os.remove(f)
    for f in docs: shutil.copy(f, os.path.join(SRC, 'days'))
    if not NO_IMAGES:
        run('refresh_listings.py', 'images', SRC, WORK, IMG, '100000')

def build_site_data():
    today = TODAY.isoformat()
    days, dirs, used = [], [], set()
    for f in sorted(glob.glob(os.path.join(SRC, 'days', '*.json'))):
        name = os.path.splitext(os.path.basename(f))[0]
        if DATED.match(name) and name < today: continue
        days.append({'id': name, 'items': load(f, {}).get('items', [])})
    for f in sorted(glob.glob(os.path.join(SRC, 'dir', '*.json'))):
        name, doc = os.path.splitext(os.path.basename(f))[0], load(f, {})
        if name == 'news' and doc.get('pulled', '') < (TODAY - dt.timedelta(days=NEWS_DAYS)).isoformat(): continue
        dirs.append({'id': name, 'items': doc.get('items', [])})
    for d in days + dirs:
        for x in d['items']:
            if x.get('u'): used.add(x['u'])
    img = {}
    if not NO_IMAGES:
        have = set(os.listdir(IMG)) if os.path.isdir(IMG) else set()
        img = {u: f for u, f in load(os.path.join(WORK, 'image_map.json'), {}).items() if u in used and f in have}
        for f in have - set(img.values()):
            os.remove(os.path.join(IMG, f))
    os.makedirs(os.path.join(SITE, 'data'), exist_ok=True)
    save(os.path.join(SITE, 'data', 'listings.json'), {'updated': today, 'days': days, 'dir': dirs, 'img': img}, separators=(',', ':'))
    n = sum(len(d['items']) for d in days), sum(len(d['items']) for d in dirs)
    print(f'site data written: {n[0]} events, {n[1]} directory listings, {len(set(img.values()))} images, updated {today}')

if '--data-only' not in sys.argv: refresh()
build_site_data()
