from __future__ import print_function

from collections import namedtuple
import re
import sys

import lxml.html

from server import connect_db


letter_pages = [
    'http://forums.previously.tv/forum/636--/',  # numbers
    'http://forums.previously.tv/forum/6-a/',
    'http://forums.previously.tv/forum/7-b/',
    'http://forums.previously.tv/forum/11-c/',
    'http://forums.previously.tv/forum/12-d/',
    'http://forums.previously.tv/forum/13-e/',
    'http://forums.previously.tv/forum/14-f/',
    'http://forums.previously.tv/forum/15-g/',
    'http://forums.previously.tv/forum/16-h/',
    'http://forums.previously.tv/forum/17-i/',
    'http://forums.previously.tv/forum/29-j/',
    'http://forums.previously.tv/forum/30-k/',
    'http://forums.previously.tv/forum/31-l/',
    'http://forums.previously.tv/forum/32-m/',
    'http://forums.previously.tv/forum/33-n/',
    'http://forums.previously.tv/forum/34-o/',
    'http://forums.previously.tv/forum/35-p-q/',
    'http://forums.previously.tv/forum/37-r/',
    'http://forums.previously.tv/forum/38-s/',
    'http://forums.previously.tv/forum/39-t/',
    'http://forums.previously.tv/forum/40-u/',
    'http://forums.previously.tv/forum/41-v/',
    'http://forums.previously.tv/forum/62-w/',
    'http://forums.previously.tv/forum/46-x-y-z/',
    'http://forums.previously.tv/forum/54-misc-tv-talk/',
    'http://forums.previously.tv/forum/53-off-topic/',
    'http://forums.previously.tv/forum/47-site-business/',
]

forum_url_fmt = re.compile(r'http://forums.previously.tv/forum/(\d+)-.*')
SiteShow = namedtuple('SiteShow', 'name forum_id topics posts')


def get_site_show_list():
    for letter in letter_pages:
        root = lxml.html.parse(letter).getroot()
        for tr in root.cssselect('table.ipb_table tr'):
            a = tr.cssselect('td.col_c_forum a')[0]
            forum_id = forum_url_fmt.match(a.attrib['href']).group(1)
            name = a.text_content()
            if tr.attrib['class'] == 'redirect_forum':
                topics = None
                posts = None
            else:
                topics, posts = [
                    int(s.text_content().replace(',', ''))
                    for s in tr.cssselect('td.col_c_stats li span')]
            yield SiteShow(name, forum_id, topics, posts)


# TODO: support multiple TVDB keys for a given show
#       for example: Masterpiece has Classic, Contemporary, Mystery, Theater
def merge_shows_list():
    db = connect_db()
    try:
        for show in get_site_show_list():
            name = show.name
            forum_id = show.forum_id

            # find matching show
            res = db.execute('''SELECT id, name, forum_id, tvdb_ids
                                FROM shows
                                WHERE forum_id = ?''', [forum_id]).fetchall()

            if not res:
                # show is on the site, not in the db
                db.execute(
                    '''INSERT INTO shows
                       (name, tvdb_ids, forum_id, forum_posts, forum_topics,
                        needs_leads)
                       VALUES (?, ?, ?, ?, ?, ?)''',
                    [name, "(new)", forum_id, show.posts, show.topics, True])
                db.commit()

            elif len(res) == 1:
                # show both in the db and on the site
                # update the posts

                if res[0]['name'] != name:
                    print("Name disagreement: '{}' in db, renaming to '{}'."
                          .format(res[0]['name'], name),
                          file=sys.stderr)

                db.execute(
                    '''UPDATE shows
                       SET name = ?, forum_posts = ?, forum_topics = ?
                       WHERE id = ?''',
                    [name, show.posts, show.topics, res[0]['id']])
                db.commit()

            else:
                s = "{} entries for {} - {}"
                raise ValueError(s.format(len(res), show.name, show.forum_id))
    finally:
        db.close()


if __name__ == '__main__':
    merge_shows_list()
