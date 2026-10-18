import re
from flask import Blueprint, render_template, request, jsonify, session
from flaskr.db import get_db
import MySQLdb.cursors

bp = Blueprint("chatbot", __name__, url_prefix="/chatbot")


TRANSLATIONS = {
    "en": {
        "no_schemes_category": "No schemes found in this category.",
        "there_are_schemes": "There are <b>{count}</b> schemes under <b>{category}</b>.",
        "category_schemes": "<b>{category} Schemes:</b><br><br>",
        "documents_required": "<b>Documents Required for {title}:</b><br><br>{formatted}",
        "no_document_info": "No document information available for {title}.",
        "benefits_of": "<b>Benefits of {title}:</b><br><br>{formatted}",
        "no_benefit_info": "No benefit information available for {title}.",
        "please_enter_age": "Please enter your age.",
        "enter_age_numbers": "Please enter your age in numbers only.",
        "please_enter_income": "Please enter your annual income.",
        "enter_income_numbers": "Please enter your income in numbers only.",
        "eligible_for": "<b>You are eligible for:</b><br><br>",
        "no_match_eligibility": "No schemes matched your eligibility criteria.",
        "default_reply": """
I can only help with:

• Category based scheme search  
• Documents required for a scheme  
• Benefits of a scheme  
• Eligibility check  

Please ask a valid supported question.
"""
    },
    "hi": {
        "no_schemes_category": "इस श्रेणी में कोई योजना नहीं मिली।",
        "there_are_schemes": "<b>{category}</b> के अंतर्गत <b>{count}</b> योजनाएँ हैं।",
        "category_schemes": "<b>{category} योजनाएँ:</b><br><br>",
        "documents_required": "<b>{title} के लिए आवश्यक दस्तावेज:</b><br><br>{formatted}",
        "no_document_info": "{title} के लिए दस्तावेज़ की जानकारी उपलब्ध नहीं है।",
        "benefits_of": "<b>{title} के लाभ:</b><br><br>{formatted}",
        "no_benefit_info": "{title} के लिए लाभ की जानकारी उपलब्ध नहीं है।",
        "please_enter_age": "कृपया अपनी आयु दर्ज करें।",
        "enter_age_numbers": "कृपया अपनी आयु केवल अंकों में दर्ज करें।",
        "please_enter_income": "कृपया अपनी वार्षिक आय दर्ज करें।",
        "enter_income_numbers": "कृपया अपनी आय केवल अंकों में दर्ज करें।",
        "eligible_for": "<b>आप इन योजनाओं के लिए पात्र हैं:</b><br><br>",
        "no_match_eligibility": "आपकी पात्रता के अनुसार कोई योजना नहीं मिली।",
        "default_reply": """
मैं केवल इन चीज़ों में मदद कर सकता हूँ:

• श्रेणी आधारित योजना खोज  
• किसी योजना के लिए आवश्यक दस्तावेज  
• किसी योजना के लाभ  
• पात्रता जांच  

कृपया सही समर्थित प्रश्न पूछें।
"""
    },
    "mr": {
        "no_schemes_category": "या वर्गात कोणतीही योजना सापडली नाही.",
        "there_are_schemes": "<b>{category}</b> अंतर्गत <b>{count}</b> योजना आहेत.",
        "category_schemes": "<b>{category} योजना:</b><br><br>",
        "documents_required": "<b>{title} साठी आवश्यक कागदपत्रे:</b><br><br>{formatted}",
        "no_document_info": "{title} साठी कागदपत्रांची माहिती उपलब्ध नाही.",
        "benefits_of": "<b>{title} चे फायदे:</b><br><br>{formatted}",
        "no_benefit_info": "{title} साठी लाभांची माहिती उपलब्ध नाही.",
        "please_enter_age": "कृपया तुमचे वय प्रविष्ट करा.",
        "enter_age_numbers": "कृपया तुमचे वय फक्त अंकांमध्ये प्रविष्ट करा.",
        "please_enter_income": "कृपया तुमचे वार्षिक उत्पन्न प्रविष्ट करा.",
        "enter_income_numbers": "कृपया तुमचे उत्पन्न फक्त अंकांमध्ये प्रविष्ट करा.",
        "eligible_for": "<b>तुम्ही या योजनांसाठी पात्र आहात:</b><br><br>",
        "no_match_eligibility": "तुमच्या पात्रतेनुसार कोणतीही योजना सापडली नाही.",
        "default_reply": """
मी फक्त खालील गोष्टींमध्ये मदत करू शकतो:

• वर्गानुसार योजना शोध  
• योजनेसाठी लागणारी कागदपत्रे  
• योजनेचे फायदे  
• पात्रता तपासणी  

कृपया योग्य समर्थित प्रश्न विचारा.
"""
    }
}


LANGUAGE_KEYWORDS = {
    "scheme": [
        "scheme", "schemes",
        "योजना", "योजनाएँ", "योजनाएं",
        "yojana", "yojna",
        "યોજના", "યોજનાઓ",
        "প্রকল্প", "স্কিম", "আঁচনি",
        "திட்டம்", "திட்டங்கள்",
        "పథకం", "పథకాలు",
        "ಯೋಜನೆ", "ಯೋಜನೆಗಳು",
        "പദ്ധതി", "പദ്ധതികൾ",
        "ਸਕੀਮ", "ਸਕੀਮਾਂ", "ਯੋਜਨਾ",
        "ଯୋଜନା", "ଯୋଜନାଗୁଡ଼ିକ",
        "اسکیم", "اسکیمیں"
    ],
    "document": [
        "document", "documents", "doc", "docs",
        "दस्तावेज", "दस्तावेज़", "कागज", "कागज़",
        "कागदपत्र", "कागदपत्रे",
        "દસ્તાવેજ", "કાગળ",
        "নথি", "ডকুমেন্ট",
        "ஆவணம்", "ஆவணங்கள்",
        "పత్రం", "పత్రాలు", "డాక్యుమెంట్స్",
        "ದಾಖಲೆ", "ದಾಖಲೆಗಳು",
        "രേഖ", "രേഖകൾ", "ഡോക്യുമെന്റ്സ്",
        "ਦਸਤਾਵੇਜ਼",
        "ଦଲିଲ", "ଦସ୍ତାବେଜ",
        "دستاویز", "دستاویزات"
    ],
    "benefit": [
        "benefit", "benefits",
        "लाभ", "फायदा", "फायदे",
        "લાભ", "ફાયદા",
        "সুবিধা", "লাভ",
        "பலன்", "பலன்கள்", "நன்மை",
        "ప్రయోజనం", "ప్రయోజనాలు", "లాభాలు",
        "ಲಾಭ", "ಪ್ರಯೋಜನ",
        "ഗുണം", "പ്രയോജനം", "ആനുകൂല്യം",
        "ਲਾਭ",
        "ଲାଭ", "ସୁବିଧା",
        "فائدہ", "فوائد"
    ],
    "eligibility": [
        "check eligibility", "eligibility", "eligible",
        "पात्रता", "योग्य", "पात्र",
        "पात्रता तपासणी", "पात्रता तपासा",
        "પાત્રતા", "લાયક",
        "যোগ্যতা", "যোগ্য",
        "தகுதி",
        "అర్హత",
        "ಅರ್ಹತೆ",
        "യോഗ്യത",
        "ਯੋਗਤਾ",
        "ଯୋଗ୍ୟତା",
        "اہلیت"
    ],
    "how_many": [
        "how many",
        "कितनी", "कितने",
        "किती",
        "કેટલી", "કેટલા",
        "কত",
        "எத்தனை",
        "ఎన్ని",
        "ಎಷ್ಟು",
        "എത്ര",
        "ਕਿੰਨੀ", "ਕਿੰਨੇ",
        "କେତେ",
        "کتنی", "کتنے"
    ]
}


CATEGORY_ALIASES = {
    "agriculture": ["agriculture", "kisan", "farmer", "कृषि", "खेती", "शेती", "કૃષિ", "কৃষি", "விவசாயம்", "వ్యవసాయం", "ಕೃಷಿ", "കൃഷി", "ਖੇਤੀਬਾੜੀ", "କୃଷି", "زراعت"],
    "education": ["education", "student", "शिक्षा", "विद्यार्थी", "शिक्षण", "શિક્ષણ", "শিক্ষা", "கல்வி", "విద్య", "ಶಿಕ್ಷಣ", "വിദ്യാഭ്യാസം", "ਸਿੱਖਿਆ", "ଶିକ୍ଷା", "تعلیم"],
    "health": ["health", "medical", "स्वास्थ्य", "आरोग्य", "આરોગ્ય", "স্বাস্থ্য", "சுகாதாரம்", "ఆరోగ్యం", "ಆರೋಗ್ಯ", "ആരോഗ്യം", "ਸਿਹਤ", "ସ୍ୱାସ୍ଥ୍ୟ", "صحت"],
    "housing": ["housing", "house", "home", "आवास", "घर", "गृहनिर्माण", "રહેઠાણ", "আবাসন", "வீடமைப்பு", "గృహ", "ವಸತಿ", "ഭവനം", "ਆਵਾਸ", "ଆବାସ", "رہائش"],
    "skills": ["skills", "employment", "job", "jobs", "रोजगार", "कौशल", "कौशल्य", "રોજગાર", "দক্ষতা", "வேலைவாய்ப்பு", "నైపుణ్యాలు", "ಉದ್ಯೋಗ", "തൊഴിൽ", "ਰੋਜ਼ਗਾਰ", "ଚାକିରି", "روزگار"],
    "transport": ["transport", "vehicle", "travel", "परिवहन", "transport", "પરિવહન", "পরিবহন", "போக்குவரத்து", "రవాణా", "ಸಾರಿಗೆ", "ഗതാഗതം", "ਆਵਾਜਾਈ", "ପରିବହନ", "ٹرانسپورٹ"],
    "women": ["women", "woman", "child", "women and child", "महिला", "बाल", "महिला और बाल", "महिला आणि बालक", "મહિલા", "শিশু", "பெண்கள்", "మహిళలు", "ಮಹಿಳೆ", "വനിത", "ਮਹਿਲਾ", "ମହିଳା", "خواتین"]
}


def tr(lang, key, **kwargs):
    lang_map = TRANSLATIONS.get(lang, TRANSLATIONS["en"])
    text = lang_map.get(key, TRANSLATIONS["en"].get(key, key))
    return text.format(**kwargs)


def contains_any(text, words):
    for word in words:
        if word.lower() in text:
            return True
    return False


def detect_category(message):
    message = message.lower()
    for category, aliases in CATEGORY_ALIASES.items():
        if contains_any(message, aliases):
            return category
    return None


@bp.route("/")
def chatbot_page():
    return render_template("chatbot.html")


@bp.route("/api", methods=["POST"])
def chat_api():

    data = request.get_json() or {}
    message = data.get("message", "").strip().lower()
    language = data.get("language", "en")

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)

    category = detect_category(message)
    asks_scheme = contains_any(message, LANGUAGE_KEYWORDS["scheme"])
    asks_documents = contains_any(message, LANGUAGE_KEYWORDS["document"])
    asks_benefits = contains_any(message, LANGUAGE_KEYWORDS["benefit"])
    asks_eligibility = contains_any(message, LANGUAGE_KEYWORDS["eligibility"])
    asks_how_many = contains_any(message, LANGUAGE_KEYWORDS["how_many"])

    if category and asks_scheme:
        cursor.execute("""
            SELECT title FROM schemes
            WHERE LOWER(category) LIKE %s
        """, (f"%{category}%",))

        schemes = cursor.fetchall()

        if not schemes:
            return jsonify({"reply": tr(language, "no_schemes_category")})

        if asks_how_many:
            return jsonify({
                "reply": tr(language, "there_are_schemes", count=len(schemes), category=category.title())
            })

        reply = tr(language, "category_schemes", category=category.title())
        for scheme in schemes:
            reply += f"• {scheme['title']}<br>"

        return jsonify({"reply": reply})

    if asks_documents:
        cursor.execute("SELECT title, documents FROM schemes")
        schemes = cursor.fetchall()

        for scheme in schemes:
            if scheme["title"] and scheme["title"].lower() in message:
                if scheme["documents"]:
                    formatted = scheme["documents"].replace("\n", "<br>")
                    return jsonify({
                        "reply": tr(language, "documents_required", title=scheme['title'], formatted=formatted)
                    })
                else:
                    return jsonify({
                        "reply": tr(language, "no_document_info", title=scheme['title'])
                    })

    if asks_benefits:
        cursor.execute("SELECT title, benefits FROM schemes")
        schemes = cursor.fetchall()

        for scheme in schemes:
            if scheme["title"] and scheme["title"].lower() in message:
                if scheme["benefits"]:
                    formatted = scheme["benefits"].replace("\n", "<br>")
                    return jsonify({
                        "reply": tr(language, "benefits_of", title=scheme['title'], formatted=formatted)
                    })
                else:
                    return jsonify({
                        "reply": tr(language, "no_benefit_info", title=scheme['title'])
                    })

    if asks_eligibility:
        session["chat_state"] = "ask_age"
        session["eligibility_data"] = {}
        return jsonify({"reply": tr(language, "please_enter_age")})

    if session.get("chat_state") == "ask_age":

        if not message.isdigit():
            return jsonify({"reply": tr(language, "enter_age_numbers")})

        session["eligibility_data"]["age"] = int(message)
        session["chat_state"] = "ask_income"

        return jsonify({"reply": tr(language, "please_enter_income")})

    if session.get("chat_state") == "ask_income":

        if not message.isdigit():
            return jsonify({"reply": tr(language, "enter_income_numbers")})

        session["eligibility_data"]["income"] = int(message)
        session["chat_state"] = None

        age = session["eligibility_data"]["age"]
        income = session["eligibility_data"]["income"]

        cursor.execute("""
            SELECT title FROM schemes
            WHERE (min_age IS NULL OR min_age <= %s)
            AND (max_age IS NULL OR max_age >= %s)
            AND (max_income IS NULL OR max_income >= %s)
        """, (age, age, income))

        eligible = cursor.fetchall()

        if eligible:
            reply = tr(language, "eligible_for")
            for scheme in eligible:
                reply += f"• {scheme['title']}<br>"
        else:
            reply = tr(language, "no_match_eligibility")

        return jsonify({"reply": reply})

    return jsonify({
        "reply": tr(language, "default_reply")
    })


@bp.route("/suggest", methods=["POST"])
def suggest():

    data = request.get_json() or {}
    user_input = data.get("text", "").lower().strip()
    language = data.get("language", "en")

    if not user_input:
        return jsonify({"suggestions": []})

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)

    cursor.execute("SELECT title, category FROM schemes")
    schemes = cursor.fetchall()

    suggestions = []

    categories = set([s["category"].lower() for s in schemes if s["category"]])

    for category in categories:
        if language == "hi":
            possible = [
                f"{category} schemes दिखाओ",
                f"{category} schemes कितनी हैं?"
            ]
        elif language == "mr":
            possible = [
                f"{category} schemes दाखवा",
                f"{category} schemes किती आहेत?"
            ]
        elif language == "gu":
            possible = [
                f"{category} schemes બતાવો",
                f"{category} schemes કેટલી છે?"
            ]
        else:
            possible = [
                f"Show {category} schemes",
                f"How many {category} schemes are there?"
            ]

        for q in possible:
            if user_input in q.lower():
                suggestions.append(q)

    for scheme in schemes:
        title = scheme["title"]

        if language == "hi":
            possible = [
                f"{title} के लिए कौन से documents चाहिए?",
                f"{title} के benefits क्या हैं?",
                f"{title} के लिए eligibility check"
            ]
        elif language == "mr":
            possible = [
                f"{title} साठी कोणती documents लागतात?",
                f"{title} चे benefits काय आहेत?",
                f"{title} साठी eligibility check"
            ]
        elif language == "gu":
            possible = [
                f"{title} માટે કયા documents જોઈએ?",
                f"{title} ના benefits શું છે?",
                f"{title} માટે eligibility check"
            ]
        else:
            possible = [
                f"What documents are required for {title}?",
                f"What are the benefits of {title}?",
                f"Check eligibility for {title}"
            ]

        for q in possible:
            if user_input in q.lower():
                suggestions.append(q)

    return jsonify({"suggestions": suggestions[:6]})