# coding=utf-8
from __future__ import unicode_literals
import datetime
import re
import socket
import tempfile
import traceback

from flask import g, Response, request
from robobrowser import RoboBrowser

from ..app import app
from ..models import Mod, Report, Show, Turf, TURF_LOOKUP


BASE = 'http://forums.previously.tv'
REPORT_URL = re.compile(r'{}/modcp/reports/(\d+)/?$'.format(BASE))

import warnings
warnings.filterwarnings(
    'ignore', "No parser was explicitly specified", UserWarning)


def make_browser():
    return RoboBrowser(history=True)


def login(browser):
    browser.open('{}/login/'.format(BASE))
    form = browser.get_form(method='post')
    if form is None:
        with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as f:
            f.write(browser.response.content)
            raise ValueError("no login form; response in {}".format(f.name))
    form['auth'] = app.config['FORUM_USERNAME']
    form['password'] = app.config['FORUM_PASSWORD']
    browser.submit_form(form)


def open_with_login(browser, url):
    browser.open(url)
    error_divs = browser.select('#elError')
    if error_divs:
        error_div, = error_divs
        msg = error_div.select_one('#elErrorMessage').text
        if "is not available for your account" in msg:
            login(browser)
            browser.open(url)


def get_reports(browser):
    # only gets from the first page, for now
    open_with_login(browser, '{}/modcp/reports/'.format(BASE))
    resp = []
    for a in browser.select('h4 a[href^={}/modcp/reports/]'.format(BASE)):
        report_id = int(REPORT_URL.match(a.attrs['href']).group(1))
        resp.append((a.text.strip(), report_id))
    return resp


def report_forum(report_id, browser):
    url = '{}/modcp/reports/{}/?action=find'.format(BASE, report_id)
    open_with_login(browser, url)
    if browser.url.startswith('{}/messenger/'.format(BASE)):
        return Show.get(Show.name == 'PMs')

    sel = ".ipsBreadcrumb li[itemprop=itemListElement] a[href^={}/forum/]"
    for a in reversed(browser.select(sel.format(BASE))):
        try:
            return Show.get(Show.url == a.attrs['href'])
        except Show.DoesNotExist:
            pass

    msg = "No shows found for {}. Maybe a brand-new forum?"
    raise ValueError(msg.format(report_id))


def _mention(user, text):
    if not user.profile_url or not u.forum_id:
        return ('''@{u.name} [except {me} forgot to hook '''
                '''up them up in the db properly ಠ_ಠ, so someone else should '''
                '''at-mention them properly and yell at {me} to fix it]'''
            ).format(u=user, me=at_mention(Mod.get(Mod.name == 'Dougal')))

    return ('''<a contenteditable="false" data-ipshover="" '''
            '''data-ipshover-target="{u.profile_url}?do=hovercard" '''
            '''data-mentionid="{u.forum_id}" href="{u.profile_url}" '''
            '''rel="">{text}</a>''').format(u=user, text=text)

def at_mention(user):
    return _mention(user, '@{}'.format(user.name))

def quiet_mention(user):
    return _mention(user, '')


def build_comment(report_id, show):
    turfs = show.turf_set.join(Mod).order_by(Mod.name)
    leads = [t.mod for t in turfs.where(Turf.state == TURF_LOOKUP['lead'])]
    backups = [t.mod for t in turfs.where(Turf.state == TURF_LOOKUP['backup'])]

    c = '<a href="{show.url}">{show.name}</a>'.format(show=show)

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

    c += ' (<a href="https://ptv.dougal.me/turfs/#show-{}">turfs entry</a>)' \
        .format(show.id)

    interested = Mod.select().where(Mod.reports_interested)
    c += ''.join(quiet_mention(u) for u in interested)
    return c


def comment_on(report, browser):
    c = build_comment(report.report_id, report.show)
    url = '{}/modcp/reports/{}/'.format(BASE, report.report_id)
    open_with_login(browser, url)
    f = browser.get_form(method='post', class_='ipsForm')
    f['report_comment_{}_noscript'.format(report.report_id)] = c
    browser.submit_form(f)
    err = browser.parsed.find(attrs={'data-role': 'commentFormError'})
    if err:
        raise ValueError('''Submission error on report {}: {}'''.format(
            report.report_id, '\n'.join(err.contents)))
    report.commented = True
    report.save()


# get local IPs: http://stackoverflow.com/a/1267524/344821
_allowed_ips = {'127.0.0.1'}
for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
    _allowed_ips.add(ip)
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.connect(('8.8.8.8', 53))
_allowed_ips.add(s.getsockname()[0])
s.close()


@app.route('/reports-update/')
def run_update():
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ip not in _allowed_ips:
        msg = "Can't run this from {}".format(ip)
        return Response(msg, mimetype='text/plain', status=403)

    try:
        if hasattr(g, 'browser'):
            br = g.browser
        else:
            br = g.browser = make_browser()

        for name, report_id in get_reports(br):
            try:
                report = Report.get(Report.report_id == report_id)
            except Report.DoesNotExist:
                show = report_forum(report_id, br)
                report = Report(
                    report_id=report_id, name=name, show=show, commented=False)
                report.save()

            if not report.commented:
                comment_on(report, br)
    except Exception:
        info = traceback.format_exc()
        now = datetime.datetime.now()
        info += '\nFailure at {:%Y-%m-%d %H:%M:%S}'.format(now)
        return Response(info, mimetype='text/plain', status=500)

    return Response("", mimetype='text/plain')


if __name__ == '__main__':
    run_update()
