# GatherBristol

A static what's-on site for Bristol. No accounts, no server: one page that reads one data file.

## What's where

| Folder | What it holds |
|---|---|
| `site/` | Everything that gets published: `index.html`, `data/listings.json`, `img/` |
| `source/days/` | Events by date, plus `ongoing`, `seasonal` and `sport`. Dated files are rewritten by the daily refresh |
| `source/dir/` | Clubs, courses, health & fitness, promotions, volunteering, places and news. Edited by hand |
| `work/` | The scraper's cache (event pages already read, image map) |
| `scripts/` | The daily refresh |
| `.github/workflows/` | Runs the refresh every morning and publishes `site/` to GitHub Pages |

## The daily refresh

`python scripts/daily_update.py` does this:

1. Finds Headfirst Bristol event links for the next 42 days, from its listing pages, its page for each day and every venue page it has seen.
2. Reads each new event page, and re-reads anything in the next 2 days so price and sold-out stay current.
3. Places each event on the map: by a venue already known, by postcode, or by looking the venue name up once on OpenStreetMap (kept in `work/venues_geo.json`; only a single exact-name match in Bristol is used, anything else is left off).
3. Rebuilds the dated files in `source/days/`. Listings from other sources on those dates are kept.
4. Downloads a 400px preview image for each new event.
5. Writes `site/data/listings.json` and deletes images nothing points to.

If it finds fewer than half as many events as last time, it stops and leaves the site as it is.

- `python scripts/daily_update.py --data-only` skips the scrape and only rebuilds the data file. Use it after editing anything in `source/`.
- `NO_IMAGES=1` publishes without scraped images; cards fall back to the coloured posters.
- Needs Python 3.10+ and Pillow (`pip install pillow`).

## Things that are not automatic

- Only Headfirst events refresh. Everything in `source/dir/` and the `ongoing`, `seasonal` and `sport` files is as it was last edited.
- The First Table offers (50% off the food bill) are refreshed by hand: `python scripts/first_table.py`, then `python scripts/daily_update.py --data-only`. It replaces only the First Table entries in `source/dir/deals.json`.
- New groups from the Bristol Social directory are added by hand: `python scripts/bristol_social.py`, then `python scripts/daily_update.py --data-only`. It only adds sessions that `source/dir/clubs.json` does not have.
- News headlines are dropped from the site once `source/dir/news.json` is more than 7 days old (its `pulled` date).
- The contact form posts to FormSubmit, which forwards to the inbox set in `CONTACT` near the end of `site/index.html`.
