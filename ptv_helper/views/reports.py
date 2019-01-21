# coding=utf-8
from __future__ import unicode_literals
import datetime
import re
import traceback
import warnings

from flask import Response
from six.moves.urllib.parse import urlsplit, urlunsplit

from ..app import app, celery, redis
from ..helpers import SITE_BASE, get_browser, open_with_login, require_local
from ..models import Mod, Report, Show, TURF_LOOKUP, Turf
from .grab_shows import get_site_show, other_shows_pattern, update_show_info


REPORT_URL = re.compile(
    r'{}/modcp/reports/(\d+)(?:/(?:\?page=\d+)?)?$'.format(SITE_BASE))

warnings.filterwarnings(
    'ignore', "No parser was explicitly specified", UserWarning)


def get_reports():
    br = get_browser()

    # only gets from the first page, for now
    open_with_login(br, '{}/modcp/reports/'.format(SITE_BASE))
    resp = []
    for a in br.select('h4 a[href^="{}/modcp/reports/"]'.format(SITE_BASE)):
        report_id = int(REPORT_URL.match(a.attrs['href']).group(1))
        resp.append((a.text.strip(), report_id))
    return resp


def report_forum(report_id):
    br = get_browser()

    url = '{}/modcp/reports/{}/?action=find'.format(SITE_BASE, report_id)
    open_with_login(br, url)
    if br.url.startswith('{}/messenger/'.format(SITE_BASE)):
        return Show.get(Show.name == 'PMs')
    if br.url == url and br.find(id='elError'):
        # "Sorry, there is a problem" shown when the reported content
        # is already deleted.
        return None

    # drop query string, fragment from url
    base_url = urlunsplit(urlsplit(br.url)[:-2] + (None, None))
    try:
        return Show.get(Show.url == base_url)
    except Show.DoesNotExist:
        pass

    crumbs = br.select(".ipsBreadcrumb li a[href^='{}/forum/']".format(SITE_BASE))
    for a in reversed(crumbs):
        # if we hit an Other XYZ Shows category, then this must be a new thread
        if other_shows_pattern.search(a.text.strip()):
            return update_show_info(get_site_show(crumbs[-1]['href']))

        try:
            return Show.get(Show.url == a['href'])
        except Show.DoesNotExist:
            pass

    return None


def _mention(user, text):
    if not user.profile_url or not user.forum_id:
        me = Mod.get(Mod.name == 'Dougal')
        return ('@{u.name} [except {me} forgot to hook them up in the db '
                'ಠ_ಠ, so someone else should at-mention them properly and '
                'yell at {me} to fix it]').format(u=user, me=at_mention(me))

    return ('''<a contenteditable="false" data-ipshover="" '''
            '''data-ipshover-target="{u.profile_url}?do=hovercard" '''
            '''data-mentionid="{u.forum_id}" href="{u.profile_url}" '''
            '''rel="">{text}</a>''').format(u=user, text=text)


def at_mention(user):
    return _mention(user, '@{}'.format(user.name))


def quiet_mention(user):
    return _mention(user, '')


def build_comment(report_id, show):
    interested = Mod.select().where(Mod.reports_interested)
    c = ''.join(quiet_mention(u) for u in interested)

    if show is None:
        c += ("<strong>Unknown show.</strong> (If it isn't something "
              "brand-new, vaulted, or a post that got deleted "
              "super-fast, then I might be malfunctioning.)")
        return c

    turfs = show.turf_set.join(Mod).order_by(Mod.name)
    leads = [t.mod for t in turfs.where(Turf.state == TURF_LOOKUP['lead'])]
    backups = [t.mod for t in turfs.where(Turf.state == TURF_LOOKUP['backup'])]

    c += '<a href="{show.url}">{show.name}</a>'.format(show=show)

    if leads:
        c += ' leads: ' + ', '.join(at_mention(m) for m in leads) + '.'
        if backups:
            c += ' Backups: ' + ', '.join(m.name for m in backups) + '.'
    elif backups:
        c += ': No leads for this show.'
        c += ' Backups: ' + ', '.join(at_mention(m) for m in backups) + '.'
    else:
        c += ': <strong>No mods for this show.</strong>'

        watch = [t.mod for t in turfs.where(Turf.state == TURF_LOOKUP['watch'])]
        if watch:
            c += ' ' + ', '.join(at_mention(m) for m in watch)
            c += ' say they could help.'
        elif not show.has_forum:
            team = list(Mod.select().where(Mod.is_turfs_manager))
            if team:
                c += '(CC: {})'.format(', '.join(at_mention(u) for u in team))

    c += (' (<a href="https://powertools.previously.tv/turfs/#show-{}">'
          'turfs entry</a>)').format(show.id)
    return c


def comment_on(report):
    br = get_browser()

    c = build_comment(report.report_id, report.show)
    url = '{}/modcp/reports/{}/'.format(SITE_BASE, report.report_id)
    open_with_login(br, url)

    f = br.get_form(method='post', class_='ipsForm')
    f['report_comment_{}_noscript'.format(report.report_id)] = c
    br.submit_form(f)

    err = br.parsed.find(attrs={'data-role': 'commentFormError'})
    if err:
        raise ValueError('''Submission error on report {}: {}'''.format(
            report.report_id, '\n'.join(err.contents)))

    report.commented = True
    report.save()


@celery.task
def handle_report(report_id, name):
    lock = redis.lock("handle_report_{}".format(report_id), timeout=180)
    try:
        have_lock = lock.acquire(blocking=False)
        if not have_lock:
            return False

        try:
            report = Report.get(Report.report_id == report_id)
        except Report.DoesNotExist:
            show = report_forum(report_id)
            report = Report(report_id=report_id, name=name, show=show,
                            commented=False)
            report.save()

        if not report.commented:
            comment_on(report)
    finally:
        if have_lock:
            lock.release()


def handle_reports():
    for name, report_id in get_reports():
        try:
            report = Report.get(Report.report_id == report_id)
            if report.commented:
                continue
        except Report.DoesNotExist:
            pass

        handle_report.delay(report_id, name)


@app.route('/reports-update/')
@require_local
def run_update():
    try:
        handle_reports()
    except Exception:
        info = traceback.format_exc()
        now = datetime.datetime.now()
        info += '\nFailure at {:%Y-%m-%d %H:%M:%S}'.format(now)

        app.logger.error(info)
        return Response(info, mimetype='text/plain', status=500)

    return Response("", mimetype='text/plain')
