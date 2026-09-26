"""
Application ARPPSD — Association des Relais Polyvalents du Poste de Santé
de Darou Khoudoss.

Zéro dépendance fragile : uniquement Flask + le module sqlite3 intégré à
Python. Aucune compilation, aucune bibliothèque externe pour la base de
données — ça évite les erreurs d'installation rencontrées avec SQLAlchemy/
psycopg2 sur certains PC Windows.

Pour lancer en local :
    pip install -r requirements.txt
    python app.py
Puis ouvrez http://127.0.0.1:5000 dans votre navigateur.
"""
import io
import os
from datetime import date
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for, session, flash,
                    send_from_directory, Response, abort)
from werkzeug.utils import secure_filename

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import db
import gdrive
from constants import ROLES, PERM_KEYS, PERM_LABELS, DEFAULT_PERMISSIONS, MONTHS_FR, DOC_CATEGORIES

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "cle-provisoire-a-changer")
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 Mo max par fichier envoyé

UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", os.path.join(os.path.dirname(__file__), "uploads"))
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

db.init_db(app)


@app.after_request
def backup_db_after_write(response):
    """Après chaque requête qui modifie des données (POST réussi), on
    envoie une copie à jour de la base vers Google Drive si configuré.
    Léger et silencieux : n'affecte jamais la réponse à l'utilisateur,
    même si Google Drive est indisponible."""
    if request.method == "POST" and response.status_code < 400 and gdrive.is_configured():
        try:
            gdrive.backup_db_file(db.DB_PATH)
        except Exception:
            pass
    return response


@app.errorhandler(413)
def file_too_large(e):
    flash("Le fichier est trop volumineux (20 Mo maximum).", "danger")
    return redirect(request.referrer or url_for("dashboard"))


# ============================== OUTILS ==============================

def get_permissions():
    return db.get_setting("permissions", DEFAULT_PERMISSIONS)


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    m = db.get_member(uid)
    if not m or m.status != "actif":
        session.clear()
        return None
    return {"id": m.id, "name": m.full_name, "role": m.fonction}


def current_perms():
    user = current_user()
    if not user:
        return {}
    return get_permissions().get(user["role"], {})


def add_audit(action, details=""):
    user = current_user()
    db.add_audit_log(action, f"{user['name']} ({user['role']})" if user else "Système", details)


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def require_perm(key):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_perms().get(key):
                flash("Vous n'avez pas la permission d'effectuer cette action.", "danger")
                return redirect(url_for("dashboard"))
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def generate_member_qr_svg(data):
    """Génère un QR code au format SVG (texte) sans dépendre de Pillow.
    Renvoie None si la bibliothèque 'qrcode' n'est pas disponible, pour que
    la page fonctionne quand même (juste sans image de QR code)."""
    try:
        import qrcode
        import qrcode.image.svg
        img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=10)
        buf = io.BytesIO()
        img.save(buf)
        return buf.getvalue().decode("utf-8")
    except Exception:
        return None


def format_file_size(num_bytes):
    if not num_bytes:
        return ""
    for unit in ["o", "Ko", "Mo", "Go"]:
        if num_bytes < 1024:
            return f"{num_bytes:.0f} {unit}" if unit == "o" else f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} To"


app.jinja_env.filters["file_size"] = format_file_size


def compute_member_status(member, year=None):
    year = year or date.today().year
    current_month = date.today().month
    join_year = member.join_date.year if member.join_date else year
    start_month = member.join_date.month if (member.join_date and join_year == year) else 1
    expected = max(current_month - start_month + 1, 0) if join_year <= year else 0
    paid = db.count_contributions_for_member(member.id, year)
    if expected == 0:
        return "à jour"
    if paid >= expected:
        return "à jour"
    if paid > 0:
        return "partiel"
    return "retard"


@app.context_processor
def inject_globals():
    user = current_user()
    unread = db.count_unread_notifications(user["id"], user["role"]) if user else 0
    return dict(
        current_user=user,
        perms=current_perms(),
        org_name=db.get_setting("org_name", "Association des Relais Polyvalents du Poste de Santé de Darou Khoudoss"),
        org_acronym=db.get_setting("org_acronym", "ARPPSD"),
        MONTHS_FR=MONTHS_FR,
        unread_notifications=unread,
    )


# ============================== AUTHENTIFICATION ==============================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        member_id = request.form.get("member_id", "")
        password = request.form.get("password", "")
        member = db.get_member(member_id) if member_id else None
        if member and member.status == "actif" and db.verify_member_password(member_id, password):
            session.clear()
            session["user_id"] = member_id
            return redirect(url_for("dashboard"))
        flash("Nom ou mot de passe incorrect.", "danger")
    members_list = db.get_members("actif")
    return render_template("login.html", members=members_list,
                            org_name=db.get_setting("org_name", "Association des Relais Polyvalents du Poste de Santé de Darou Khoudoss"),
                            org_acronym=db.get_setting("org_acronym", "ARPPSD"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ============================== RECHERCHE GLOBALE ==============================

@app.route("/recherche")
@login_required
def search():
    q = request.args.get("q", "").strip()
    results = {"members": [], "activities": [], "announcements": [], "documents": []}
    if len(q) >= 2:
        results["members"] = db.search_members(q)
        results["activities"] = db.search_activities(q)
        results["announcements"] = db.search_announcements(q)
        if current_perms().get("manage_documents") or True:
            results["documents"] = db.search_documents(q)
    total = sum(len(v) for v in results.values())
    return render_template("search_results.html", q=q, results=results, total=total)


# ============================== NOTIFICATIONS ==============================

@app.route("/notifications")
@login_required
def notifications():
    user = current_user()
    notifs = db.get_notifications_for_user(user["id"], user["role"], limit=100)
    return render_template("notifications.html", notifications=notifs)


@app.route("/notifications/<nid>/lire", methods=["POST"])
@login_required
def notification_read(nid):
    user = current_user()
    db.mark_notification_read(nid, user["id"])
    row = next((n for n in db.get_notifications_for_user(user["id"], user["role"], 100) if n.id == nid), None)
    return redirect(request.form.get("next") or url_for("notifications"))


@app.route("/notifications/tout-lire", methods=["POST"])
@login_required
def notifications_mark_all_read():
    user = current_user()
    db.mark_all_notifications_read(user["id"], user["role"])
    return redirect(url_for("notifications"))


# ============================== TABLEAU DE BORD ==============================

def run_diagnostics():
    """Vérifications de sécurité/fiabilité visibles seulement par l'admin
    sur le tableau de bord. Chaque alerte disparaît automatiquement une
    fois le problème corrigé (rien n'est stocké, tout est recalculé)."""
    issues = []
    on_render = os.environ.get("RENDER") is not None

    if on_render and not UPLOAD_FOLDER.startswith("/var/data") and not gdrive.is_configured():
        issues.append(dict(
            title="Documents non persistants",
            detail="Les documents téléversés seront effacés à chaque redéploiement. "
                   "Définissez UPLOAD_FOLDER=/var/data/uploads sur un disque persistant, "
                   "ou configurez GOOGLE_SERVICE_ACCOUNT_JSON + GOOGLE_DRIVE_FOLDER_ID "
                   "pour stocker les documents sur Google Drive gratuitement.",
        ))
    if app.config["SECRET_KEY"] == "cle-provisoire-a-changer":
        issues.append(dict(
            title="Clé secrète non personnalisée",
            detail="Définissez la variable d'environnement SECRET_KEY avec une valeur "
                   "unique et secrète dans les paramètres de votre hébergeur.",
        ))
    for m in db.get_members():
        if m.is_demo and db.verify_member_password(m.id, "demo1234"):
            issues.append(dict(
                title="Mot de passe de démonstration actif",
                detail=f"« {m.first_name} {m.last_name} » utilise encore le mot de passe "
                       "demo1234. Changez-le avant d'ouvrir l'application aux membres.",
            ))
            break
    return issues


@app.route("/")
@login_required
def dashboard():
    members = db.get_members("actif")
    statuses = [compute_member_status(m) for m in members]
    up_to_date = statuses.count("à jour")
    late = statuses.count("retard")

    year, month = date.today().year, date.today().month
    month_total = db.sum_contributions(year=year, month=month)
    annual_total = db.sum_contributions(year=year)
    total_in, total_out, solde = db.caisse_totals()

    upcoming = db.get_upcoming_activities(3)
    recent_caisse = db.get_caisse_ops()[:3]
    recent_announcements = db.get_recent_published_announcements(3)
    recent_docs = db.get_recent_documents(3)

    diagnostics = run_diagnostics() if current_user()["role"] == "ADMINISTRATEUR" else []

    return render_template(
        "dashboard.html",
        active_count=len(members), up_to_date=up_to_date, late=late, solde=solde,
        month_total=month_total, annual_total=annual_total, month_label=MONTHS_FR[month - 1], year=year,
        upcoming=upcoming, recent_caisse=recent_caisse, diagnostics=diagnostics,
        recent_announcements=recent_announcements, recent_docs=recent_docs,
    )


# ============================== MEMBRES ==============================

@app.route("/membres")
@login_required
def members():
    q = request.args.get("q", "").strip().lower()
    status_filter = request.args.get("status", "tous")
    members_list = db.get_members(status_filter)
    if q:
        members_list = [m for m in members_list if q in f"{m.first_name} {m.last_name} {m.member_code}".lower()]
    statuses = {m.id: compute_member_status(m) for m in members_list}
    return render_template("members.html", members=members_list, statuses=statuses,
                            q=q, status_filter=status_filter, roles=ROLES)


@app.route("/membres/<mid>")
@login_required
def member_detail(mid):
    member = db.get_member(mid)
    contribs = db.get_contributions_for_member(mid)[:8]
    return render_template("member_detail.html", member=member, contribs=contribs,
                            status=compute_member_status(member))


@app.route("/membres/nouveau", methods=["GET", "POST"])
@login_required
@require_perm("manage_members")
def member_new():
    if request.method == "POST":
        password = request.form.get("password", "").strip()
        if len(password) < 4:
            flash("Le mot de passe doit contenir au moins 4 caractères.", "danger")
            return render_template("member_form.html", member=None, roles=ROLES)
        count = db.count_members() + 1
        data = {
            "first_name": request.form["first_name"], "last_name": request.form["last_name"],
            "phone": request.form.get("phone"), "address": request.form.get("address"),
            "fonction": request.form.get("fonction", "MEMBRE"),
            "member_code": request.form.get("member_code") or f"ARPPSD-{count:03d}",
            "join_date": request.form["join_date"], "notes": request.form.get("notes"),
        }
        new_id = db.insert_member(data)
        db.set_member_password(new_id, password)
        add_audit("Ajout d'un membre", f"{data['first_name']} {data['last_name']}")
        flash("Membre ajouté.", "success")
        return redirect(url_for("members"))
    return render_template("member_form.html", member=None, roles=ROLES)


@app.route("/membres/<mid>/modifier", methods=["GET", "POST"])
@login_required
@require_perm("manage_members")
def member_edit(mid):
    m = db.get_member(mid)
    if request.method == "POST":
        data = {
            "first_name": request.form["first_name"], "last_name": request.form["last_name"],
            "phone": request.form.get("phone"), "address": request.form.get("address"),
            "fonction": request.form.get("fonction", "MEMBRE"),
            "member_code": request.form.get("member_code"),
            "join_date": request.form["join_date"], "notes": request.form.get("notes"),
        }
        db.update_member(mid, data)
        new_password = request.form.get("password", "").strip()
        if new_password:
            if len(new_password) < 4:
                flash("Le mot de passe doit contenir au moins 4 caractères (non modifié).", "danger")
            else:
                db.set_member_password(mid, new_password)
        add_audit("Modification d'un membre", f"{data['first_name']} {data['last_name']}")
        flash("Membre mis à jour.", "success")
        return redirect(url_for("member_detail", mid=mid))
    return render_template("member_form.html", member=m, roles=ROLES)


@app.route("/membres/<mid>/statut", methods=["POST"])
@login_required
@require_perm("manage_members")
def member_toggle_status(mid):
    m = db.get_member(mid)
    new_status = db.toggle_member_status(mid)
    add_audit("Changement de statut d'un membre", f"{m.full_name} → {new_status}")
    flash("Statut mis à jour.", "success")
    return redirect(url_for("member_detail", mid=mid))


@app.route("/membres/<mid>/carte")
@login_required
def member_card(mid):
    member = db.get_member(mid)
    if not member:
        abort(404)
    qr_data = f"ARPPSD|{member.member_code}|{member.full_name}|{member.fonction}"
    qr_svg = generate_member_qr_svg(qr_data)
    return render_template("member_card.html", member=member, qr_svg=qr_svg)


@app.route("/membres/<mid>/reinitialiser-mdp", methods=["POST"])
@login_required
@require_perm("manage_members")
def member_reset_password(mid):
    new_password = request.form.get("new_password", "").strip()
    m = db.get_member(mid)
    if len(new_password) < 4:
        flash("Le mot de passe doit contenir au moins 4 caractères.", "danger")
    else:
        db.set_member_password(mid, new_password)
        add_audit("Réinitialisation du mot de passe d'un membre", m.full_name)
        flash("Mot de passe réinitialisé.", "success")
    return redirect(url_for("member_detail", mid=mid))


@app.route("/mon-compte", methods=["GET", "POST"])
@login_required
def my_account():
    user = current_user()
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        if not db.verify_member_password(user["id"], current_password):
            flash("Mot de passe actuel incorrect.", "danger")
        elif len(new_password) < 4:
            flash("Le nouveau mot de passe doit contenir au moins 4 caractères.", "danger")
        elif new_password != confirm_password:
            flash("Les deux mots de passe ne correspondent pas.", "danger")
        else:
            db.set_member_password(user["id"], new_password)
            add_audit("Changement de mot de passe personnel")
            flash("Mot de passe mis à jour.", "success")
            return redirect(url_for("my_account"))
    return render_template("my_account.html")


# ============================== COTISATIONS ==============================

@app.route("/cotisations")
@login_required
def contributions():
    if not current_perms().get("view_finance"):
        flash("Accès restreint aux informations de cotisation.", "danger")
        return redirect(url_for("dashboard"))
    year = int(request.args.get("year", date.today().year))
    members_list = db.get_members("actif")
    grid = {}
    for m in members_list:
        row = {}
        for c in db.get_contributions_for_member(m.id, year):
            row[c.month] = c
        grid[m.id] = row
    monthly_fee = db.get_setting("monthly_fee", 250)
    annual_fee = db.get_setting("annual_fee", 3000)
    return render_template("contributions.html", members=members_list, grid=grid, year=year,
                            monthly_fee=monthly_fee, annual_fee=annual_fee)


@app.route("/cotisations/enregistrer", methods=["POST"])
@login_required
@require_perm("manage_contributions")
def contribution_save():
    member_id = request.form["member_id"]
    month = int(request.form["month"])
    year = int(request.form["year"])
    amount = int(request.form["amount"])
    date_paid = request.form["date_paid"]
    user = current_user()
    db.upsert_contribution(member_id, month, year, amount, date_paid, user["name"])
    add_audit("Enregistrement d'une cotisation", f"{MONTHS_FR[month-1]} {year}")
    db.insert_notification(
        "Cotisation enregistrée", f"{MONTHS_FR[month-1]} {year} — {amount} FCFA",
        link=url_for("member_detail", mid=member_id), target_member_id=member_id,
    )
    flash("Cotisation enregistrée.", "success")
    return redirect(url_for("contributions", year=year))


@app.route("/cotisations/<cid>/supprimer", methods=["POST"])
@login_required
@require_perm("manage_contributions")
def contribution_delete(cid):
    c = db.get_contribution(cid)
    year = c.year if c else date.today().year
    db.delete_contribution(cid)
    add_audit("Suppression d'une cotisation")
    flash("Cotisation supprimée.", "success")
    return redirect(url_for("contributions", year=year))


# ============================== CAISSE SOCIALE ==============================

@app.route("/caisse")
@login_required
def caisse():
    if not current_perms().get("view_finance"):
        flash("Accès restreint à la caisse sociale.", "danger")
        return redirect(url_for("dashboard"))
    type_filter = request.args.get("type", "tous")
    ops = db.get_caisse_ops(type_filter)
    total_in, total_out, solde = db.caisse_totals()
    return render_template("caisse.html", ops=ops, total_in=total_in, total_out=total_out,
                            solde=solde, type_filter=type_filter)


@app.route("/caisse/ajouter", methods=["POST"])
@login_required
@require_perm("manage_caisse")
def caisse_add():
    user = current_user()
    db.insert_caisse_op(request.form["type"], int(request.form["amount"]),
                         request.form["date"], request.form["motif"], user["name"])
    add_audit(f"Opération caisse ({request.form['type']})", f"{request.form['motif']} — {request.form['amount']} FCFA")
    flash("Opération enregistrée.", "success")
    return redirect(url_for("caisse"))


# ============================== ACTIVITÉS ==============================

@app.route("/activites")
@login_required
def activities():
    status_filter = request.args.get("status", "tous")
    acts = db.get_activities(status_filter)
    return render_template("activities.html", activities=acts, status_filter=status_filter)


@app.route("/activites/<aid>")
@login_required
def activity_detail(aid):
    a = db.get_activity(aid)
    return render_template("activity_detail.html", a=a)


@app.route("/activites/nouvelle", methods=["GET", "POST"])
@login_required
@require_perm("manage_activities")
def activity_new():
    if request.method == "POST":
        data = {
            "title": request.form["title"], "description": request.form.get("description"),
            "date": request.form["date"], "time": request.form.get("time"),
            "location": request.form.get("location"), "responsable": request.form.get("responsable"),
            "status": request.form.get("status", "prévue"), "report": request.form.get("report"),
        }
        ids = request.form.getlist("participants")
        aid = db.insert_activity(data, ids)
        add_audit("Création d'une activité", data["title"])
        db.insert_notification("Nouvelle activité", f"{data['title']} — {data['date']}",
                                link=url_for("activity_detail", aid=aid))
        flash("Activité créée.", "success")
        return redirect(url_for("activity_detail", aid=aid))
    members_list = db.get_members("actif")
    return render_template("activity_form.html", activity=None, members=members_list)


@app.route("/activites/<aid>/modifier", methods=["GET", "POST"])
@login_required
@require_perm("manage_activities")
def activity_edit(aid):
    a = db.get_activity(aid)
    if request.method == "POST":
        data = {
            "title": request.form["title"], "description": request.form.get("description"),
            "date": request.form["date"], "time": request.form.get("time"),
            "location": request.form.get("location"), "responsable": request.form.get("responsable"),
            "status": request.form.get("status", "prévue"), "report": request.form.get("report"),
        }
        ids = request.form.getlist("participants")
        db.update_activity(aid, data, ids)
        add_audit("Modification d'une activité", data["title"])
        flash("Activité mise à jour.", "success")
        return redirect(url_for("activity_detail", aid=aid))
    members_list = db.get_members("actif")
    return render_template("activity_form.html", activity=a, members=members_list)


# ============================== ANNONCES ==============================

@app.route("/annonces")
@login_required
def announcements():
    return render_template("announcements.html", announcements=db.get_announcements())


@app.route("/annonces/ajouter", methods=["POST"])
@login_required
@require_perm("manage_announcements")
def announcement_add():
    user = current_user()
    db.insert_announcement(request.form["title"], request.form["content"],
                            request.form.get("status", "publié"), user["name"])
    add_audit("Publication d'une annonce", request.form["title"])
    if request.form.get("status", "publié") == "publié":
        db.insert_notification("Nouvelle annonce", request.form["title"], link=url_for("announcements"))
    flash("Annonce enregistrée.", "success")
    return redirect(url_for("announcements"))


@app.route("/annonces/<aid>/modifier", methods=["POST"])
@login_required
@require_perm("manage_announcements")
def announcement_edit(aid):
    db.update_announcement(aid, request.form["title"], request.form["content"], request.form.get("status", "publié"))
    add_audit("Modification d'une annonce", request.form["title"])
    flash("Annonce mise à jour.", "success")
    return redirect(url_for("announcements"))


# ============================== DOCUMENTS ==============================

@app.route("/documents")
@login_required
def documents():
    cat_filter = request.args.get("category", "Toutes")
    return render_template("documents.html", documents=db.get_documents(cat_filter),
                            categories=DOC_CATEGORIES, cat_filter=cat_filter)


@app.route("/documents/ajouter", methods=["POST"])
@login_required
@require_perm("manage_documents")
def document_add():
    user = current_user()
    filename = original_name = None
    file_size = None
    drive_file_id = None
    uploaded = request.files.get("file")
    if uploaded and uploaded.filename:
        original_name = secure_filename(uploaded.filename)
        if gdrive.is_configured():
            uploaded.stream.seek(0, os.SEEK_END)
            file_size = uploaded.stream.tell()
            uploaded.stream.seek(0)
            drive_file_id = gdrive.upload_file(uploaded, original_name)
            if drive_file_id is None:
                flash("Le fichier n'a pas pu être envoyé sur Google Drive, il a été gardé en local.", "warning")
        if drive_file_id is None:
            ext = os.path.splitext(original_name)[1]
            filename = f"{db.gen_id()}{ext}"
            uploaded.save(os.path.join(UPLOAD_FOLDER, filename))
            file_size = os.path.getsize(os.path.join(UPLOAD_FOLDER, filename))
    db.insert_document(request.form["name"], request.form.get("category"),
                        request.form.get("note"), user["name"],
                        filename=filename, original_name=original_name, file_size=file_size,
                        drive_file_id=drive_file_id)
    add_audit("Ajout d'un document", request.form["name"])
    flash("Document enregistré.", "success")
    return redirect(url_for("documents"))


@app.route("/documents/<did>/telecharger")
@login_required
def document_download(did):
    doc = db.get_document(did)
    if not doc:
        abort(404)
    if doc.drive_file_id:
        buf = gdrive.download_file(doc.drive_file_id)
        if buf is None:
            abort(404)
        return Response(buf.read(), mimetype="application/octet-stream", headers={
            "Content-Disposition": f"attachment; filename=\"{doc.original_name or 'document'}\""
        })
    if not doc.filename:
        abort(404)
    return send_from_directory(UPLOAD_FOLDER, doc.filename, as_attachment=True,
                                download_name=doc.original_name or doc.filename)


@app.route("/documents/<did>/supprimer", methods=["POST"])
@login_required
@require_perm("manage_documents")
def document_delete(did):
    name, stored_filename, drive_file_id = db.delete_document(did)
    if drive_file_id:
        gdrive.delete_file(drive_file_id)
    elif stored_filename:
        path = os.path.join(UPLOAD_FOLDER, stored_filename)
        if os.path.exists(path):
            os.remove(path)
    add_audit("Suppression d'un document", name)
    flash("Document supprimé.", "success")
    return redirect(url_for("documents"))


# ============================== RAPPORTS ==============================

def _report_data():
    year = date.today().year
    members_list = db.get_members("actif")
    statuses = [compute_member_status(m) for m in members_list]
    total_in, total_out, solde = db.caisse_totals()
    annual_contribs = db.sum_contributions(year=year)
    return dict(
        year=year, active_count=len(members_list),
        up_to_date=statuses.count("à jour"), partial=statuses.count("partiel"), late=statuses.count("retard"),
        annual_contribs=annual_contribs, solde=solde, total_in=total_in, total_out=total_out,
        total_activities=db.count_activities(), realized=db.count_activities("réalisée"),
        upcoming=db.count_activities("prévue"),
    )


@app.route("/rapports/pdf")
@login_required
def report_pdf():
    if not current_perms().get("view_finance"):
        flash("Accès restreint aux rapports financiers.", "danger")
        return redirect(url_for("dashboard"))
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas as pdfcanvas

    d = _report_data()
    org_name = db.get_setting("org_name", "Association des Relais Polyvalents du Poste de Santé de Darou Khoudoss")
    org_acronym = db.get_setting("org_acronym", "ARPPSD")

    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=A4)
    width, height = A4
    primary = colors.HexColor("#146356")
    muted = colors.HexColor("#6C776F")

    y = height - 25 * mm
    logo_path = os.path.join(app.root_path, "static", "logo.jpg")
    if os.path.exists(logo_path):
        try:
            c.drawImage(logo_path, 20 * mm, y - 10 * mm, width=18 * mm, height=18 * mm,
                        preserveAspectRatio=True, mask="auto")
        except Exception:
            pass
    c.setFont("Helvetica-Bold", 15)
    c.setFillColor(primary)
    c.drawString(44 * mm, y - 2 * mm, org_acronym)
    c.setFont("Helvetica", 9)
    c.setFillColor(muted)
    c.drawString(44 * mm, y - 8 * mm, org_name[:70])
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 8)
    c.drawRightString(width - 20 * mm, y - 2 * mm, f"Rapport généré le {date.today().strftime('%d/%m/%Y')}")

    y -= 22 * mm

    def section(title, rows):
        nonlocal y
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(primary)
        c.drawString(20 * mm, y, title)
        y -= 7 * mm
        c.setFont("Helvetica", 10)
        c.setFillColor(colors.black)
        for label, value in rows:
            c.drawString(22 * mm, y, label)
            c.drawRightString(width - 20 * mm, y, str(value))
            c.line(20 * mm, y - 2 * mm, width - 20 * mm, y - 2 * mm)
            y -= 7 * mm
        y -= 6 * mm

    section("Rapport membres", [
        ("Membres actifs", d["active_count"]),
        ("Membres à jour", d["up_to_date"]),
        ("Partiellement à jour", d["partial"]),
        ("En retard", d["late"]),
    ])
    section(f"Cotisations & caisse sociale {d['year']}", [
        ("Cotisations perçues", f"{d['annual_contribs']:,} FCFA".replace(",", " ")),
        ("Solde caisse sociale", f"{d['solde']:,} FCFA".replace(",", " ")),
        ("Total entrées", f"{d['total_in']:,} FCFA".replace(",", " ")),
        ("Total sorties", f"{d['total_out']:,} FCFA".replace(",", " ")),
    ])
    section("Activités", [
        ("Total activités", d["total_activities"]),
        ("Réalisées", d["realized"]),
        ("À venir", d["upcoming"]),
    ])

    c.showPage()
    c.save()
    buf.seek(0)
    add_audit("Export PDF du rapport")
    return Response(buf.read(), mimetype="application/pdf", headers={
        "Content-Disposition": f"attachment; filename=rapport-{org_acronym.lower()}-{date.today().isoformat()}.pdf"
    })


@app.route("/rapports")
@login_required
def reports():
    if not current_perms().get("view_finance"):
        flash("Accès restreint aux rapports financiers.", "danger")
        return redirect(url_for("dashboard"))
    return render_template("reports.html", **_report_data())


# ============================== PARAMÈTRES ==============================

@app.route("/parametres", methods=["GET", "POST"])
@login_required
def settings_view():
    if not current_perms().get("manage_users") and not current_perms().get("view_audit_log"):
        flash("Accès réservé à l'administration.", "danger")
        return redirect(url_for("dashboard"))

    if request.method == "POST" and current_perms().get("manage_users"):
        db.set_setting("org_name", request.form["org_name"])
        db.set_setting("org_acronym", request.form["org_acronym"])
        db.set_setting("monthly_fee", int(request.form["monthly_fee"]))
        db.set_setting("annual_fee", int(request.form["annual_fee"]))
        flash("Paramètres enregistrés.", "success")
        return redirect(url_for("settings_view"))

    tab = request.args.get("tab", "general")
    permissions = get_permissions()
    logs = db.get_audit_logs(50)
    return render_template(
        "settings.html", tab=tab, roles=ROLES, perm_keys=PERM_KEYS, perm_labels=PERM_LABELS,
        permissions=permissions, logs=logs,
        org_name=db.get_setting("org_name", "Association des Relais Polyvalents du Poste de Santé de Darou Khoudoss"),
        org_acronym=db.get_setting("org_acronym", "ARPPSD"),
        monthly_fee=db.get_setting("monthly_fee", 250), annual_fee=db.get_setting("annual_fee", 3000),
    )


@app.route("/parametres/sauvegarde")
@login_required
@require_perm("manage_users")
def backup_download():
    buf = _build_backup_zip()
    add_audit("Téléchargement d'une sauvegarde")
    org_acronym = db.get_setting("org_acronym", "ARPPSD")
    stamp = date.today().isoformat()
    return Response(buf.read(), mimetype="application/zip", headers={
        "Content-Disposition": f"attachment; filename=sauvegarde-{org_acronym.lower()}-{stamp}.zip"
    })


@app.route("/parametres/sauvegarde-drive", methods=["POST"])
@login_required
@require_perm("manage_users")
def backup_to_drive():
    if not gdrive.is_configured():
        flash("Google Drive n'est pas configuré (variables d'environnement manquantes).", "danger")
        return redirect(url_for("settings_view", tab="general"))
    buf = _build_backup_zip()
    org_acronym = db.get_setting("org_acronym", "ARPPSD")
    stamp = date.today().strftime("%Y-%m-%d_%Hh%M")
    filename = f"sauvegarde-{org_acronym.lower()}-{stamp}.zip"
    file_id = gdrive.upload_bytes(buf, filename, mimetype="application/zip")
    if file_id is None:
        flash("Échec de l'envoi vers Google Drive. Vérifiez la configuration.", "danger")
    else:
        add_audit("Sauvegarde envoyée sur Google Drive", filename)
        flash(f"Sauvegarde envoyée sur Google Drive : {filename}", "success")
    return redirect(url_for("settings_view", tab="general"))


@app.route("/parametres/restaurer", methods=["POST"])
@login_required
@require_perm("manage_users")
def restore_backup():
    import zipfile
    uploaded = request.files.get("backup_file")
    if not uploaded or not uploaded.filename:
        flash("Choisissez un fichier de sauvegarde (.zip) à importer.", "danger")
        return redirect(url_for("settings_view", tab="general"))
    if not uploaded.filename.lower().endswith(".zip"):
        flash("Le fichier doit être un .zip de sauvegarde.", "danger")
        return redirect(url_for("settings_view", tab="general"))
    try:
        zf = zipfile.ZipFile(uploaded.stream)
        names = zf.namelist()
        if "arppsd.db" not in names:
            flash("Ce fichier ne contient pas de base de données (arppsd.db) valide.", "danger")
            return redirect(url_for("settings_view", tab="general"))
        db.close_db()
        with zf.open("arppsd.db") as src, open(db.DB_PATH, "wb") as dst:
            dst.write(src.read())
        for name in names:
            if name.startswith("uploads/") and not name.endswith("/"):
                target_name = os.path.basename(name)
                if not target_name:
                    continue
                with zf.open(name) as src, open(os.path.join(UPLOAD_FOLDER, target_name), "wb") as dst:
                    dst.write(src.read())
    except zipfile.BadZipFile:
        flash("Le fichier envoyé n'est pas un zip valide.", "danger")
        return redirect(url_for("settings_view", tab="general"))
    except Exception:
        flash("Erreur pendant la restauration : le fichier est peut-être corrompu.", "danger")
        return redirect(url_for("settings_view", tab="general"))
    session.clear()
    flash("Sauvegarde restaurée avec succès. Merci de vous reconnecter.", "success")
    return redirect(url_for("login"))


def _build_backup_zip():
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if os.path.exists(db.DB_PATH):
            zf.write(db.DB_PATH, arcname="arppsd.db")
        if os.path.isdir(UPLOAD_FOLDER):
            for fname in os.listdir(UPLOAD_FOLDER):
                fpath = os.path.join(UPLOAD_FOLDER, fname)
                if os.path.isfile(fpath):
                    zf.write(fpath, arcname=os.path.join("uploads", fname))
    buf.seek(0)
    return buf


@app.route("/parametres/permissions", methods=["POST"])
@login_required
@require_perm("manage_users")
def settings_permissions():
    role = request.form["role"]
    key = request.form["key"]
    permissions = get_permissions()
    permissions.setdefault(role, {})
    permissions[role][key] = not permissions[role].get(key, False)
    db.set_setting("permissions", permissions)
    return redirect(url_for("settings_view", tab="roles"))


@app.route("/parametres/reinitialiser", methods=["POST"])
@login_required
@require_perm("manage_users")
def reset_demo():
    db.clear_all_data()
    seed_demo_data()
    add_audit("Réinitialisation des données de démonstration")
    flash("Données de démonstration réinitialisées.", "success")
    return redirect(url_for("dashboard"))


# ============================== DONNÉES DE DÉMONSTRATION ==============================

def seed_demo_data():
    """Crée des données provisoires clairement marquées 'démo', à remplacer par les
    informations officielles de l'association dès qu'elles seront disponibles."""
    if db.count_members() > 0:
        return
    year = date.today().year

    m1 = db.insert_member({"first_name": "Aïda", "last_name": "Ndiaye", "phone": "77 000 00 01",
                            "address": "Darou Khoudoss", "fonction": "SECRÉTAIRE", "member_code": "ARPPSD-001",
                            "join_date": f"{year}-01-10", "notes": "", "is_demo": True})
    m2 = db.insert_member({"first_name": "Moussa", "last_name": "Diop", "phone": "77 000 00 02",
                            "address": "Darou Khoudoss", "fonction": "TRÉSORIÈRE", "member_code": "ARPPSD-002",
                            "join_date": f"{year}-01-12", "notes": "", "is_demo": True})
    m3 = db.insert_member({"first_name": "Fatou", "last_name": "Sarr", "phone": "77 000 00 03",
                            "address": "Darou Khoudoss", "fonction": "MEMBRE", "member_code": "ARPPSD-003",
                            "join_date": f"{year}-02-01", "notes": "", "is_demo": True})
    admin = db.insert_member({"first_name": "Admin", "last_name": "Démo", "phone": "",
                               "address": "", "fonction": "ADMINISTRATEUR", "member_code": "ARPPSD-000",
                               "join_date": f"{year}-01-01", "notes": "Compte de démonstration à supprimer plus tard.",
                               "is_demo": True})
    for mid in (m1, m2, m3, admin):
        db.set_member_password(mid, "demo1234")

    db.upsert_contribution(m1, 1, year, 250, f"{year}-01-15", "Démo")
    db.upsert_contribution(m1, 2, year, 250, f"{year}-02-14", "Démo")
    db.upsert_contribution(m2, 1, year, 250, f"{year}-01-16", "Démo")

    db.insert_caisse_op("entrée", 500, f"{year}-01-20", "Cotisations sociales (démo)", "Trésorière (démo)")
    db.insert_caisse_op("sortie", 100, f"{year}-02-05", "Aide sociale ponctuelle (démo)", "Trésorière (démo)")

    db.insert_activity({
        "title": "Séance de Seet-Setal (démo)", "description": "Nettoyage communautaire autour du poste de santé.",
        "date": f"{year}-03-02", "time": "08:00", "location": "Darou Khoudoss",
        "responsable": "Organisation (démo)", "status": "réalisée", "report": "Compte rendu à compléter.",
    }, [m1, m3])
    db.insert_activity({
        "title": "Assemblée Générale", "description": "Contenu officiel à fournir par le bureau.",
        "date": f"{year}-08-08", "time": "10:00", "location": "À préciser",
        "responsable": "Président", "status": "réalisée",
        "report": "Procès-verbal officiel à ajouter ultérieurement.",
    }, [])

    db.insert_announcement("Bienvenue sur l'application ARPPSD (démo)",
                            "Ceci est une version provisoire. Les informations officielles seront ajoutées progressivement.",
                            "publié", "Administrateur")
    db.insert_document("Statuts de l'association", "Statuts", "En attente du document officiel", "Démo")


with app.app_context():
    if db.get_setting("permissions") is None:
        db.set_setting("permissions", DEFAULT_PERMISSIONS)
    seed_demo_data()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
