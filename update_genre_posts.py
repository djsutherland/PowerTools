import operator as op
import itertools

from flask import render_template
import mechanize

from server import app, get_db, strip_the

LOGIN_URL = "https://forums.previously.tv/index.php" \
            "?app=core&module=global&section=login"


def login(br, username, password):
    br.open(LOGIN_URL)
    assert len(list(br.forms())) == 1
    br.select_form(nr=0)

    br.form['ips_username'] = username
    br.form['ips_password'] = password
    br.submit()


def edit_post(br, edit_url, content):
    br.open(edit_url)
    assert len(list(br.forms())) == 1
    br.select_form(nr=0)

    br.form['Post'] = content
    br.form['add_edit'] = ['1']
    br.submit()


def get_genres_lists():
    with app.app_context():
        db = get_db()

        # shows with no tvdb_ids don't have any show_genres entries
        # also, (none) sorts first, so these should be first
        shows = db.execute(
            '''SELECT '(none)' AS genre, shows.name, shows.forum_id
               FROM shows
               WHERE shows.tvdb_ids = '' OR shows.tvdb_ids = '(new)'
            ''').fetchall()

        shows += db.execute(
            '''SELECT show_genres.genre, shows.name, shows.forum_id
               FROM shows, show_genres
               WHERE shows.id = show_genres.showid
               ORDER BY show_genres.genre COLLATE NOCASE
            ''').fetchall()

        return [
            render_template('genre-list.bbcode', genre=genre, shows=sorted(
                genre_shows, key=lambda s: strip_the(s['name']).lower()))
            for genre, genre_shows
            in itertools.groupby(shows, op.itemgetter('genre'))
        ]


def main():
    from getpass import getpass
    br = mechanize.Browser()
    lists = get_genres_lists()
    login(br, 'hsfuap', getpass())
    edit_post(br, 'http://forums.previously.tv/index.php?app=forums&module=post&section=post&do=edit_post&f=690&t=7834&p=91822&page=',
              '\n\n'.join(lists[:15]))
    edit_post(br, 'http://forums.previously.tv/index.php?app=forums&module=post&section=post&do=edit_post&f=690&t=7834&p=91892&page=',
              '\n\n'.join(lists[15:]))

if __name__ == '__main__':
    main()