import functools
import time
import random
import re

from flask import (
    Blueprint, flash, g, redirect,
    render_template, request, session, url_for
)
from werkzeug.security import check_password_hash, generate_password_hash
from flaskr.db import get_db
from flaskr import email, mail, limiter
from flaskr.pii import configured_key, email_lookup, encrypt_email, decrypt_email, mask_email


bp = Blueprint('auth', __name__, url_prefix='/auth')


def verify_and_upgrade_password(stored_password, supplied_password):
    """Verify modern hashes and transparently upgrade legacy plaintext rows."""
    if not isinstance(stored_password, str):
        return False, None

    if stored_password.startswith(('scrypt:', 'pbkdf2:')):
        try:
            return check_password_hash(stored_password, supplied_password), None
        except (ValueError, TypeError):
            return False, None

    # Older deployments may have plaintext passwords. Upgrade only after a
    # constant-time successful match; no schema change or bulk migration needed.
    import hmac
    if hmac.compare_digest(stored_password.encode('utf-8'),
                           supplied_password.encode('utf-8')):
        return True, generate_password_hash(supplied_password)
    return False, None


# ---------------- PASSWORD VALIDATION ----------------

def validate_password(password, username):
    if len(password) < 8:
        return "Password must be at least 8 characters long."
    if re.search(r"\s", password):
        return "Password must not contain spaces."
    if not re.search(r"[A-Z]", password):
        return "Password must contain at least one uppercase letter."
    if not re.search(r"[a-z]", password):
        return "Password must contain at least one lowercase letter."
    if not re.search(r"[0-9]", password):
        return "Password must contain at least one number."
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return "Password must contain at least one special character."
    if password.lower() == username.lower():
        return "Password cannot be same as username."
    return None


# ---------------- OTP HELPERS ----------------

def ensure_otps_table(cur):
    """
    Make sure the otps table has a proper user_id column.
    This handles both old schema (id=user_id) and new schema (user_id column).
    """
    try:
        # Try to add user_id column if it doesn't exist
        cur.execute("""
            ALTER TABLE otps
            ADD COLUMN IF NOT EXISTS user_id INT,
            ADD COLUMN IF NOT EXISTS otp_code VARCHAR(10)
        """)
    except Exception:
        pass  # columns already exist or DB doesn't support IF NOT EXISTS


def save_otp(user_id, otp):
    """
    Save OTP to database. Works with both old and new schema.
    Uses a simple REPLACE approach: delete existing, insert new.
    """
    db  = get_db()
    cur = db.cursor()

    # First try the new clean approach: store in a separate lookup column
    # Try DELETE + INSERT using the id column as user reference (original schema)
    try:
        # Delete any existing OTP for this user
        cur.execute("DELETE FROM otps WHERE id = %s", (user_id,))
        # Insert new OTP with explicit id = user_id
        cur.execute(
            "INSERT INTO otps (id, otp, created) VALUES (%s, %s, %s)",
            (user_id, otp, int(time.time()))
        )
        try:
            db.commit()
        except Exception:
            pass
        return True
    except Exception as e:
        raise Exception(f"OTP save failed: {str(e)}")


def create_otp(user_id):
    """Generate a 6-digit OTP and save it."""
    otp = str(random.randint(100000, 999999))
    save_otp(user_id, otp)
    return otp


def get_otp_record(user_id):
    """Retrieve OTP record for a user."""
    db  = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM otps WHERE id = %s", (user_id,))
    return cur.fetchone()


# =========================================
# REGISTER
# =========================================
@bp.route('/register', methods=('GET', 'POST'))
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        emails   = request.form.get('email', '').strip()

        error = None

        if not username:
            error = 'Username is required.'
        elif not password:
            error = 'Password is required.'
        elif not emails:
            error = 'Email is required.'
        else:
            error = validate_password(password, username)

        if error:
            flash(error)
            return render_template('auth/register.html')

        db  = get_db()
        cur = db.cursor()
        key = configured_key()
        email_index = email_lookup(emails, key)

        # ── STEP 1: Check if username or email already exists ────────────
        cur.execute("SELECT id FROM user WHERE username = %s OR email_lookup = %s",
                    (username, email_index))
        existing = cur.fetchone()
        if existing:
            flash("Username or email is already taken. Please use a different one.")
            return render_template('auth/register.html')

        # ── STEP 2: Insert the new user ──────────────────────────────────
        try:
            cur.execute(
                "INSERT INTO user (username, email, email_lookup, password, is_registered) "
                "VALUES (%s, %s, %s, %s, 0)",
                (username, encrypt_email(emails, username, key), email_index,
                 generate_password_hash(password)),
            )
            try:
                db.commit()
            except Exception:
                pass
        except Exception as e:
            flash("Registration failed. Please try again.")
            return render_template('auth/register.html')

        # ── STEP 3: Fetch the new user's ID ─────────────────────────────
        cur.execute("SELECT * FROM user WHERE username = %s", (username,))
        user = cur.fetchone()

        if not user:
            flash("Registration failed. Please try again.")
            return render_template('auth/register.html')

        user['email'] = decrypt_email(user['email'], user['username'], key)

        # ── STEP 4: Generate and save OTP ───────────────────────────────
        try:
            otp = create_otp(user['id'])
        except Exception as e:
            # OTP table issue - user is created, tell them clearly
            flash(f"Account created but OTP failed: {str(e)}. "
                  "Please contact support or try the Aiven console to run: "
                  "ALTER TABLE otps AUTO_INCREMENT = 1;")
            return render_template('auth/register.html')

        # ── STEP 5: Send OTP email ───────────────────────────────────────
        email_sent = False
        try:
            html = render_template('auth/confirmation_mail.html', otp=otp)
            email.send_email(
                user['email'],
                "OTP to verify your SarkariSahayata registration",
                html,
                mail
            )
            email_sent = True
        except Exception as e:
            # Email failed but OTP is saved — user can still verify if shown OTP
            pass

        # ── STEP 6: Redirect to OTP page ────────────────────────────────
        if not email_sent:
            # Show OTP directly on screen as fallback since email failed
            flash(f"Account created! Email delivery failed. Your OTP is: {otp} "
                  f"(valid 10 minutes). Use it on the next page.")

        return redirect(url_for("auth.verify_otp", identifier=user['id']))

    return render_template('auth/register.html')


# =========================================
# LOGIN
# =========================================
@bp.route('/login', methods=('GET', 'POST'))
@limiter.limit("5 per minute", methods=["POST"])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        db  = get_db()
        cur = db.cursor()
        error = None

        cur.execute("SELECT * FROM user WHERE username = %s", (username,))
        user = cur.fetchone()

        if user is None:
            error = 'Incorrect username.'
        else:
            password_valid, upgraded_hash = verify_and_upgrade_password(
                user['password'], password
            )
            if not password_valid:
                error = 'Incorrect password.'
            elif upgraded_hash:
                cur.execute("UPDATE user SET password = %s WHERE id = %s",
                            (upgraded_hash, user['id']))
                db.commit()
        if error is None and user['is_registered'] == 0:
            error = 'Email not verified. Please check your email for the OTP.'

        if error is None:
            session.clear()
            session['user_id'] = user['id']
            return redirect(url_for('home.index'))

        flash(error)

    return render_template('auth/login.html')


# =========================================
# LOAD USER
# =========================================
@bp.before_app_request
def load_logged_in_user():
    user_id = session.get('user_id')
    g.user = None

    if user_id is not None:
        try:
            db = get_db()
            cur = db.cursor(MySQLdb.cursors.DictCursor)
            cur.execute("SELECT * FROM user WHERE id = %s", (user_id,))
            g.user = cur.fetchone()
            cur.close()
        except Exception:
            g.user = None


# =========================================
# LOGOUT
# =========================================
@bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home.index'))


# =========================================
# VERIFY OTP
# =========================================
@bp.route('/verify-otp/<identifier>', methods=('GET', 'POST'))
def verify_otp(identifier):

    duration = 600  # 10 minutes

    db  = get_db()
    cur = db.cursor()

    key = configured_key()
    if identifier.isdigit():
        cur.execute("SELECT * FROM user WHERE id = %s", (int(identifier),))
    else:
        # Compatibility for short-lived pre-migration OTP pages; all new URLs
        # contain only the numeric user ID, never the email address.
        cur.execute("SELECT * FROM user WHERE email_lookup = %s",
                    (email_lookup(identifier, key),))
    user = cur.fetchone()

    if not user:
        flash("Invalid session. Please register again.")
        return redirect(url_for("auth.register"))

    if not identifier.isdigit():
        return redirect(url_for("auth.verify_otp", identifier=user['id']))

    record = get_otp_record(user['id'])

    if request.method == 'POST':
        entered_otp = request.form.get('otp', '').strip()

        if (record and
                record['otp'] == entered_otp and
                (time.time() - float(record['created'])) < duration):

            # Mark user as verified
            cur.execute(
                "UPDATE user SET is_registered = 1 WHERE id = %s",
                (user['id'],)
            )
            try:
                db.commit()
            except Exception:
                pass

            # Clean up used OTP
            try:
                cur.execute("DELETE FROM otps WHERE id = %s", (user['id'],))
                db.commit()
            except Exception:
                pass

            flash("Email verified successfully! You can now log in.")
            return redirect(url_for('auth.login'))

        else:
            flash("Invalid or expired OTP. Please try again.")

    return render_template(
        'auth/verify_otp.html',
        email_s=mask_email(decrypt_email(user['email'], user['username'], key)),
    )


# =========================================
# LOGIN REQUIRED DECORATOR
# =========================================
def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            return redirect(url_for('auth.login'))
        return view(**kwargs)
    return wrapped_view
