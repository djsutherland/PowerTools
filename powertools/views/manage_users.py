from flask import abort, flash, g, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from ..auth import require_test
from ..base import app
from ..models import Mod


@app.route("/user/manage/")
@require_test(lambda u: u.is_superuser)
def manage_users():
    return render_template(
        "manage_users.html", mods=Mod.select().order_by(Mod.name.asc())
    )


@app.route("/user/delete/<int:modid>/", methods=["GET", "POST"])
@require_test(lambda u: u.is_superuser)
def delete_user(modid):
    if current_user.id == modid:
        raise abort(400)
    try:
        mod = Mod.get(id=modid)
    except Mod.DoesNotExist:
        abort(404)

    if request.method == "GET":
        return render_template("delete_user.html", mod=mod)
    else:
        flash(f"Okay, {mod.name} is gone forever.")
        mod.delete_instance()
        return redirect(url_for('manage_users'))


@require_test(lambda u: u.is_superuser)
def update_mod(attr, bool_val=False):
    modid = request.form.get("modid", type=int)
    val = request.form.get("val")
    if bool_val:
        val = {"true": 1, "false": 0}.get(val, None)
    if val is None:
        return abort(400)

    try:
        with g.db.atomic():
            mod = Mod.get(id=modid)
            setattr(mod, attr, val)
            mod.save(only=[getattr(Mod, attr)])

            return jsonify(curr=val)
    except Mod.DoesNotExist:
        return abort(404)


@app.route("/user/_mark_reports_team/", methods=["POST"])
def _mark_reports_team():
    return update_mod("is_reports_team", bool_val=True)


@app.route("/user/_mark_superuser/", methods=["POST"])
def _mark_superuser():
    return update_mod("is_superuser", bool_val=True)


@app.route("/user/_mark_masquerader/", methods=["POST"])
def _mark_masquerader():
    return update_mod("is_masquerader", bool_val=True)


@app.route("/user/_mark_turfs_manager/", methods=["POST"])
def _mark_turfs_manager():
    return update_mod("is_turfs_manager", bool_val=True)
