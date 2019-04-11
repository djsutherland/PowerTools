from __future__ import unicode_literals
import logging
from logging import handlers
import sys
import time

from .default import *

DEBUG = False

# in deploy.py, remember to set:
#  - SECRET_KEY for security
#  - FORUM_USERNAME, FORUM_PASSWORD for report commenting
#  - TVDB_API_KEY for tvdb updating

mailhost = '127.0.0.1'
fromaddr = 'ptv@dougal.me'
toaddrs = ADMINS

logging.basicConfig(stream=sys.stderr, level=logging.INFO)

# mail_handler = handlers.SMTPHandler(
#     mailhost=mailhost, fromaddr=fromaddr, toaddrs=toaddrs,
#     subject="[powertools] blew up")
# mail_handler.setLevel(logging.ERROR)
# mail_handler.setFormatter(LOG_FORMATTER)
# LOG_HANDLERS.append(mail_handler)


# based on https://gist.github.com/anonymous/1379446
# combined with current version of SMTPHandler
class BufferingSMTPHandler(logging.handlers.BufferingHandler):
    def __init__(self, mailhost, fromaddr, toaddrs, subject,
                 capacity=float('inf'), maxtime=3600,
                 credentials=None, secure=None, smtp_timeout=5.0):
        logging.handlers.BufferingHandler.__init__(self, capacity)
        self.maxtime = maxtime

        if isinstance(mailhost, (list, tuple)):
            self.mailhost, self.mailport = mailhost
        else:
            self.mailhost, self.mailport = mailhost, None
        if isinstance(credentials, (list, tuple)):
            self.username, self.password = credentials
        else:
            self.username = None
        self.fromaddr = fromaddr
        if isinstance(toaddrs, str):
            toaddrs = [toaddrs]
        self.toaddrs = toaddrs
        self.subject = subject
        self.secure = secure
        self.smtp_timeout = smtp_timeout

    def getSubject(self, records):
        return self.subject

    def shouldFlush(self, record):
        if len(self.buffer) >= self.capacity:
            return True

        if self.buffer:
            first = min(r.created for r in self.buffer)
            if time.time() - first > self.maxtime:
                return True

        return False

    def flush(self):
        self.acquire()
        try:
            if len(self.buffer) > 0:
                import smtplib
                from email.message import EmailMessage
                import email.utils

                port = self.mailport
                if not port:
                    port = smtplib.SMTP_PORT
                smtp = smtplib.SMTP(
                    self.mailhost, port, timeout=self.smtp_timeout)
                msg = EmailMessage()
                msg['From'] = self.fromaddr
                msg['To'] = ','.join(self.toaddrs)
                msg['Subject'] = self.getSubject(self.buffer)
                msg['Date'] = email.utils.localtime()
                msg.set_content('\n'.join(self.format(r) for r in self.buffer))
                if self.username:
                    if self.secure is not None:
                        smtp.ehlo()
                        smtp.starttls(*self.secure)
                        smtp.ehlo()
                    smtp.login(self.username, self.password)
                smtp.send_message(msg)
                smtp.quit()
                self.buffer = []
        except Exception:
            self.handleError(self.buffer[-1])
        finally:
            self.release()


reg_emailer = BufferingSMTPHandler(
    mailhost=mailhost, fromaddr=fromaddr, toaddrs=toaddrs,
    subject="[PowerTools] info", capacity=50, maxtime=3600)
reg_emailer.setLevel(logging.WARNING)
reg_emailer.setFormatter(LOG_FORMATTER)
SIDE_LOG_HANDLERS.append(reg_emailer)
