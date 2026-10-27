from flask import (
    Blueprint, flash, g, redirect,
    render_template, request, url_for, abort
)
from flaskr.db import get_db
from flaskr.pii import configured_key, encrypt_profile, decrypt_profile, ELIGIBILITY_FIELDS
import MySQLdb.cursors


# =====================================================
# Blueprint
# =====================================================
bp = Blueprint('home', __name__)



# =====================================================
# TRANSLATE PROXY (avoids browser CORS on Google Translate)
# =====================================================
@bp.route("/translate")
def translate_proxy():
    from flask import request, jsonify
    import urllib.request, urllib.parse, json as _json

    text = request.args.get("q", "")
    lang = request.args.get("tl", "en")

    if not text or lang == "en":
        return jsonify({"t": text})

    try:
        url = (
            "https://translate.googleapis.com/translate_a/single"
            "?client=gtx&sl=en&dt=t&tl="
            + urllib.parse.quote(lang)
            + "&q="
            + urllib.parse.quote(text)
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        translated = "".join(item[0] for item in data[0] if item[0])
        return jsonify({"t": translated})
    except Exception as e:
        return jsonify({"t": text, "error": str(e)})


# =====================================================
# TTS — TEXT-TO-SPEECH CONTENT ENDPOINT
# Returns translated scheme content for browser Speech API
# =====================================================
@bp.route("/tts-content/<int:scheme_id>")
def tts_content(scheme_id):
    from flask import jsonify
    import urllib.request, urllib.parse, json as _json

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM schemes WHERE id=%s", (scheme_id,))
    scheme = cursor.fetchone()
    if not scheme:
        return jsonify({"error": "Scheme not found"}), 404

    lang = request.args.get("lang", "en")

    # Build a single readable script from scheme fields
    parts = []
    if scheme.get("title"):
        parts.append(f"Scheme Name: {scheme['title']}.")
    if scheme.get("description"):
        parts.append(f"Description: {scheme['description']}")
    if scheme.get("objectives"):
        parts.append(f"Objectives: {scheme['objectives']}")
    if scheme.get("benefits"):
        parts.append(f"Benefits: {scheme['benefits']}")
    if scheme.get("eligibility"):
        parts.append(f"Eligibility: {scheme['eligibility']}")
    if scheme.get("min_age") or scheme.get("max_age"):
        age_str = ""
        if scheme.get("min_age"):
            age_str += f"Minimum age is {scheme['min_age']} years. "
        if scheme.get("max_age"):
            age_str += f"Maximum age is {scheme['max_age']} years."
        parts.append(f"Age Criteria: {age_str}")
    if scheme.get("max_income"):
        parts.append(f"Maximum annual income allowed: Rupees {scheme['max_income']}.")
    if scheme.get("exclusions"):
        parts.append(f"Exclusions: {scheme['exclusions']}")
    if scheme.get("application_process"):
        parts.append(f"How to Apply: {scheme['application_process']}")
    if scheme.get("documents"):
        parts.append(f"Documents Required: {scheme['documents']}")

    full_text = "\n".join(parts)

    if lang == "en":
        return jsonify({"text": full_text, "lang": lang})

    # Translate via Google Translate (same proxy logic as existing translate_proxy)
    try:
        # Split into chunks to avoid URL length limits (~4000 chars each)
        CHUNK = 3000
        words = full_text.split(" ")
        chunks, current = [], ""
        for word in words:
            if len(current) + len(word) + 1 > CHUNK:
                chunks.append(current.strip())
                current = word
            else:
                current += " " + word
        if current.strip():
            chunks.append(current.strip())

        translated_parts = []
        for chunk in chunks:
            url = (
                "https://translate.googleapis.com/translate_a/single"
                "?client=gtx&sl=en&dt=t&tl="
                + urllib.parse.quote(lang)
                + "&q="
                + urllib.parse.quote(chunk)
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            translated = "".join(item[0] for item in data[0] if item[0])
            translated_parts.append(translated)

        return jsonify({"text": " ".join(translated_parts), "lang": lang})
    except Exception as e:
        return jsonify({"text": full_text, "lang": "en", "error": str(e)})


# =====================================================
# HOME PAGE
# =====================================================
@bp.route("/")
def index():

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)

    cursor.execute("SELECT * FROM schemes ORDER BY id DESC")
    schemes = cursor.fetchall()

    return render_template("index.html", json_schemes=schemes)


# =====================================================
# SCHEME DETAIL PAGE
# =====================================================
@bp.route('/scheme/<int:scheme_id>')
def scheme_detail(scheme_id):

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)

    cursor.execute("SELECT * FROM schemes WHERE id=%s", (scheme_id,))
    scheme = cursor.fetchone()

    if not scheme:
        abort(404)

    return render_template("scheme_detail.html", scheme=scheme)


# =====================================================
# ADD USER DETAILS  (with DOB + document verification)
# =====================================================
@bp.route("/add-details", methods=["GET", "POST"])
def add_details():
    from flask import jsonify
    import os, base64, json as _json, datetime, re
    import urllib.request

    if not g.user:
        return redirect(url_for("auth.login"))

    db = get_db()
    cursor = db.cursor()

    if request.method == "POST":
        name       = request.form.get("name", "").strip()
        dob_str    = request.form.get("dob", "").strip()       # YYYY-MM-DD
        gender     = request.form.get("gender", "")
        income     = request.form.get("income", 0)
        caste      = request.form.get("caste", "")
        state      = request.form.get("state", "")
        occupation = request.form.get("occupation", "").strip()
        doc_type   = request.form.get("doc_type", "")         # "aadhar" or "pan"

        # ── Compute age from DOB ──
        age = 0
        dob = None
        if dob_str:
            try:
                dob = datetime.date.fromisoformat(dob_str)
                today = datetime.date.today()
                age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            except ValueError:
                pass

        # ── Document verification via Anthropic Vision API ──
        doc_verified = False
        doc_file = request.files.get("doc_image")

        if doc_file and doc_file.filename:
            try:
                img_bytes = doc_file.read()
                img_b64   = base64.b64encode(img_bytes).decode("utf-8")

                # Detect MIME type
                mime = doc_file.content_type or "image/jpeg"
                if mime not in ("image/jpeg", "image/png", "image/webp"):
                    mime = "image/jpeg"

                # Build prompt based on doc type
                if doc_type == "pan":
                    extraction_prompt = (
                        "This is an Indian PAN card image. "
                        "Extract and return ONLY a JSON object with keys: "
                        "\"name\" (full name as printed on card) and "
                        "\"dob\" (date of birth in DD/MM/YYYY format as printed). "
                        "If a field is not visible, use null. Return ONLY the JSON, nothing else."
                    )
                else:
                    extraction_prompt = (
                        "This is an Indian Aadhaar card image. "
                        "Extract and return ONLY a JSON object with keys: "
                        "\"name\" (full name as printed on card) and "
                        "\"dob\" (date of birth in DD/MM/YYYY format as printed). "
                        "If a field is not visible, use null. Return ONLY the JSON, nothing else."
                    )

                api_payload = _json.dumps({
                    "model": "claude-opus-4-5",
                    "max_tokens": 256,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": mime,
                                    "data": img_b64
                                }
                            },
                            {"type": "text", "text": extraction_prompt}
                        ]
                    }]
                }).encode("utf-8")

                api_key = os.environ.get("ANTHROPIC_API_KEY", "")
                req = urllib.request.Request(
                    "https://api.anthropic.com/v1/messages",
                    data=api_payload,
                    headers={
                        "Content-Type": "application/json",
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01"
                    },
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    result = _json.loads(resp.read().decode("utf-8"))

                raw_text = result["content"][0]["text"].strip()
                # Strip any markdown fences
                raw_text = re.sub(r"```[a-z]*", "", raw_text).strip().strip("`").strip()

                extracted = _json.loads(raw_text)
                doc_name  = (extracted.get("name") or "").strip().lower()
                doc_dob   = (extracted.get("dob") or "").strip()   # DD/MM/YYYY

                # ── Name match (fuzzy: normalise & check substring) ──
                def norm(s):
                    return re.sub(r"[^a-z ]", "", s.lower()).strip()

                user_name_norm = norm(name)
                doc_name_norm  = norm(doc_name)

                name_ok = False
                if doc_name_norm and user_name_norm:
                    # Accept if either is a substring of the other (handles initials etc.)
                    n1 = user_name_norm.split()
                    n2 = doc_name_norm.split()
                    # At least 60% of words match
                    common = sum(1 for w in n1 if w in n2)
                    name_ok = common / max(len(n1), 1) >= 0.6

                # ── DOB match ──
                dob_ok = False
                if doc_dob and dob:
                    # Parse DD/MM/YYYY
                    parts = doc_dob.replace("-", "/").split("/")
                    if len(parts) == 3:
                        try:
                            # Handle 2-digit year
                            yr = int(parts[2])
                            if yr < 100:
                                yr += 1900 if yr > 24 else 2000
                            doc_date = datetime.date(yr, int(parts[1]), int(parts[0]))
                            dob_ok = (doc_date == dob)
                        except (ValueError, IndexError):
                            pass

                doc_verified = name_ok and dob_ok

            except Exception:
                doc_verified = False

        # ── Upsert user details ──
        profile = encrypt_profile({
            "name": name, "age": age, "dob": dob_str or None,
            "gender": gender, "income": income, "caste": caste,
            "states": state, "occupation": occupation,
            "doc_type": doc_type, "doc_verified": doc_verified,
        }, g.user["id"], configured_key())
        cursor.execute("SELECT id FROM user_details WHERE user_id=%s", (g.user["id"],))
        existing = cursor.fetchone()

        if existing:
            cursor.execute("""
                UPDATE user_details
                SET name=%s, age=%s, dob=%s, gender=%s, income=%s, caste=%s,
                    states=%s, occupation=%s, doc_type=%s, doc_verified=%s
                WHERE user_id=%s
            """, (
                profile["name"], profile["age"], profile["dob"],
                profile["gender"], profile["income"], profile["caste"],
                profile["states"], profile["occupation"],
                profile["doc_type"], profile["doc_verified"], g.user["id"]
            ))
        else:
            cursor.execute("""
                INSERT INTO user_details
                (name, age, dob, gender, income, caste, states, occupation,
                 doc_type, doc_verified, user_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                profile["name"], profile["age"], profile["dob"],
                profile["gender"], profile["income"], profile["caste"],
                profile["states"], profile["occupation"],
                profile["doc_type"], profile["doc_verified"], g.user["id"]
            ))

        db.commit()

        if doc_file and doc_file.filename and not doc_verified:
            flash("Details saved. ⚠️ Document verification failed — name or date of birth did not match. You can resubmit with a clearer image.")
        elif doc_verified:
            flash("✅ Details saved and document verified successfully!")
        else:
            flash("Details submitted successfully!")

        return redirect(url_for("home.index"))

    import datetime as _dt2
    return render_template("add_details.html", today=_dt2.date.today().isoformat())


# =====================================================
# ELIGIBILITY ENGINE (FULLY DATABASE DRIVEN)
# =====================================================
@bp.route("/eligibility")
def eligibility():

    if not g.user:
        return redirect(url_for("auth.login"))

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)

    # Get user details
    cursor.execute("""
        SELECT name, age, dob, gender, income, caste, states, occupation, user_id
        FROM user_details
        WHERE user_id = %s
    """, (g.user["id"],))

    user = cursor.fetchone()

    if not user:
        flash("Please add your details first.")
        return redirect(url_for("home.add_details"))

    user = decrypt_profile(user, g.user["id"], configured_key(), ELIGIBILITY_FIELDS)
    import datetime as _dt
    age = int(user["age"] or 0)
    if user.get("dob"):
        try:
            dob_val = user["dob"]
            if isinstance(dob_val, str):
                dob_val = _dt.date.fromisoformat(dob_val)
            today = _dt.date.today()
            age = today.year - dob_val.year - ((today.month, today.day) < (dob_val.month, dob_val.day))
        except Exception:
            pass
    gender = (user["gender"] or "").lower()
    income = int(user["income"] or 0)
    caste = (user["caste"] or "").lower()
    state = (user["states"] or "").lower()
    occupation = (user["occupation"] or "").lower()

    # Get all schemes
    cursor.execute("SELECT * FROM schemes")
    schemes = cursor.fetchall()

    eligible_schemes = []
    rejected_schemes = []

    for scheme in schemes:

        is_eligible = True
        reasons = []

        # ---------------- AGE CHECK ----------------
        if scheme["min_age"] and age < scheme["min_age"]:
            is_eligible = False
            reasons.append(f"Minimum age required is {scheme['min_age']}")

        if scheme["max_age"] and age > scheme["max_age"]:
            is_eligible = False
            reasons.append(f"Maximum age allowed is {scheme['max_age']}")

        # ---------------- INCOME CHECK ----------------
        if scheme["max_income"] and income > scheme["max_income"]:
            is_eligible = False
            reasons.append(f"Income must be ≤ ₹{scheme['max_income']}")

        # ---------------- GENDER CHECK ----------------
        if scheme["gender"] and scheme["gender"].lower() != gender:
            is_eligible = False
            reasons.append(f"Only for {scheme['gender']} candidates")

        # ---------------- CASTE CHECK ----------------
        if scheme["caste"] and scheme["caste"].lower() != caste:
            is_eligible = False
            reasons.append(f"Only for {scheme['caste']} category")

        # ---------------- STATE CHECK ----------------
        if scheme["state"] and scheme["state"].lower() != state:
            is_eligible = False
            reasons.append(f"Only available in {scheme['state']}")

        # ---------------- OCCUPATION CHECK ----------------
        if scheme["occupation"] and scheme["occupation"].lower() != occupation:
            is_eligible = False
            reasons.append(f"Only for {scheme['occupation']} occupation")

        # ---------------- FINAL RESULT ----------------
        if is_eligible:
            eligible_schemes.append({
                "scheme": scheme,
                "reason": "All eligibility criteria satisfied"
            })
        else:
            rejected_schemes.append({
                "scheme": scheme,
                "reasons": reasons
            })

    return render_template(
        "eligibility.html",
        name=user["name"],
        eligible_schemes=eligible_schemes,
        rejected_schemes=rejected_schemes,
        scheme_count=len(eligible_schemes)
    )
