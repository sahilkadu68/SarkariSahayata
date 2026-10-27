from flask import (
    Blueprint, render_template, request,
    redirect, url_for, session, flash,
    make_response, current_app
)
from flaskr.db import get_db
from flaskr import limiter
from flaskr.auth import verify_and_upgrade_password
from flaskr.pii import configured_key, decrypt_value, decrypt_email
import MySQLdb.cursors
import csv, io, datetime

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

def admin_required(fn):
    import functools
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            flash("Please log in as admin first.", "warning")
            return redirect(url_for("admin.admin_login"))
        return fn(*args, **kwargs)
    return wrapper

def log_activity(action, detail=""):
    try:
        db = get_db()
        cur = db.cursor()
        admin_name = session.get("admin_username", "admin")
        cur.execute(
            "INSERT INTO admin_activity_log (admin_name, action, detail, created_at) VALUES (%s,%s,%s,NOW())",
            (admin_name, action, detail)
        )
        db.commit()
    except Exception:
        pass

@admin_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def admin_login():
    if session.get("admin_logged_in"):
        return redirect(url_for("admin.info_dashboard"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        master_user = current_app.config.get("MASTER_USER", "sarkariadmin1")
        master_pass = current_app.config.get("MASTER_PASSWORD", "sarkari123")
        valid = False
        if username == master_user and password == master_pass:
            valid = True
            session["admin_role"] = "master"
        else:
            try:
                db = get_db()
                cur = db.cursor(MySQLdb.cursors.DictCursor)
                cur.execute(
                    "SELECT * FROM user WHERE username=%s AND user_type IN ('admin','master')",
                    (username,)
                )
                row = cur.fetchone()
                if row:
                    password_valid, upgraded_hash = verify_and_upgrade_password(
                        row["password"], password
                    )
                    if password_valid:
                        valid = True
                        session["admin_role"] = row["user_type"]
                        if upgraded_hash:
                            cur.execute("UPDATE user SET password=%s WHERE id=%s",
                                        (upgraded_hash, row["id"]))
                            db.commit()
            except Exception:
                pass
        if valid:
            session["admin_logged_in"] = True
            session["admin_username"] = username
            log_activity("LOGIN", f"{username} logged in")
            return redirect(url_for("admin.info_dashboard"))
        else:
            error = "Invalid username or password."
    return render_template("admin_login.html", error=error)

@admin_bp.route("/logout")
def admin_logout():
    log_activity("LOGOUT", f"{session.get('admin_username','?')} logged out")
    session.pop("admin_logged_in", None)
    session.pop("admin_username", None)
    session.pop("admin_role", None)
    flash("You have been logged out.", "info")
    return redirect(url_for("admin.admin_login"))

@admin_bp.route("/dashboard")
@admin_required
def info_dashboard():
    db  = get_db()
    cur = db.cursor(MySQLdb.cursors.DictCursor)
    gender = [0, 0]
    cur.execute("SELECT COUNT(*) AS c FROM user");           reg   = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM user_details");   info  = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM schemes");        total = cur.fetchone()["c"]
    categories = ["Education","Health","Agriculture","Skills and Employment","Housing","Women and Child"]
    cat_count = []
    for c in categories:
        cur.execute("SELECT COUNT(*) AS c FROM schemes WHERE category=%s", (c,))
        cat_count.append(cur.fetchone()["c"])
    aggregate_counts = {}
    cur.execute("SELECT user_id, gender, caste, occupation FROM user_details")
    profile_rows = cur.fetchall()
    key = configured_key()
    for profile in profile_rows:
        owner_id = profile.get("user_id")
        for field in ("gender", "caste", "occupation"):
            profile[field] = decrypt_value(profile.get(field), field, owner_id, key)
        if profile.get("gender") == "Male":
            gender[0] += 1
        elif profile.get("gender") == "Female":
            gender[1] += 1
        caste = profile.get("caste")
        if caste:
            aggregate_counts[caste] = aggregate_counts.get(caste, 0) + 1
    caste_count = [aggregate_counts.get(c, 0) for c in ["General", "OBC", "SC", "ST", "Other"]]
    recent_logs = []
    try:
        cur.execute("SELECT * FROM admin_activity_log ORDER BY created_at DESC LIMIT 5")
        recent_logs = cur.fetchall()
    except Exception:
        pass
    occupation_counts = {}
    for profile in profile_rows:
        occupation = profile.get("occupation")
        if occupation:
            occupation_counts[occupation] = occupation_counts.get(occupation, 0) + 1
    occupations = [
        {"occupation": occupation, "c": count}
        for occupation, count in sorted(occupation_counts.items(), key=lambda item: item[1], reverse=True)[:6]
    ]
    cur.close()
    return render_template(
        "admin/dashboard.html",
        gender_data=gender, registrations=reg, info=info,
        total_schemes=total, cat_list=cat_count,
        caste_data=caste_count, recent_logs=recent_logs,
        occupations=occupations,
        admin_username=session.get("admin_username","Admin"),
        admin_role=session.get("admin_role","admin"),
    )

@admin_bp.route("/admin_page", methods=["GET", "POST"])
@admin_required
def admin_dashboard():
    db     = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    if request.method == "POST":
        title               = request.form.get("title")
        category            = request.form.get("category")
        description         = request.form.get("description")         or None
        benefits            = request.form.get("benefits")            or None
        objectives          = request.form.get("objectives")          or None
        application_process = request.form.get("application_process") or None
        documents           = request.form.get("documents")           or None
        min_age    = request.form.get("min_age");    min_age    = int(min_age)    if min_age    else None
        max_age    = request.form.get("max_age");    max_age    = int(max_age)    if max_age    else None
        max_income = request.form.get("max_income"); max_income = int(max_income) if max_income else None
        gender     = request.form.get("gender")     or None
        caste      = request.form.get("caste")      or None
        state      = request.form.get("state")      or None
        occupation = request.form.get("occupation") or None
        eligibility    = request.form.get("eligibility")          or None
        exclusions     = request.form.get("exclusions")           or None
        faq            = request.form.get("faq")                  or None
        table_data     = request.form.get("table_data")           or None
        table_section  = request.form.get("table_section","benefits")
        tags           = request.form.get("tags")                 or None
        cursor.execute("""
            INSERT INTO schemes (title, category, description, benefits, objectives,
             application_process, documents, min_age, max_age, max_income,
             gender, caste, state, occupation,
             eligibility, exclusions, faq, table_data, table_section, tags)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (title, category, description, benefits, objectives,
              application_process, documents,
              min_age, max_age, max_income, gender, caste, state, occupation,
              eligibility, exclusions, faq, table_data, table_section, tags))
        db.commit()
        log_activity("ADD_SCHEME", f"Added: {title}")
        flash(f"Scheme '{title}' added successfully!", "success")
        return redirect(url_for("admin.admin_dashboard"))
    search   = request.args.get("q", "").strip()
    cat_filt = request.args.get("cat", "").strip()
    query    = "SELECT * FROM schemes WHERE 1=1"
    params   = []
    if search:
        query  += " AND (title LIKE %s OR description LIKE %s)"
        params += [f"%{search}%", f"%{search}%"]
    if cat_filt:
        query  += " AND category=%s"
        params.append(cat_filt)
    query += " ORDER BY id DESC"
    cursor.execute(query, params)
    schemes = cursor.fetchall()
    return render_template(
        "admin_dashboard.html", schemes=schemes, search=search, cat_filter=cat_filt,
        admin_username=session.get("admin_username","Admin"),
        admin_role=session.get("admin_role","admin"),
    )

@admin_bp.route("/scheme/edit/<int:scheme_id>", methods=["GET", "POST"])
@admin_required
def edit_scheme(scheme_id):
    db     = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    if request.method == "POST":
        title               = request.form.get("title")
        category            = request.form.get("category")
        description         = request.form.get("description")         or None
        benefits            = request.form.get("benefits")            or None
        objectives          = request.form.get("objectives")          or None
        application_process = request.form.get("application_process") or None
        documents           = request.form.get("documents")           or None
        min_age    = request.form.get("min_age");    min_age    = int(min_age)    if min_age    else None
        max_age    = request.form.get("max_age");    max_age    = int(max_age)    if max_age    else None
        max_income = request.form.get("max_income"); max_income = int(max_income) if max_income else None
        gender     = request.form.get("gender")     or None
        caste      = request.form.get("caste")      or None
        state      = request.form.get("state")      or None
        occupation = request.form.get("occupation") or None
        eligibility    = request.form.get("eligibility")          or None
        exclusions     = request.form.get("exclusions")           or None
        faq            = request.form.get("faq")                  or None
        table_data     = request.form.get("table_data")           or None
        table_section  = request.form.get("table_section","benefits")
        tags           = request.form.get("tags")                 or None
        cursor.execute("""
            UPDATE schemes SET title=%s, category=%s, description=%s, benefits=%s,
              objectives=%s, application_process=%s, documents=%s,
              min_age=%s, max_age=%s, max_income=%s,
              gender=%s, caste=%s, state=%s, occupation=%s,
              eligibility=%s, exclusions=%s, faq=%s,
              table_data=%s, table_section=%s, tags=%s
            WHERE id=%s
        """, (title, category, description, benefits, objectives,
              application_process, documents,
              min_age, max_age, max_income,
              gender, caste, state, occupation,
              eligibility, exclusions, faq, table_data, table_section, tags,
              scheme_id))
        db.commit()
        log_activity("EDIT_SCHEME", f"Edited ID {scheme_id}: {title}")
        flash(f"Scheme '{title}' updated!", "success")
        return redirect(url_for("admin.admin_dashboard"))
    cursor.execute("SELECT * FROM schemes WHERE id=%s", (scheme_id,))
    scheme = cursor.fetchone()
    if not scheme:
        flash("Scheme not found.", "danger")
        return redirect(url_for("admin.admin_dashboard"))
    return render_template(
        "admin_edit_scheme.html", scheme=scheme,
        admin_username=session.get("admin_username","Admin"),
        admin_role=session.get("admin_role","admin"),
    )

@admin_bp.route("/scheme/delete/<int:scheme_id>", methods=["POST"])
@admin_required
def delete_scheme(scheme_id):
    db     = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT title FROM schemes WHERE id=%s", (scheme_id,))
    row = cursor.fetchone()
    if row:
        cursor.execute("DELETE FROM schemes WHERE id=%s", (scheme_id,))
        db.commit()
        log_activity("DELETE_SCHEME", f"Deleted ID {scheme_id}: {row['title']}")
        flash(f"Scheme '{row['title']}' deleted.", "danger")
    return redirect(url_for("admin.admin_dashboard"))

@admin_bp.route("/view_user")
@admin_required
def view_user():
    db  = get_db()
    cur = db.cursor(MySQLdb.cursors.DictCursor)
    search = request.args.get("q", "").strip()
    cur.execute("SELECT * FROM user ORDER BY id DESC")
    users = cur.fetchall()
    key = configured_key()
    search_lower = search.casefold()
    users = [
        {**user, "email": decrypt_email(user["email"], user["username"], key)}
        for user in users
    ]
    if search:
        users = [user for user in users
                 if search_lower in user["username"].casefold()
                 or search_lower in user["email"].casefold()]
    return render_template(
        "admin/view_users.html", users=users, search=search,
        admin_username=session.get("admin_username","Admin"),
        admin_role=session.get("admin_role","admin"),
    )

@admin_bp.route("/user/delete/<int:user_id>", methods=["POST"])
@admin_required
def delete_user(user_id):
    if session.get("admin_role") != "master":
        flash("Only master admin can delete users.", "danger")
        return redirect(url_for("admin.view_user"))
    db  = get_db()
    cur = db.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT username FROM user WHERE id=%s", (user_id,))
    row = cur.fetchone()
    if row:
        cur.execute("DELETE FROM user WHERE id=%s", (user_id,))
        db.commit()
        log_activity("DELETE_USER", f"Deleted user: {row['username']}")
        flash(f"User '{row['username']}' deleted.", "danger")
    return redirect(url_for("admin.view_user"))

@admin_bp.route("/export/schemes")
@admin_required
def export_schemes():
    db  = get_db()
    cur = db.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT * FROM schemes ORDER BY id DESC")
    schemes = cur.fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID","Title","Category","Description","Benefits","Objectives",
        "Application Process","Documents","Min Age","Max Age","Max Income",
        "Gender","Caste","State","Occupation"])
    for s in schemes:
        writer.writerow([s.get("id"),s.get("title"),s.get("category"),
            s.get("description"),s.get("benefits"),s.get("objectives"),
            s.get("application_process"),s.get("documents"),
            s.get("min_age"),s.get("max_age"),s.get("max_income"),
            s.get("gender"),s.get("caste"),s.get("state"),s.get("occupation")])
    log_activity("EXPORT", "Exported schemes CSV")
    resp = make_response(output.getvalue())
    resp.headers["Content-Disposition"] = f"attachment; filename=schemes_{datetime.date.today()}.csv"
    resp.headers["Content-Type"] = "text/csv"
    return resp

@admin_bp.route("/activity-log")
@admin_required
def activity_log():
    db  = get_db()
    cur = db.cursor(MySQLdb.cursors.DictCursor)
    logs = []
    try:
        cur.execute("SELECT * FROM admin_activity_log ORDER BY created_at DESC LIMIT 100")
        logs = cur.fetchall()
    except Exception:
        flash("Run migration_activity_log.sql to enable this feature.", "warning")
    return render_template(
        "admin/activity_log.html", logs=logs,
        admin_username=session.get("admin_username","Admin"),
        admin_role=session.get("admin_role","admin"),
    )
