from __future__ import unicode_literals
import operator as op
import itertools

from flask import render_template
from peewee import fn, SQL
import mechanize
from unidecode import unidecode

from ptv_helper.app import app
from ptv_helper.helpers import strip_the
from ptv_helper.models import Show, ShowGenre

LOGIN_URL = "https://forums.previously.tv/index.php" \
            "?app=core&module=global&section=login"


def login(br, username, password):
    br.open(LOGIN_URL)
    assert len(list(br.forms())) == 2
    br.select_form(nr=1)

    br.form['ips_username'] = username
    br.form['ips_password'] = password
    br.submit()


def edit_post(br, edit_url, content):
    br.open(edit_url)
    assert len(list(br.forms())) == 2
    br.select_form(nr=1)

    br.form['Post'] = unidecode(content)
    br.form['add_edit'] = ['1']
    br.submit()


def get_genres_lists():
    with app.app_context():
        # shows with no tvdb_ids don't have any show_genres entries
        # also, (none) sorts first, so these should be first
        shows = list(
            Show
            .select(SQL("'(none)'").alias('genre'), Show.name, Show.forum_id)
            .where(Show.tvdb_ids << ['', '(new)'])
        )
        shows += list(
            Show
            .select(fn.distinct(ShowGenre.genre), Show.name, Show.forum_id)
            .join(ShowGenre)
            .order_by(fn.lower(ShowGenre.genre).asc())
        )

        return [
            render_template('genre-list.bbcode', genre=genre, shows=sorted(
                genre_shows, key=lambda s: strip_the(s.name).lower()))
            for genre, genre_shows
            in itertools.groupby(shows, op.attrgetter('genre'))
        ]


def main():
    from getpass import getpass

    lists = get_genres_lists()

    br = mechanize.Browser()
    login(br, 'hsfuap', getpass())
    edit_post(br, 'http://forums.previously.tv/index.php?app=forums&module=post&section=post&do=edit_post&f=690&t=7834&p=91822&page=',
              '\n\n'.join(lists[:7]))
    edit_post(br, 'http://forums.previously.tv/index.php?app=forums&module=post&section=post&do=edit_post&f=690&t=7834&p=91892&page=',
              '\n\n'.join(lists[7:17]))
    edit_post(br, 'http://forums.previously.tv/index.php?app=forums&module=post&section=post&do=edit_post&f=690&t=7834&p=101974&page=',
              '\n\n'.join(lists[17:]))

if __name__ == '__main__':
    main()
