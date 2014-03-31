import os
import sqlite3

from flask import Flask, g, render_template

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

@app.route('/')
def list_shows():
    db = get_db()
    cur = db.execute('''SELECT name, forum_url, tvdb_id
                        FROM shows
                        ORDER BY name ASC''')
    shows = cur.fetchall()
    return render_template('list_shows.html', shows=shows)


if __name__ == '__main__':
    app.run()
