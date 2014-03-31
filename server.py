from collections import defaultdict, OrderedDict
import datetime
import os
import sqlite3

import tvdb_api

from flask import Flask, g, render_template, redirect, url_for

app = Flask(__name__)
app.config.from_object(__name__)

# load default config, override config from an environment variable
app.config.update(dict(
    DATABASE=os.path.join(app.root_path, 'ptv.db'),
    DEBUG=True,
    SECRET_KEY='9Zbl48DxpawebuOKcTIxsIo7rZhgw2U5qs2mcE5Hqxaa7GautgOh3rkvTabKp',
    USERNAME='admin',
    PASSWORD='default'
))
app.config.from_envvar('PTV_SETTINGS', silent=True)


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

@app.route('/list/')
def list_shows():
    db = get_db()
    cur = db.execute('''SELECT name, forum_url, tvdb_id, gone_forever
                        FROM shows
                        ORDER BY name ASC''')
    shows = cur.fetchall()
    return render_template('list_shows.html', shows=shows)


################################################################################

def get_airing_soon(shows, start=None, end=None, days=3, group_by_date=True,
                    **api_kwargs):
    "Returns episodes of shows airing in [start, end)."
    if start is None:
        start = datetime.date.today()
    if end is None:
        end = start + datetime.timedelta(days=days)

    if group_by_date:
        res = defaultdict(list)
        add = lambda date, ep: res[date].append(ep)
    else:
        res = []
        add = res.append

    t = tvdb_api.Tvdb(interactive=False, **api_kwargs)

    for show in shows:
        show_obj = t[show['tvdb_id']]
        for season_obj in show_obj.itervalues():
            for ep_obj in season_obj.itervalues():
                date = ep_obj.get('firstaired', None)
                if date is not None:
                    date = datetime.datetime.strptime(date, '%Y-%m-%d').date()
                    if start <= date < end:
                        add(date, (show['name'], ep_obj))
    return res


# TODO: cache this better.
# keep a Tvdb object across calls, and hack in a bigger show cache?
# just keep the results of get_airing_soon in memory for a set time?
@app.route('/soon/')
@app.route('/soon/<days>')
def eps_soon(days=3):
    db = get_db()
    cur = db.execute('''SELECT name, forum_url, tvdb_id
                        FROM shows
                        WHERE gone_forever = 0''')
    shows = cur.fetchall()

    names_to_url = {show['name']: show['forum_url'] for show in shows}
    soon = get_airing_soon(shows)

    soon = sorted(
        (date,
         sorted([(show_name, ep) for show_name, ep in eps],
                key=lambda p: p[0][4:] if p[0].startswith('The ') else p[0]))
        for date, eps in soon.iteritems())

    return render_template(
        'eps_soon.html', soon=soon, names_to_url=names_to_url)


################################################################################

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    app.run()
