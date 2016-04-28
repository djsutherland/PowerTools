from __future__ import print_function
from functools import partial
from itertools import count
import os
import sys
import time

from peewee import fn, IntegrityError
import requests

from ptv_helper.app import db
from ptv_helper.models import Episode, Meta, Show, ShowGenre, ShowTVDB


API_BASE = "https://api.thetvdb.com/"
HEADERS = {
    'User-Agent': 'ptv-updater',
    'Content-Type': 'application/json',
    'Accept': 'application/json',
}

def make_request(method, path, **kwargs):
    headers = kwargs.pop('headers', {})
    for k, v in HEADERS.iteritems():
        headers.setdefault(k, v)
    return getattr(requests, method)(
        '{}{}'.format(API_BASE, path), headers=headers, **kwargs)
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
        try:
            tvdb = ShowTVDB.select(ShowTVDB, Show).join(Show) \
                           .where(ShowTVDB.tvdb_id == tvdb_id).get()
            show = tvdb.show
        except ShowTVDB.DoesNotExist:
            raise ValueError("No show matching tvdb id {}".format(tvdb_id))

        # get basic info
        path = 'series/{}'.format(tvdb_id)
        r = get(path)
        resp = r.json()
        if 'data' not in resp:
            e = resp.get('Error', resp)
            raise ValueError('TVDB error on {}: {}'.format(path, e))
        show_info = resp['data']

        # update meta info
        tvdb.network = show_info['network']
        tvdb.airs_day = show_info['airsDayOfWeek']
        tvdb.airs_time = show_info['airsTime']
        tvdb.runtime = show_info['runtime']
        tvdb.status = show_info['status']
        tvdb.imdb_id = show_info['imdbId']
        tvdb.zaptoit_id = show_info['zap2itId']
        tvdb.overview = show_info['overview']
        tvdb.save()

        # update genres
        genres = show_info['genre'] or ['(none)']
        ShowGenre.insert_many(
            {'show': show, 'seriesid': tvdb_id, 'genre': g} for g in genres
        ).execute()

        # update episodes
        page_num = 1
        while page_num is not None:
            path = 'series/{}/episodes'.format(tvdb_id)
            r = get(path, params={'page': page_num})
            resp = r.json()

            if 'data' in resp:
                Episode.insert_many([
                    {'id': ep['id'],
                     'seasonid': ep['airedSeasonID'],
                     'seriesid': tvdb_id,  # tvdb_id
                     'show': show,
                     'season_number': ep['airedSeason'],
                     'episode_number': ep['airedEpisodeNumber'],
                     'name': ep['episodeName'],
                     'overview': ep['overview'],
                     'first_aired': ep['firstAired'],
                    } for ep in resp['data']
                ]).execute()

                page_num = resp['links']['next']
            else:
                if 'Error' in resp:
                    e = resp['Error']
                    if e.startswith('No results for your query:'):
                        # no known episodes for this series yet; that's okay
                        break
                else:
                    e = resp
                raise ValueError('TVDB error on {}: {}'.format(path, e))



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
    our_shows = {st.tvdb_id for st in ShowTVDB.select(ShowTVDB.tvdb_id)}

    # the shows we have any info for in our db
    in_db = {e.seriesid for e in Episode.select(fn.distinct(Episode.seriesid))}

    # when's the last time we updated?
    try:
        last_time = int(Meta.get(name='episode_update_time').value)
    except Meta.DoesNotExist:
        last_time = 0
    update_time = int(time.time())

    # which shows did we have problems with last time?
    try:
        bad_ids = Meta.get(name='bad_tvdb_ids').value.split(',')
        if bad_ids == ['']:
            bad_ids = []
    except Meta.DoesNotExist:
        bad_ids = []
    bad_ids = set(int(i) for i in bad_ids)

    # which shows have been updated since last_time?
    now = int(time.time())
    if force or now - last_time > 60 * 60 * 24 * 7:
        # API only allows updates within the last week
        updated = our_shows
    else:
        r = get('updated/query', params={'fromTime': last_time - 10})
        assert r.status_code in {200, 404}
        if r.status_code == 404 or r.json()['data'] is None:
            updated = set()
        else:
            updated = {d['id'] for d in r.json()['data']}

    needs_update = ((our_shows & updated)
                  | (our_shows - in_db)
                  | (our_shows & bad_ids))
    bad_ids = update_serieses(needs_update)
    if bad_ids:
        print("Failures on:", sorted(bad_ids), file=sys.stderr)

    with db.atomic():
        try:
            Meta.create(name='episode_update_time', value=update_time) \
                .execute()
        except IntegrityError:
            Meta.update(value=update_time) \
                .where(Meta.name=='episode_update_time') \
                .execute()

        bad_ids_s = ','.join(map(str, sorted(bad_ids)))
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
