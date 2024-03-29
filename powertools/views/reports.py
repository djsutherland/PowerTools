import datetime
import re
import traceback
from urllib.parse import urlsplit, urlunsplit
import warnings

from flask import Response, url_for
import redis_lock

from ..base import app, celery, redis
from ..helpers import SITE_BASE, get_browser, open_with_login, require_local
from ..models import Mod, Report, Show, TURF_LOOKUP, Turf
from .grab_shows import get_site_show, subcategory_pages, update_show_info


REPORT_URL = re.compile(r'/modcp/reports/(\d+)/?$')

warnings.filterwarnings(
    'ignore', "No parser was explicitly specified", UserWarning)


def get_reports():
    br = get_browser()

    # only gets from the first page, for now
    open_with_login(br, '{}/modcp/reports/'.format(SITE_BASE))
    resp = []
    for a in br.select('h4 a[href^="{}/modcp/reports/"]'.format(SITE_BASE)):
        tgt = urlsplit(a.attrs['href']).path
        report_id = int(REPORT_URL.match(tgt).group(1))
        resp.append((a.text.strip(), report_id))
    return resp


def report_forum(report_id, check_if_deleted=False):
    br = get_browser()

    if check_if_deleted:
        url = '{}/modcp/reports/{}/'.format(SITE_BASE, report_id)
        open_with_login(br, url)
        if br.find(id='elReportCommentDeleted'):
            return Show.get(Show.name == 'Already Deleted')

    url = '{}/modcp/reports/{}/?action=find'.format(SITE_BASE, report_id)
    open_with_login(br, url)
    if br.url.startswith('{}/messenger/'.format(SITE_BASE)):
        return Show.get(Show.name == 'PMs', Show.deleted_at.is_null(True))
    if br.url == url and br.find(id='elError'):
        # "Sorry, there is a problem" shown when the reported content
        # is already deleted.
        return Show.get(Show.name == 'Already Deleted', Show.deleted_at.is_null(True))

    # drop query string, fragment from url
    base_url = urlunsplit(urlsplit(br.url)[:-2] + (None, None))
    try:
        return Show.get(Show.url == base_url, Show.deleted_at.is_null(True))
    except Show.DoesNotExist:
        pass

    sel = 'ul[data-role="breadcrumbList"] li a[href^="{}/forum/"]'
    crumbs = br.select(sel.format(SITE_BASE))
    for a in reversed(crumbs):
        # if we hit Other Dramas/etc, then this must be a new thread
        if a['href'] in subcategory_pages:
            return update_show_info(get_site_show(base_url))

        try:
            return Show.get(Show.url == a['href'], Show.deleted_at.is_null(True))
        except Show.DoesNotExist:
            pass

    return None


def _mention(user, text):
    if not user.profile_url or not user.forum_id:
        me = Mod.get(Mod.name == 'halgia')
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
    elif show.name == 'Already Deleted':
        c += "Content already deleted; my job is done here."
        return c

    turfs = show.turf_set.join(Mod).order_by(Mod.name)
    leads = [t.mod for t in turfs.where(Turf.state == TURF_LOOKUP['lead'])]
    backups = [t.mod for t in turfs.where(Turf.state == TURF_LOOKUP['backup'])]

    c += '<a href="{url}">{show.name}</a>'.format(
        show=show, url=url_for('show', show_id=show.id, _external=True))

    if leads:
        c += ' leads: ' + ', '.join(at_mention(m) for m in leads) + '.'
        if backups:
            c += ' Backups: ' + ', '.join(m.name for m in backups) + '.'
    elif backups:
        c += ': No leads for this show.'
        c += ' Backups: ' + ', '.join(at_mention(m) for m in backups) + '.'
    else:
        c += ': <strong>No mods for this show.</strong>'

        watch = [t.mod for t in turfs.where(Turf.state == TURF_LOOKUP['could help'])]
        if watch:
            c += ' ' + ', '.join(at_mention(m) for m in watch)
            c += ' say they could help.'
        elif not show.has_forum:
            team = list(Mod.select().where(Mod.is_reports_team))
            if team:
                c += '(CC: {})'.format(', '.join(at_mention(u) for u in team))
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
    lock = redis_lock.Lock(redis, name='handle_report_{}'.format(report_id),
                           expire=120, auto_renewal=True)
    if not lock.acquire(blocking=False):
        return False

    try:
        try:
            report = Report.get(Report.report_id == report_id)
        except Report.DoesNotExist:
            show = report_forum(report_id, check_if_deleted=name == 'Unknown')
            report = Report(report_id=report_id, name=name, show=show,
                            commented=False)
            report.save(force_insert=True)

        if not report.commented:
            comment_on(report)
    finally:
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
