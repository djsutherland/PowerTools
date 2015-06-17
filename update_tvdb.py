from __future__ import print_function

import itertools
import os
import sys
import time

from lxml import etree
from peewee import fn, IntegrityError

from ptv_helper.app import db
from ptv_helper.helpers import split_tvdb_ids
from ptv_helper.models import Episode, Meta, Show, ShowGenre


def grouper(iterable, n, fillvalue=None):
    "Collect data into fixed-length chunks or blocks"
    # grouper('ABCDEFG', 3, 'x') --> ABC DEF Gxx
    args = [iter(iterable)] * n
    return itertools.izip_longest(fillvalue=fillvalue, *args)



with open(os.path.join(os.path.dirname(__file__), 'tvdb_api_key')) as f:
    KEY = f.read().strip()
UPDATES_URLS = {
    'day': 'http://thetvdb.com/api/{0}/updates/updates_day.xml'.format(KEY),
    'month': 'http://thetvdb.com/api/{0}/updates/updates_month.xml'.format(KEY),
    'all': 'http://thetvdb.com/api/{0}/updates/updates_all.xml'.format(KEY),
}
DATA_URL = 'http://thetvdb.com/api/{0}/series/{{0}}/all/en.xml'.format(KEY)


def update_episodes(tvdb_id, xml):
    with db.atomic():
        Episode.delete().where(Episode.seriesid == tvdb_id).execute()
        ShowGenre.delete().where(ShowGenre.seriesid == tvdb_id).execute()

        # find the showid...
        show = next(
            show for show
            in Show.select().where(Show.tvdb_ids ** "%{}%".format(tvdb_id))
            if int(tvdb_id) in split_tvdb_ids(show.tvdb_ids))

        genres = xml.find("Series").find("Genre").text
        if genres:
            genres = [g.strip() for g in genres.split('|') if g.strip()]
        if not genres:
            genres = ['(none)']

        ShowGenre.insert_many(
            {'show': show, 'seriesid': tvdb_id, 'genre': g} for g in genres
        ).execute()

        eps = ({'id': ep.find('id').text,
                'seasonid': ep.find('seasonid').text,
                'seriesid': ep.find('seriesid').text,
                'show': show,
                'season_number': ep.find('SeasonNumber').text,
                'episode_number': ep.find('EpisodeNumber').text,
                'name': ep.find('EpisodeName').text,
                'overview': ep.find('Overview').text,
                'first_aired': ep.find('FirstAired').text,
               } for ep in xml.iterfind("Episode"))
        for sub_eps in grouper(eps, 200, fillvalue=None):
            Episode.insert_many([e for e in sub_eps if e is not None]) \
                   .execute()


def parse_xml(url, max_errors=3, sleep=1):
    if max_errors <= 0:
        raise IOError("repeated failures")

    try:
        return etree.parse(url).getroot()
    except IOError as e:
        print(e, file=sys.stderr)
        time.sleep(sleep)
        return parse_xml(url, max_errors=max_errors - 1)


def grab_ids(ids):
    print("Getting for {0} shows".format(len(ids)))
    bad_ids = set()

    for i, tvdb_id in enumerate(ids):
        print("{0}: getting {1}".format(i, tvdb_id))

        try:
            result = parse_xml(DATA_URL.format(tvdb_id))
        except (etree.XMLSyntaxError, IOError) as e:
            print("{0}: {1}".format(tvdb_id, e), file=sys.stderr)
            bad_ids.add(tvdb_id)
        else:
            update_episodes(tvdb_id, result)

    return bad_ids


def update_db(which=None, force=False):
    try:
        last_time = int(Meta.get(name='episode_update_time').value)
    except Meta.DoesNotExist:
        last_time = 0

    try:
        bad_ids = Meta.get(name='bad_tvdb_ids').value.split(',')
        if bad_ids == ['']:
            bad_ids = []
    except Meta.DoesNotExist:
        bad_ids = []
    bad_ids = set(bad_ids)

    our_shows = {tvdb_id for show in Show.select(Show.tvdb_ids)
                         for tvdb_id in split_tvdb_ids(show.tvdb_ids)}
    in_db = set(e.seriesid
                for e in Episode.select(fn.distinct(Episode.seriesid)))

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
        updated = set(int(s.find('id').text)
                      for s in updated_things.findall('Series')
                      if force or int(s.find('time').text) >= update_time)

    bad_ids = grab_ids((our_shows & updated) | (our_shows - in_db) | bad_ids)

    with db.atomic():
        try:
            Meta.create(name='episode_update_time', value=update_time) \
                .execute()
        except IntegrityError:
            Meta.update(value=update_time) \
                .where(Meta.name=='episode_update_time') \
                .execute()

        bad_ids_s = ','.join(map(str, bad_ids))
        try:
            Meta.create(name='bad_tvdb_ids', value=bad_ids_s).execute()
        except IntegrityError:
            Meta.update(value=bad_ids_s).where(Meta.name=='bad_tvdb_ids') \
                .execute()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('which_updates', default=None, nargs='?',
                        choices=['day', 'month', 'all'])
    parser.add_argument('--force', '-f', action='store_true', default=False)
    args = parser.parse_args()

    update_db(which=args.which_updates, force=args.force)
