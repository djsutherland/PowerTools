from __future__ import unicode_literals
import re
import json
import time
import traceback
from itertools import groupby

from flask import (Response, abort, flash, g, redirect, render_template,
                   request, url_for)
from peewee import JOIN, fn
from six.moves.urllib.parse import parse_qs, urlparse

from ..app import app
from ..models import Episode, Show, ShowGenre, ShowTVDB
from ..tvdb import fill_show_meta, get, get_show_info


@app.route('/show/<int:show_id>/tvdb/')
def edit_tvdb(show_id, errors=None):
    try:
        show = Show.get(Show.id == show_id)
    except Show.DoesNotExist:
        abort(404)

    return render_template('edit_tvdb.html', show=show, errors=errors)


ep_regex = re.compile('/series/[^/]+/episodes/(\d+)/?$')


def parse_tvdb_id(url):
    try:
        return int(url)
    except ValueError:
        r = urlparse(url)
        if 'thetvdb.com' not in r.netloc:
            raise ValueError("Expected a thetvdb.com URL")

        m = ep_regex.match(r.path)
        if m:
            ep_id = m.group(1)
            r = get('/episodes/{}'.format(ep_id)).json()
            try:
                return int(r['data']['seriesId'])
            except KeyError:
                return ValueError("TVDB api was confused. {}".format(
                    r.get('errors', '')))
        elif r.path.startswith('/series/'):
            raise ValueError("The new TVDB site doesn't quite work right for "
                             "our purposes; please put in an *epsiode* URL "
                             "and it'll work.")
        else:
            qs = parse_qs(r.query)
            if 'tab' in qs and qs['tab'][-1] in {'series', 'seasonall'}:
                return int(qs['id'][-1])
            elif 'seriesid' in qs:
                return int(qs['seriesid'][-1])

        raise ValueError("Can't parse url {!r}".format(url))


@app.route('/show/<int:show_id>/tvdb/add/', methods=['POST'])
def add_tvdb(show_id):
    target = url_for('edit_tvdb', show_id=show_id)

    try:
        tvdb_id = parse_tvdb_id(request.form['tvdb-url'])
    except ValueError as e:
        flash(e.message, 'error')
        return redirect(target)

    try:
        st = ShowTVDB.get(ShowTVDB.tvdb_id == tvdb_id)
    except ShowTVDB.DoesNotExist:
        pass
    else:
        if st.showid != show_id:
            flash("TVDB {} ('{}') already used for show {}".format(
                tvdb_id, st.name, st.show.name), 'error')
        return redirect(target)

    try:
        show = Show.get(Show.id == show_id)
    except Show.DoesNotExist:
        abort(404)

    tvdb = ShowTVDB(show=show, tvdb_id=tvdb_id)
    fill_show_meta(tvdb)
    tvdb.save()

    show.tvdb_not_matched_yet = False
    show.save()
    return redirect(target)


@app.route('/show/<int:show_id>/tvdb/delete/<int:tvdb_id>',
           methods=['POST', 'DELETE'])
def delete_tvdb(show_id, tvdb_id):
    try:
        tvdb = ShowTVDB.get(ShowTVDB.showid == show_id,
                            ShowTVDB.tvdb_id == tvdb_id)
    except ShowTVDB.DoesNotExist:
        abort(404)

    with g.db.atomic():
        tvdb.delete_instance()
        # TODO: turn these into foreign keys with cascading deletes
        ShowGenre.delete().where(ShowGenre.seriesid == tvdb_id).execute()
        Episode.delete().where(Episode.seriesid == tvdb_id).execute()

    flash("Removed TVDB '{}' ({})".format(tvdb.name, tvdb_id))
    return redirect(url_for('edit_tvdb', show_id=show_id))


@app.route('/match-tvdb/')
@app.route('/match-tvdb/redo-old/', defaults={'include_notvdb': True},
           endpoint='match_tvdb_redo_old')
def match_tvdb(include_notvdb=False):
    matches = []
    errors = []

    # NOTE: if anything has TVDBs set already but also has tvdb_not_matched_yet,
    #       this is going to behave oddly, especially if include_notvdb.
    shows = Show.select().where(Show.is_a_tv_show) \
                .join(ShowTVDB, JOIN.LEFT_OUTER) \
                .where(ShowTVDB.show >> None)
    if not include_notvdb:
        shows = shows.where(Show.tvdb_not_matched_yet)
    shows = shows.order_by(fn.lower(Show.name).asc())

    for show in shows:
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
                    seen_tvdb_ids[tvdb_id] = show
                    try:
                        info = get_show_info(tvdb_id)
                    except ValueError as e:
                        if e.message.endswith('Resource not found'):
                            # try again once more, since this just happens
                            # all the time for seemingly no reason
                            try:
                                time.sleep(.2)
                                info = get_show_info(tvdb_id)
                            except ValueError as e:
                                errors.append((show, tvdb_id,
                                               "Error: {}".format(e)))
                            else:
                                tvdbs.append((tvdb_id, info))
                        else:
                            errors.append((show, tvdb_id,
                                           "Error: {}".format(e)))
                    else:
                        tvdbs.append((tvdb_id, info))
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
                        add_tvdb(parse_tvdb_id(thing))
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
        changes=sorted(changes), non_shows=sorted(non_shows),
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
                errors.append((show, tvdb_ids, traceback.format_exc()))
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

    if errors:
        resp = render_template('match_tvdb_execute.html', errors=errors)
        return Response(resp, status=500)
    else:
        return redirect(url_for('match_tvdb'))
