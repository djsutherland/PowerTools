#!/bin/bash
set -e

cd `dirname $0`

git pull

./venv/bin/pip install -r requirements.txt
find . -name '*.pyc' -delete
touch *.wsgi

echo "maybe run    sudo service celery restart"
