from flask import abort, g, jsonify, render_template, request
from flask_login import current_user, login_required
from peewee import fn, IntegrityError, prefetch, SQL

from ..app import app
from ..models import BingoSquare, Mod, ModBingo

# TODO: port to peewee

@app.route('/bingo/')
@login_required
def bingo():
    entries = {(b.row, b.col): b.name for b in BingoSquare.select()}
    active = {
        (mb.bingo.row, mb.bingo.col)
        for mb in prefetch(current_user.modbingo_set, BingoSquare.select())
    }
    mod_squares = [
        (mb.mod.name, mb.num)
        for mb in ModBingo.select(ModBingo, fn.Count(SQL('*')).alias('num'))
                          .join(Mod)
                          .group_by(ModBingo.mod)
                          .order_by(SQL('num').desc())
    ]
    return render_template('bingo.html', entries=entries,
                           active=active, mod_squares=mod_squares)


@app.route('/bingo/_mark/', methods=['POST'])
def mark_bingo():
    if not current_user.is_authenticated():
        return abort(401)
    mod = Mod(**current_user._data)

    row = request.form.get('row', type=int)
    col = request.form.get('col', type=int)
    on = {'true': 1, 'false': 0}.get(request.form.get('on'), None)
    try:
        square = BingoSquare.get(row=row, col=col)
    except BingoSquare.DoesNotExist:
        return abort(404)

    with g.db.atomic():
        if on:
            try:
                ModBingo.insert(bingo=square, mod=mod).execute()
            except IntegrityError:
                pass  # no metadata here to change
        else:
            ModBingo.delete().where((ModBingo.bingo==square)
                                  & (ModBingo.mod==mod)).execute()

    return jsonify(on=bool(on))
