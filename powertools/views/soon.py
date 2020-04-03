from collections import namedtuple
import datetime
import itertools

from flask import render_template
from flask_login import current_user, login_required
from peewee import JOIN, fn

from ..base import app
from ..helpers import strip_the
from ..models import Episode, Show, ShowTVDB, TURF_ORDER, TURF_STATES


################################################################################
### Episodes airing soon

def get_airing_soon(start=None, end=None, days=3):
    "Returns episodes of shows airing in [start, end)."
    if start is None:
        start = datetime.date.today() - datetime.timedelta(days=1)
    if end is None:
        end = start + datetime.timedelta(days=days)

    date_fmt = '{:%Y-%m-%d}'
    date_right = (fn.date(Episode.first_aired)
                    .between(date_fmt.format(start), date_fmt.format(end)))
    return (Episode.select()
                   .join(Show)
                   .where(date_right)
                   .order_by(fn.date(Episode.first_aired).asc()))


@app.route('/soon/')
@app.route('/soon/<int:days>')
def eps_soon(days=3):
    soon = sorted(
        (date,
         sorted(eps, key=lambda e: (strip_the(e.show.name).lower(),
                                    strip_the(e.name).lower())))
        for date, eps in itertools.groupby(get_airing_soon(days=days),
                                           key=lambda e: e.first_aired))
    return render_template('eps_soon.html', soon=soon)


################################################################################
### "My" shows' next episodes

far_future = datetime.date(9999, 1, 1)


@app.route('/my-next/')
@login_required
def my_shows_next():
    # just get all the eps and filter in python, instead of trying to do
    # some absurd sql
    show_states = {t.showid: t.state for t in current_user.turf_set}
    query = (Show.id << list(show_states)
             & (Show.gone_forever == 0)
             & (Show.deleted_at >> None) & ~Show.hidden & Show.is_a_tv_show)
    eps = Episode.select().join(Show).where(query).order_by(Show.id)
    no_ep_shows = (Show.select().join(Episode, JOIN.LEFT_OUTER).where(query)
                   .where(Episode.id >> None))

    today = datetime.date.today()
    last_and_next = {state: [] for state in TURF_STATES}

    if show_states:
        ShowInfo = namedtuple('ShowInfo', 'show_id has_forum forum_id url name')
        key = lambda e: ShowInfo(e.showid, e.show.has_forum, e.show.forum_id,
                                 e.show.url, e.show.name)
        for (showid, has_forum, forum_id, url, showname), show_eps \
                in itertools.groupby(eps, key):
            # sort by date here instead of in sql, because dunno how to tell sql
            # to sort missing dates last
            show_eps = sorted(show_eps,
                              key=lambda x: x.first_aired or far_future)
            last_ep = None
            next_ep = None
            for next_ep in show_eps:
                if not next_ep.first_aired or next_ep.first_aired > today:
                    break
                last_ep = next_ep
            else:  # loop ended without finding something in future
                next_ep = None

            show_info = ShowInfo(showid, has_forum, forum_id, url, showname)
            last_and_next[show_states[showid]].append(
                (show_info, last_ep, next_ep))
        last_and_next = {
           k: sorted(v, key=lambda inf: strip_the(inf[0].name).lower())
           for k, v in last_and_next.items()
        }

    my_turfs = current_user.turf_set.join(Show).order_by(Show.name)
    non_shows = [t.show for t in my_turfs.where(~Show.is_a_tv_show)]
    my_shows = my_turfs.where(Show.is_a_tv_show)
    over = [t.show for t in my_shows.where(Show.gone_forever)]
    no_tvdb = [t.show for t in my_shows.join(ShowTVDB, JOIN.LEFT_OUTER)
                                       .where(ShowTVDB.tvdb_id >> None)]
    no_ep_shows = [s for s in no_ep_shows if s not in no_tvdb]

    return render_template(
        'my_shows_next.html',
        last_and_next=last_and_next, state_names=TURF_STATES,
        over=over, non_shows=non_shows, no_tvdb=no_tvdb,
        no_ep_shows=no_ep_shows,
        TURF_ORDER=TURF_ORDER)
