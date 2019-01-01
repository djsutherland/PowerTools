from __future__ import unicode_literals
from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import (current_user, LoginManager, login_required,
                         login_user, logout_user)
import itsdangerous
from peewee import fn

from .app import app
from .helpers import check_mod, get_browser, get_next_url, send_pm
from .models import Mod

login_manager = LoginManager(app)
login_manager.login_view = 'login'

confirm_ts = itsdangerous.URLSafeTimedSerializer(
    app.config['SECRET_KEY'], salt='confirm account')
reset_ts = itsdangerous.URLSafeTimedSerializer(
    app.config['SECRET_KEY'], salt='reset password')


@login_manager.user_loader
def load_user(userid):
    try:
        return Mod.get(id=userid)
    except Mod.DoesNotExist:
        return None


def require_superuser(fn):
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_superuser:
            flash("Sorry, you're not allowed to do that.")
            args = {k: v for k, v in request.args.items() if k == 'next'}
            return redirect(url_for('login', **args))
        return fn(*args, **kwargs)
    return wrapped


@app.route("/user/login/", methods=['GET', 'POST'])
def login():
    chosen = None
    if request.method == 'POST':
        chosen = int(request.form.get('modid'))
        mod = load_user(chosen)
        if mod is None:
            flash("No such mod. Whatchu up to?")
            return abort(404)

        if request.form.get('action') == "Forgot password":
            if request.form.get('next'):
                k = {'next': request.form['next']}
            else:
                k = {}
            return redirect(url_for('forgot_password', modid=chosen, **k))
        else:
            try:
                if not mod.check_password(request.form.get('password')):
                    raise ValueError("Wrong password")
            except ValueError as e:
                flash(str(e))
            else:
                login_user(mod, remember=True)
                return redirect(get_next_url(request.form.get('next')))

    mods = Mod.select().order_by(fn.Lower(Mod.name))
    return render_template('auth/login.html', mods=mods, chosen=chosen)


@app.route("/user/register/", methods=['POST'])
def register():
    url = request.form.get('profile_url').strip()

    kw = {'next': request.form['next']} if request.form.get('next') else {}
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
        'auth/register-pm.txt', name=name, confirm_url=confirm_url)

    pm_url = send_pm(br, name, 'PowerTools Registration', content)
    return render_template('auth/register.html', name=name, pm_url=pm_url)


def check_password(password):
    if len(password) < 5:
        flash("Come on, your password's gotta be longer than <i>that</i>.")
        return False
    return True


@app.route('/user/register/<token>/', methods=['GET', 'POST'])
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
        if check_password(password):
            mod = Mod(name=token_data['name'])
            mod.set_password(password)
            mod.set_url(token_data['profile_url'])
            mod.is_superuser = token_data['group'] == 'Admin'
            mod.save()

            login_user(mod, remember=True)
            return redirect(get_next_url())

    return render_template(
        'auth/register-confirm.html', name=token_data['name'])


@app.route('/user/reset-password/<int:modid>/', methods=['GET', 'POST'])
def forgot_password(modid):
    try:
        mod = Mod.get(Mod.id == modid)
    except Mod.DoesNotExist:
        flash("No such mod!")
        return abort(404)

    if request.method == 'POST':
        token = reset_ts.dumps(modid)
        reset_url = url_for('confirm_reset', token=token, _external=True)
        content = render_template(
            'auth/reset-password-pm.txt', name=mod.name, reset_url=reset_url)

        br = get_browser()
        pm_url = send_pm(br, mod.name, "PowerTools Password Reset", content)
        return render_template(
            'auth/reset-sent.html', name=mod.name, pm_url=pm_url)

    return render_template('auth/forgot-password.html', name=mod.name)


@app.route('/user/reset-password/confirm/<token>/')
def confirm_reset(token):
    try:
        modid = reset_ts.loads(token, max_age=60 * 60 * 48)
    except itsdangerous.BadSignature as e:
        flash(e.message)
        return redirect(url_for('login'))

    try:
        mod = Mod.get(Mod.id == modid)
    except Mod.DoesNotExist:
        flash("No such mod.")
        return redirect(url_for('login'))

    login_user(mod, remember=True)
    return redirect(url_for('change_password'))


@app.route('/user/change-password/', methods=['GET', 'POST'])
@login_required
def change_password():
    mod = current_user
    if request.method == 'POST':
        password = request.form.get('password')
        if check_password(password):
            mod.set_password(password)
            mod.save()
            return redirect(get_next_url())
    return render_template('auth/change-password.html')


@app.route('/user/masquerade/', methods=['GET', 'POST'])
@require_superuser
def masquerade():
    if request.method == 'POST':
        # TODO: do this with actual support, instead of logging in as them
        target = request.form.get('modid')
        try:
            mod = Mod.get(Mod.id == target)
        except Mod.DoesNotExist:
            flash("Huh? No such user.")
        else:
            flash("Okay, now you're {}! Remember to log out when you're done."
                  .format(mod.name))
            login_user(mod, remember=False)
            return redirect(get_next_url())

    mods = Mod.select().order_by(fn.Lower(Mod.name))
    return render_template('auth/masquerade.html', mods=mods)


@app.route('/logout/')
def logout():
    logout_user()
    return redirect(get_next_url())


@app.context_processor
def inject_user():
    return {'user': current_user}
