import json
import time
import traceback
from urllib.parse import parse_qs, urlparse
from itertools import groupby

from flask import (Response, abort, flash, g, redirect, render_template,
                   request, url_for)
from flask_login import login_required
from peewee import JOIN, fn

from ..base import app, db
from ..models import Show, ShowTVDB
from ..tvdb import fill_show_meta, get, get_show_info, update_series


@app.route('/show/<int:show_id>/tvdb/')
@login_required
def edit_tvdb(show_id, errors=None):
    try:
        show = Show.get(Show.id == show_id)
    except Show.DoesNotExist:
        abort(404)

    resp = get('/search/series', params={'name': show.name})
    search = resp.json()
    if resp.ok and 'Error' not in search:
        matches = {m['id']: m for m in search['data']}

        already_matched = []
        for st in ShowTVDB.select().where(ShowTVDB.tvdb_id << list(matches)):
            m = matches.pop(st.tvdb_id)
            if st.show != show:
                already_matched.append((m, st))

        available = matches.values()
    else:
        available = []
        already_matched = []

    return render_template('edit_tvdb.html', show=show, errors=errors,
                           already_matched=already_matched,
                           available=available)


def parse_tvdb_id(url):
    try:
        return int(url)
    except ValueError:
        r = urlparse(url)
        if 'thetvdb.com' not in r.netloc:
            raise ValueError("Expected a thetvdb.com URL")

        path = r.path
        if path.startswith('/eng/'):
            path = path[len('/eng/'):]

        if path.startswith('/series/'):
            slug = path.split('/')[2]
            search = get('/search/series', params={'slug': slug}).json()
            if 'Error' in search:
                msg = "Couldn't find that show: {}".format(search['Error'])
                raise ValueError(msg)
            assert len(search['data']) == 1
            return search['data'][0]['id']
        else:
            qs = parse_qs(r.query)
            if 'tab' in qs and qs['tab'][-1] in {'series', 'seasonall'}:
                return int(qs['id'][-1])
            elif 'seriesid' in qs:
                return int(qs['seriesid'][-1])

        raise ValueError("Can't parse url {!r}".format(url))


@app.route('/show/<int:show_id>/tvdb/add/', methods=['POST'])
@login_required
def add_tvdb(show_id):
    target = url_for('edit_tvdb', show_id=show_id)

    try:
        tvdb_id = parse_tvdb_id(request.form['tvdb-url'])
    except ValueError as e:
        flash(str(e), 'error')
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

    with db.atomic():
        tvdb = ShowTVDB(show=show, tvdb_id=tvdb_id)
        fill_show_meta(tvdb)
        tvdb.save(force_insert=True)

        show.tvdb_not_matched_yet = False
        show.save()

    update_series.delay(tvdb_id).forget()
    return redirect(target)


@app.route('/show/<int:show_id>/tvdb/delete/<int:tvdb_id>',
           methods=['POST', 'DELETE'])
@login_required
def delete_tvdb(show_id, tvdb_id):
    try:
        tvdb = ShowTVDB.get(ShowTVDB.showid == show_id,
                            ShowTVDB.tvdb_id == tvdb_id)
    except ShowTVDB.DoesNotExist:
        abort(404)

    tvdb.delete_instance()

    flash("Removed TVDB '{}' ({})".format(tvdb.name, tvdb_id))
    return redirect(url_for('edit_tvdb', show_id=show_id))


@app.route('/match-tvdb/')
@app.route('/match-tvdb/redo-old/', defaults={'include_notvdb': True},
           endpoint='match_tvdb_redo_old')
@login_required
def match_tvdb(include_notvdb=False):
    matches = []
    errors = []

    # NOTE: if anything has TVDBs set already but also has tvdb_not_matched_yet,
    #       this is going to behave oddly, especially if include_notvdb.
    shows = (Show.select()
                 .where(Show.is_a_tv_show)
                 .where(~Show.hidden).where(Show.deleted_at >> None)
                 .join(ShowTVDB, JOIN.LEFT_OUTER).where(ShowTVDB.show >> None))
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
@login_required
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
                        if str(e).endswith('Resource not found'):
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
                            errors.append((show, tvdb_id, info,
                                           "Error: {}".format(e)))
                    else:
                        tvdbs.append((tvdb_id, info))
            else:
                msg = "TVDB entry already associated with {}"
                errors.append((show, tvdb_id, {'slug': show_tvdb.slug},
                               msg.format(show_tvdb.show.name)))

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
                    errors.append((show, v, {}, str(e)))
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
@login_required
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
                        st = ShowTVDB(show=show, tvdb_id=tvdb_id)
                        fill_show_meta(st)
                        st.save()
                    except Exception:
                        errors.append((show, tvdb_id, traceback.format_exc()))
                    else:
                        update_series.delay(tvdb_id).forget()
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
