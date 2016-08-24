from __future__ import unicode_literals
import json
from itertools import groupby
import traceback
from urlparse import parse_qs, urlparse

from flask import g, render_template, request, Response
from peewee import fn

from ..app import app
from ..models import Show, ShowTVDB
from ..tvdb import get, get_show_info


@app.route('/match-tvdb/')
def match_tvdb():
    matches = []
    errors = []

    for show in (Show.select().where(Show.tvdb_not_matched_yet)
                     .order_by(fn.lower(Show.name).asc())):

        resp = get('/search/series', params={'name': show.name})
        if resp.status_code == 404:
            matches.append((show, []))
        elif not resp.ok:
            errors.append((show, resp))
        else:
            matches.append((show, resp.json()['data']))

    return render_template('match_tvdb.html', matches=matches, errors=errors)


@app.route('/match-tvdb/confirm/', methods=['POST'])
def confirm_match_tvdb():
    s = []

    seen_tvdb_ids = {}
    changes = []
    leave_alone = []
    non_shows = []
    errors = []

    for show_id, pairs in groupby(sorted(request.form.items()),
                                  key=lambda kv: int(kv[0][:kv[0].index('-')])):
        show = Show.get(Show.id == show_id)
        skip_show = True
        non_show = False
        tvdbs = []

        def add_tvdb(tvdb_id):
            try:
                show_tvdb = ShowTVDB.get(tvdb_id=tvdb_id)
            except ShowTVDB.DoesNotExist:
                if tvdb_id in seen_tvdb_ids:
                    msg = "You also wanted to associate this entry with {}"
                    s = seen_tvdb_ids[tvdb_id]
                    errors.append((show, tvdb_id, msg.format(s.name)))
                else:
                    info = get_show_info(tvdb_id)
                    tvdbs.append((tvdb_id, info))
                    seen_tvdb_ids[tvdb_id] = show
            else:
                msg = "TVDB entry already associated with {}"
                errors.append((show, tvdb_id, msg.format(show_tvdb.show.name)))
                    

        for k, v in pairs:
            if not v:
                continue

            skip_show = False
            if k.endswith('-none'):
                pass
            elif k.endswith('-notashow'):
                non_show = True
            elif k.endswith('-manual'):
                try:
                    for thing in v.split(','):
                        thing = thing.strip()
                        if not thing:
                            continue
                        if 'thetvdb.com' in thing:
                            qs = parse_qs(urlparse(thing).query)
                            if qs['tab'] == ['series']:
                                thing = qs['id'][-1]
                            elif 'seriesid' in qs:
                                thing = qs['seriesid'][-1]
                            else:
                                msg = "Can't parse url {!r}"
                                raise ValueError(msg.format(thing))
                        add_tvdb(int(thing))
                except (ValueError, KeyError) as e:
                    errors.append((show, v, e.message))
            else:
                add_tvdb(int(k[k.index('-') + 1:]))

        if skip_show:
            leave_alone.append(show)
        elif non_show:
            non_shows.append(show)
        else:
            changes.append((show, tvdbs))

    changes_json = [
        (show.id, [i for i, info in tvdbs]) for show, tvdbs in changes]
    non_shows_json = [show.id for show in non_shows]

    return render_template(
        'match_tvdb_confirm.html',
        errors=sorted(errors), leave_alone=sorted(leave_alone),
        changes=sorted(changes), non_show=sorted(non_shows),
        changes_json=sorted(changes_json),
        non_shows_json=sorted(non_shows_json))


@app.route('/match-tvdb/execute/', methods=['POST'])
def match_tvdb_execute():
    changes = json.loads(request.form.get('changes', '[]'))
    non_shows = json.loads(request.form.get('non_shows', '[]'))

    errors = []

    for show_id, tvdb_ids in changes:
        with g.db.atomic():
            try:
                show = Show.get(id=show_id)
            except Exception:
                errors.append((show, tvdb_id, traceback.format_exc()))
            else:
                for tvdb_id in tvdb_ids:
                    try:
                        ShowTVDB(show=show, tvdb_id=tvdb_id).save()
                    except Exception:
                        errors.append((show, tvdb_id, traceback.format_exc()))
            show.tvdb_not_matched_yet = False
            show.save()

    for show_id in non_shows:
        with g.db.atomic():
            try:
                show = Show.get(id=show_id)
                show.is_a_tv_show = False
                show.tvdb_not_matched_yet = False
                show.save()
            except Exception:
                errors.append((show, None, traceback.format_exc()))

    resp = render_template('match_tvdb_execute.html', errors=errors)
    return Response(resp, status=(500 if errors else 200))
