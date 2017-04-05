from ptv_helper.app import app
from ptv_helper.tvdb import update_db, update_serieses


def main(force=False, quiet=False):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', '-f', action='store_true', default=False)
    parser.add_argument('--quiet', '-q', dest='verbose', action='store_false',
                        default=True)
    parser.add_argument('ids', nargs='*', type=int)
    args = parser.parse_args()

    with app.app_context():
        if args.ids:
            update_serieses(args.ids, verbose=args.verbose)
        else:
            update_db(force=args.force, verbose=args.verbose)


if __name__ == '__main__':
    main()
