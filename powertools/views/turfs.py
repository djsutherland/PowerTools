from __future__ import unicode_literals
import datetime
from collections import namedtuple
from itertools import groupby

from flask import Response, abort, g, jsonify, redirect, render_template, \
                  request, url_for
from flask_login import current_user, login_required
from peewee import IntegrityError, NodeList, SQL, fn, prefetch
from six import itervalues, text_type

from ..base import app
from ..helpers import strip_the
from ..models import Mod, Show, ShowTVDB, Turf, \
                     TURF_LOOKUP, TURF_STATES, TURF_ORDER, PUBLIC_TURF_LOOKUP


@app.route('/show/<int:show_id>/')
@login_required
def show(show_id):
    try:
        show = Show.get(Show.id == show_id)
    except Show.DoesNotExist:
        abort(404)

    return render_template(
        'show.html', show=show, Turf=Turf,
        TURF_LOOKUP=TURF_LOOKUP, PUBLIC_TURF_LOOKUP=PUBLIC_TURF_LOOKUP)


@app.route('/show/<int:show_id>/edit/', methods=['POST'])
def show_edit_turf(show_id):
    if not current_user.is_authenticated:
        return abort(401)
    try:
        show = Show.get(Show.id == show_id)
        mod = Mod.get(Mod.id == current_user.id)
    except (Show.DoesNotExist, Mod.DoesNotExist):
        abort(404)

    val = request.form.get('val')
    comments = request.form.get('comments')

    with g.db.atomic():
        if not val:
            try:
                t = Turf.get(show=show, mod=mod)
                t.delete_instance()
            except Turf.DoesNotExist:
                pass
        elif val not in TURF_STATES:
            raise abort(403)
        else:
            try:
                Turf.insert(show=show, mod=mod,
                            state=val, comments=comments).execute()
            except IntegrityError:
                turf = Turf.get(show=show, mod=mod)
                turf.state = val
                turf.comments = comments
                turf.save()

    return redirect(url_for('show', show_id=show_id))


@app.route('/show/<int:show_id>/edit-needs-help/', methods=['POST'])
def show_edit_needs_help(show_id):
    if not current_user.is_authenticated:
        return abort(401)

    val = request.form.get('needs-help', 'off') == 'on'

    r = Show.update(needs_help=val).where(Show.id == show_id).execute()
    if r in {0, 1}:
        return redirect(url_for('show', show_id=show_id))
    else:
        m = "something weird happened in show_edit_needs_help...{}, {}, {}"
        raise ValueError(m.format(show_id, val, r))


@app.route('/topic/<int:forums_id>-<rest>/')
@app.route('/forum/<int:forums_id>-<rest>/')
def show_redirect(forums_id, rest=None):
    try:
        show = Show.get(Show.forum_id == forums_id)
    except Show.DoesNotExist:
        abort(404)
    return redirect(url_for('show', show_id=show.id))


@app.route('/search/')
def show_search():
    q = request.args.get('q')
    matches = Show.select().where(Show.name ** '%{}%'.format(q)).order_by(Show.name)
    if len(matches) == 1:
        return redirect(url_for('show', show_id=matches[0].id))
    return render_template('search.html', query=q, matches=matches)


################################################################################
### Main turfs page

ModInfo = namedtuple('ModInfo', ['modname', 'state', 'comments'])
MyInfo = namedtuple('MyInfo', ['state', 'comments'])


@app.route('/turfs/')
@login_required
def mod_turfs():
    if hasattr(current_user, 'id'):
        modid = int(current_user.id)
    else:
        modid = None
    one_year_ago = datetime.datetime.now() - datetime.timedelta(days=365)

    turfs_with_stuff = prefetch(
        Turf.select(), Show.select(), Mod.select(), ShowTVDB.select())

    show_info = {
        s.id: (s, {
            'n_mods': 0, 'mod_info': [], 'my_info': MyInfo(None, None),
            'in_last_year': (
                s.last_post is not None and s.last_post >= one_year_ago)
        }) for s in Show.select().where(~Show.hidden)
                                 .where(Show.deleted_at.is_null(True))
    }

    turfs_that_count = {TURF_LOOKUP['lead'], TURF_LOOKUP['backup']}

    for turf in turfs_with_stuff:
        show = turf.show
        if show.hidden or show.deleted_at is not None:
            continue
        _, show_inf = show_info[show.id]

        if turf.modid == modid:
            show_inf['my_info'] = MyInfo(turf.state, turf.comments)

        show_inf['mod_info'].append(ModInfo(
            turf.mod.name,
            turf.state,
            turf.comments,
        ))

        if turf.state in turfs_that_count:
            show_inf['n_mods'] += 1

    def get_name(show_and_info):
        return strip_the(show_and_info[0].name).lower()

    show_info = sorted(itervalues(show_info), key=get_name)
    for show_id, info in show_info:
        info['mod_info'] = sorted(
            info['mod_info'],
            key=lambda info: (TURF_ORDER.find(info.state), info.modname.lower()))

    niceify = lambda c: c if c.isalpha() else '#'
    firsts = [
        (letter, next(iter(letter_show_infos))[0].id)
        for letter, letter_show_infos
        in groupby(show_info, key=lambda s: niceify(get_name(s)[0]))]

    n_postses = sorted(show.n_posts() for show, info in show_info
                       if show.n_posts() != 'n/a')
    hi_post_thresh = n_postses[int(len(n_postses) * .9)]

    return render_template(
        'mod_turfs.html',
        shows=show_info, mods=Mod.select(), hi_post_thresh=hi_post_thresh,
        now=datetime.datetime.now(), firsts=firsts,
        TURF_LOOKUP=TURF_LOOKUP)


@login_required
def update_show(attr, bool_val=False):
    showid = request.form.get('showid', type=int)
    val = request.form.get('val')
    if bool_val:
        val = {'true': 1, 'false': 0}.get(val, None)
    if val is None:
        return abort(400)

    try:
        with g.db.atomic():
            show = Show.get(id=showid)
            setattr(show, attr, val)
            show.save(only=[getattr(Show, attr)])

            return jsonify(curr=val)
    except Show.DoesNotExist:
        return abort(404)


@app.route('/_mark_needs_help/', methods=['POST'])
def _mark_needs_help():
    return update_show('needs_help', bool_val=True)


@app.route('/_mark_territory/', methods=['POST'])
def _mark_territory():
    if not current_user.is_authenticated:
        return abort(401)
    modid = current_user.id
    showid = request.form.get('showid', type=int)
    val = request.form.get('val')
    comments = request.form.get('comments')
    hi_post_thresh = request.form.get('hi_post_thresh', type=int)
    parity = 'odd' if request.form.get('is_odd', type=int) else 'even'

    try:
        show = Show.get(id=showid)
        mod = Mod.get(id=modid)
    except (Show.DoesNotExist, Mod.DoesNotExist):
        raise abort(404)

    modname = mod.name

    with g.db.atomic():
        if not val:
            try:
                t = Turf.get(show=show, mod=mod)
                t.delete_instance()
            except Turf.DoesNotExist:
                pass
        elif val not in TURF_STATES:
            raise abort(403)
        else:
            try:
                Turf.insert(show=show, mod=mod,
                            state=val, comments=comments).execute()
            except IntegrityError:
                turf = Turf.get(show=show, mod=mod)
                turf.state = val
                turf.comments = comments
                turf.save()

    year_ago = datetime.datetime.now() - datetime.timedelta(days=365)
    info = {
        'my_info': [val, comments],
        'n_posts': show.n_posts(),
        'in_last_year': (
            show.last_post is not None and show.last_post >= year_ago),
    }
    info['mod_info'] = sorted(
        (ModInfo(turf.mod.name, turf.state, turf.comments)
         for turf in Show.get(id=showid).turf_set),
        key=lambda modinf: (-'nwcg'.find(modinf.state), modinf.modname.lower())
    )
    info['n_mods'] = sum(
        1 for modinf in info['mod_info']
        if modinf.state in {TURF_LOOKUP['lead'], TURF_LOOKUP['backup']})

    return render_template(
        "turf_row.html", show=show, info=info, modid=modid, modname=modname,
        hi_post_thresh=hi_post_thresh, parity=parity,
        TURF_LOOKUP=TURF_LOOKUP)


################################################################################
### Turfs CSV dump

turfs_query = Show.select(
    Show,
    Turf
    .select(fn.count(SQL('*')))
    .where((Turf.state == TURF_LOOKUP['lead']) & (Turf.show == Show.id))
    .alias('leadcount'),
    Turf
    .select(fn.count(SQL('*')))
    .where((Turf.state == TURF_LOOKUP['backup']) & (Turf.show == Show.id))
    .alias('helpercount'),
    Turf
    .select(fn.group_concat(NodeList((Mod.name, SQL("SEPARATOR ', '")))))
    .join(Mod)
    .where((Turf.show == Show.id) & (Turf.state == TURF_LOOKUP['lead']))
    .alias('leads'),
    Turf
    .select(fn.group_concat(NodeList((Mod.name, SQL("SEPARATOR ', '")))))
    .join(Mod)
    .where((Turf.show == Show.id) & (Turf.state == TURF_LOOKUP['backup']))
    .alias('backups'),
    Turf
    .select(fn.group_concat(NodeList((Mod.name, SQL("SEPARATOR ', '")))))
    .join(Mod)
    .where((Turf.show == Show.id) & (Turf.state == TURF_LOOKUP['could help']))
    .alias('couldhelps'),
).where(~Show.hidden).where(Show.deleted_at.is_null(True)) \
 .order_by(fn.Lower(Show.name).asc())
# NOTE: group_concat works only in sqlite or mysql


def _query_to_csv(query):
    def generate():
        yield ("name,posts,last_post,gone_forever,has_forum,"
               "leadcount,helpercount,leads,backups,couldhelps,needs_help\n")

        for r in query:
            yield ','.join(
                '"{}"'.format(text_type(x).replace('"', '\\"')) for x in (
                    r.name,
                    r.n_posts(),
                    '' if r.last_post is None
                    else r.last_post.strftime('%Y-%m-%d'),
                    int(r.gone_forever),
                    int(r.has_forum),
                    r.leadcount,
                    r.helpercount,
                    r.leads or '',
                    r.backups or '',
                    r.couldhelps or '',
                    int(r.needs_help),
                )) + '\n'

    return Response(generate(), mimetype='text/csv')


@app.route('/turfs.csv')
@login_required
def turfs_csv():
    return _query_to_csv(turfs_query)


@app.route('/my-turfs.csv')
@login_required
def my_turfs_csv():
    return _query_to_csv(
        turfs_query.join(Turf).where(Turf.modid == current_user.id))


@app.route('/my-leads.csv')
@login_required
def my_leads_csv():
    return _query_to_csv(
        turfs_query.join(Turf).where((Turf.modid == current_user.id)
                                     & (Turf.state == TURF_LOOKUP['lead'])))


@app.route('/my-backups.csv')
@login_required
def my_backups_csv():
    return _query_to_csv(
        turfs_query.join(Turf).where((Turf.modid == current_user.id)
                                     & (Turf.state == TURF_LOOKUP['backup'])))
