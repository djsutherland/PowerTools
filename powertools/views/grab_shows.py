import datetime
import itertools
import logging
import operator
import re
import time
from urllib.parse import urlsplit, urlunsplit
import warnings
from collections import namedtuple

from flask import jsonify, redirect, render_template, url_for
from peewee import fn
import redis_lock
from tzlocal import get_localzone
from unidecode import unidecode

from ..base import app, celery, db, redis
from ..auth import require_test
from ..helpers import ensure_logged_in, get_browser, parse_dt, SITE_BASE
from ..models import Meta, Show, Turf, TURF_STATES

warnings.filterwarnings("ignore", "No parser was explicitly specified", UserWarning)
warnings.filterwarnings(
    "ignore",
    message=r"Data truncated for column 'last_post' at row",
    # mysql doesn't handle timezone information, and peewee warns about that
    module="peewee",
)

logger = logging.getLogger("powertools")

forum_base = SITE_BASE + "/forum/"
category_pages = {
    forum_base + s + "/"
    for s in {
        "4339-drama",
        "4340-comedy",
        "4341-genre-television",
        "4342-candid-reality",
        "4372-competitive-reality-game-shows",
        "4345-lifestyle-reality",
        "4344-soap-opera",
        "4346-kids-animated",
        "4347-talk-news-non-fiction",
        "4990-limited-series-one-offs",
    }
}
subcategory_pages = {
    forum_base + s + "/"
    for s in {
        "4355-other-dramas",
        "4353-other-comedies",
        "4360-other-genre-television",
        "4359-other-candid-reality-shows",
        "4373-other-competitive-reality-shows",
        "4358-other-lifestyle-reality-shows",
        "4361-other-soaps",
        "4357-other-kids-animated-shows",
        "4362-other-non-fiction-shows",
        "4593-star-trek-shows",
        "4992-limited-event-series",
    }
}
non_show_pages = {
    forum_base + s + "/"
    for s in {
        "4349-other-tv-talk",
        "4351-pop-culture",
        "4352-interests-hobbies",
        "52-site-business",
    }
}
all_categories = category_pages | subcategory_pages | non_show_pages

standalone_forums = {
    forum_base + s + "/"
    for s in {
        "351-everything-else",
        # inside the NCIS forum
        "4846-ncis-hawaii",
        "312-ncis-los-angeles",
        "802-ncis-new-orleans",
        # inside The Rookie
        "4988-the-rookie-feds",
    }
}

forum_url_fmt = re.compile(re.escape(SITE_BASE) + r"/forum/(\d+)-.*")
topic_url_fmt = re.compile(re.escape(SITE_BASE) + r"/topic/(\d+)-.*")
SiteShow = namedtuple(
    "SiteShow",
    "name forum_id has_forum url topics posts last_post " "gone_forever is_tv",
)


def parse_number(s):
    s = s.strip().lower()
    if s.endswith("k"):
        return int(float(s[:-1]) * 1000)
    else:
        return int(s.replace(",", ""))


add_href = re.compile(r"/\?do=add")
locked_msg = re.compile(r"now closed to further replies|topic is locked")


def is_locked(url, is_forum):
    br = get_browser()
    # ensure_logged_in(br)
    br.open(url)

    if is_forum:
        return br.find("a", href=add_href) is None
    else:
        div = br.find(attrs={"data-role": "replyArea"})
        if div is None:
            return True
        else:
            return div.find(text=locked_msg) is not None


def get_site_show_list(categories=None, standalones=None):
    "Get all of the SiteShow info from the forum letter pages."
    br = get_browser()
    ensure_logged_in(br)

    if categories is None:
        global all_categories
        categories = all_categories

    if standalones is None:
        global standalone_forums
        standalones = standalone_forums

    for page in standalones:
        yield get_site_show(page)

    page_queue = [(page, True) for page in categories]
    while page_queue:
        page, do_subfora = page_queue.pop()

        br.open(page)
        if not br.response.ok:
            m = "HTTP code {} for {}"
            raise IOError(m.format(br.response.status_code, page))

        # do we have multiple pages?
        a = br.parsed.select_one('[data-role="tablePagination"] a[rel="next"]')
        if a and a.find_parent(class_="ipsPagination_inactive") is None:
            page_queue.append((a["href"], False))

        fora = br.select(".cForumList li[data-forumid]") if do_subfora else []
        for li in fora:
            if len(li.select(".cForumIcon_redirect")) > 0:
                continue

            forum_id = li["data-forumid"]
            # sometimes there are "queued posts" links in here,
            # but they're inside a <strong>.
            a = li.select_one(".ipsDataItem_title > a:nth-of-type(1)")
            name = str(a.string).strip()
            url = str(a["href"])

            if url in subcategory_pages:
                continue

            gone_forever = None  # not tracked anymore
            is_tv = page not in non_show_pages

            topics = 0  # doesn't seem to be available anymore
            dts = li.select(".ipsDataItem_stats dt")
            if len(dts) == 1:
                posts = parse_number(dts[0].string)
            elif len(dts) == 0:
                posts = 0
            else:
                s = "{} stats entry for {} - {}"
                raise ValueError(s.format(len(dts), name, page))

            times = li.select("time")
            if len(times) == 0:
                last_post = None
            elif len(times) == 1:
                last_post = parse_dt(times[0]["datetime"])
            else:
                s = "{} time entries for {} - {}"
                raise ValueError(s.format(len(times), name, page))

            yield SiteShow(
                name, forum_id, True, url, topics, posts, last_post, gone_forever, is_tv
            )

        for li in br.select(".cTopicList li[data-rowid]"):
            if li.select('.ipsBadge[title^="Hidden"]'):
                continue
            # TODO: redirects here?

            topic_id = li["data-rowid"]
            (a,) = li.select(".ipsDataItem_title a[data-ipshover]")
            (name,) = a.stripped_strings
            name = str(name)

            # drop query string from url
            url = urlunsplit(urlsplit(a["href"])[:-2] + (None, None))

            gone_forever = None  # leave as default
            is_tv = page not in non_show_pages

            topics = 0
            (stats,) = li.select(".ipsDataItem_stats")
            lis = stats.select("li")
            assert len(lis) == 2
            assert lis[0].select_one(".ipsDataItem_stats_type").text.strip() in {
                "reply",
                "replies",
            }
            posts = parse_number(lis[0].select(".ipsDataItem_stats_number")[0].string)

            times = li.select(".ipsDataItem_lastPoster time")
            assert len(times) == 1
            last_post = parse_dt(times[0]["datetime"])

            yield SiteShow(
                name,
                topic_id,
                False,
                url,
                topics,
                posts,
                last_post,
                gone_forever,
                is_tv,
            )


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
        name = br.parsed.select_one(".ipsType_pageTitle").text.strip()
        topics = posts = None  # annoying to get from forum page directly

    elif topic_match:
        has_forum = False
        forum_id = topic_match.group(1)
        name = br.parsed.select_one(".ipsType_pageTitle").text.strip()
        topics = 1
        posts = None  # annoying to get from thread directly now
    else:
        raise ValueError("confusing URL '{}'".format(url))

    return SiteShow(
        name, forum_id, has_forum, url, topics, posts, last_post, gone_forever, is_tv
    )


def update_show_info(site_show):
    # find matching show
    with db.atomic():
        r = list(
            Show.select().where(
                Show.forum_id == site_show.forum_id,
                Show.has_forum == site_show.has_forum,
            )
        )
        copy_turfs = []

        # handle converting between forum and thread
        if not r:
            try:
                old = Show.get(
                    Show.name == site_show.name, Show.has_forum != site_show.has_forum
                )
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
                    c.text.strip().endswith(" Vault")
                    for c in br.select('[data-role="breadcrumbList"] a')
                ):
                    old_alive = False

                if old_alive and is_locked(old.url, old.has_forum):
                    old_alive = False

                if old_alive and is_locked(site_show.url, site_show.has_forum):
                    # this is the forum for a locked show
                    return

                if old_alive:
                    logger.warn(
                        "WARNING: {} confusion: {} and {}".format(
                            site_show.name, old.url, site_show.url
                        )
                    )
                    copy_turfs = old.turf_set
                else:
                    logger.info(
                        "{} converted from {} to {}: {} - {}".format(
                            site_show.name,
                            "forum" if old.has_forum else "thread",
                            "thread" if old.has_forum else "forum",
                            old.url,
                            site_show.url,
                        )
                    )
                    old.has_forum = site_show.has_forum
                    old.forum_id = site_show.forum_id
                    old.url = site_show.url
                    r = [old]

        if not r:

            def _maybe(x, default):
                return default if x is None else x

            # show is on the site, not in the db
            if site_show.posts is not None and site_show.topics is not None:
                needs_help = site_show.posts + site_show.topics > 100
            else:
                needs_help = False

            db_show = Show(
                name=site_show.name,
                tvdb_id_not_matched_yet=True,
                forum_id=site_show.forum_id,
                has_forum=site_show.has_forum,
                url=site_show.url,
                forum_posts=_maybe(site_show.posts, 0),
                forum_topics=_maybe(site_show.topics, 0),
                last_post=_maybe(site_show.last_post, datetime.datetime.today()),
                # unlikely this will ever hit, but...
                needs_help=needs_help,
                gone_forever=_maybe(site_show.gone_forever, False),
                is_a_tv_show=_maybe(site_show.is_tv, True),
            )
            db_show.save()

            if copy_turfs:
                data = []
                for t in copy_turfs:
                    d = t.__data__.copy()
                    d["show"] = db_show.id
                    data.append(d)
                Turf.insert_many(data).execute()

            logger.info("New show: {}".format(site_show.name))
            return db_show

        elif len(r) == 1:
            # show both in the db and on the site
            # update the posts
            (db_show,) = r

            if db_show.name != site_show.name:
                if unidecode(db_show.name).lower() != unidecode(site_show.name).lower():
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
            else:
                # guess gone_forever based on TVDB
                statuses = {x.status for x in db_show.tvdb_ids if x.status}
                if "Continuing" in statuses:
                    db_show.gone_forever = False
                elif statuses == {"Ended"}:
                    db_show.gone_forever = True
                else:
                    pass  # inconclusive, leave as-is
            if site_show.is_tv is not None:
                if db_show.is_a_tv_show != site_show.is_tv:
                    m = "{}: we had as {}a tv show, site as {}one"
                    logger.info(
                        m.format(
                            site_show.name,
                            "" if db_show.is_a_tv_show else "not ",
                            "" if site_show.is_tv else "not ",
                        )
                    )
                    db_show.is_a_tv_show = site_show.is_tv
            db_show.deleted_at = None
            db_show.save()
            return db_show

        else:
            raise ValueError(
                "{} entries for {} - {}".format(
                    len(r), site_show.name, site_show.forum_id
                )
            )


@celery.task(bind=True)
def merge_shows_list(self, **kwargs):
    lock = redis_lock.Lock(redis, "lock_grab_shows", expire=600, auto_renewal=True)
    if not lock.acquire(blocking=False):
        raise redis_lock.NotAcquired("another update is in progress")

    try:
        if self.request.id is None:
            # celery crashes on self.update_state when task_id is None
            # ("expected a bytes-like object, NoneType found")
            def progress(**meta):
                pass

            redis.set("grab_shows_taskid", "NOT IN CELERY")
        else:

            def progress(**meta):
                self.update_state(state="PROGRESS", meta=meta)

            redis.set("grab_shows_taskid", self.request.id.encode())

        try:
            _do_merge_shows_list(self, progress=progress, **kwargs)
        finally:
            redis.delete("grab_shows_taskid")
    finally:
        for h in logger.handlers:
            h.flush()
        lock.release()


def merge_is_running():
    lock = redis_lock.Lock(redis, "lock_grab_shows", expire=2)
    if lock.acquire(blocking=False):
        lock.release()
        return False
    else:
        return True


def start_or_join_merge_shows_list(**kwargs):
    if merge_is_running():
        task_id = redis.get("grab_shows_taskid").decode()
        if task_id == "NOT IN CELERY":
            raise ValueError("update currently happening outside celery, can't join")
        return merge_shows_list.AsyncResult(task_id)
    else:
        return merge_shows_list.apply_async(kwargs=kwargs)


def _do_merge_shows_list(self, progress, **kwargs):
    update_time = time.time()
    seen_forum_ids = {
        (s.has_forum, s.forum_id)
        for s in Show.select(Show.has_forum, Show.forum_id).where(Show.hidden)
    }

    for i, site_show in enumerate(get_site_show_list(**kwargs)):
        progress(step="main", current=i)
        seen_forum_ids.add((site_show.has_forum, site_show.forum_id))
        update_show_info(site_show)

    progress(step="wrapup")
    # mark unseen shows as deleted
    unseen = []
    for has_forum in [True, False]:
        seen_ids = [forum_id for h, forum_id in seen_forum_ids if h is has_forum]
        if seen_ids:
            unseen.extend(
                Show.select().where(
                    ~(Show.forum_id << seen_ids), Show.has_forum == has_forum
                )
            )

    now = datetime.datetime.fromtimestamp(update_time)
    thresh = datetime.timedelta(days=1)
    get_state = operator.attrgetter("state")
    for s in unseen:
        if s.deleted_at is None:
            s.deleted_at = now
            s.save()
        elif (now - s.deleted_at) > thresh:
            mod_info = []
            bits = {
                k: ", ".join(t.mod.name for t in v)
                for k, v in itertools.groupby(
                    s.turf_set.order_by(Turf.state), key=get_state
                )
            }
            for k, n in TURF_STATES.items():
                if k in bits:
                    mod_info.append("{}: {}".format(n, bits[k]))
            if not mod_info:
                mod_info.append("no mods")
            tvdb_info = ", ".join(str(st.tvdb_id) for st in s.tvdb_ids)
            logger.info(
                "Deleting {} ({}) ({})".format(s.name, "; ".join(mod_info), tvdb_info)
            )
            s.delete_instance()

    Meta.set_value("forum_update_time", update_time)


@app.route("/grab-shows/start/", methods=["POST"])
@require_test(lambda u: u.can_manage_turfs, json=True)
def grab_start():
    task = start_or_join_merge_shows_list()
    body = {
        "pathname": url_for("grab_control", task_id=task.id),
    }
    headers = {
        "Location": url_for("grab_status", task_id=task.id),
    }
    return jsonify(body), 202, headers


def get_status_info(task):
    resp = {"state": task.state}
    if task.state == "FAILURE":
        resp["status"] = "ERROR: {}".format(task.info)
    elif task.state == "PENDING":
        resp["status"] = "Pending..."
    elif task.state == "SUCCESS":
        resp["status"] = "Done!"
    else:
        resp.update(task.info)
        if task.info.get("step") == "main":
            resp["status"] = "Processing show {:,} of about {:,}".format(
                task.info["current"], Show.select(fn.COUNT("*")).scalar()
            )
        elif task.info.get("step") == "wrapup":
            resp["status"] = "Wrapping up"
        else:
            resp["status"] = str(task.info)  # not sure what happened here...
    return resp


@app.route("/grab-shows/status/<task_id>/")
def grab_status(task_id):
    task = merge_shows_list.AsyncResult(task_id)
    return jsonify(get_status_info(task))


@app.route("/grab-shows/")
@app.route("/grab-shows/going/<task_id>/")
def grab_control(task_id=None):
    if task_id is None and merge_is_running():
        task_id = redis.get("grab_shows_taskid").decode()
        if task_id != "NOT IN CELERY":
            return redirect(url_for("grab_control", task_id=task_id))

    tz = get_localzone()
    return render_template(
        "grab_shows.html",
        update_time=tz.localize(
            datetime.datetime.fromtimestamp(
                float(Meta.get_value("forum_update_time", 0))
            )
        ),
        yesterday=tz.localize(datetime.datetime.now() - datetime.timedelta(days=1)),
        task_id=task_id,
    )


def main():
    import argparse

    parser = argparse.ArgumentParser()
    args = parser.parse_args()

    with app.app_context():
        merge_shows_list(**vars(args))


if __name__ == "__main__":
    main()
