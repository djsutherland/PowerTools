from __future__ import division, print_function

import datetime
import itertools
import logging
import os
import sqlite3
import sys

from flask import (Flask, g, request, url_for, send_from_directory,
                   abort, redirect, render_template, jsonify)
from flask.ext.login import (LoginManager, UserMixin, login_required,
                             login_user, logout_user, current_user)


app = Flask(__name__)
app.config.from_object(__name__)

# load default config, override config from an environment variable
app.config.update(dict(
    DATABASE=os.path.join(app.root_path, 'ptv.db'),
    DEBUG=True,
    SECRET_KEY='9Zbl48DxpawebuOKcTIxsIo7rZhgw2U5qs2mcE5Hqxaa7GautgOh3rkvTabKp',
    USERNAME='admin',
    PASSWORD='default',
))
app.config.from_envvar('PTV_SETTINGS', silent=True)

login_manager = LoginManager(app)
login_manager.login_view = 'login'

# logging.basicConfig(stream=sys.stderr)


################################################################################
### General utilities

def strip_the(s):
    if s is None:
        return ''
    if s.startswith('The '):
        return s[4:]
    return s


@app.template_filter()
def forum_url(forum_id):
    return 'http://forums.previously.tv/forum/{}-'.format(forum_id)


def tvdb_url(series_id):
    return 'http://thetvdb.com/?tab=series&id={}'.format(series_id)


def split_tvdb_ids(s):
    if not s or s == '(new)' or s == '(not a show)':
        return []
    return map(int, s.split(','))


@app.template_filter()
def tvdb_links(tvdb_ids):
    ids = split_tvdb_ids(tvdb_ids)
    if not ids:
        return 'no tvdb'
    elif len(ids) == 1:
        return '<a href="{}">tvdb</a>'.format(tvdb_url(ids[0]))
    else:
        return 'tvdb: ' + ' '.join(
            '<a href="{}">{}</a>'.format(tvdb_url(sid), i)
            for i, sid in enumerate(ids, 1))


@app.template_filter()
def episodedate(ep):
    date = ep.get('firstaired', None)
    if date is None:
        return 'unknown'
    date = datetime.datetime.strptime(date, '%Y-%m-%d').date()
    return '{d:%B} {d.day}, {d.year}'.format(d=date)


################################################################################
### Database stuff

def connect_db():
    rv = sqlite3.connect(app.config['DATABASE'])
    rv.row_factory = sqlite3.Row
    return rv


def init_db():
    with app.app_context():
        db = get_db()
        with app.open_resource('schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()


def get_db():
    "Opens a new database connection if there isn't one yet."
    if not hasattr(g, 'sqlite_db'):
        g.sqlite_db = connect_db()
    return g.sqlite_db


@app.teardown_appcontext
def close_db(error):
    if hasattr(g, 'sqlite_db'):
        g.sqlite_db.close()


################################################################################
### Login management stuff

class User(UserMixin):
    def __init__(self, userid, name):
        self.id = userid
        self.name = name


@login_manager.user_loader
def load_user(userid):
    db = get_db()
    name = db.execute('SELECT name FROM mods WHERE id = ?', [userid]).fetchone()
    if name is None:
        return None
    else:
        return User(userid, name['name'])


@app.route("/login", methods=['GET', 'POST'])
def login():
    db = get_db()
    if request.method == 'POST':
        print(request.form)
        modid = request.form.get('modid')
        if request.form.get('name'):
            name = request.form['name']
            existing = db.execute('''SELECT id FROM mods WHERE name = ?
                                     COLLATE NOCASE''', [name]).fetchone()
            if existing:
                modid = existing['id']
            else:
                cur = db.execute('INSERT INTO mods (name) VALUES (?)', [name])
                db.commit()
                modid = cur.lastrowid

        user = load_user(modid)
        if user:
            login_user(load_user(modid), remember=True)
            return redirect(request.form.get('next') or url_for('index'))

    mods = db.execute('''SELECT id, name FROM mods
                         ORDER BY name COLLATE NOCASE''').fetchall()
    return render_template('login.html', mods=mods)


@app.route('/logout')
def logout():
    logout_user()
    return redirect(request.args.get('next') or url_for('index'))


@app.context_processor
def inject_user():
    return {'user': current_user}


################################################################################
### List: kind of superceded by turfs, still here to test

@app.route('/list/')
def list_shows():
    db = get_db()
    cur = db.execute('''SELECT name, forum_id, tvdb_ids,
                               gone_forever, we_do_ep_posts
                        FROM shows
                        ORDER BY name COLLATE NOCASE''')
    shows = cur.fetchall()
    return render_template('list_shows.html', shows=shows)


################################################################################
### Episodes airing soon

def get_airing_soon(start=None, end=None, days=3):
    "Returns episodes of shows airing in [start, end)."
    if start is None:
        start = datetime.date.today() - datetime.timedelta(days=1)
    if end is None:
        end = start + datetime.timedelta(days=days)

    db = get_db()

    date_fmt = '{:%Y-%m-%d}'
    return db.execute('''SELECT episodes.id AS episodeid, seasonid, seriesid,
                                showid, shows.name AS showname,
                                shows.forum_id AS show_forum_id,
                                season_number, episode_number, first_aired,
                                episodes.name, overview
                         FROM episodes
                         INNER JOIN shows ON showid = shows.id
                         WHERE date(first_aired) BETWEEN date(?) AND date(?)
                           AND shows.we_do_ep_posts = 1
                         ORDER BY date(first_aired) ASC''',
                      [date_fmt.format(start), date_fmt.format(end)])


@app.route('/soon/')
@app.route('/soon/<int:days>')
def eps_soon(days=3):
    soon = sorted(
        (datetime.datetime.strptime(date, '%Y-%m-%d').date(),
         sorted(eps, key=lambda e: (strip_the(e['showname']).lower(),
                                    strip_the(e['name']).lower())))
        for date, eps in itertools.groupby(get_airing_soon(days=days),
                                           key=lambda e: e['first_aired']))
    return render_template('eps_soon.html', soon=soon)


################################################################################
### Turfs

TURF_STATES = {
    'g': 'got it',
    'c': 'can take',
    'w': 'watch it',
    'n': 'nope',
}


def n_posts(show):
    try:
        return show['forum_topics'] + show['forum_posts']
    except TypeError:
        return 'n/a'


@app.route('/turfs/')
def mod_turfs():
    db = get_db()
    modid = getattr(current_user, 'id', None)

    shows = {show['id']: show for show in db.execute(
        '''SELECT id, name, forum_id, tvdb_ids, forum_topics, forum_posts,
                  gone_forever, we_do_ep_posts, eps_up_to_snuff
           FROM shows'''
    )}

    mods = {mod['id']: mod for mod in db.execute("SELECT id, name FROM mods")}

    turfs = db.execute('''SELECT showid, modid, state, comments
                          FROM turfs''').fetchall()

    show_info = {show: {'n_mods': 0, 'mod_info': [], 'my_info': [None, None],
                        'n_posts': n_posts(show)}
                 for show in shows.itervalues()}
    for turf in turfs:
        show_inf = show_info[shows[turf['showid']]]

        if turf['modid'] == modid:
            show_inf['my_info'][:] = [turf['state'], turf['comments']]
        show_inf['mod_info'].append((
            mods[turf['modid']]['name'],
            turf['state'],
            turf['comments'],
        ))

        if turf['state'] in 'gc':
            show_inf['n_mods'] += 1
    show_info = sorted(show_info.iteritems(),
                       key=lambda p: strip_the(p[0]['name']).lower())
    for show, info in show_info:
        info['mod_info'] = sorted(
            info['mod_info'],
            key=lambda tf: (-'nwcg'.find(tf[1]), tf[0].lower()))

    no_coverage = sum(1 for show, info in show_info if info['n_mods'] == 0)

    n_postses = sorted(info['n_posts'] for show, info in show_info
                       if info['n_posts'] != 'n/a')
    hi_post_thresh = n_postses[int(len(n_postses) * .9)]

    return render_template(
        'mod_turfs.html',
        shows=show_info, mods=mods.values(),
        no_coverage=no_coverage, hi_post_thresh=hi_post_thresh)


def update_show(attr, bool_val=False):
    showid = request.form.get('showid', type=int)
    val = request.form.get('val')
    if bool_val:
        val = {'true': 1, 'false': 0}.get(val, None)
    if val is None:
        return abort(400)

    db = get_db()
    cur = db.execute("UPDATE shows SET {} = ? WHERE id = ?".format(attr),
                     [val, showid])

    if cur.rowcount == 1:
        db.commit()

        cur = db.execute("SELECT {} FROM shows WHERE id = ?".format(attr),
                         [showid])
        return jsonify(curr=cur.fetchone()[attr])

    if cur.rowcount > 1:
        # uh-oh! hit too many things!
        # TODO: log error
        db.rollback()
        return abort(500)

    return abort(404)


@app.route('/_mark_over/', methods=['POST'])
def _mark_over():
    return update_show('gone_forever', bool_val=True)


@app.route('/_mark_per_ep/', methods=['POST'])
def _mark_per_ep():
    return update_show('we_do_ep_posts', bool_val=True)


@app.route('/_mark_eps_up_to_snuff/', methods=['POST'])
def _mark_eps_up_to_snuff():
    return update_show('eps_up_to_snuff', bool_val=True)


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

    db = get_db()

    show = db.execute('''SELECT id, name, forum_id, tvdb_ids,
                                forum_topics, forum_posts,
                                gone_forever, we_do_ep_posts, eps_up_to_snuff
                         FROM shows
                         WHERE id = ?''', [showid]).fetchone()
    if show is None:
        raise abort(404)

    mod = db.execute("SELECT name FROM mods WHERE id = ?", [modid]).fetchone()
    if mod is None:
        raise abort(404)
    modname = mod['name']

    if not val and not comments:
        db.execute("DELETE FROM turfs WHERE showid = ? AND modid = ?",
                   [showid, modid])
    else:
        db.execute('''INSERT OR REPLACE INTO turfs
                      (showid, modid, state, comments)
                      VALUES (?, ?, ?, ?)''',
                   [showid, modid, val, comments])
    db.commit()

    info = {
        'my_info': [val, comments],
        'n_posts': n_posts(show)
    }
    info['mod_info'] = sorted(
        ((turf['modname'], turf['state'], turf['comments'])
         for turf in db.execute('''SELECT state, comments, mods.name as modname
                                   FROM turfs
                                   INNER JOIN mods ON turfs.modid = mods.id
                                   WHERE showid = ?''', [showid])),
        key=lambda tf: (-'nwcg'.find(tf[1]), tf[0].lower())
    )
    info['n_mods'] = sum(1 for modname, state, comments in info['mod_info']
                         if state in 'gc')

    return render_template(
        "turf_row.html", show=show, info=info, modid=modid, modname=modname,
        hi_post_thresh=hi_post_thresh, parity=parity)


################################################################################

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/robots.txt')
def static_from_root():
    return send_from_directory(app.static_folder, request.path[1:])

if __name__ == '__main__':
    app.run(debug=True)
