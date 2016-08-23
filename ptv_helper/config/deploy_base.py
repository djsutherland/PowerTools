from __future__ import unicode_literals
import logging
from logging.handlers import SMTPHandler
import sys

from .default import *

DEBUG = False

# in deploy.py, remember to set:
#  - SECRET_KEY for security
#  - FORUM_USERNAME, FORUM_PASSWORD for report commenting
#  - TVDB_API_KEY for tvdb updating

logging.basicConfig(stream=sys.stderr)
mail_handler = SMTPHandler('127.0.0.1', 'ptv@dougal.me', ADMINS,
                           "[ptv-helper] blew up")
mail_handler.setLevel(logging.ERROR)
LOG_HANDLERS = [mail_handler]
