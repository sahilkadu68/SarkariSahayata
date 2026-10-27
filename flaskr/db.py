from flask_mysqldb import MySQL
import MySQLdb.cursors
from flaskr import mysql
import click
from flask import current_app, g
from werkzeug.security import generate_password_hash
from flaskr.pii import decode_key, email_lookup, encrypt_email

def get_db():
    """Get a per-request MySQL connection and reconnect if needed."""
    if 'db' not in g:
        g.db = connect_db()
    else:
        try:
            g.db.ping(True)  # check connection, reconnect if needed
        except (MySQLdb.OperationalError, AttributeError):
            g.db = connect_db()
    return g.db


def connect_db():
    """Create a new MySQL connection using Flask app config."""
    cfg = current_app.config
    return MySQLdb.connect(
        host=cfg.get('MYSQL_HOST', '127.0.0.1'),
        user=cfg.get('MYSQL_USER', 'root'),
        passwd=cfg.get('MYSQL_PASSWORD', ''),
        db=cfg.get('MYSQL_DB', 'defaultdb'),
        port=int(cfg.get('MYSQL_PORT', 3306)),
        cursorclass=MySQLdb.cursors.DictCursor,  # rows as dicts
        charset='utf8mb4',
        autocommit=True
    )

def close_db(e=None):
    """Close the database connection at the end of the request."""
    db = g.pop('db', None)
    if db is not None:
        try:
            db.close()
        except Exception:
            pass

def init_db():
    db = get_db()
    cfg = current_app.config

    with current_app.open_resource('schema.sql') as f:
        sql_script = f.read().decode('utf8')

    cur = db.cursor()
    for statement in sql_script.split(';'):
        stmt = statement.strip()
        if stmt:
            cur.execute(stmt)

    master_user = cfg.get('MASTER_USER') or 'sarkariadmin1'
    mail_user = cfg.get('MAIL_USERNAME') or 'admin@sarkarisahayata.gov.in'
    master_pass = cfg.get('MASTER_PASSWORD') or 'sarkari123'
    key = decode_key(cfg.get('PERSONAL_DATA_ENCRYPTION_KEY'))

    cur.execute(
        "INSERT INTO user (username, email, email_lookup, password, user_type, is_registered) VALUES (%s, %s, %s, %s, %s, 1)",
        (master_user, encrypt_email(mail_user, master_user, key),
         email_lookup(mail_user, key), generate_password_hash(master_pass), "master")
    )
    db.commit()
    cur.close()

def create_master():
    db = get_db()
    cur = db.cursor()
    cfg = current_app.config

    master_user = cfg.get('MASTER_USER') or 'sarkariadmin1'
    mail_user = cfg.get('MAIL_USERNAME') or 'admin@sarkarisahayata.gov.in'
    master_pass = cfg.get('MASTER_PASSWORD') or 'sarkari123'
    key = decode_key(cfg.get('PERSONAL_DATA_ENCRYPTION_KEY'))

    try:
        cur.execute("ALTER TABLE user ADD user_type VARCHAR(15) DEFAULT 'user';")
    except Exception:
        pass
    cur.execute(
        "INSERT INTO user (username, email, email_lookup, password, user_type, is_registered) VALUES (%s, %s, %s, %s, %s, 1)",
        (master_user, encrypt_email(mail_user, master_user, key),
         email_lookup(mail_user, key), generate_password_hash(master_pass), "master")
    )
    db.commit()
    cur.close() 

@click.command('init-db')
def init_db_command():
    """Clear the existing data and create new tables."""
    init_db()
    click.echo('Initialized the database.')

@click.command('create-master')
def create_master_command():
    create_master()
    click.echo('master created successfully')

def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(create_master_command)
