import ptv_helper.app
import ptv_helper.auth
import ptv_helper.models
import ptv_helper.helpers
import ptv_helper.views

app = ptv_helper.app.app

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5000)
    g = parser.add_mutually_exclusive_group()
    g.add_argument('--debug', action='store_true', default=True)
    g.add_argument('--no-debug', action='store_false', dest='debug')
    args = parser.parse_args()
    app.run(**vars(args))
