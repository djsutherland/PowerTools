from collections import namedtuple
import operator as op

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

from flask import abort, g, jsonify, render_template, Response, request
from flask_login import current_user, login_required
from peewee import IntegrityError, prefetch
import unicodecsv as csv

from ..app import app
from ..helpers import strip_the
from ..models import Mod, Show, Turf


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

    turfs_with_stuff = prefetch(Turf.select(), Show.select(), Mod.select())

    show_info = {}
    for turf in turfs_with_stuff:
        show = turf.show
        if show.id not in show_info:
            show_info[show.id] = (show, {
                'n_mods': 0, 'mod_info': [], 'my_info': MyInfo(None, None),
            })
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

    show_info = sorted(
        ((show, info) for id, (show, info) in show_info.iteritems()),
        key=lambda (show, info): strip_the(show.name).lower())
    for show_id, info in show_info:
        info['mod_info'] = sorted(
            info['mod_info'],
            key=lambda info: (-'nwcg'.find(info.state), info.modname.lower()))

    n_postses = sorted(show.n_posts() for show, info in show_info
                       if show.n_posts() != 'n/a')
    hi_post_thresh = n_postses[int(len(n_postses) * .8)]

    return render_template(
        'mod_turfs.html',
        shows=show_info, mods=Mod.select(), hi_post_thresh=hi_post_thresh)


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

@app.route('/_mark_over/', methods=['POST'])
def _mark_over():
    return update_show('gone_forever', bool_val=True)

@app.route('/_mark_per_ep/', methods=['POST'])
def _mark_per_ep():
    return update_show('we_do_ep_posts', bool_val=True)

@app.route('/_mark_needs_leads/', methods=['POST'])
def _mark_need_leads():
    return update_show('needs_leads', bool_val=True)

@app.route('/_mark_needs_backups/', methods=['POST'])
def _mark_needs_backups():
    return update_show('needs_backups', bool_val=True)


@app.route('/_mark_territory/', methods=['POST'])
def _mark_territory():
    if not current_user.is_authenticated():
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
        if not val and not comments:
            t = Turf.get(show=show, mod=mod)
            t.delete_instance()
            print('a')
        else:
            try:
                Turf.insert(show=show, mod=mod,
                            state=val, comments=comments).execute()
            except IntegrityError:
                turf = Turf.get(show=show, mod=mod)
                turf.state = val
                turf.comments = comments
                turf.save()


    info = {
        'my_info': [val, comments],
        'n_posts': show.n_posts()
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

# TODO: make portable

turfs_query = '''SELECT
    shows.name,
    shows.forum_topics + shows.forum_posts AS posts,
    shows.gone_forever,
    shows.we_do_ep_posts,
    (SELECT COUNT(*) FROM turfs
        WHERE turfs.showid = shows.id
          AND turfs.state = 'g')
     AS leadcount,
    (SELECT COUNT(*) FROM turfs
        WHERE turfs.showid = shows.id
          AND turfs.state = 'c')
     AS helpercount,
    (SELECT GROUP_CONCAT(mods.name, ", ") FROM turfs, mods
        WHERE turfs.showid = shows.id AND turfs.modid = mods.id
          AND turfs.state = 'g')
     AS leads,
    (SELECT GROUP_CONCAT(mods.name, ", ") FROM turfs, mods
        WHERE turfs.showid = shows.id AND turfs.modid = mods.id
          AND turfs.state = 'c')
     AS backups,
    (SELECT GROUP_CONCAT(mods.name, ", ") FROM turfs, mods
        WHERE turfs.showid = shows.id AND turfs.modid = mods.id
          AND turfs.state = 'w')
     AS watchers
    FROM shows {0}
    ORDER BY shows.name'''

def _query_to_csv(query):
    db = g.db
    sio = StringIO()
    writer = csv.writer(sio)

    rows = db.execute_sql(query)
    it = iter(rows)

    try:
        row = next(it)
    except StopIteration:
        return Response('', mimetype='text/csv')

    # keys = row.keys()
    # writer.writerow(keys)
    writer.writerow(
        ("name posts gone_forever we_do_ep_posts leadcount helpercount "
         "leads backups watchers").split())

    # get = op.itemgetter(*keys)
    writer.writerow(row)
    for row in it:
        writer.writerow(row)

    return Response(sio.getvalue(), mimetype='text/csv')

@app.route('/turfs.csv')
def turfs_csv():
    return _query_to_csv(turfs_query.format(''))

@app.route('/my-turfs.csv')
@login_required
def my_turfs_csv():
    return _query_to_csv(turfs_query.format(
        '''INNER JOIN turfs ON turfs.showid = shows.id AND turfs.modid = {0}
        '''.format(current_user.id)))

@app.route('/my-leads.csv')
@login_required
def my_leads_csv():
    return _query_to_csv(turfs_query.format(
        '''INNER JOIN turfs ON turfs.showid = shows.id AND turfs.modid = {0}
           AND turfs.state = 'g' '''.format(current_user.id)))

@app.route('/my-backups.csv')
@login_required
def my_backups_csv():
    return _query_to_csv(turfs_query.format(
        '''INNER JOIN turfs ON turfs.showid = shows.id AND turfs.modid = {0}
           AND turfs.state = 'c' '''.format(current_user.id)))
