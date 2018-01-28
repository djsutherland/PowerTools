from __future__ import unicode_literals
import datetime
import socket
import tempfile

from flask import Response, escape, g, request
from robobrowser import RoboBrowser

from .app import app


################################################################################
### General utilities

@app.template_filter()
def strip_the(s):
    if s is None:
        return ''
    if s.startswith('The '):
        return s[4:]
    return s


@app.template_filter()
def tvdb_url(series_id):
    return escape('http://thetvdb.com/?tab=series&id={0}'.format(series_id))


@app.template_filter()
def tvdb_ep_url(episode):
    return escape(
        ("http://thetvdb.com/?tab=episode&seriesid={ep.seriesid:d}"
         "&seasonid={ep.seasonid:d}&id={ep.epid:d}&lid=7") .format(ep=episode))


@app.template_filter()
def any_tvdbs(tvdb_ids):
    try:
        next(iter(tvdb_ids.select()))
    except StopIteration:
        return False
    else:
        return True


@app.template_filter()
def tvdb_links(tvdb_ids):
    ids = sorted(t.tvdb_id for t in tvdb_ids)
    if not ids:
        return 'no tvdb'
    elif len(ids) == 1:
        return '<a href="{0}">tvdb</a>'.format(tvdb_url(ids[0]))
    else:
        return 'tvdb: ' + ' '.join(
            '<a href="{0}">{1}</a>'.format(tvdb_url(sid), i)
            for i, sid in enumerate(ids, 1))


@app.template_filter()
def episodedate(ep):
    date = ep.get('firstaired', None)
    if date is None:
        return 'unknown'
    date = datetime.datetime.strptime(date, '%Y-%m-%d').date()
    return '{d:%B} {d.day}, {d.year}'.format(d=date)


_one_day = datetime.timedelta(days=1)
@app.template_filter()
def last_post(dt):
    if dt is None:
        return 'never'
    date = dt.date()
    today = datetime.date.today()
    diff = today - date
    if diff.days == 0:
        return 'today'
    elif diff.days == 1:
        return 'yesterday'
    elif diff.days <= 6:
        return 'this week'
    elif diff.days <= 14:
        return '2 weeks ago'
    elif diff.days <= 21:
        return '3 weeks ago'
    elif diff.days <= 200:
        return date.strftime('%B')
    else:
        return date.strftime('%b %Y')


@app.template_filter()
def commify(n):
    """
    Add commas to an integer `n`.

        >>> commify(1)
        '1'
        >>> commify(123)
        '123'
        >>> commify(1234)
        '1,234'
        >>> commify(1234567890)
        '1,234,567,890'
        >>> commify(123.0)
        '123.0'
        >>> commify(1234.5)
        '1,234.5'
        >>> commify(1234.56789)
        '1,234.56789'
        >>> commify('%.2f' % 1234.5)
        '1,234.50'
        >>> commify(None)
        >>>

    """
    if n is None:
        return None
    n = str(n)
    if '.' in n:
        dollars, cents = n.split('.')
    else:
        dollars, cents = n, None

    r = []
    for i, c in enumerate(str(dollars)[::-1]):
        if i and (not (i % 3)):
            r.insert(0, ',')
        r.insert(0, c)
    out = ''.join(r)
    if cents:
        out += '.' + cents
    return out


################################################################################
# Check that view's request is from a local IP

# get local IPs: http://stackoverflow.com/a/1267524/344821
_allowed_ips = {}
def local_ips():
    global _allowed_ips
    if _allowed_ips is not None:
        return _allowed_ips

    _allowed_ips = {'127.0.0.1'}
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            _allowed_ips.add(ip)
    except socket.gaierror:
        pass
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('8.8.8.8', 53))
    _allowed_ips.add(s.getsockname()[0])
    s.close()

    return _allowed_ips


def require_local(fn):
    def wrapped(*args, **kwargs):
        ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        if ip not in local_ips():
            msg = "Can't run this from {}".format(ip)
            return Response(msg, mimetype='text/plain', status=403)
        return fn(*args, **kwargs)
    return wrapped


################################################################################
# Helpers to make a browser that can log into the site

SITE_BASE = 'http://forums.previously.tv'


def make_browser():
    return RoboBrowser(history=True)


def get_browser():
    if not hasattr(g, 'browser'):
        g.browser = make_browser()
    return g.browser


def login(browser):
    browser.open('{}/login/'.format(SITE_BASE))
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
