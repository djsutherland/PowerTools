import os
execfile(os.path.join(os.path.dirname(__file__), 'ptv_helper.wsgi'))

application.config['APPLICATION_ROOT'] = '/ptv'
