#!/usr/bin/env python
import argparse
import sys

from server import connect_db

def summarize_mod(modid):
    db = connect_db()
    try:
        q = '''SELECT shows.name, turfs.comments
               FROM turfs, shows
               WHERE turfs.modid = ?
                 AND turfs.showid = shows.id
                 AND turfs.state = ?
               ORDER BY shows.name COLLATE NOCASE'''

        def do(row):
            s = '\t' + row['name']
            if row['comments']:
                s = s + ' ({})'.format(row['comments'])
            return s

        report = (['Lead:'] + map(do, db.execute(q, [modid, 'g']))
                + ['', 'Backup:'] + map(do, db.execute(q, [modid, 'c']))
                + ['', 'Watch:'] + map(do, db.execute(q, [modid, 'w'])))
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


def main():
    parser = argparse.ArgumentParser(description="Drop a mod from the database.")
    parser.add_argument("mod")
    args = parser.parse_args()

    db = connect_db()
    try:
        q = 'SELECT id FROM mods WHERE name = ? COLLATE NOCASE'
        res = db.execute(q, [args.mod]).fetchmany()
        if len(res) == 0:
            sys.exit('No such mod "{}".'.format(args.mod))
        elif len(res) > 1:
            sys.exit('Too many mods named "{}"!'.format(args.mod))
        else:
            modid = res[0]['id']
    finally:
        db.close()

    print(summarize_mod(modid))

    go_on = raw_input('\nReally delete "{}"? [yN]'.format(args.mod))
    if go_on.strip().lower() == 'y':
        drop_mod(modid)
        print("Okay, done. :/")
    else:
        print("Whew, not deleting anyone.")


if __name__ == '__main__':
    main()
