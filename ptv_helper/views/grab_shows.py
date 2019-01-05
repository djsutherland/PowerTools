from __future__ import unicode_literals

import datetime
import itertools
import logging
import operator
import re
import time
import warnings
from collections import defaultdict, namedtuple

from flask import jsonify, render_template, url_for
from peewee import fn
from six import iteritems, text_type
from six.moves.urllib.parse import urlsplit, urlunsplit
from tzlocal import get_localzone
from unidecode import unidecode

from ptv_helper.app import app, celery, db
from ptv_helper.auth import require_superuser
from ptv_helper.helpers import ensure_logged_in, get_browser, parse_dt
from ptv_helper.models import Meta, Show, Turf, TURF_STATES

warnings.filterwarnings(
    'ignore', "No parser was explicitly specified", UserWarning)
warnings.filterwarnings(
    'ignore',
    message=r"Data truncated for column 'last_post' at row",
    # mysql doesn't handle timezone information, and peewee warns about that
    module='peewee',
)

logger = logging.getLogger('ptv_helper')

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
    'http://forums.previously.tv/forum/2361-t/',
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

forum_url_fmt = re.compile(r'https?://forums.previously.tv/forum/(\d+)-.*')
topic_url_fmt = re.compile(r'https?://forums.previously.tv/topic/(\d+)-.*')
SiteShow = namedtuple(
    'SiteShow', 'name forum_id has_forum url topics posts last_post '
                'gone_forever is_tv')

# populated as side-effect of get_site_show_list (gross)
megashow_children = defaultdict(set)


def parse_number(s):
    s = s.strip().lower()
    if s.endswith('k'):
        return int(float(s[:-1]) * 1000)
    else:
        return int(s.replace(',', ''))


add_href = re.compile(r'/\?do=add')
locked_msg = re.compile(r'now closed to further replies|topic is locked')


def is_locked(url, is_forum):
    br = get_browser()
    ensure_logged_in(br)
    br.open(url)

    if is_forum:
        return br.find('a', href=add_href) is None
    else:
        div = br.find(attrs={'data-role': 'replyArea'})
        if div is None:
            return True
        else:
            return div.find(text=locked_msg) is not None


vault_pattern = re.compile(r'(\[V(ault)?\]| Vault)\s*$')
other_shows_pattern = re.compile(r'^Other .* Shows$')


def get_site_show_list(pages=None):
    "Get all of the SiteShow info from the forum letter pages."
    br = get_browser()
    ensure_logged_in(br)

    if pages is None:
        global all_pages
        pages = all_pages
    page_queue = list(reversed(pages))
    while page_queue:
        page = page_queue.pop()

        br.open(page)
        if not br.response.ok:
            m = "HTTP code {} for {}"
            raise IOError(m.format(br.response.status_code, page))

        mega = page in megashows
        if mega:
            mega_id = forum_url_fmt.match(page).group(1)

        # do we have multiple pages?
        a = br.parsed.select_one('[data-role="tablePagination"] a[rel="next"]')
        if a and a.find_parent(class_='ipsPagination_inactive') is None:
            page_queue.append(a['href'])
            # TODO: will forums show up on page 2 (so we need to skip them)?
            # current organization doesn't have any like this...

        for forum_list in br.select('.cForumList'):
            for li in forum_list.select('li[data-forumid]'):
                if len(li.select('.cForumIcon_redirect')) > 0:
                    continue

                forum_id = li['data-forumid']
                a, = li.select('.ipsDataItem_title a:nth-of-type(1)')
                name = text_type(a.string).strip()
                url = text_type(a['href'])

                if other_shows_pattern.search(name):
                    page_queue.append(url)
                    continue
                if vault_pattern.search(name):
                    continue  # forum in the process of being vaulted

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

                if vault_pattern.search(name):
                    continue  # thread in the process of being vaulted

                # drop query string from url
                url = text_type(urlunsplit(urlsplit(
                    a['href'])[:-2] + (None, None)))

                # leave these as default bc no way to know...
                gone_forever = None
                is_tv = None

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


def get_site_show(url):
    "Get SiteShow info from a show page."
    forum_match = forum_url_fmt.match(url)
    topic_match = topic_url_fmt.match(url)

    gone_forever = is_tv = None  # can't get these directly from the site page
    last_post = None  # haven't bothered implementing yet

    br = get_browser()
    br.open(url)

    if forum_match:
        has_forum = True
        forum_id = forum_match.group(1)
        name = br.parsed.select_one('.forum-title').text.strip()
        topics = posts = None  # annoying to get from forum page directly

    elif topic_match:
        has_forum = False
        forum_id = topic_match.group(1)
        name = br.parsed.select_one('.topic-title').text.strip()
        topics = 0

        num, post_txt = br.parsed.select_one(
            '.topic-meta-inline .ptvf-comment').parent.text.strip().split()
        assert post_txt.lower() in {'post', 'posts'}
        posts = parse_number(num)
    else:
        raise ValueError("confusing URL '{}'".format(url))

    return SiteShow(name, forum_id, has_forum, url, topics, posts, last_post,
                    gone_forever, is_tv)


def update_show_info(site_show):
    # find matching show
    with db.atomic():
        r = list(Show.select().where(Show.forum_id == site_show.forum_id,
                                     Show.has_forum == site_show.has_forum))
        copy_turfs = []

        # handle converting between forum and thread
        if not r:
            try:
                old = Show.get(Show.name == site_show.name,
                               Show.has_forum != site_show.has_forum)
            except Show.DoesNotExist:
                pass
            else:
                # make sure that the old version is actually dead
                old_alive = old.deleted_at is None

                if old_alive:
                    br = get_browser()
                    br.open(old.url)
                    old_alive = br.response.ok

                if old_alive and any(
                        c.text.strip().endswith(' Vault')
                        for c in br.select(
                            '[data-role="breadcrumbList"] a')):
                    old_alive = False

                if old_alive and is_locked(old.url, old.has_forum):
                    old_alive = False

                if old_alive and is_locked(site_show.url, site_show.has_forum):
                    # this is the forum for a locked show
                    return

                if old_alive:
                    logger.warn(
                        "WARNING: {} confusion: {} and {}".format(
                            site_show.name, old.url, site_show.url))
                    copy_turfs = old.turf_set
                else:
                    logger.info(
                        "{} converted from {} to {}: {} - {}".format(
                            site_show.name,
                            "forum" if old.has_forum else "thread",
                            "thread" if old.has_forum else "forum",
                            old.url, site_show.url))
                    old.has_forum = site_show.has_forum
                    old.forum_id = site_show.forum_id
                    old.url = site_show.url
                    r = [old]

        if not r:
            def _maybe(x, default):
                return default if x is None else x

            # show is on the site, not in the db
            db_show = Show(
                name=site_show.name,
                tvdb_id_not_matched_yet=True,
                forum_id=site_show.forum_id,
                has_forum=site_show.has_forum,
                url=site_show.url,
                forum_posts=_maybe(site_show.posts, 0),
                forum_topics=_maybe(site_show.topics, 0),
                last_post=_maybe(site_show.last_post,
                                 datetime.datetime.today()),
                # unlikely that needs_leads will ever hit, but...
                needs_leads=site_show.posts + site_show.topics > 50,
                gone_forever=_maybe(site_show.gone_forever, False),
                is_a_tv_show=_maybe(site_show.is_tv, True),
            )
            db_show.save()

            if copy_turfs:
                data = []
                for t in copy_turfs:
                    d = t.__data__.copy()
                    d['show'] = db_show.id
                    data.append(d)
                Turf.insert_many(data).execute()

            logger.info("New show: {}".format(site_show.name))
            return db_show

        elif len(r) == 1:
            # show both in the db and on the site
            # update the posts
            db_show, = r

            if db_show.name != site_show.name:
                if (unidecode(db_show.name).lower()
                        != unidecode(site_show.name).lower()):
                    m = "Name disagreement: '{}' in db, renaming to '{}'."
                    logger.info(m.format(db_show.name, site_show.name))
                db_show.name = site_show.name

            if db_show.url != site_show.url:
                m = "URL disagreement: '{}' in db, changing to '{}'."
                logger.info(m.format(db_show.url, site_show.url))
                db_show.url = site_show.url

            if site_show.posts is not None:
                db_show.forum_posts = site_show.posts
            if site_show.topics is not None:
                db_show.forum_topics = site_show.topics
            if site_show.last_post is not None:
                db_show.last_post = site_show.last_post
            if site_show.gone_forever is not None:
                db_show.gone_forever = site_show.gone_forever
            if site_show.is_tv is not None:
                if db_show.is_a_tv_show != site_show.is_tv:
                    m = "{}: we had as {}a tv show, site as {}one"
                    logger.info(m.format(
                        site_show.name,
                        '' if db_show.is_a_tv_show else 'not ',
                        '' if site_show.is_tv else 'not '))
                    db_show.is_a_tv_show = site_show.is_tv
            db_show.deleted_at = None
            db_show.save()
            return db_show

        else:
            raise ValueError("{} entries for {} - {}".format(
                len(r), site_show.name, site_show.forum_id))


@celery.task(bind=True)
def merge_shows_list(self, pages=None):
    if self.request.id is None:
        # celery crashes on self.update_state when task_id is None
        # ("expected a bytes-like object, NoneType found")
        def progress(**meta):
            pass
    else:
        def progress(**meta):
            self.update_state(state='PROGRESS', meta=meta)

    update_time = time.time()
    seen_forum_ids = {
        (s.has_forum, s.forum_id)
        for s in Show.select(Show.has_forum, Show.forum_id)
                     .where(Show.hidden)}

    for i, site_show in enumerate(get_site_show_list(pages=pages)):
        progress(step='main', current=i)
        seen_forum_ids.add((site_show.has_forum, site_show.forum_id))
        update_show_info(site_show)

    progress(step='wrapup')
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

    # mark unseen shows as deleted
    unseen = []
    for has_forum in [True, False]:
        seen_ids = [forum_id for h, forum_id in seen_forum_ids
                    if h is has_forum]
        if seen_ids:
            unseen.extend(Show.select().where(
                ~(Show.forum_id << seen_ids),
                Show.has_forum == has_forum))

    now = datetime.datetime.fromtimestamp(update_time)
    thresh = datetime.timedelta(days=7)
    get_state = operator.attrgetter('state')
    for s in unseen:
        if s.deleted_at is None:
            s.deleted_at = now
            s.save()
        elif (now - s.deleted_at) > thresh:
            mod_info = []
            bits = {k: ', '.join(t.mod.name for t in v)
                    for k, v in itertools.groupby(
                        s.turf_set.order_by(Turf.state), key=get_state)}
            for k, n in TURF_STATES.items():
                if k in bits:
                    mod_info.append('{}: {}'.format(n, bits[k]))
            if not mod_info:
                mod_info.append('no mods')
            tvdb_info = ', '.join(str(st.tvdb_id) for st in s.tvdb_ids)
            logger.info("Deleting {} ({}) ({})".format(
                    s.name, '; '.join(mod_info), tvdb_info))
            s.delete_instance()

    Meta.set_value('forum_update_time', update_time)

    for h in logger.handlers:
        h.flush()


@app.route('/grab-shows/start/', methods=['POST'])
@require_superuser
def grab_start():
    task = merge_shows_list.apply_async()
    body = {
        'pathname': url_for('grab_control', task_id=task.id),
    }
    headers = {
        'Location': url_for('grab_status', task_id=task.id),
    }
    return jsonify(body), 202, headers


@app.route('/grab-shows/status/<task_id>/')
def grab_status(task_id):
    task = merge_shows_list.AsyncResult(task_id)
    resp = {'state': task.state}
    if task.state == 'FAILURE':
        resp['status'] = 'ERROR: {}'.format(task.info)
    elif task.state == 'PENDING':
        resp['status'] = 'Pending...'
    elif task.state == 'SUCCESS':
        resp['status'] = 'Done!'
    else:
        resp.update(task.info)
        if task.info.get('step') == 'main':
            resp['status'] = "Processing show {:,} of about {:,}".format(
                task.info['current'],
                Show.select(fn.COUNT('*')).scalar())
        elif task.info.get('step') == 'wrapup':
            resp['status'] = "Wrapping up"
        else:
            resp['status'] = str(task.info)  # not sure what happened here...
    return jsonify(resp)


@app.route('/grab-shows/')
@app.route('/grab-shows/going/<task_id>/')
def grab_control(task_id=None):
    tz = get_localzone()
    return render_template(
        'grab_shows.html',
        update_time=tz.localize(datetime.datetime.fromtimestamp(
            float(Meta.get_value('forum_update_time', 0)))),
        yesterday=tz.localize(
            datetime.datetime.now() - datetime.timedelta(days=1)),
        task_id=task_id)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    args = parser.parse_args()

    with app.app_context():
        merge_shows_list(**vars(args))


if __name__ == '__main__':
    main()
