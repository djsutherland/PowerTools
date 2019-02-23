#!/usr/bin/env python
import argparse
import shutil
import sys
import time

from ptv_helper.views.grab_shows import start_or_join_merge_shows_list, \
                                        get_status_info

try:
    parser = argparse.ArgumentParser()
    parser.add_argument('--refresh', type=int, default=2)
    parser.add_argument('--quiet', '-q', action='store_true', default=False)
    parser.add_argument('--detach', '-d', action='store_true', default=False)
    args = parser.parse_args()

    task = start_or_join_merge_shows_list()
    if args.detach:
        sys.exit(0)

    while True:
        info = get_status_info(task)
        cols, _ = shutil.get_terminal_size()

        if not args.quiet or task.state in {'FAILURE'}:
            print("\r{:{width}}".format(str(info)[:cols], width=cols), end='')
        if task.state in {'FAILURE', 'SUCCESS'}:
            break
        time.sleep(args.refresh)

    print()
except KeyboardInterrupt:
    pass
