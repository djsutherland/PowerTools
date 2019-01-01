from .app import celery

# import any files with a celery.task here so workers can see them...
from .views.grab_shows import merge_shows_list
