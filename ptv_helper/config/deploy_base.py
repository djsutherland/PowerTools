from __future__ import unicode_literals
import logging
from logging import handlers
import sys

from .default import *

DEBUG = False

# in deploy.py, remember to set:
#  - SECRET_KEY for security
#  - FORUM_USERNAME, FORUM_PASSWORD for report commenting
#  - TVDB_API_KEY for tvdb updating

def get_mail_handler(subject):
    return handlers.SMTPHandler(mailhost='127.0.0.1', subject=subject,
                                fromaddr='ptv@dougal.me', toaddrs=ADMINS)

logging.basicConfig(stream=sys.stderr, level=logging.INFO)

mail_handler = get_mail_handler(subject="[ptv-helper] blew up")
mail_handler.setLevel(logging.ERROR)
mail_handler.setFormatter(LOG_FORMATTER)
LOG_HANDLERS.append(mail_handler)

reg_emailer = get_mail_handler(subject="[ptv-helper] info")
reg_emailer.setLevel(logging.INFO)
reg_emailer.setFormatter(LOG_FORMATTER)
SIDE_LOG_HANDLERS.append(
    handlers.MemoryHandler(capacity=20, target=reg_emailer))
