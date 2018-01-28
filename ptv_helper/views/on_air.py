from __future__ import unicode_literals
import datetime

from flask import render_template
from tzlocal import get_localzone

from ..app import app
from ..helpers import strip_the
from ..models import Meta, Show, ShowTVDB


def get_airing_mismatch():
    we_think_done = sorted(
        Show.select().where(Show.gone_forever)
            .join(ShowTVDB).where(ShowTVDB.status == 'Continuing')
            .distinct(Show.id),
        key=lambda s: strip_the(s.name))

    we_think_continuing = []
    for show in (Show.select().where(~Show.gone_forever)
                     .join(ShowTVDB).where(ShowTVDB.status == 'Ended')
                     .distinct(Show.id)):
        if not show.tvdb_ids.where(ShowTVDB.status == 'Continuing').exists():
            we_think_continuing.append(show)
    we_think_continuing.sort(key=lambda s: strip_the(s.name))

    return we_think_done, we_think_continuing


@app.route('/onair/')
def on_air():
    we_think_done, we_think_continuing = get_airing_mismatch()

    tz = get_localzone()
    last_tvdb_update = tz.localize(datetime.datetime.fromtimestamp(float(
        Meta.get_value('episode_update_time', 0))))
    last_forum_update = tz.localize(datetime.datetime.fromtimestamp(float(
        Meta.get_value('forum_update_time', 0))))
    yesterday = tz.localize(datetime.datetime.now() - datetime.timedelta(days=1))

    return render_template(
        'onair.html',
        we_think_done=we_think_done, we_think_continuing=we_think_continuing,
        last_tvdb_update=last_tvdb_update, last_forum_update=last_forum_update,
        yesterday=yesterday)
