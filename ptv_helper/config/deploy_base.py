import logging
from logging.handlers import SMTPHandler
import sys

from .default import *

DEBUG = False


logging.basicConfig(stream=sys.stderr)
mail_handler = SMTPHandler('127.0.0.1', 'dougal@ptv.dougal.me', ADMINS,
                           "[ptv-helper] blew up")
mail_handler.setLevel(logging.ERROR)
app.logger.addHandler(mail_handler)
