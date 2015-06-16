from __future__ import unicode_literals

from collections import OrderedDict
import itertools

import peewee as pw

from .app import db


class BaseModel(pw.Model):
    class Meta:
        database = db


class Meta(BaseModel):
    name = pw.TextField(null=True, primary_key=True)
    value = pw.TextField(null=True)

    class Meta:
        db_table = 'meta'

    def __unicode__(self):
        return self.name


################################################################################
### Info about TV shows.

class Show(BaseModel):
    name = pw.TextField()
    forum_id = pw.IntegerField()
    tvdb_ids = pw.TextField()

    gone_forever = pw.BooleanField(default=False)
    we_do_ep_posts = pw.BooleanField(default=True)

    needs_backups = pw.BooleanField(default=False)
    needs_leads = pw.BooleanField(default=False)

    forum_posts = pw.IntegerField()
    forum_topics = pw.IntegerField()

    class Meta:
        db_table = 'shows'

    def __unicode__(self):
        return self.name

    def n_posts(self):
        try:
            return self.forum_posts + self.forum_topics
        except TypeError:
            return 'n/a'


class Episode(BaseModel):
    name = pw.TextField(null=True)

    show = pw.ForeignKeyField(db_column='showid', null=True,
                              rel_model=Show, to_field='id',
                              on_delete='cascade', on_update='cascade')
    seriesid = pw.IntegerField()
    seasonid = pw.IntegerField()

    season_number = pw.TextField()
    episode_number = pw.TextField()
    first_aired = pw.TextField()
    overview = pw.TextField()

    class Meta:
        db_table = 'episodes'

    def __unicode__(self):
        return '{} S{}E{}: {}'.format(
            self.show.name, self.season_number, self.episode_number, self.name)


class ShowGenre(BaseModel):
    genre = pw.TextField()
    seriesid = pw.IntegerField()
    show = pw.ForeignKeyField(db_column='showid', null=True,
                              rel_model=Show, to_field='id',
                              on_delete='cascade', on_update='cascade')

    class Meta:
        db_table = 'show_genres'
        primary_key = pw.CompositeKey('genre', 'seriesid')

    def __unicode__(self):
        return '{} - {}'.format(self.genre, self.show.name)


################################################################################
### Info about our mods.

class Mod(BaseModel):
    name = pw.TextField()

    def is_active(self):
        return True
    def is_authenticated(self):
        return True
    def is_anonymous(self):
        return True
    def get_id(self):
        return unicode(self.id)

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
TURF_ORDER = ''.join(TURF_STATES)

class Turf(BaseModel):
    mod = pw.ForeignKeyField(db_column='modid', null=True,
                             rel_model=Mod, to_field='id',
                             on_delete='cascade', on_update='cascade')
    show = pw.ForeignKeyField(db_column='showid', null=True,
                              rel_model=Show, to_field='id',
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

    class Meta:
        db_table = 'bingo'
        indexes = (
            (('row', 'col'), True),  # unique
        )

    def __unicode__(self):
        return '({}, {}): {}'.format(self.row, self.col, self.name)


class ModBingo(BaseModel):
    bingo = pw.ForeignKeyField(db_column='bingoid', null=True,
                               rel_model=BingoSquare, to_field='id')
    mod = pw.ForeignKeyField(db_column='modid', null=True,
                             rel_model=Mod, to_field='id')

    class Meta:
        db_table = 'mod_bingo'
        primary_key = pw.CompositeKey('bingo', 'mod')

    def __unicode__(self):
        return '{}: {}'.format(self.mod.name, self.bingo.__unicode__())

