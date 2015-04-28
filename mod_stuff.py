#!/usr/bin/env python
import itertools

from server import connect_db, TURF_STATES


def get_modid(name):
    db = connect_db()
    try:
        q = 'SELECT id FROM mods WHERE name = ? COLLATE NOCASE'
        res = db.execute(q, [name]).fetchmany()
        if len(res) == 0:
            raise ValueError('No such mod "{}".'.format(name))
        elif len(res) > 1:
            raise ValueError('Too many mods named "{}"!'.format(name))
        else:
            return res[0]['id']
    finally:
        db.close()


def list_mods():
    db = connect_db()
    try:
        q = 'SELECT name FROM mods ORDER BY name COLLATE NOCASE'
        return [r['name'] for r in db.execute(q)]
    finally:
        db.close()


def summarize_mod(modid):
    db = connect_db()
    try:
        q = '''SELECT shows.name, shows.id, turfs.comments
               FROM turfs, shows
               WHERE turfs.modid = ?
                 AND turfs.showid = shows.id
                 AND turfs.state = ?
               ORDER BY shows.name COLLATE NOCASE'''

        def do(row):
            comm = ' ({})'.format(row['comments']) if row['comments'] else ''
            others = db.execute('''SELECT turfs.state, mods.name
                                   FROM mods, turfs
                                   WHERE mods.id = turfs.modid
                                     AND turfs.showid = ?
                                     AND mods.id <> ?''',
                                [row['id'], modid])
            bits = sorted([(r['state'], r['name']) for r in others],
                          key=lambda x: ('gcw'.index(x[0]), x[1]))
            oths = '; '.join(
                    '{}: {}'.format(
                        TURF_STATES[k],
                        ', '.join(m[1] for m in v))
                    for k, v in itertools.groupby(bits, key=lambda x: x[0]))
            if not oths:
                oths = '[b]nobody[/b]'
            
            return '   [*][i]{name}[/i]{comments} ({others})[/*]'.format(
                name=row['name'],
                comments=comm,
                others=oths)

        report = (['Lead: [LIST]']
                + map(do, db.execute(q, [modid, 'g']))
                + ['[/LIST]', 'Backup:[LIST]']
                + map(do, db.execute(q, [modid, 'c']))
                + ['[/LIST]', 'Watch:[LIST]']
                + map(do, db.execute(q, [modid, 'w']))
                + ['[/LIST]'])
        return '\n'.join(report)

    finally:
        db.close()


def drop_mod(modid):
    db = connect_db()
    try:
        db.execute('DELETE FROM turfs WHERE modid = ?', [modid])
        db.execute('DELETE FROM mods WHERE id = ?', [modid])
        db.commit()
    finally:
        db.close()
