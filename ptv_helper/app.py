from __future__ import unicode_literals
import logging
import os
import warnings

from celery import Celery
from celery.signals import after_setup_logger
from flask import Flask, g
from flask_bcrypt import Bcrypt
import peewee
from playhouse.db_url import connect
from raven.contrib.flask import Sentry


# based on flask docs
def make_celery(app):
    celery = Celery(app.import_name, config_source=app.config['CELERY'])

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask

    @after_setup_logger.connect
    def add_celery_handlers(logger, *args, **kwargs):
        for handler in app.config.get('LOG_HANDLERS', []):
            logger.addHandler(handler)

    return celery


def setup_logging(app):
    for handler in app.config.get('LOG_HANDLERS', []):
        app.logger.addHandler(handler)
    app.logger.propagate = False

    side_logger = logging.getLogger(app.import_name)
    side_logger.setLevel(logging.INFO)
    side_logger.propagate = False
    for handler in app.config.get('SIDE_LOG_HANDLERS', []):
        side_logger.addHandler(handler)


def make_sentry(app):
    if 'SENTRY_DSN' in app.config:
        return Sentry(app, dsn=app.config['SENTRY_DSN'])
    else:
        warnings.warn("No SENTRY_DSN config; not setting up Sentry.")


def make_peewee_db(app):
    db = connect(app.config['DATABASE'])

    @app.before_request
    def before_request():
        g.db = db
        try:
            g.db.connect()
        except peewee.OperationalError as e:
            if not str(e).startswith('Connection already open'):
                raise

    @app.after_request
    def after_request(response):
        g.db.close()
        return response

    return db


app = Flask('ptv_helper')
app.config.from_object('ptv_helper.config.default')
if 'PTV_SETTINGS' in os.environ:
    app.config.from_envvar('PTV_SETTINGS')
elif os.path.exists(os.path.join(os.path.dirname(__file__), 'config/deploy.py')):
    app.config.from_object('ptv_helper.config.deploy')

setup_logging(app)
bcrypt = Bcrypt(app)
sentry = make_sentry(app)
celery = make_celery(app)
db = make_peewee_db(app)
