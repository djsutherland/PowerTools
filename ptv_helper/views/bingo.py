from flask import abort, g, jsonify, render_template, request
from flask_login import current_user, login_required

from ..app import app

# TODO: port to peewee

@app.route('/bingo/')
@login_required
def bingo():
    modid = current_user.id
    db = g.db
    entries = dict(
        ((b[0], b[1]), b[2])
        for b in db.execute_sql('''SELECT row, col, name FROM bingo''')
    )
    active = set(
        (x[0], x[1])
        for x in db.execute_sql('''SELECT bingo.row, bingo.col
                                   FROM bingo, mod_bingo
                                   WHERE bingo.id = mod_bingo.bingoid
                                     AND mod_bingo.modid = ?''',
                                [modid])
    )
    mod_squares = [
        (r[0], r[1])
        for r in db.execute_sql('''SELECT mods.name AS name, COUNT(*) as num
                                   FROM mod_bingo
                                   JOIN mods ON mod_bingo.modid = mods.id
                                   GROUP BY modid
                                   ORDER BY num DESC''')
    ]
    return render_template('bingo.html', entries=entries,
                           active=active, mod_squares=mod_squares)


@app.route('/bingo/_mark/', methods=['POST'])
def mark_bingo():
    if not current_user.is_authenticated():
        return abort(401)
    modid = current_user.id
    row = request.form.get('row', type=int)
    col = request.form.get('col', type=int)
    on = {'true': 1, 'false': 0}.get(request.form.get('on'), None)

    db = g.db

    with db.atomic():
        bingoids = [
            r[0] for r in
            db.execute_sql('SELECT id FROM bingo WHERE row = ? AND col = ?', [row, col])
        ]
        if not bingoids:
            return abort(404)
        bingoid, = bingoids   

        if on:
            db.execute_sql('''INSERT OR REPLACE INTO mod_bingo (bingoid, modid)
                              VALUES (?, ?)''', [bingoid, modid])
        else:
            db.execute_sql('DELETE FROM mod_bingo WHERE bingoid = ? AND modid = ?',
                           [bingoid, modid])

    return jsonify(on=bool(on))
