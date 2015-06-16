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

    forum_posts = pw.IntegerField(null=True)
    forum_topics = pw.IntegerField(null=True)

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
                              rel_model=Show, to_field='id')
    seriesid = pw.IntegerField(null=True)
    seasonid = pw.IntegerField(null=True)

    season_number = pw.TextField(null=True)
    episode_number = pw.TextField(null=True)
    first_aired = pw.TextField(null=True)
    overview = pw.TextField(null=True)

    class Meta:
        db_table = 'episodes'

    def __unicode__(self):
        return '{} S{}E{}: {}'.format(
            self.show.name, self.season_number, self.episode_number, self.name)


class ShowGenre(BaseModel):
    genre = pw.TextField()
    seriesid = pw.IntegerField()
    show = pw.ForeignKeyField(db_column='showid', null=True,
                              rel_model=Show, to_field='id')

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

    # is_active = True
    # is_authenticated = True
    # is_anonymous = False

    def get_id(self):
        return unicode(self.id)

    class Meta:
        db_table = 'mods'

    def __unicode__(self):
        return self.name


TURF_STATES = {
    'g': 'lead',
    'c': 'backup',
    'w': 'watch',
}

class Turf(BaseModel):
    mod = pw.ForeignKeyField(db_column='modid', null=True,
                             rel_model=Mod, to_field='id')
    show = pw.ForeignKeyField(db_column='showid', null=True,
                              rel_model=Show, to_field='id')

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
    name = pw.TextField(null=True)
    row = pw.IntegerField()
    col = pw.IntegerField()

    class Meta:
        db_table = 'bingo'


class ModBingo(BaseModel):
    bingo = pw.ForeignKeyField(db_column='bingoid', null=True,
                               rel_model=BingoSquare, to_field='id')
    mod = pw.ForeignKeyField(db_column='modid', null=True,
                             rel_model=Mod, to_field='id')

    class Meta:
        db_table = 'mod_bingo'
        primary_key = pw.CompositeKey('bingo', 'mod')


