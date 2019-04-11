import datetime
from peewee import JOIN
from powertools.models import Show, Turf

month_ago = datetime.date.today() - datetime.timedelta(days=30)
want = Show.select().join(Turf, JOIN.LEFT_OUTER).where(Turf.show >> None)
want = want.where(Show.forum_posts > 100).where(Show.last_post >= month_ago)
want = list(want)
Show.update(needs_help=True).where(Show.id << want).execute()

year_ago = datetime.date.today() - datetime.timedelta(days=365)
Show.update(needs_help=False).where(Show.last_post <= year_ago).execute()
