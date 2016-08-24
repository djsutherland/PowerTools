from ptv_helper.tvdb import update_db


def main(force=False, quiet=False):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', '-f', action='store_true', default=False)
    parser.add_argument('--quiet', '-q', dest='verbose', action='store_false',
                        default=True)
    args = parser.parse_args()

    update_db(**vars(args))


if __name__ == '__main__':
    main()
