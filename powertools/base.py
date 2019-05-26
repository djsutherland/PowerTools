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
from redis import Redis
import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.flask import FlaskIntegration


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
        sentry_sdk.init(
            dsn=app.config['SENTRY_DSN'],
            integrations=[FlaskIntegration(), CeleryIntegration()])
    else:
        warnings.warn("No SENTRY_DSN config; not setting up Sentry.")


# based on flask docs
def make_celery(app, db):
    celery = Celery(app.import_name, config_source=app.config['CELERY'])

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                g.db = db
                _connect_db(db)
                try:
                    return self.run(*args, **kwargs)
                finally:
                    g.db.close()

    celery.Task = ContextTask

    @after_setup_logger.connect
    def add_celery_handlers(logger, *args, **kwargs):
        for handler in app.config.get('LOG_HANDLERS', []):
            logger.addHandler(handler)

    return celery


def _connect_db(db):
    try:
        g.db.connect()
    except peewee.OperationalError as e:
        if not str(e).startswith('Connection already open'):
            raise


def make_peewee_db(app):
    db = connect(app.config['DATABASE'])

    @app.before_request
    def before_request():
        g.db = db
        _connect_db(db)

    @app.after_request
    def after_request(response):
        g.db.close()
        return response

    return db


app = Flask('powertools')
if 'POWERTOOLS_SETTINGS' in os.environ:
    app.config.from_envvar('POWERTOOLS_SETTINGS')
elif os.path.exists(os.path.join(os.path.dirname(__file__), 'config/deploy.py')):
    app.config.from_object('powertools.config.deploy')
else:
    app.config.from_object('powertools.config.default')

setup_logging(app)
bcrypt = Bcrypt(app)
db = make_peewee_db(app)
celery = make_celery(app, db)
sentry = make_sentry(app)
redis = Redis()
