import datetime

from flask import render_template, request, send_from_directory
from peewee import fn
from tzlocal import get_localzone

from ..base import app
from ..models import BingoSquare, Meta, Mod

from . import bingo, grab_shows, manage_users, match_tvdb, reports, soon, turfs


@app.route("/")
def index():
    num_bingo = BingoSquare.select(fn.Max(BingoSquare.which)).scalar()
    tz = get_localzone()
    return render_template(
        "index.html",
        now=datetime.datetime.now(),
        num_bingo=num_bingo,
        mods=Mod.select().order_by(Mod.name.asc()),
        update_time=tz.localize(datetime.datetime.fromtimestamp(
            float(Meta.get_value('forum_update_time', 0))))
    )


@app.route("/robots.txt")
def static_from_root():
    return send_from_directory(app.static_folder, request.path[1:])
