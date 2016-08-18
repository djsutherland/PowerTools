import os

DATABASE = 'sqlite:///' + os.path.abspath(
    os.path.join(os.path.dirname(__file__), '../../ptv.db'))
SECRET_KEY = '9Zbl48DxpawebuOKcTIxsIo7rZhgw2U5qs2mcE5Hqxaa7GautgOh3rkvTabKp'
# ^ remember to override in deploy!
ADMINS = ['dougal@gmail.com']

DEBUG = True
