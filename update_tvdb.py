from __future__ import print_function

from contextlib import closing
import time

from lxml import etree
from server import connect_db, split_tvdb_ids

UPDATES_URLS = {
    'day': 'http://thetvdb.com/data/updates/updates_day.xml',
    'month': 'http://thetvdb.com/data/updates/updates_month.xml',
    'all': 'http://thetvdb.com/data/updates/updates_all.xml',
}
DATA_URL = 'http://thetvdb.com/data/series/{}/all/en.xml'


def update_episodes(tvdb_id, xml, db):
    db.execute("BEGIN TRANSACTION")
    db.execute("DELETE FROM episodes WHERE seriesid = ?", [tvdb_id])

    # find the showid...
    shows = db.execute(
        "SELECT id, tvdb_ids FROM shows WHERE tvdb_ids LIKE '%' || ? || '%'",
        [tvdb_id]).fetchall()
    showid = next(
        show['id'] for show in shows
        if int(tvdb_id) in split_tvdb_ids(show['tvdb_ids'])
    )

    # TODO: what about genres for shows with multiple tvdb_ids?
    db.execute("DELETE FROM show_genres WHERE showid = ?", [showid])
    genres = xml.find("Series").find("Genre").text
    if genres:
        genres = [g.strip() for g in genres.split('|') if g.strip()]
    if not genres:
        genres = ['(none)']
    db.executemany("INSERT INTO show_genres (showid, genre) VALUES (?, ?)",
                   [(showid, genre) for genre in genres])

    for ep in xml.iterfind("Episode"):
        db.execute('''INSERT INTO episodes
                      (id, seasonid, seriesid, showid, season_number,
                       episode_number, name, overview, first_aired)
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                   [ep.find('id').text,
                    ep.find('seasonid').text,
                    ep.find('seriesid').text,
                    showid,
                    ep.find('SeasonNumber').text,
                    ep.find('EpisodeNumber').text,
                    ep.find('EpisodeName').text,
                    ep.find('Overview').text,
                    ep.find('FirstAired').text])

    db.commit()


def parse_xml(url, max_errors=3, sleep=1):
    if max_errors <= 0:
        raise IOError("repeated failures")

    try:
        return etree.parse(url).getroot()
    except IOError:
        time.sleep(sleep)
        return parse_xml(url, max_errors=max_errors - 1)


def grab_ids(ids):
    print("Getting for {} shows".format(len(ids)))
    bad_ids = set()

    with closing(connect_db()) as db:
        for i, tvdb_id in enumerate(ids):
            print("{}: getting {}".format(i, tvdb_id))

            try:
                result = parse_xml(DATA_URL.format(tvdb_id))
            except (etree.XMLSyntaxError, IOError) as e:
                print("{}: {}".format(tvdb_id, e))
                bad_ids.add(tvdb_id)
            else:
                update_episodes(tvdb_id, result, db)

    return bad_ids


def all_our_tvdb_ids():
    with closing(connect_db()) as db:
        return [tvdb_id for show in db.execute("SELECT tvdb_ids FROM shows")
                        for tvdb_id in split_tvdb_ids(show['tvdb_ids'])]


def update_db(which=None, force=False):
    with closing(connect_db()) as db:
        q = 'SELECT value FROM meta WHERE name = "episode_update_time"'
        times = db.execute(q).fetchall()
        if len(times) == 1:
            last_time = int(times[0]['value'])
        elif len(times) == 0:
            last_time = 0

        q = 'SELECT value FROM meta WHERE name = "bad_tvdb_ids"'
        bad_ids = db.execute(q).fetchall()
        if bad_ids:
            bad_ids = bad_ids[0]['value'].split(',')
            if bad_ids == ['']:
                bad_ids = []
        bad_ids = set(bad_ids)

    our_shows = set(all_our_tvdb_ids())
    with closing(connect_db()) as db:
        in_db = {e['seriesid'] for e in
                 db.execute("SELECT DISTINCT seriesid FROM episodes")}

    now = int(time.time())
    if time is None:
        update_time = now
        updated = our_shows
    else:
        if which is None:
            if now - last_time < 60 * 60 * 18:
                which = 'day'
            elif now - last_time < 60 * 60 * 24 * 28:
                which = 'month'
            else:
                which = 'all'
        url = UPDATES_URLS[which]

        updated_things = parse_xml(url)
        update_time = int(updated_things.attrib['time'])
        updated = {int(s.find('id').text)
                   for s in updated_things.findall('Series')
                   if force or int(s.find('time').text) >= update_time}

    bad_ids = grab_ids((our_shows & updated) | (our_shows - in_db) | bad_ids)

    with closing(connect_db()) as db:
        db.execute('''INSERT OR REPLACE INTO meta (name, value)
                      VALUES ("episode_update_time", ?)''', [update_time])
        db.execute('''INSERT OR REPLACE INTO meta(name, value)
                      VALUES ("bad_tvdb_ids", ?)''', [','.join(bad_ids)])
        db.commit()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('which_updates', default=None, nargs='?',
                        choices=['day', 'month', 'all'])
    parser.add_argument('--force', '-f', action='store_true', default=False)
    args = parser.parse_args()

    update_db(which=args.which_updates, force=args.force)
