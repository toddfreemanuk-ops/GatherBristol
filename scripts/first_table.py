"""Refresh the First Table offers (50% off the food bill) in source/dir/deals.json.

Usage:  python scripts/first_table.py            rewrite the First Table offers, leave every other promotion alone
        python scripts/first_table.py --dry-run  show what would be written, change nothing
Then run  python scripts/daily_update.py --data-only  to rebuild the file the site reads.

Reads First Table's public restaurant sitemap and each Bristol restaurant page. Keeps restaurants that are
live, offer a First Table and sit inside the map area. If it finds far fewer than last time it stops.
"""
import concurrent.futures as cf, datetime as dt, json, os, re, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEALS = os.path.join(ROOT, 'source', 'dir', 'deals.json')
SITE = 'https://www.firsttable.co.uk'
UA = 'GatherBristolBot/1.0'
DRY = '--dry-run' in sys.argv
MEALS = ['breakfast', 'lunch', 'dinner']

def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'en-GB'})
    return urllib.request.urlopen(req, timeout=40).read().decode('utf-8', 'replace')

def page(url):
    try:
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', get(url), re.S)
        return url, json.loads(m.group(1))['props']['pageProps']['page']
    except Exception as e:
        return url, {'error': str(e)}

def fee_for_two(g):
    """Lowest booking fee for two diners across the sessions, as the page states it (e.g. '£8')."""
    best = None
    for s in g.get('bookingPricesBySession') or []:
        for d in s.get('dinerPrices') or []:
            m = re.match(r'£(\d+(?:\.\d+)?)$', str(d.get('price', '')))
            if d.get('pax') == 2 and m and (best is None or float(m.group(1)) < best[0]):
                best = (float(m.group(1)), d['price'])
    return best[1] if best else ''

def offer(url, g):
    meals = [m for m in MEALS if m in {s.replace('dinner2', 'dinner') for s in g.get('firstTableSessionTypes') or []}]
    when = ' or '.join([', '.join(meals[:-1]), meals[-1]] if len(meals) > 2 else meals) or 'dinner'
    fee = fee_for_two(g)
    note = 'booked through First Table' + (f'; booking fee {fee} for two' if fee else '; a booking fee applies') + '; food only, drinks are full price'
    return {'k': 'first', 'pt': 'food', 't': f'50% off the food bill on the first table at {when}', 'v': g['title'].strip(),
            'll': [round(float(g['lat']), 4), round(float(g['lng']), 4)], 'u': url, 'g': note,
            'w': 'Days vary; pick a date on First Table', 'dow': [], 'wk': True}

urls = sorted({u for u in re.findall(r'<loc>([^<]+)</loc>', get(SITE + '/sitemap-restaurants.xml'))
               if u.startswith(SITE + '/bristol/') and not u.endswith('/menu')})
with cf.ThreadPoolExecutor(4) as ex:
    pages = list(ex.map(page, urls))

new, skipped = [], {}
def skip(why): skipped[why] = skipped.get(why, 0) + 1
for url, g in pages:
    if g.get('error'): skip('could not read'); continue
    if g.get('__typename') != 'Restaurant': skip('not a restaurant page'); continue
    if g.get('status') != 'Live' or not g.get('offersFirstTable') or not g.get('showOnFrontend'): skip('not live'); continue
    try: lat, lng = float(g['lat']), float(g['lng'])
    except (TypeError, ValueError, KeyError): skip('no location'); continue
    if not (51.385 <= lat <= 51.525 and -2.735 <= lng <= -2.495): skip('outside the map'); continue
    new.append(offer(url, g))
new.sort(key=lambda x: x['v'].lower())

doc = json.load(open(DEALS, encoding='utf-8'))
old = [x for x in doc['items'] if 'firsttable.co.uk' in x.get('u', '')]
keep = [x for x in doc['items'] if 'firsttable.co.uk' not in x.get('u', '')]
print(f'First Table: {len(urls)} pages read, {len(new)} offers kept (was {len(old)}), skipped {skipped}; {len(keep)} other promotions untouched')
if len(new) < max(20, len(old) // 2):
    sys.exit('Too few offers found. Leaving deals.json as it is.')
if DRY:
    for x in new[:8]: print(' ', x['v'], '|', x['t'], '|', x['g'])
    sys.exit(0)
doc['items'] = keep + new
if 'First Table' not in doc.get('src', ''): doc['src'] = (doc.get('src', '') + ', First Table').lstrip(', ')
doc['first_table_pulled'] = dt.date.today().isoformat()
with open(DEALS, 'w', encoding='utf-8', newline='\n') as f:
    json.dump(doc, f, ensure_ascii=False, indent=2, sort_keys=True); f.write('\n')
print('deals.json written')
