from flask import abort, g, redirect, render_template, request
from flask.ext.login import LoginManager, login_user, logout_user, current_user
from peewee import fn

from .app import app, get_next_url
from .models import Mod

login_manager = LoginManager(app)
login_manager.login_view = 'login'


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
                mod = Mod.get_or_create(name=request.form['name'])
        else:
            mod = load_user(request.form.get('modid'))
            if mod is None:
                return abort(404)

        login_user(mod, remember=True)
        return redirect(get_next_url(request.form.get('next')))

    mods = Mod.select().order_by(fn.Lower(Mod.name))
    return render_template('login.html', mods=mods)


@app.route('/logout')
def logout():
    logout_user()
    return redirect(get_next_url(request.args.get('next')))


@app.context_processor
def inject_user():
    return {'user': current_user}
