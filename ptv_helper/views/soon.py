from __future__ import unicode_literals
import datetime
import itertools

from flask import render_template
from flask_login import current_user, login_required
from peewee import fn, JOIN

from ..app import app
from ..helpers import strip_the
from ..models import Episode, Show, ShowTVDB, TURF_STATES


################################################################################
### Episodes airing soon

def get_airing_soon(start=None, end=None, days=3):
    "Returns episodes of shows airing in [start, end)."
    if start is None:
        start = datetime.date.today() - datetime.timedelta(days=1)
    if end is None:
        end = start + datetime.timedelta(days=days)

    date_fmt = '{:%Y-%m-%d}'
    return (Episode
        .select()
        .join(Show)
        .where(
            (fn.date(Episode.first_aired).between(
                date_fmt.format(start), date_fmt.format(end)))
            & (Show.we_do_ep_posts == 1))
        .order_by(fn.date(Episode.first_aired).asc())
    )


@app.route('/soon/')
@app.route('/soon/<int:days>')
def eps_soon(days=3):
    soon = sorted(
        (datetime.datetime.strptime(date, '%Y-%m-%d').date(),
         sorted(eps, key=lambda e: (strip_the(e.show.name).lower(),
                                    strip_the(e.name).lower())))
        for date, eps in itertools.groupby(get_airing_soon(days=days),
                                           key=lambda e: e.first_aired))
    return render_template('eps_soon.html', soon=soon)


################################################################################
### "My" shows' next episodes

@app.route('/my-next/')
@login_required
def my_shows_next():
    # just get all the eps and filter in python, instead of trying to do
    # some absurd sql
    show_states = {t.show_id: t.state for t in current_user.turf_set}
    eps = (Episode
        .select()
        .join(Show)
        .where(
            (Episode.show << list(show_states))
          & (Show.gone_forever == 0)
          & (Show.we_do_ep_posts == 1)
        )
        .order_by(Show.id)
    )

    today = '{:%Y-%m-%d}'.format(datetime.date.today())
    last_and_next = {state: [] for state in TURF_STATES}

    if show_states:
        key = lambda e: (e.show_id, e.show.forum_id, e.show.url, e.show.name)
        for (showid, forum_id, url, showname), show_eps \
                in itertools.groupby(eps, key):
            # sort by date here instead of in sql, because dunno how to tell sql
            # to sort missing dates last
            show_eps = sorted(show_eps,
                              key=lambda x: x.first_aired or '9999-99-99')
            last_ep = None
            next_ep = None
            for next_ep in show_eps:
                if next_ep.first_aired > today or next_ep.first_aired is None:
                    break
                last_ep = next_ep
            else:  # loop ended without finding something in future
                next_ep = None

            show_info = (forum_id, url, showname)
            last_and_next[show_states[showid]].append(
                (show_info, last_ep, next_ep))
        last_and_next = {
           k: sorted(v, key=lambda inf: strip_the(inf[0][2]).lower())
           for k, v in last_and_next.iteritems()
        }

    my_turfs = current_user.turf_set.join(Show).order_by(Show.name)
    non_shows = [t.show for t in my_turfs.where(~Show.is_a_tv_show)]
    my_shows = my_turfs.where(Show.is_a_tv_show)
    over = [t.show for t in my_shows.where(Show.gone_forever)]
    not_per_ep = [t.show for t in my_shows.where(~Show.we_do_ep_posts)]
    no_tvdb = [t.show for t in my_shows.join(ShowTVDB, JOIN.LEFT_OUTER)
                                       .where(ShowTVDB.tvdb_id >> None)]

    return render_template(
        'my_shows_next.html',
        last_and_next=last_and_next, state_names=TURF_STATES,
        over=over, not_per_ep=not_per_ep, non_shows=non_shows, no_tvdb=no_tvdb)
