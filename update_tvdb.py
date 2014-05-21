from __future__ import print_function

from contextlib import closing
import os
import time
import urllib

from lxml import etree
from server import connect_db, split_tvdb_ids

UPDATES_DAY_URL = 'http://thetvdb.com/data/updates/updates_day.xml'
UPDATES_MONTH_URL = 'http://thetvdb.com/data/updates/updates_month.xml'
UPDATES_ALL_URL = 'http://thetvdb.com/data/updates/updates_all.xml'
DATA_URL = 'http://thetvdb.com/data/series/{}/all/en.xml'


def get_current_time():
    # silliness, but why not
    doc = etree.parse(TIME_URL)
    return doc.getroot().find('Time').text


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

    with closing(connect_db()) as db:
        for i, tvdb_id in enumerate(ids):
            print("{}: getting {}".format(i, tvdb_id))

            try:
                result = parse_xml(DATA_URL.format(tvdb_id))
            except (etree.XMLSyntaxError, IOError) as e:
                print("{}: {}".format(tvdb_id, e))
            else:
                update_episodes(tvdb_id, result, db)


def all_our_tvdb_ids():
    with closing(connect_db()) as db:
        return [tvdb_id for show in db.execute("SELECT tvdb_ids FROM shows")
                        for tvdb_id in split_tvdb_ids(show['tvdb_ids'])]


def update_db():
    with closing(connect_db()) as db:
        q = 'SELECT value FROM meta WHERE name = "episode_update_time"'
        times = db.execute(q).fetchall()
        if len(times) == 1:
            last_time = int(times[0]['value'])
        elif len(times) == 0:
            last_time = None
        else:
            raise ValueError("db corrupted")

    our_shows = set(all_our_tvdb_ids())
    with closing(connect_db()) as db:
        in_db = {e['seriesid'] for e in
                 db.execute("SELECT DISTINCT seriesid FROM episodes")}

    now = int(time.time())
    if time is None:
        update_time = now
        updated = our_shows
    else:
        if now - last_time < 60 * 60 * 18:
            url = UPDATES_DAY_URL
        elif now - last_time < 60 * 60 * 24 * 28:
            url = UPDATES_MONTH_URL
        else:
            url = UPDATES_ALL_URL

        updated_things = parse_xml(url)
        update_time = int(updated_things.attrib['time'])
        updated = {int(s.find('id').text)
                   for s in updated_things.findall('Series')
                   if int(s.find('time').text) >= update_time}

    grab_ids((our_shows & updated) | (our_shows - in_db))

    with closing(connect_db()) as db:
        db.execute('''INSERT OR REPLACE INTO meta (name, value)
                      VALUES ("episode_update_time", ?)''',
                   [update_time])
        db.commit()


if __name__ == '__main__':
    update_db()