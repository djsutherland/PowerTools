from __future__ import print_function

from peewee import fn
import tvdb_api

from ptv_helper.app import db
from ptv_helper.helpers import forum_url
from ptv_helper.models import Show


def match_tvdbs(interactive=True, **api_kwargs):
    t = tvdb_api.Tvdb(interactive=interactive, **api_kwargs)

    db.connect()
    try:
        # for show in db.execute('''SELECT id, name, forum_id
        #                           FROM shows
        #                           WHERE tvdb_ids = '(new)' 
        #                           ORDER BY name COLLATE NOCASE''').fetchall():
        for show in (Show.select()
                         .where(Show.tvdb_ids == '(new)')
                         .order_by(fn.lower(Show.name).asc())):

            print('\n', show.name, forum_url(show.forum_id))
            try:
                tvdb_id = t[show.name]['id']
            except (tvdb_api.tvdb_shownotfound, tvdb_api.tvdb_userabort):
                print("Show not found! Not giving it a TVDB link.\n")
                tvdb_id = ''
            # TODO: allow selecting multiple here

            with db.atomic():
                show.tvdb_ids = tvdb_id
                show.save()
    finally:
        db.close()

if __name__ == '__main__':
    match_tvdbs()
