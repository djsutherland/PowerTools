from __future__ import print_function, unicode_literals

import codecs
from collections import defaultdict, namedtuple
import re
import sys

import lxml.html
from peewee import fn

from ptv_helper.app import db
from ptv_helper.models import Show


stderr = codecs.getwriter('utf8')(sys.stderr)


import warnings
warnings.filterwarnings(
    'ignore',
    message=r"Data truncated for column 'last_post' at row",
    # mysql doesn't handle timezone information, and peewee warns about that
    module='peewee',
)

letter_pages = [
    'http://forums.previously.tv/forum/2361-podcasts/',
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
megashows = []
all_pages = letter_pages + megashows

forum_url_fmt = re.compile(r'http://forums.previously.tv/forum/(\d+)-.*')
SiteShow = namedtuple('SiteShow', 'name forum_id url topics posts last_post')

# populated as side-effect of get_site_show_list (gross)
megashow_children = defaultdict(set)

dt_parse = re.compile(r'(\d\d\d\d)-(\d?\d)-(\d?\d)T(\d?\d):(\d\d):(\d\d)Z')
dt_format = '{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'

def get_site_show_list():
    for page in all_pages:
        root = lxml.html.parse(page).getroot()
        mega = page in megashows
        if mega:
            mega_id = forum_url_fmt.match(page).group(1)

        for forum_list in root.cssselect('.cForumList'):
            for li in forum_list.cssselect('li[data-forumid]'):
                if len(li.cssselect('.cForumIcon_redirect')) > 0:
                    continue

                forum_id = li.attrib['data-forumid']
                a, = li.cssselect('.ipsDataItem_title a:first-child')
                name = a.text_content()
                url = a.attrib['href']

                topics = 0  # doesn't seem to be available anymore
                dts = li.cssselect('.ipsDataItem_stats dt')
                if len(dts) == 1:
                    posts = dts[0].text_content().strip()
                    if posts.endswith('k'):
                        posts = int(float(posts[:-1]) * 1000)
                    else:
                        posts = int(posts.replace(',', ''))
                elif len(dts) == 0:
                    posts = 0
                else:
                    s = "{} stats entry for {} - {}"
                    raise ValueError(s.format(len(dts), name, page))

                times = li.cssselect('time')
                if len(times) == 0:
                    last_post = None
                elif len(times) == 1:
                    m = dt_parse.match(times[0].attrib['datetime'])
                    last_post = dt_format.format(*(int(x) for x in m.groups()))
                else:
                    s = "{} time entries for {} - {}"
                    raise ValueError(s.format(len(times), name, page))

                if mega:
                    megashow_children[mega_id].add(forum_id)
                yield SiteShow(unicode(name), unicode(forum_id), unicode(url),
                               topics, posts, last_post)


def merge_shows_list(show_dead=True):
    db.connect()
    try:
        seen_forum_ids = {
            s.forum_id for s in Show.select(Show.forum_id).where(Show.hidden)}

        for show in get_site_show_list():
            seen_forum_ids.add(show.forum_id)

            # find matching show
            with db.atomic():
                res = list(Show.select().where(Show.forum_id == show.forum_id))

                if not res:
                    # show is on the site, not in the db
                    db_show = Show(
                        name=show.name,
                        tvdb_id_not_matched_yet=True,
                        forum_id=show.forum_id,
                        url=show.url,
                        forum_posts=show.posts,
                        forum_topics=show.topics,
                        last_post=show.last_post,
                        needs_leads=show.posts + show.topics > 50,
                        # unlikely that this'll ever hit, but...
                    )
                    db_show.save()
                    print("New show: {}".format(show.name), file=stderr)

                elif len(res) == 1:
                    # show both in the db and on the site
                    # update the posts

                    db_show, = res

                    if db_show.name != show.name:
                        m = "Name disagreement: '{0}' in db, renaming to '{1}'."
                        print(m.format(db_show.name, show.name),
                              file=stderr)
                        db_show.name = show.name

                    if db_show.url != show.url:
                        m = "URL disagreement: '{0}' in db, changing to '{1}'."
                        print(m.format(db_show.url, show.url),
                              file=stderr)
                        db_show.url = show.url

                    db_show.forum_posts = show.posts
                    db_show.forum_topics = show.topics
                    db_show.last_post = show.last_post
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

        # dead shows
        if show_dead:
            seen_ids = list(seen_forum_ids)
            if seen_ids:
                unseen = Show.select().where(~(Show.forum_id << seen_ids))
                s = '\n'.join(
                    '\t{} - {}'.format(show.name, show.url) for show in unseen)
                if s:
                    print("Didn't see the following shows:\n" + s,
                          file=stderr)

    finally:
        db.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    g = parser.add_mutually_exclusive_group()
    g.add_argument('--show-dead', action='store_true', default=True)
    g.add_argument('--no-show-dead', action='store_false', dest='show_dead')
    args = parser.parse_args()

    merge_shows_list(**vars(args))
