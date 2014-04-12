from __future__ import print_function

import sys

from server import connect_db, tvdb_api


def fill_cache(**api_kwargs):
    db = connect_db()
    t = tvdb_api.Tvdb(interactive=False, **api_kwargs)

    for show in db.execute('''SELECT name, tvdb_id FROM shows
                              WHERE gone_forever = 0 AND we_do_ep_posts = 1
                              ORDER BY name COLLATE NOCASE'''):
        t[show['tvdb_id']]
        print(show['name'], file=sys.stderr)

if __name__ == '__main__':
    fill_cache()
