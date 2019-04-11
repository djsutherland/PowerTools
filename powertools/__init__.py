# import stuff that the server / celery need to have run
from . import auth, base, models, helpers, tasks, tvdb, views

app = base.app
