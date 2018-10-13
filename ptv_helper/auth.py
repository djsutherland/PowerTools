from __future__ import unicode_literals
from flask import abort, flash, g, redirect, render_template, request, url_for
from flask_login import LoginManager, login_user, logout_user, current_user
import itsdangerous
from peewee import fn

from .app import app, get_next_url
from .helpers import check_mod, get_browser, send_pm
from .models import Mod

login_manager = LoginManager(app)
login_manager.login_view = 'login'

confirm_ts = itsdangerous.URLSafeTimedSerializer(
    app.config['SECRET_KEY'], salt='confirm account')


@login_manager.user_loader
def load_user(userid):
    try:
        return Mod.get(id=userid)
    except Mod.DoesNotExist:
        return None


@app.route("/login", methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('name'):
            with g.db.atomic():
                mod, new = Mod.get_or_create(name=request.form['name'])
        else:
            mod = load_user(request.form.get('modid'))
            if mod is None:
                return abort(404)

        login_user(mod, remember=True)
        return redirect(get_next_url(request.form.get('next')))

    mods = Mod.select().order_by(fn.Lower(Mod.name))
    return render_template('login.html', mods=mods)


@app.route("/register", methods=['POST'])
def register():
    url = request.form.get('profile_url').strip()

    kw = {}
    if 'next' in request.form:
        kw['next'] = request.form['next']
    fail_target = url_for('login', **kw)

    br = get_browser()
    try:
        name, group = check_mod(br, url)
    except ValueError as e:
        flash(str(e))
        return redirect(fail_target)

    try:
        Mod.get(Mod.name == name)
    except Mod.DoesNotExist:
        pass
    else:
        flash('You already have an account! Hit "forgot password" if '
              'you need to.')
        return redirect(fail_target)

    token_data = {'profile_url': url, 'name': name, 'group': group}
    if group not in {'Mod', 'Admin'}:
        flash("This site is for mods, not {}s!".format(group))
        return redirect(fail_target)

    token = confirm_ts.dumps(token_data)
    confirm_url = url_for('confirm_register', token=token, _external=True)
    content = render_template(
        'register_pm.txt', name=name, confirm_url=confirm_url)

    send_pm(br, name, 'PowerTools Registration', content)

    return render_template('register.html', name=name)


@app.route('/register/<token>/', methods=['GET', 'POST'])
def confirm_register(token):
    try:
        token_data = confirm_ts.loads(token, max_age=60 * 60 * 48)
    except itsdangerous.BadSignature as e:
        flash(e.message)
        return abort(404)

    try:
        Mod.get(Mod.name == token_data['name'])
    except Mod.DoesNotExist:
        pass
    else:
        flash(('The account for {} already exists; hit "forgot password" '
               'if you need to.').format(token_data['name']))

    if request.method == 'POST':
        password = request.form.get('password')
        if len(password) < 5:
            flash("Come on, your password's gotta be better than that.")
        else:
            mod = Mod(name=token_data['name'])
            mod.set_password(password)
            mod.set_url(token_data['profile_url'])
            mod.is_superuser = token_data['group'] == 'Admin'
            mod.save()

            login_user(mod, remember=True)
            return redirect(get_next_url())

    return render_template('register-confirm.html', name=token_data['name'])


@app.route('/logout')
def logout():
    logout_user()
    return redirect(get_next_url(request.args.get('next')))


@app.context_processor
def inject_user():
    return {'user': current_user}
