from __future__ import print_function

import tvdb_api

from server import connect_db, forum_url


def match_tvdbs(interactive=True, **api_kwargs):
    t = tvdb_api.Tvdb(interactive=interactive, **api_kwargs)

    db = connect_db()
    try:
        for show in db.execute('''SELECT id, name, forum_id
                                  FROM shows
                                  WHERE tvdb_ids = '(new)' ''').fetchall():

            print('\n', show['name'], forum_url(show['forum_id']))
            try:
                tvdb_id = t[show['name']]['id']
            except (tvdb_api.tvdb_shownotfound, tvdb_api.tvdb_userabort):
                print("Show not found! Not giving it a TVDB link.\n")
                tvdb_id = ''
            # TODO: allow selecting multiple here

            db.execute('UPDATE shows SET tvdb_ids = ? WHERE id = ?',
                       [tvdb_id, show['id']])
            db.commit()
    finally:
        db.close()

if __name__ == '__main__':
    match_tvdbs()
