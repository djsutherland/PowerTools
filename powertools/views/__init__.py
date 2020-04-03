import datetime

from flask import render_template, request, send_from_directory
from peewee import fn

from ..base import app
from ..models import BingoSquare, Mod

from . import bingo, grab_shows, manage_users, match_tvdb, reports, soon, turfs


@app.route("/")
def index():
    num_bingo = BingoSquare.select(fn.Max(BingoSquare.which)).scalar()
    return render_template(
        "index.html",
        now=datetime.datetime.now(),
        num_bingo=num_bingo,
        mods=Mod.select().order_by(Mod.name.asc()),
    )


@app.route("/robots.txt")
def static_from_root():
    return send_from_directory(app.static_folder, request.path[1:])
