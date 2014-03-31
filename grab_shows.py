from __future__ import print_function
import re

import lxml.html
import tvdb_api

from server import connect_db


def get_site_show_list(forum_url='http://forums.previously.tv'):
    root = lxml.html.parse(forum_url).getroot()
    ols = root.cssselect('div#category_5 ol.subforums')
    assert ols[-1].getparent()[0].text_content().strip() == 'Misc TV Talk'
    ols = ols[:-1]

    all_x = re.compile(r'^\s*All (\d+)\s*$', re.IGNORECASE)

    shows = []
    for ol in ols:
        lis = ol.findall('li')

        m = all_x.match(lis[-1].text_content())
        assert int(m.group(1)) == len(lis) - 1

        for li in lis[:-1]:
            a = li[0]
            assert a.tag == 'a'
            assert a.attrib['href'].startswith(forum_url + '/forum/')
            shows.append((a.text_content().strip(), a.attrib['href']))
    return shows

# TODO: support multiple TVDB keys for a given show

def merge_shows_list(interactive=True, **api_kwargs):
    db = connect_db()
    t = tvdb_api.Tvdb(interactive=interactive, **api_kwargs)

    c = db.cursor()
    try:
        site_shows = get_site_show_list()

        # db won't be too big, so just grab everything, why not.
        c.execute('''SELECT id, name, forum_url, tvdb_id FROM shows''')
        db_shows = c.fetchall()
        db_urls = {row['forum_url'] for row in db_shows}

        # check if shows are in the db but not on the site.
        # this is probably an error, since we don't delete forums.
        site_urls = frozenset(url for name, url in site_shows)
        any_missing = False
        for row in db_shows:
            if row['forum_url'] not in site_urls:
                print("IN DB BUT NOT SITE: {name}, {href}".format(**row))
                any_missing = True
        if any_missing and interactive:
            raw_input('Press any key to continue, or ^C me...')

        # check which shows are on the site but not in the db
        for name, url in site_shows:
            if url not in db_urls:
                print()
                print(name, url)
                try:
                    tvdb_id = int(t[name]['id'])
                except (tvdb_api.tvdb_shownotfound, tvdb_api.tvdb_userabort):
                    print("Show not found! Continuing without it.\n")
                    continue

                c.execute('''INSERT INTO shows (name, forum_url, tvdb_id)
                             VALUES (?, ?, ?)''',
                          (name, url, tvdb_id))
                db.commit()

    finally:
        db.close()


if __name__ == '__main__':
    merge_shows_list()
