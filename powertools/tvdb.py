from __future__ import unicode_literals
import datetime
import json
import logging
import os
import time
from functools import partial

from cachecontrol import CacheControl
from cachecontrol.caches import FileCache
from flask import g
from peewee import fn
import requests
from six import iteritems

from .base import app, celery, db
from .models import Episode, Meta, Show, ShowGenre, ShowTVDB

logger = logging.getLogger('powertools')

API_BASE = "https://api.thetvdb.com/"
HEADERS = {
    'User-Agent': 'powertools-updater',
    'Content-Type': 'application/json',
    'Accept': 'application/json',
}


class TVDBError(Exception):
    pass


class TVDBKeyError(KeyError, TVDBError):
    pass


class TVDBResponseError(ValueError, TVDBError):
    pass


def _make_request(method, path, **kwargs):
    if 'cache_sess' not in g:
        if os.path.exists('/dev/shm/'):
            pth = '/dev/shm/{}/web_cache'.format(os.getuid())
        else:
            pth = os.path.expanduser('~/.web_cache')
        g.cache_sess = CacheControl(requests.session(), FileCache(pth))

    headers = kwargs.pop('headers', {})
    for k, v in iteritems(HEADERS):
        headers.setdefault(k, v)
    return getattr(g.cache_sess, method)(
        '{}{}'.format(API_BASE, path), headers=headers, **kwargs)


def authenticate():
    r = _make_request(
        'post', 'login', json={'apikey': app.config['TVDB_API_KEY']})
    assert r.status_code == 200, r.status_code
    HEADERS['Authorization'] = 'Bearer ' + r.json()['token']


def make_request(method, path, authenticate_if_error=True, **kwargs):
    resp = _make_request(method, path, **kwargs)
    if resp.status_code == 401 and authenticate_if_error:
        authenticate()
        resp = _make_request(method, path, **kwargs)
    return resp


get = partial(make_request, 'get')
head = partial(make_request, 'head')
post = partial(make_request, 'post')


def get_show_info(tvdb_id):
    path = 'series/{}'.format(tvdb_id)
    r = get(path)

    try:
        resp = r.json()
    except json.decoder.JSONDecodeError as e:
        if e.msg == "Expecting value" and e.lineno == 1 and e.pos == 0:
            msg = "TVDB returned no content for {}".format(tvdb_id)
            raise TVDBResponseError(msg)
        else:
            raise

    if not r.ok or 'data' not in resp:
        e = resp.get('Error', resp)
        if str(e).strip() == 'ID: {} not found'.format(tvdb_id):
            raise TVDBKeyError("TVDB id {} not found".format(tvdb_id))
        else:
            raise TVDBResponseError('TVDB error on {}: {}'.format(path, e))
    return resp['data']


################################################################################
### Update the database with new episodes / genres / etc

def fill_show_meta(tvdb):
    show_info = get_show_info(tvdb.tvdb_id)
    tvdb.name = show_info['seriesName'] or '(???)'
    tvdb.aliases = json.dumps(show_info['aliases'])
    tvdb.first_aired = show_info['firstAired'] or None
    tvdb.network = show_info['network']
    tvdb.airs_day = show_info['airsDayOfWeek']
    tvdb.airs_time = show_info['airsTime']
    tvdb.runtime = show_info['runtime']
    tvdb.status = show_info['status']
    tvdb.imdb_id = show_info['imdbId']
    tvdb.zaptoit_id = show_info['zap2itId']
    tvdb.overview = show_info['overview'] or ''
    tvdb.slug = show_info['slug']
    return show_info


@celery.task
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

        # update meta info; don't save until the end
        show_info = fill_show_meta(tvdb)

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

            try:
                resp = r.json()
            except json.decoder.JSONDecodeError as e:
                if e.msg == "Expecting value" and e.lineno == 1 and e.pos == 0:
                    msg = "TVDB returned no content for {}?page={}"
                    raise TVDBResponseError(msg.format(path, page_num))
                else:
                    raise

            if 'data' in resp:
                Episode.insert_many([{
                    'epid': ep['id'],
                    'seasonid': ep['airedSeasonID'],
                    'seriesid': tvdb_id,  # tvdb_id
                    'show': show,
                    'season_number': ep['airedSeason'] or '',
                    'episode_number': ep['airedEpisodeNumber'],
                    'name': ep['episodeName'],
                    'overview': ep['overview'],
                    'first_aired': (
                        None
                        if (not ep['firstAired'] or ep['firstAired'].startswith('0000'))
                        else ep['firstAired']
                    ),
                } for ep in resp['data']]).execute()

                page_num = resp['links']['next']
            else:
                if 'Error' in resp:
                    e = resp['Error']
                    if e.startswith('No results for your query:'):
                        # no known episodes for this series yet; that's okay
                        break
                else:
                    e = resp
                raise TVDBResponseError('TVDB error on {}: {}'.format(path, e))

        # mark on the ShowTVDB that it's been synced
        tvdb.last_synced = datetime.datetime.utcnow()
        tvdb.save()


@celery.task
def update_serieses(ids, verbose=False):
    if verbose:
        from tqdm import tqdm
        ids = tqdm(ids)
    bad_ids = set()
    not_found_ids = set()

    for i, tvdb_id in enumerate(ids, 1):
        try:
            update_series(tvdb_id)
        except (TVDBResponseError, requests.exceptions.HTTPError) as e:
            logger.error("{}: {}".format(tvdb_id, e))
            bad_ids.add(tvdb_id)
            ShowTVDB.update(last_synced='1970-01-01') \
                    .where(ShowTVDB.tvdb_id == tvdb_id).execute()
        except TVDBKeyError:
            not_found_ids.add(tvdb_id)

    return bad_ids, not_found_ids


def update_db(force=False, verbose=False):
    if force:
        needs_update = {st.tvdb_id for st in ShowTVDB.select(ShowTVDB.tvdb_id)}
    else:
        # MySQL (or peewee at least) doesn't have proper TZ support.
        # everything here is a "naive" datetime in UTC
        needs_update = set()
        recently_updated = set()

        # sort ShowTVDBs into ones updated in the last week, or not
        # also track last update time for ones updated within last week
        # (so fresh entries don't "invalidate" everything)
        now = datetime.datetime.utcnow()
        long_ago = now - datetime.timedelta(days=7)
        last_update = now
        for st in ShowTVDB.select(ShowTVDB.tvdb_id, ShowTVDB.last_synced):
            t = st.last_synced
            if t < long_ago:
                needs_update.add(st.tvdb_id)
            else:
                recently_updated.add(st.tvdb_id)
                if t < last_update:
                    last_update = t

        # what's been updated since last check?
        if recently_updated:
            last_time = last_update.replace(tzinfo=datetime.timezone.utc).timestamp()
            r = get('updated/query', params={'fromTime': last_time - 10})

            if r.status_code not in {200, 404}:
                msg = "Response code {}: {}".format(r.status_code, r.content)
                raise TVDBResponseError(msg)

            # 404 just means no updates
            if r.status_code == 200:
                resp = r.json()
                if 'data' in resp and resp['data'] is not None:
                    new = {d['id'] for d in r.json()['data']}
                    needs_update |= new
                    recently_updated -= new

        # stuff that hasn't changed since the last time we touched it
        # doesn't need anything
        ShowTVDB.update(last_synced=now) \
                .where(ShowTVDB.tvdb_id.in_(recently_updated)) \
                .execute()

    bad_ids, not_found_ids = update_serieses(needs_update, verbose=verbose)
    if verbose and (bad_ids or not_found_ids):
        logger.error("TVDB failures on:", sorted(bad_ids | not_found_ids))

    if len(not_found_ids) < 10:
        for dead_id in not_found_ids:
            with db.atomic():
                st = ShowTVDB.get(ShowTVDB.tvdb_id == dead_id)
                s = st.show
                other_ids = s.tvdb_ids.count() - 1
                logger.warning(
                    "{}: deleting bad tvdb id {} ({} others)".format(
                        s, dead_id, other_ids))
                st.delete_instance()
                Episode.delete().where(Episode.seriesid == dead_id).execute()
                if not other_ids:
                    s.tvdb_not_matched_yet = True
                    s.save()

    for h in logger.handlers:
        h.flush()
