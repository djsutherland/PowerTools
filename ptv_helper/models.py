from __future__ import unicode_literals
from collections import OrderedDict
from functools import total_ordering
import itertools
import json

from flask_login import UserMixin
import peewee as pw
from six import iteritems
from six.moves.urllib.parse import urlsplit

from .app import db
from .helpers import last_post


class BaseModel(pw.Model):
    class Meta:
        database = db


class Meta(BaseModel):
    name = pw.CharField(primary_key=True, max_length=50)
    value = pw.TextField()

    class Meta:
        table_name = 'meta'

    def __unicode__(self):
        return self.name

    @classmethod
    def get_value(cls, key, default=None):
        try:
            return cls.get(name=key).value
        except cls.DoesNotExist:
            return default

    @classmethod
    def set_value(cls, key, value):
        with db.atomic():
            try:
                cls(name=key, value=value).save(force_insert=True)
            except pw.IntegrityError:
                cls.update(value=value).where(cls.name == key).execute()


################################################################################
### Info about TV shows.

@total_ordering
class Show(BaseModel):
    name = pw.TextField()
    forum_id = pw.IntegerField()
    has_forum = pw.BooleanField(default=True)
    url = pw.TextField()
    forum_topics = pw.IntegerField()
    forum_posts = pw.IntegerField()
    last_post = pw.DateTimeField()

    gone_forever = pw.BooleanField(default=False)
    we_do_ep_posts = pw.BooleanField(default=True)

    needs_help = pw.BooleanField(default=False)
    up_for_grabs = pw.BooleanField(default=False)

    tvdb_not_matched_yet = pw.BooleanField(default=True)
    is_a_tv_show = pw.BooleanField(default=True)

    hidden = pw.BooleanField(default=False, null=False)

    class Meta:
        table_name = 'shows'

    def __unicode__(self):
        return self.name

    def n_posts(self):
        try:
            return self.forum_posts + self.forum_topics
        except TypeError:
            return 'n/a'

    def __lt__(self, other):
        return ((self.name.lower(), self.has_forum, self.forum_id) <
                (other.name.lower(), other.has_forum, other.forum_id))


class ShowTVDB(BaseModel):
    show = pw.ForeignKeyField(column_name='showid',
                              model=Show, field='id',
                              backref='tvdb_ids',
                              on_delete='cascade', on_update='cascade')
    tvdb_id = pw.IntegerField(unique=True)

    name = pw.TextField()
    aliases = pw.TextField()  # a JSON list
    first_aired = pw.DateField()
    network = pw.TextField()
    airs_day = pw.TextField()
    airs_time = pw.TextField()
    runtime = pw.TextField()
    status = pw.TextField()
    overview = pw.TextField()
    slug = pw.TextField()

    imdb_id = pw.TextField()
    zaptoit_id = pw.TextField()

    @property
    def alias_list(self):
        return json.loads(self.aliases or '[]')

    class Meta:
        table_name = 'show_tvdb'

    def __unicode__(self):
        return '{} - {}'.format(self.show.name, self.tvdb_id)


class Episode(BaseModel):
    epid = pw.IntegerField()
    seasonid = pw.IntegerField()
    seriesid = pw.IntegerField()

    show = pw.ForeignKeyField(column_name='showid',
                              model=Show, field='id',
                              on_delete='cascade', on_update='cascade')

    season_number = pw.TextField()
    episode_number = pw.TextField()
    name = pw.TextField(null=True)

    overview = pw.TextField(null=True)
    first_aired = pw.DateField(null=True)

    class Meta:
        table_name = 'episodes'

    def __unicode__(self):
        return '{} S{:02}E{:02}: {}'.format(
            self.show.name, self.season_number, self.episode_number, self.name)


class ShowGenre(BaseModel):
    show = pw.ForeignKeyField(column_name='showid',
                              model=Show, field='id',
                              on_delete='cascade', on_update='cascade')
    seriesid = pw.IntegerField()
    genre = pw.CharField(max_length=30)

    class Meta:
        table_name = 'show_genres'
        primary_key = pw.CompositeKey('genre', 'seriesid')

    def __unicode__(self):
        return '{} - {}'.format(self.genre, self.show.name)


################################################################################
### Info about our mods.

class Mod(BaseModel, UserMixin):
    name = pw.TextField()
    forum_id = pw.IntegerField(unique=True)
    profile_url = pw.TextField()

    reports_interested = pw.BooleanField(default=False, null=False)

    class Meta:
        table_name = 'mods'

    def __unicode__(self):
        return self.name

    def set_url(self, url):
        r = urlsplit(url)
        assert r.netloc.endswith('previously.tv')
        assert r.path.startswith('/profile/')
        pth = r.path[len('/profile/'):]
        if pth.endswith('/'):
            pth = pth[:-1]
        assert '/' not in pth
        id = int(pth.split('-')[0])
        self.forum_id = id
        self.profile_url = url

    def summarize(self):
        def mod_key(state_modname):
            state, modname = state_modname
            return TURF_ORDER.index(state), modname

        report = []
        for state, name in iteritems(TURF_STATES):
            report.append("{}: [LIST]".format(name.capitalize()))
            for turf in (self.turf_set.where(Turf.state == state)
                                      .join(Show)
                                      .order_by(pw.fn.lower(Show.name).asc())):
                comm = ' ({0})'.format(turf.comments) if turf.comments else ''
                others = turf.show.turf_set.where(Turf.mod != self).join(Mod)
                bits = sorted(
                    ((t.state, t.mod.name) for t in others),
                    key=mod_key)
                oths = '; '.join(
                    '{}: {}'.format(TURF_STATES[state],
                                    ', '.join(name for st, name in vals))
                    for state, vals
                    in itertools.groupby(bits, key=lambda x: x[0]))
                if not oths:
                    oths = '[b]nobody[/b]'

                info = "({} posts; last {})".format(
                    turf.show.n_posts(), last_post(turf.show.last_post))

                report.append(
                    '   [*][i]{name}[/i]{comments} ({others}) {info} [/*]'
                    .format(name=turf.show.name, comments=comm, others=oths,
                            info=info))

            report.append("[/LIST]")
        return '\n'.join(report)


TURF_STATES = OrderedDict([
    ('g', 'lead',),
    ('c', 'backup',),
    ('w', 'watch',),
])
TURF_LOOKUP = OrderedDict([(v, k) for k, v in iteritems(TURF_STATES)])
TURF_ORDER = ''.join(TURF_STATES)

class Turf(BaseModel):
    show = pw.ForeignKeyField(column_name='showid',
                              model=Show, field='id',
                              on_delete='cascade', on_update='cascade')
    mod = pw.ForeignKeyField(column_name='modid',
                             model=Mod, field='id',
                             on_delete='cascade', on_update='cascade')

    state = pw.CharField(max_length=1, choices=list(iteritems(TURF_STATES)))
    comments = pw.TextField()

    class Meta:
        table_name = 'turfs'
        primary_key = pw.CompositeKey('mod', 'show')

    def __unicode__(self):
        return '{} - {} - {}'.format(
            self.mod.name, self.show.name,
            TURF_STATES.get(self.state, self.state))


################################################################################
### Bingo!

class BingoSquare(BaseModel):
    name = pw.TextField()
    row = pw.IntegerField()
    col = pw.IntegerField()
    which = pw.IntegerField()

    class Meta:
        table_name = 'bingo'
        indexes = (
            (('which', 'row', 'col'), True),  # unique
        )

    def __unicode__(self):
        return '{}: ({}, {}): {}'.format(
            self.which, self.row, self.col, self.name)


class ModBingo(BaseModel):
    bingo = pw.ForeignKeyField(column_name='bingoid',
                               model=BingoSquare, field='id')
    mod = pw.ForeignKeyField(column_name='modid',
                             model=Mod, field='id')

    class Meta:
        table_name = 'mod_bingo'
        primary_key = pw.CompositeKey('bingo', 'mod')

    def __unicode__(self):
        return '{}: {}'.format(self.mod.name, self.bingo.__unicode__())


################################################################################
### Stuff about the report center

class Report(BaseModel):
    report_id = pw.IntegerField(unique=True)
    name = pw.TextField()
    show = pw.ForeignKeyField(
        column_name='show_id', model=Show, field='id',
        on_delete='cascade', on_update='cascade')
    commented = pw.BooleanField(default=False, null=False)
