from __future__ import print_function, unicode_literals

from collections import defaultdict, namedtuple
import re
import sys

import lxml.html
from peewee import fn

from ptv_helper.app import db
from ptv_helper.models import Show


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
megashows = [
    'http://forums.previously.tv/forum/1350-the-real-housewives/',
    'http://forums.previously.tv/forum/1751-dc-tv-universe/',
]
all_pages = letter_pages + megashows

forum_url_fmt = re.compile(r'http://forums.previously.tv/forum/(\d+)-.*')
SiteShow = namedtuple('SiteShow', 'name forum_id topics posts')

# populated as side-effect of get_site_show_list (gross)
megashow_children = defaultdict(set)

def get_site_show_list():
    for page in all_pages:
        root = lxml.html.parse(page).getroot()
        mega = page in megashows
        if mega:
            mega_id = forum_url_fmt.match(page).group(1)

        for table in root.cssselect('table.ipb_table'):
            if not table.attrib['summary'].startswith('Sub-forums within'):
                continue
            for tr in table.cssselect('tr'):
                if tr.attrib['class'] == 'redirect_forum':
                    continue
                a = tr.cssselect('td.col_c_forum a')[0]
                forum_id = forum_url_fmt.match(a.attrib['href']).group(1)
                name = a.text_content()
                topics, posts = [
                    int(s.text_content().replace(',', ''))
                    for s in tr.cssselect('td.col_c_stats li span')]

                if mega:
                    megashow_children[mega_id].add(forum_id)
                yield SiteShow(name, forum_id, topics, posts)


def merge_shows_list():
    db.connect()
    try:
        for show in get_site_show_list():
            # find matching show
            with db.atomic():
                res = list(Show.select().where(Show.forum_id == show.forum_id))

                if not res:
                    # show is on the site, not in the db
                    db_show = Show(
                        name=show.name,
                        tvdb_ids="(new)",
                        forum_id=show.forum_id,
                        forum_posts=show.posts,
                        forum_topics=show.topics,
                        needs_leads=show.posts + show.topics > 50,
                        # unlikely that this'll ever hit, but...
                    )
                    db_show.save()

                elif len(res) == 1:
                    # show both in the db and on the site
                    # update the posts

                    db_show, = res

                    if db_show.name != show.name:
                        m = "Name disagreement: '{0}' in db, renaming to '{1}'."
                        print(m.format(db_show.name, show.name),
                              file=sys.stderr)
                        db_show.name = show.name

                    db_show.forum_posts = show.posts
                    db_show.forum_topics = show.topics
                    db_show.save()

                else:
                    raise ValueError("{} entries for {} - {}"
                        .format(len(res), show.name, show.forum_id))

        # patch up the mega-shows
        for mega, children_ids in megashow_children.iteritems():
            with db.atomic():
                child_topics, child_posts = (Show
                    .select(fn.sum(Show.forum_topics), fn.sum(Show.forum_posts))
                    .where(Show.forum_id << list(children_ids))
                    .scalar(as_tuple=True))

                Show.update(
                    forum_topics=Show.forum_topics - child_topics,
                    forum_posts=Show.forum_posts - child_posts,
                ).where(Show.forum_id == mega).execute()

    finally:
        db.close()


if __name__ == '__main__':
    merge_shows_list()
