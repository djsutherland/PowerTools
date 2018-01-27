from __future__ import unicode_literals
from collections import namedtuple
import datetime
from itertools import groupby

from flask import abort, g, jsonify, render_template, Response, request
from flask_login import current_user, login_required
from peewee import fn, IntegrityError, prefetch, SQL

from ..app import app
from ..helpers import strip_the
from ..models import Mod, Show, ShowTVDB, Turf, TURF_STATES


################################################################################
### Main turfs page

ModInfo = namedtuple('ModInfo', ['modname', 'state', 'comments'])
MyInfo = namedtuple('MyInfo', ['state', 'comments'])

@app.route('/turfs/')
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
            })
        for s in Show.select().where(~Show.hidden)
    }

    for turf in turfs_with_stuff:
        show = turf.show
        if show.hidden:
            continue
        _, show_inf = show_info[show.id]

        if turf.mod_id == modid:
            show_inf['my_info'] = MyInfo(turf.state, turf.comments)

        show_inf['mod_info'].append(ModInfo(
            turf.mod.name,
            turf.state,
            turf.comments,
        ))

        if turf.state in 'gc':
            show_inf['n_mods'] += 1

    get_name = lambda (show, info): strip_the(show.name).lower()
    show_info = sorted(show_info.itervalues(), key=get_name)
    for show_id, info in show_info:
        info['mod_info'] = sorted(
            info['mod_info'],
            key=lambda info: (-'nwcg'.find(info.state), info.modname.lower()))

    niceify = lambda c: c if c.isalpha() else '#'
    firsts = [
        (letter, next(iter(letter_show_infos))[0].id)
        for letter, letter_show_infos
        in groupby(show_info, key=lambda s: niceify(get_name(s)[0]))]

    n_postses = sorted(show.n_posts() for show, info in show_info
                       if show.n_posts() != 'n/a')
    hi_post_thresh = n_postses[int(len(n_postses) * .8)]

    return render_template(
        'mod_turfs.html',
        shows=show_info, mods=Mod.select(), hi_post_thresh=hi_post_thresh,
        now=datetime.datetime.now(), firsts=firsts)


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

# Can't change gone_forever anymore, handled on the real site
# @app.route('/_mark_over/', methods=['POST'])
# def _mark_over():
#     return update_show('gone_forever', bool_val=True)

@app.route('/_mark_per_ep/', methods=['POST'])
def _mark_per_ep():
    return update_show('we_do_ep_posts', bool_val=True)

@app.route('/_mark_needs_help/', methods=['POST'])
def _mark_needs_help():
    return update_show('needs_help', bool_val=True)

@app.route('/_mark_up_for_grabs/', methods=['POST'])
def _mark_up_for_grabs():
    return update_show('up_for_grabs', bool_val=True)


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
    info['n_mods'] = sum(1 for modinf in info['mod_info']
                         if modinf.state in 'gc')

    return render_template(
        "turf_row.html", show=show, info=info, modid=modid, modname=modname,
        hi_post_thresh=hi_post_thresh, parity=parity)


################################################################################
### Turfs CSV dump

turfs_query = Show.select(
    Show,
    Turf.select(fn.count(SQL('*')))
        .where((Turf.state == 'g') & (Turf.show == Show.id))
        .alias('leadcount'),
    Turf.select(fn.count(SQL('*')))
        .where((Turf.state == 'c') & (Turf.show == Show.id))
        .alias('helpercount'),
    Turf.select(fn.group_concat(Mod.name, ", "))
        .join(Mod)
        .where((Turf.show == Show.id) & (Turf.state == 'g'))
        .alias('leads'),
    Turf.select(fn.group_concat(Mod.name, ", "))
        .join(Mod)
        .where((Turf.show == Show.id) & (Turf.state == 'c'))
        .alias('backups'),
    Turf.select(fn.group_concat(Mod.name, ", "))
        .join(Mod)
        .where((Turf.show == Show.id) & (Turf.state == 'w'))
        .alias('watchers'),
).where(~Show.hidden).order_by(fn.Lower(Show.name).asc())
# NOTE: group_concat works only in sqlite or mysql


def _query_to_csv(query):
    def generate():
        yield u','.join(
            ("name posts last_post gone_forever we_do_ep_posts "
             "leadcount helpercount leads backups watchers").split()) + '\n'

        for row in query:
            yield u','.join(
                u'"{}"'.format(unicode(x).replace('"', '\\"')) for x in (
                    row.name,
                    row.n_posts(),
                    '' if row.last_post is None else
                        row.last_post.strftime('%Y-%m-%d'),
                    int(row.gone_forever),
                    int(row.we_do_ep_posts),
                    row.leadcount,
                    row.helpercount,
                    row.leads or '',
                    row.backups or '',
                    row.watchers or '',
                )) + '\n'

    return Response(generate(), mimetype='text/csv')


@app.route('/turfs.csv')
def turfs_csv():
    return _query_to_csv(turfs_query)

@app.route('/my-turfs.csv')
@login_required
def my_turfs_csv():
    return _query_to_csv(
        turfs_query.join(Turf).where(Turf.mod == Mod(id=current_user.id)))

@app.route('/my-leads.csv')
@login_required
def my_leads_csv():
    return _query_to_csv(
        turfs_query.join(Turf).where((Turf.mod == Mod(id=current_user.id))
                                   & (Turf.state == 'g')))

@app.route('/my-backups.csv')
@login_required
def my_backups_csv():
    return _query_to_csv(
        turfs_query.join(Turf).where((Turf.mod == Mod(id=current_user.id))
                                   & (Turf.state == 'c')))
