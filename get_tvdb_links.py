from __future__ import print_function

from peewee import fn
import tvdb_api

from ptv_helper.app import db
from ptv_helper.models import Show, ShowTVDB


def match_tvdbs(interactive=True, **api_kwargs):
    t = tvdb_api.Tvdb(interactive=interactive, **api_kwargs)

    db.connect()
    try:
        for show in (Show.select()
                         .where(Show.tvdb_not_matched_yet)
                         .order_by(fn.lower(Show.name).asc())):

            print('\n', show.name, show.url)
            try:
                tvdb_id = t[show.name]['id']
            except (tvdb_api.tvdb_shownotfound, tvdb_api.tvdb_userabort):
                print("Show not found! Not giving it a TVDB link.\n")
                
                show.tvdb_not_matched_yet = False
                show.save()
            else:
                with db.atomic():
                    ShowTVDB(show=show, tvdb_id=int(tvdb_id)).save()
                    show.tvdb_not_matched_yet = False
                    show.save()
            # TODO: allow selecting multiple here


    finally:
        db.close()

if __name__ == '__main__':
    match_tvdbs()
