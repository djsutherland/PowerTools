from __future__ import print_function
from functools import partial
from itertools import count
import os
import time

import requests

from ptv_helper.app import db
from ptv_helper.helpers import split_tvdb_ids
from ptv_helper.models import Episode, Meta, Show, ShowGenre


API_BASE = "https://api-beta.thetvdb.com/"
HEADERS = {'User-Agent': 'Awesome PTV Updater Script'}

def make_request(method, path, **kwargs):
    headers = HEADERS.copy()
    headers.update(kwargs.pop('headers', {}))
    return getattr(requests, method)(
        '{}{}'.format(API_BASE, method), headers=headers, **kwargs)
get = partial(make_request, 'get')
head = partial(make_request, 'head')
post = partial(make_request, 'post')


def authenticate():
    with open(os.path.join(os.path.dirname(__file__), 'tvdb_api_key')) as f:
        KEY = f.read().strip()
    r = post('login', json={'apikey': KEY})
    assert r.status_code == 200
    HEADERS['Authorization'] = 'Bearer ' + r.json()['token']


def update_series(tvdb_id):
    with db.atomic():
        # delete old info that we'll replace
        Episode.delete().where(Episode.seriesid == tvdb_id).execute()
        ShowGenre.delete().where(ShowGenre.seriesid == tvdb_id).execute()

        # find the showid...
        show = next(
            show for show
            in Show.select().where(Show.tvdb_ids ** "%{}%".format(tvdb_id))
            if int(tvdb_id) in split_tvdb_ids(show.tvdb_ids))

        # get basic info
        r = get('series/{}'.format(tvdb_id))
        show_info = r.json()['data']

        # update genres
        genres = show_info['genre'] or ['(none)']
        ShowGenre.insert_many(
            {'show': show, 'seriesid': tvdb_id, 'genre': g} for g in genres
        ).execute()

        # update episodes
        page_num = 1
        while page_num is not None:
            r = get('series/{}/episodes'.format(tvdb_id),
                    params={'page': page_num})

            Episode.insert_many([
                {'id': ep['id'],
                 'seasonid': None,  # seems not to be available...
                 'seriesid': tvdb_id,  # tvdb_id
                 'show': show,
                 'season_number': ep['airedSeason'],
                 'episode_number': ep['airedEpisodeNumber'],
                 'name': ep['episodeName'],
                 'overview': ep['overview'],
                 'first_aired': ep['firstAired'],
                } for ep in r.json()['data']
            ]).execute()

            page_num = r.json()['links']['next']


def update_serieses(ids):
    print("Getting for {0} shows".format(len(ids)))
    bad_ids = set()

    for i, tvdb_id in enumerate(ids):
        print("{0}: getting {1}".format(i, tvdb_id))

        try:
            update_series(tvdb_id)
        except (ValueError, requests.exceptions.HTTPError) as e:
            print("{0}: {1}".format(tvdb_id, e), file=sys.stderr)
            bad_ids.add(tvdb_id)

    return bad_ids


def update_db(force=False):
    # all of the tvdb series we care about
    our_shows = {tvdb_id for show in Show.select(Show.tvdb_ids)
                         for tvdb_id in split_tvdb_ids(show.tvdb_ids)}

    # the shows we have any info for in our db
    in_db = {e.seriesid for e in Episode.select(fn.distinct(Episode.seriesid))}

    # when's the last time we updated?
    try:
        last_time = int(Meta.get(name='episode_update_time').value)
    except Meta.DoesNotExist:
        last_time = 0

    # which shows did we have problems with last time?
    try:
        bad_ids = Meta.get(name='bad_tvdb_ids').value.split(',')
        if bad_ids == ['']:
            bad_ids = []
    except Meta.DoesNotExist:
        bad_ids = []
    bad_ids = set(bad_ids)

    # which shows have been updated since last_time?
    now = int(time.time())
    if force or now - last_time > 60 * 60 * 24 * 7:
        # API only allows updates within the last week
        updated = our_shows
    else:
        r = get('updated/query', params={'fromTime': last_time - 10})
        assert r.status_code in {200, 404}
        if r.status_code == 404 or r.json()['data'] is None:
            dt = datetime.datetime.fromtimestamp(last_time)
            updated = set()
        else:
            updated = {d['id'] for d in r.json()['data']}

    needs_update = (our_shows & updated) | (our_shows - in_db) | bad_ids
    bad_ids = update_serieses(needs_update)

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
    parser.add_argument('--force', '-f', action='store_true', default=False)
    args = parser.parse_args()

    authenticate()
    update_db(**vars(args))
