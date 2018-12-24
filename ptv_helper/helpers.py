from __future__ import unicode_literals
import datetime
import re
import socket
import tempfile

from flask import Response, escape, g, request
from robobrowser import RoboBrowser
from six.moves.urllib.parse import urlsplit, urlunsplit, quote_plus
from unidecode import unidecode

from .app import app


################################################################################
### General utilities

app.add_template_filter(unidecode, name='unidecode')
app.add_template_filter(quote_plus)


@app.template_filter()
def strip_the(s):
    if s is None:
        return ''
    if s.startswith('The '):
        return s[4:]
    return s


@app.template_filter()
def tvdb_url(search_info):
    return escape(
        "https://www.thetvdb.com/series/{}".format(search_info['slug']))


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
    tvdb_ids = sorted(tvdb_ids, key=lambda s: strip_the(s.name).lower())
    if not tvdb_ids:
        return 'no tvdb'
    elif len(tvdb_ids) == 1:
        return '<a href="{0}">tvdb</a>'.format(tvdb_ids[0].tvdb_url())
    else:
        return 'tvdb: ' + ' '.join(
            '<a href="{0}">{1}</a>'.format(sid.tvdb_url(), i)
            for i, sid in enumerate(tvdb_ids, 1))


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

sentinel = object()


def get_next_url(nxt=sentinel):
    if nxt is sentinel:
        nxt = request.args.get('next')
    if nxt:
        return request.script_root + nxt
    return url_for('index')


################################################################################

dt_parse = re.compile(r'(\d\d\d\d)-(\d?\d)-(\d?\d)T(\d?\d):(\d\d):(\d\d)Z')
dt_format = '{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'


def parse_dt(s):
    m = dt_parse.match(s)
    return dt_format.format(*(int(x) for x in m.groups()))


################################################################################
# Check that view's request is from a local IP

# get local IPs: http://stackoverflow.com/a/1267524/344821
_allowed_ips = None
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


_temp_codes = {502, 503, 504}
def login(browser, retry=True):
    browser.open('{}/login/'.format(SITE_BASE))
    form = browser.get_form(method='post')
    if form is None:
        if browser.response.status_code in _temp_codes and retry:
            import time
            time.sleep(1)
            return login(browser, retry=False)

        if browser.response.status_code in _temp_codes:
            raise ValueError("{} on login".format(browser.response.status_code))

        with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as f:
            f.write(browser.response.content)
            raise ValueError("no login form (HTTP {}); response in {}".format(
                browser.response.status_code, f.name))

    form['auth'] = app.config['FORUM_USERNAME']
    form['password'] = app.config['FORUM_PASSWORD']
    browser.submit_form(form)


def open_with_login(browser, url):
    browser.open(url)
    error_divs = browser.select('#elError')
    if error_divs:
        error_div, = error_divs
        msg = error_div.select_one('#elErrorMessage').text
        if "is not available" in msg:
            login(browser)
            browser.open(url)


def is_logged_in(browser):
    # assumes browser has a forum page open...
    if browser.find(id='elSignInLink') is not None:
        return False
    elif browser.find(id='cUserLink') is not None:
        return True
    raise ValueError("is `browser` on the forums?")


def ensure_logged_in(browser):
    try:
        if is_logged_in(browser):
            return
    except ValueError:
        browser.open(SITE_BASE)
        if is_logged_in(browser):
            return
    login(browser)


def send_pm(browser, to, subject, content):
    open_with_login(browser, '{}/messenger/compose/'.format(SITE_BASE))
    f, = browser.get_forms(
        method='post',
        action=re.compile(r'.*forums\.previously\.tv/messenger/compose/?$'))
    f['messenger_to'] = to
    f['messenger_title'] = subject
    f['messenger_content_noscript'] = content
    browser.submit_form(f)

    if browser.url.endswith('/messenger/compose/'):
        raise ValueError("Something went wrong in the PM")
    return browser.url


profile_re = re.compile(r'/profile/(\d+)-([^/]+)/?$')


def check_mod(browser, profile_url):
    parts = urlsplit(profile_url)
    if not (parts.netloc.endswith('forums.previously.tv')
            and profile_re.match(parts.path)):
        raise ValueError("Bad profile URL {}".format(profile_url))
    my_url = urlunsplit(('http', 'forums.previously.tv', parts.path, '', ''))

    browser.open(my_url)
    h1, = browser.find_all('h1')
    group, = browser.find_all(class_='group-name')
    return h1.text.strip(), group.text.strip()
