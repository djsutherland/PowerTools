import re

from robobrowser import RoboBrowser

from ptv_helper.config.deploy import FORUM_USERNAME, FORUM_PASSWORD
from ptv_helper.models import Mod, Report, Show, Turf, TURF_LOOKUP

BASE = 'http://forums.previously.tv'
REPORT_URL = re.compile(r'{}/modcp/reports/(\d+)/?$'.format(BASE))

import warnings
warnings.filterwarnings(
    'ignore', "No parser was explicitly specified", UserWarning)


def login():
    browser = RoboBrowser(history=True)
    browser.open('{}/login/'.format(BASE))
    form = browser.get_form(method='post')
    form['auth'] = FORUM_USERNAME
    form['password'] = FORUM_PASSWORD
    browser.submit_form(form)
    return browser


def get_reports(browser):
    # only gets from the first page, for now
    browser.open('{}/modcp/reports/'.format(BASE))
    resp = []
    for a in browser.select('h4 a[href^={}/modcp/reports/]'.format(BASE)):
        report_id = int(REPORT_URL.match(a.attrs['href']).group(1))
        resp.append((a.text.strip(), report_id))
    return resp


def report_forum(report_id, browser):
    url = '{}/modcp/reports/{}/?action=find'.format(BASE, report_id)
    browser.open(url)
    sel = ".ipsBreadcrumb li[itemprop=itemListElement] a[href^={}/forum/]"
    for a in reversed(browser.select(sel.format(BASE))):
        try:
            return Show.get(Show.url == a.attrs['href'])
        except Show.DoesNotExist:
            pass

    msg = "No shows found for {}. Maybe a brand-new forum?"
    raise ValueError(msg.format(report_id))


def at_mention(user):
    return ('''<a contenteditable="false" data-ipshover="" '''
            '''data-ipshover-target="{u.profile_url}?do=hovercard" '''
            '''data-mentionid="{u.forum_id}" href="{u.profile_url}" '''
            '''rel="">@{u.name}</a>''').format(u=user)


def build_comment(report_id, show):
    turfs = show.turf_set.join(Mod).order_by(Mod.name)
    leads = [t.mod for t in turfs.where(Turf.state == TURF_LOOKUP['lead'])]
    backups = [t.mod for t in turfs.where(Turf.state == TURF_LOOKUP['backup'])]

    c = 'Report is in <a href="{show.url}">{show.name}</a>.'.format(show=show)

    if leads:
        c += '\n\nLeads: ' + ', '.join(at_mention(m) for m in leads) + '.'
        if backups:
            c += '\n\nBackups: ' + ', '.join(m.name for m in backups) + '.'
    elif backups:
        c += '\n\nNo leads for this show.'
        c += '\n\nBackups: ' + ', '.join(at_mention(m) for m in backups) + '.'
    else:
        c += '\n\n<strong>No mods for this show.</strong>'

        watch = [t.mod for t in turfs.where(Turf.state == TURF_LOOKUP['watch'])]
        if watch:
            c += '\n\n' + ', '.join(at_mention(m) for m in watch)
            c += ' say they could help.'

    c += '\n\n(This was an automated post; PM me if there are problems.)'
    return c


def comment_on(report, browser):
    c = build_comment(report.report_id, report.show)
    browser.open('{}/modcp/reports/{}/'.format(BASE, report.report_id))
    f = browser.get_form(method='post', class_='ipsForm')
    f['report_comment_{}_noscript'.format(report.report_id)] = c
    browser.submit_form(f)
    report.commented = True
    report.save()


def run_update():
    br = login()
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


if __name__ == '__main__':
    run_update()
