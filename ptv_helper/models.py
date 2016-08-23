from __future__ import unicode_literals
from collections import OrderedDict
import itertools

from flask_login import UserMixin
import peewee as pw

from .app import db


class BaseModel(pw.Model):
    class Meta:
        database = db


class Meta(BaseModel):
    name = pw.CharField(primary_key=True, max_length=50)
    value = pw.TextField()

    class Meta:
        db_table = 'meta'

    def __unicode__(self):
        return self.name


################################################################################
### Info about TV shows.

class Show(BaseModel):
    name = pw.TextField()
    forum_id = pw.IntegerField()
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

    class Meta:
        db_table = 'shows'

    def __unicode__(self):
        return self.name

    def n_posts(self):
        try:
            return self.forum_posts + self.forum_topics
        except TypeError:
            return 'n/a'


class ShowTVDB(BaseModel):
    show = pw.ForeignKeyField(db_column='showid',
                              rel_model=Show, to_field='id',
                              related_name='tvdb_ids',
                              on_delete='cascade', on_update='cascade')
    tvdb_id = pw.IntegerField(unique=True)

    network = pw.TextField()
    airs_day = pw.TextField()
    airs_time = pw.TextField()
    runtime = pw.TextField()
    status = pw.TextField()
    overview = pw.TextField()

    imdb_id = pw.TextField()
    zaptoit_id = pw.TextField()

    class Meta:
        db_table = 'show_tvdb'

    def __unicode__(self):
        return '{} - {}'.format(self.show.name, self.tvdb_id)


class Episode(BaseModel):
    seasonid = pw.IntegerField()
    seriesid = pw.IntegerField()

    show = pw.ForeignKeyField(db_column='showid',
                              rel_model=Show, to_field='id',
                              on_delete='cascade', on_update='cascade')

    season_number = pw.TextField()
    episode_number = pw.TextField()
    name = pw.TextField(null=True)

    overview = pw.TextField(null=True)
    first_aired = pw.TextField(null=True)

    class Meta:
        db_table = 'episodes'

    def __unicode__(self):
        return '{} S{}E{}: {}'.format(
            self.show.name, self.season_number, self.episode_number, self.name)


class ShowGenre(BaseModel):
    show = pw.ForeignKeyField(db_column='showid',
                              rel_model=Show, to_field='id',
                              on_delete='cascade', on_update='cascade')
    seriesid = pw.IntegerField()
    genre = pw.CharField(max_length=30)

    class Meta:
        db_table = 'show_genres'
        primary_key = pw.CompositeKey('genre', 'seriesid')

    def __unicode__(self):
        return '{} - {}'.format(self.genre, self.show.name)


################################################################################
### Info about our mods.

class Mod(BaseModel, UserMixin):
    name = pw.TextField()
    forum_id = pw.IntegerField(unique=True)
    profile_url = pw.TextField()

    class Meta:
        db_table = 'mods'

    def __unicode__(self):
        return self.name

    def summarize(self):
        report = []
        mod_key = lambda (state, modname): (TURF_ORDER.index(state), modname)

        for state, name in TURF_STATES.iteritems():
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

                report.append(
                    '   [*][i]{name}[/i]{comments} ({others})[/*]'
                    .format(name=turf.show.name, comments=comm, others=oths))

            report.append("[/LIST]")
        return '\n'.join(report)


TURF_STATES = OrderedDict([
    ('g', 'lead',),
    ('c', 'backup',),
    ('w', 'watch',),
])
TURF_LOOKUP = OrderedDict([(v, k) for k, v in TURF_STATES.iteritems()])
TURF_ORDER = ''.join(TURF_STATES)

class Turf(BaseModel):
    show = pw.ForeignKeyField(db_column='showid',
                              rel_model=Show, to_field='id',
                              on_delete='cascade', on_update='cascade')
    mod = pw.ForeignKeyField(db_column='modid',
                             rel_model=Mod, to_field='id',
                             on_delete='cascade', on_update='cascade')

    state = pw.CharField(max_length=1, choices=TURF_STATES.items())
    comments = pw.TextField()

    class Meta:
        db_table = 'turfs'
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
        db_table = 'bingo'
        indexes = (
            (('which', 'row', 'col'), True),  # unique
        )

    def __unicode__(self):
        return '{}: ({}, {}): {}'.format(
            self.which, self.row, self.col, self.name)


class ModBingo(BaseModel):
    bingo = pw.ForeignKeyField(db_column='bingoid',
                               rel_model=BingoSquare, to_field='id')
    mod = pw.ForeignKeyField(db_column='modid',
                             rel_model=Mod, to_field='id')

    class Meta:
        db_table = 'mod_bingo'
        primary_key = pw.CompositeKey('bingo', 'mod')

    def __unicode__(self):
        return '{}: {}'.format(self.mod.name, self.bingo.__unicode__())


################################################################################
### Stuff about the report center

class Report(BaseModel):
    report_id = pw.IntegerField(unique=True)
    name = pw.TextField()
    show = pw.ForeignKeyField(
        db_column='show_id', rel_model=Show, to_field='id',
        on_delete='cascade', on_update='cascade')
    commented = pw.BooleanField(default=False, null=False)
