from flask import Blueprint, render_template, abort
from flaskr.db import get_db
import MySQLdb.cursors

bp = Blueprint('categories', __name__, url_prefix='/categories')


@bp.route('/<category_name>')
def show_category(category_name):
    schemes = []
    try:
        db = get_db()
        cursor = db.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("""
            SELECT * FROM schemes
            WHERE LOWER(category) = LOWER(%s)
        """, (category_name,))
        schemes = cursor.fetchall()
        cursor.close()
    except Exception:
        schemes = []

    return render_template(
        'category_dynamic.html',
        category=category_name,
        schemes=schemes or []
    )
