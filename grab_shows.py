from __future__ import print_function, unicode_literals

import codecs
import re
import sys
import time
import warnings
from collections import defaultdict, namedtuple

from peewee import fn
from six import iteritems, text_type
from six.moves.urllib.parse import urlsplit, urlunsplit

from ptv_helper.app import db
from ptv_helper.helpers import login, make_browser
from ptv_helper.models import Meta, Show

if sys.version_info.major == 2:
    stderr = codecs.getwriter('utf8')(sys.stderr)
else:
    stderr = sys.stderr

warnings.filterwarnings(
    'ignore', "No parser was explicitly specified", UserWarning)
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
SiteShow = namedtuple(
    'SiteShow', 'name forum_id has_forum url topics posts last_post '
                'gone_forever is_tv')

# populated as side-effect of get_site_show_list (gross)
megashow_children = defaultdict(set)

dt_parse = re.compile(r'(\d\d\d\d)-(\d?\d)-(\d?\d)T(\d?\d):(\d\d):(\d\d)Z')
dt_format = '{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'


def parse_dt(s):
    m = dt_parse.match(s)
    return dt_format.format(*(int(x) for x in m.groups()))


def parse_number(s):
    s = s.strip().lower()
    if s.endswith('k'):
        return int(float(s[:-1]) * 1000)
    else:
        return int(s.replace(',', ''))


def get_site_show_list():
    br = make_browser()
    login(br)

    for page in all_pages:
        br.open(page)
        if not br.response.ok:
            m = "HTTP code {} for {}"
            raise IOError(m.format(br.response.status_code, page))

        mega = page in megashows
        if mega:
            mega_id = forum_url_fmt.match(page).group(1)

        for forum_list in br.select('.cForumList'):
            for li in forum_list.select('li[data-forumid]'):
                if len(li.select('.cForumIcon_redirect')) > 0:
                    continue

                forum_id = li['data-forumid']
                a, = li.select('.ipsDataItem_title a:nth-of-type(1)')
                name = text_type(a.string).strip()
                url = text_type(a['href'])

                status = li['data-forumstatus']
                if status not in {"0", "1", "2"}:
                    msg = "Confusing status: {} for {}"
                    warnings.warn(msg.format(status, name))
                    gone_forever = None
                    is_tv = None
                else:
                    gone_forever = status == "0"
                    is_tv = status != "2"

                topics = 0  # doesn't seem to be available anymore
                dts = li.select('.ipsDataItem_stats dt')
                if len(dts) == 1:
                    posts = parse_number(dts[0].string)
                elif len(dts) == 0:
                    posts = 0
                else:
                    s = "{} stats entry for {} - {}"
                    raise ValueError(s.format(len(dts), name, page))

                times = li.select('time')
                if len(times) == 0:
                    last_post = None
                elif len(times) == 1:
                    last_post = parse_dt(times[0]['datetime'])
                else:
                    s = "{} time entries for {} - {}"
                    raise ValueError(s.format(len(times), name, page))

                if mega:
                    megashow_children[mega_id].add(forum_id)
                yield SiteShow(name, forum_id, True, url,
                               topics, posts, last_post, gone_forever, is_tv)

        for topic_list in br.select('.cTopicList'):
            for li in topic_list.select('li[data-rowid]'):
                # TODO: redirects here?

                topic_id = li['data-rowid']
                a, = li.select('.ipsDataItem_title a:nth-of-type(1)')
                name = text_type(a.string).strip()

                # drop query string from url
                url = text_type(urlunsplit(urlsplit(
                    a['href'])[:-2] + (None, None)))

                # just guessing here...and of course I removed the ability to
                # change these things. fun! (#44)
                gone_forever = False
                is_tv = True

                topics = 0
                stats, = li.select('.ipsDataItem_stats')
                lis = stats.select('li')
                assert len(lis) == 2
                assert lis[0].select('.ptvf-comment')
                posts = parse_number(
                    lis[0].select('.ipsDataItem_stats_number')[0].string)

                times = li.select('.ipsDataItem_lastPoster time')
                assert len(times) == 1
                last_post = parse_dt(times[0]['datetime'])

                yield SiteShow(name, topic_id, False, url,
                               topics, posts, last_post, gone_forever, is_tv)


add_href = re.compile(r'/\?do=add')


def merge_shows_list(show_dead=True):
    db.connect()
    br = None

    try:
        update_time = time.time()
        seen_forum_ids = {
            (s.has_forum, s.forum_id)
            for s in Show.select(Show.has_forum, Show.forum_id)
                         .where(Show.hidden)}

        for show in get_site_show_list():
            seen_forum_ids.add((show.has_forum, show.forum_id))

            # find matching show
            with db.atomic():
                r = list(Show.select().where(Show.forum_id == show.forum_id,
                                             Show.has_forum == show.has_forum))

                # handle converting between forum and thread
                if not r:
                    try:
                        old = Show.get(Show.name == show.name,
                                       Show.has_forum != show.has_forum)
                    except Show.DoesNotExist:
                        pass
                    else:
                        # make sure that old version is actually dead
                        if br is None:
                            br = make_browser()
                            login(br)
                        br.open(old.url)
                        if (br.response.ok
                                and br.find('a', href=add_href) is not None):
                            print("WARNING: {} confusion: {} and {}".format(
                                show.name, old.url, show.url),
                                  file=stderr)
                        else:
                            print("{} converted from {} to {}: {} - {}".format(
                                show.name,
                                "forum" if old.has_forum else "thread",
                                "thread" if old.has_forum else "forum",
                                old.url, show.url),
                                  file=stderr)
                            old.has_forum = show.has_forum
                            old.forum_id = show.forum_id
                            old.url = show.url
                            r = [old]

                if not r:
                    # show is on the site, not in the db
                    db_show = Show(
                        name=show.name,
                        tvdb_id_not_matched_yet=True,
                        forum_id=show.forum_id,
                        has_forum=show.has_forum,
                        url=show.url,
                        forum_posts=show.posts,
                        forum_topics=show.topics,
                        last_post=show.last_post,
                        # unlikely that needs_leads will ever hit, but...
                        needs_leads=show.posts + show.topics > 50,
                        gone_forever=show.gone_forever,
                        is_a_tv_show=show.is_tv,
                    )
                    db_show.save()
                    print("New show: {}".format(show.name), file=stderr)

                elif len(r) == 1:
                    # show both in the db and on the site
                    # update the posts
                    db_show, = r

                    if db_show.name != show.name:
                        m = "Name disagreement: '{0}' in db, renaming to '{1}'."
                        print(m.format(db_show.name, show.name), file=stderr)
                        db_show.name = show.name

                    if db_show.url != show.url:
                        m = "URL disagreement: '{0}' in db, changing to '{1}'."
                        print(m.format(db_show.url, show.url), file=stderr)
                        db_show.url = show.url

                    db_show.forum_posts = show.posts
                    db_show.forum_topics = show.topics
                    db_show.last_post = show.last_post
                    if show.gone_forever is not None:
                        db_show.gone_forever = show.gone_forever
                    if show.is_tv is not None:
                        if db_show.is_a_tv_show != show.is_tv:
                            m = "{}: we had as {}a tv show, site as {}one"
                            print(m.format(
                                show.name,
                                '' if db_show.is_a_tv_show else 'not ',
                                '' if show.is_tv else 'not '), file=stderr)
                            db_show.is_a_tv_show = show.is_tv
                    db_show.save()

                else:
                    m = "{} entries for {} - {}"
                    raise ValueError(m.format(len(r), show.name, show.forum_id))

        # patch up the mega-shows
        for mega, children_ids in iteritems(megashow_children):
            with db.atomic():
                child_topics, child_posts = (
                    Show.select(fn.sum(Show.forum_topics),
                                fn.sum(Show.forum_posts))
                        .where(Show.forum_id << list(children_ids))
                        .scalar(as_tuple=True))

                Show.update(
                    forum_topics=Show.forum_topics - child_topics,
                    forum_posts=Show.forum_posts - child_posts,
                ).where(Show.forum_id == mega).execute()

        # dead shows
        if show_dead:
            unseen = []
            for has_forum in [True, False]:
                seen_ids = [forum_id for h, forum_id in seen_forum_ids
                            if h is has_forum]
                if seen_ids:
                    unseen.extend(Show.select().where(
                        ~(Show.forum_id << seen_ids),
                        Show.has_forum == has_forum))
            s = '\n'.join(sorted(
                '\t{} - {}'.format(show.name, show.url) for show in unseen))
            if s:
                print("Didn't see the following shows:\n" + s, file=stderr)

        Meta.set_value('forum_update_time', update_time)
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
