import datetime

from flask import render_template, request, send_from_directory
from peewee import fn

from ..app import app
from ..models import Show, BingoSquare

from . import bingo, soon, turfs

################################################################################
### Super basics

@app.route('/')
def index():
    num_bingo = BingoSquare.select(fn.Max(BingoSquare.which)).scalar()
    return render_template(
        'index.html', now=datetime.datetime.now(), num_bingo=num_bingo)

@app.route('/robots.txt')
def static_from_root():
    return send_from_directory(app.static_folder, request.path[1:])


################################################################################
### List: kind of superceded by turfs, still here to test

@app.route('/list/')
def list_shows():
    shows = Show.select().order_by(fn.Lower(Show.name))
    return render_template('list_shows.html', shows=shows)

