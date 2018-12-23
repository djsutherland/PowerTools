from __future__ import unicode_literals
import logging
import os

DATABASE = 'sqlite:///' + os.path.abspath(
    os.path.join(os.path.dirname(__file__), '../../ptv.db'))
SECRET_KEY = '9Zbl48DxpawebuOKcTIxsIo7rZhgw2U5qs2mcE5Hqxaa7GautgOh3rkvTabKp'
# ^ remember to override in deploy!
ADMINS = ['dougal@gmail.com']

BCRYPT_LOG_ROUNDS = 12

DEBUG = True

LOG_HANDLERS = []
SIDE_LOG_HANDLERS = []

LOG_FORMATTER = logging.Formatter('{levelname}:{module}:{message}', style='{')

lh = logging.StreamHandler()
lh.setLevel(logging.WARNING)
lh.setFormatter(LOG_FORMATTER)
LOG_HANDLERS = [lh]

side_lh = logging.StreamHandler()
side_lh.setLevel(logging.INFO)
side_lh.setFormatter(LOG_FORMATTER)
SIDE_LOG_HANDLERS = [side_lh]
