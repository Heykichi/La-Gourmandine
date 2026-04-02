import base64
import os
import tempfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg2
import streamlit as st
import streamlit.components.v1 as components
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

LOGO_PATH = Path(__file__).resolve().parent.parent / "logo_gourmandine.png"
BAKERY_NAME = "La Gourmandine"
BAKERY_ADDRESS = "Rue du Saussois 1 1315 Opprebais"
BAKERY_PHONE = "010/24.67.07"
CATEGORIES = ["Viennoiseries", "Pistolets", "Pains", "Baguettes", "Frigo", "Tartes"]
TARTE_SIZES = ["petite", "moyenne", "grande"]
CATEGORY_ALIASES = {"viennoiserie": "Viennoiseries", "viennoiseries": "Viennoiseries", "pistolet": "Pistolets", "pistolets": "Pistolets", "pain": "Pains", "pains": "Pains", "baguette": "Baguettes", "baguettes": "Baguettes", "frigo": "Frigo", "tarte": "Tartes", "tartes": "Tartes"}
WEEKDAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
DEFAULT_USERS = [{"username": "admin", "password": "admin123", "role": "articles", "label": "Administration articles"}, {"username": "magasin", "password": "magasin123", "role": "magasin", "label": "Gestion magasin"}, {"username": "atelier", "password": "atelier123", "role": "atelier", "label": "Production atelier"}]
ROLE_PAGES = {"magasin": [("accueil", "Accueil"), ("nouvelle_commande", "Nouvelle commande"), ("voir_commandes", "Voir les commandes"), ("recurrences", "Commandes recurrentes"), ("totaux", "Totaux"), ("etiquettes", "Etiquettes"), ("limites", "Limites")], "atelier": [("totaux", "Totaux")], "articles": [("liste_articles", "Articles")]}
DEFAULT_ARTICLES = [("Croissant", "Viennoiseries"), ("Pain au chocolat", "Viennoiseries"), ("Couque raisin", "Viennoiseries"), ("Pistolet blanc", "Pistolets"), ("Pistolet gris", "Pistolets"), ("Pain blanc", "Pains"), ("Pain gris", "Pains"), ("Baguette blanche", "Baguettes"), ("Baguette grise", "Baguettes"), ("Sandwich club", "Frigo"), ("Tarte al djote", "Frigo"), ("Tarte pommes", "Tartes"), ("Tarte fraises", "Tartes")]


def configure_page():
    st.set_page_config(page_title="Boulangerie", layout="wide")
    st.markdown("""
    <style>
    .stApp { background: linear-gradient(180deg, #f8eee3 0%, #ead8c2 60%, #e3c6a6 100%); color: #2d1b10; }
    [data-testid='stSidebar'] { background: linear-gradient(180deg, #ead5bf 0%, #d4b08f 100%); }
    .stButton > button { background: linear-gradient(180deg, #d7ab7f 0%, #bf8252 100%); color: #1d1009; border: 1px solid #97633d; border-radius: 14px; font-weight: 700; min-height: 42px; }
    .hero-card, .panel-card, .article-card, .summary-card, .login-card { border: 1px solid rgba(127,84,51,0.26); border-radius: 22px; background: rgba(255,249,241,0.95); box-shadow: 0 12px 24px rgba(74,43,22,0.08); }
    .hero-card, .panel-card, .article-card, .summary-card, .login-card { padding: 1rem; margin-bottom: 1rem; }
    .card-title { font-size: 1.2rem; font-weight: 700; color: #432716; margin-bottom: 0.35rem; }
    .card-subtitle { color: #6b4a35; font-size: 0.95rem; margin-bottom: 0.85rem; }
    .article-name { font-size: 1.25rem; font-weight: 700; color: #3a2213; min-height: 48px; }
    .article-meta { color: #734e36; font-size: 0.88rem; min-height: 38px; margin-bottom: 0.5rem; }
    .article-qty { text-align: center; font-size: 2rem; font-weight: 800; color: #3a2213; margin: 0.25rem 0 0.8rem 0; }
    .role-chip { display: inline-block; padding: 0.3rem 0.7rem; margin: 0.15rem 0.3rem 0.15rem 0; border-radius: 999px; background: rgba(191,130,82,0.14); border: 1px solid rgba(151,99,61,0.2); font-size: 0.85rem; font-weight: 600; color: #5b3823; }
    </style>
    """, unsafe_allow_html=True)


def get_secret(key, default=None):
    env = os.getenv(key)
    if env is not None:
        return env
    try:
        return st.secrets[key]
    except Exception:
        return default


def normalize_category(category):
    cleaned = (category or "").strip()
    return CATEGORY_ALIASES.get(cleaned.lower(), cleaned) if cleaned else cleaned


def display_name(name, category, size=None):
    return f"{name} ({size})" if category == "Tartes" and size else name


def size_key(category, article_id):
    return f"size|{category}|{article_id}"


@contextmanager
def get_cursor(commit=False):
    conn = get_connection()
    cur = conn.cursor()
    try:
        yield cur
        if commit:
            conn.commit()
    finally:
        cur.close()
        conn.close()


def get_connection():
    database_url = get_secret("DATABASE_URL")
    timeout_raw = get_secret("DB_CONNECT_TIMEOUT", 10)
    try:
        timeout = int(timeout_raw)
    except (TypeError, ValueError):
        timeout = 10
    if database_url:
        sslmode = get_secret("DB_SSLMODE", "require")
        last_error = None
        candidates = [database_url]
        parsed = urlparse(database_url)
        is_supabase_pooler = parsed.hostname and parsed.hostname.endswith(".pooler.supabase.com")
        if is_supabase_pooler:
            fallback_ports = [6543, 5432]
            current_port = parsed.port or 5432
            for port in fallback_ports:
                if port != current_port:
                    netloc = parsed.hostname
                    if parsed.username:
                        userinfo = parsed.username
                        if parsed.password:
                            userinfo += f":{parsed.password}"
                        netloc = f"{userinfo}@{netloc}"
                    netloc = f"{netloc}:{port}"
                    candidates.append(urlunparse(parsed._replace(netloc=netloc)))
        for candidate in candidates:
            try:
                return psycopg2.connect(candidate, sslmode=sslmode, connect_timeout=timeout)
            except psycopg2.OperationalError as exc:
                last_error = exc
        raise psycopg2.OperationalError(
            "Connexion PostgreSQL impossible. Verifie DATABASE_URL, DB_SSLMODE, et l'acces sortant aux ports 5432/6543."
        ) from last_error
    required = ["DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_PORT"]
    values = {k: get_secret(k) for k in required}
    missing = [k for k, v in values.items() if v in (None, "")]
    if missing:
        raise KeyError("Cles Supabase manquantes : " + ", ".join(missing))
    return psycopg2.connect(host=values["DB_HOST"], dbname=values["DB_NAME"], user=values["DB_USER"], password=values["DB_PASSWORD"], port=values["DB_PORT"], sslmode=get_secret("DB_SSLMODE", "require"), connect_timeout=timeout)


def show_database_error(exc):
    st.error("Connexion a la base de donnees impossible.")
    st.code(str(exc))
    st.info(
        "Verifie les secrets Streamlit (DATABASE_URL ou DB_HOST/DB_NAME/DB_USER/DB_PASSWORD/DB_PORT), "
        "DB_SSLMODE=require, et que ton reseau autorise les connexions PostgreSQL sortantes (ports 5432/6543)."
    )
def ensure_schema():
    with get_cursor(commit=True) as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL)")
        cur.execute("CREATE TABLE IF NOT EXISTS articles (id SERIAL PRIMARY KEY, nom TEXT NOT NULL, categorie TEXT NOT NULL, actif BOOLEAN NOT NULL DEFAULT TRUE)")
        cur.execute("CREATE TABLE IF NOT EXISTS orders (id SERIAL PRIMARY KEY, prenom TEXT, nom TEXT, date_commande DATE, commentaire TEXT, created_by_user_id INTEGER, recurring_order_id INTEGER, recurring_source_date DATE)")
        cur.execute("CREATE TABLE IF NOT EXISTS order_items (id SERIAL PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE, article_id INTEGER NOT NULL REFERENCES articles(id), article_nom_snapshot TEXT, categorie_snapshot TEXT, quantite INTEGER DEFAULT 0, taille TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS daily_limits (id SERIAL PRIMARY KEY, date_jour DATE NOT NULL, article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE, quantite_max INTEGER NOT NULL, UNIQUE(date_jour, article_id))")
        cur.execute("CREATE TABLE IF NOT EXISTS recurring_orders (id SERIAL PRIMARY KEY, prenom TEXT NOT NULL, nom TEXT NOT NULL, commentaire TEXT, weekday INTEGER NOT NULL, actif BOOLEAN NOT NULL DEFAULT TRUE)")
        cur.execute("CREATE TABLE IF NOT EXISTS recurring_orders (id SERIAL PRIMARY KEY, prenom TEXT, nom TEXT NOT NULL, commentaire TEXT, weekday INTEGER NOT NULL, actif BOOLEAN NOT NULL DEFAULT TRUE)")
        cur.execute("CREATE TABLE IF NOT EXISTS recurring_order_exceptions (id SERIAL PRIMARY KEY, recurring_order_id INTEGER NOT NULL REFERENCES recurring_orders(id) ON DELETE CASCADE, date_commande DATE NOT NULL, mode TEXT NOT NULL, commentaire TEXT, UNIQUE(recurring_order_id, date_commande))")
        for sql in [
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS first_name TEXT", "ALTER TABLE orders ADD COLUMN IF NOT EXISTS last_name TEXT", "ALTER TABLE orders ADD COLUMN IF NOT EXISTS comment TEXT", "ALTER TABLE orders ADD COLUMN IF NOT EXISTS order_date DATE", "ALTER TABLE orders ADD COLUMN IF NOT EXISTS prenom TEXT", "ALTER TABLE orders ADD COLUMN IF NOT EXISTS nom TEXT", "ALTER TABLE orders ADD COLUMN IF NOT EXISTS commentaire TEXT", "ALTER TABLE orders ADD COLUMN IF NOT EXISTS date_commande DATE",
            "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS item_name TEXT", "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS category TEXT", "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS quantity INTEGER", "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS taille TEXT",
            "ALTER TABLE recurring_order_items ADD COLUMN IF NOT EXISTS taille TEXT",
            "ALTER TABLE recurring_orders ADD COLUMN IF NOT EXISTS pause_du DATE", "ALTER TABLE recurring_orders ADD COLUMN IF NOT EXISTS pause_au DATE",
        ]:
            cur.execute(sql)
        cur.execute("UPDATE orders SET prenom = COALESCE(prenom, first_name) WHERE prenom IS NULL")
        cur.execute("UPDATE orders SET nom = COALESCE(nom, last_name) WHERE nom IS NULL")
        cur.execute("UPDATE orders SET commentaire = COALESCE(commentaire, comment) WHERE commentaire IS NULL")
        cur.execute("UPDATE orders SET date_commande = COALESCE(date_commande, order_date) WHERE date_commande IS NULL")
        cur.execute("UPDATE order_items SET article_nom_snapshot = COALESCE(article_nom_snapshot, item_name) WHERE article_nom_snapshot IS NULL")
        cur.execute("UPDATE order_items SET categorie_snapshot = COALESCE(categorie_snapshot, category) WHERE categorie_snapshot IS NULL")
        cur.execute("UPDATE order_items SET quantite = COALESCE(quantite, quantity, 0) WHERE quantite IS NULL")
        for name, category in DEFAULT_ARTICLES:
            cur.execute("INSERT INTO articles (nom, categorie, actif) SELECT %s, %s, TRUE WHERE NOT EXISTS (SELECT 1 FROM articles WHERE LOWER(nom)=LOWER(%s) AND LOWER(categorie)=LOWER(%s))", (name, category, name, category))
        for user in DEFAULT_USERS:
            cur.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, %s) ON CONFLICT (username) DO UPDATE SET password = EXCLUDED.password, role = EXCLUDED.role", (user["username"], user["password"], user["role"]))

def init_session_state():
    defaults = {"user": None, "page": "accueil", "flash_message": None, "selected_category": None, "order_quantities": {}, "article_sizes": {}, "edit_order_id": None, "edit_recurring_id": None, "edit_article_id": None}
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def go_to_page(page_name):
    st.session_state.page = page_name
    st.rerun()


def logout():
    for key in ["user", "page", "flash_message", "selected_category", "order_quantities", "article_sizes", "edit_order_id", "edit_recurring_id", "edit_article_id"]:
        st.session_state.pop(key, None)
    init_session_state()
    st.rerun()


def show_logo(width=260):
    left, center, right = st.columns([1, 2, 1])
    with center:
        if LOGO_PATH.exists():
            st.image(str(LOGO_PATH), width=width)


def show_sidebar(role):
    st.sidebar.markdown(f"### {role.title()}")
    for page_name, label in ROLE_PAGES.get(role, []):
        if st.sidebar.button(label, key=f"nav_{page_name}", use_container_width=True):
            go_to_page(page_name)
    st.sidebar.divider()
    if st.sidebar.button("Se deconnecter", use_container_width=True):
        logout()


def login_user(username, password):
    with get_cursor() as cur:
        cur.execute("SELECT id, username, role FROM users WHERE username = %s AND password = %s", (username.strip(), password))
        row = cur.fetchone()
    return {"id": row[0], "username": row[1], "role": row[2]} if row else None


def ensure_order_quantities(articles_dict):
    for category, articles in articles_dict.items():
        for article in articles:
            st.session_state.order_quantities.setdefault(f"{category}|{article['id']}", 0)
            if category == "Tartes":
                st.session_state.article_sizes.setdefault(size_key(category, article["id"]), "")


def reset_order_quantities(articles_dict):
    st.session_state.order_quantities = {}
    st.session_state.article_sizes = {}
    ensure_order_quantities(articles_dict)


def reset_editor_form(prefix, articles_dict, selected_category=None, selected_date=None, weekday_value=None):
    reset_order_quantities(articles_dict)
    st.session_state.selected_category = selected_category
    for suffix in ["prenom", "nom", "commentaire", "date", "weekday"]:
        st.session_state.pop(f"{prefix}_{suffix}", None)
    if selected_date is not None:
        st.session_state[f"{prefix}_date"] = selected_date
    if weekday_value is not None:
        st.session_state[f"{prefix}_weekday"] = weekday_value


def load_order_into_session(articles_dict, order_items, order_sizes=None):
    reset_order_quantities(articles_dict)
    order_sizes = order_sizes or {}
    for category, articles in articles_dict.items():
        for article in articles:
            st.session_state.order_quantities[f"{category}|{article['id']}"] = order_items.get(article["id"], 0)
            if category == "Tartes":
                st.session_state.article_sizes[size_key(category, article["id"])] = order_sizes.get(article["id"], "")


def get_articles(active_only=True):
    query = "SELECT id, nom, categorie FROM articles"
    if active_only:
        query += " WHERE COALESCE(actif, TRUE) = TRUE"
    query += " ORDER BY categorie, nom"
    with get_cursor() as cur:
        cur.execute(query)
        rows = cur.fetchall()
    result = {}
    for article_id, nom, categorie in rows:
        result.setdefault(normalize_category(categorie), []).append({"id": article_id, "nom": nom})
    return result


def get_all_articles():
    with get_cursor() as cur:
        cur.execute("SELECT id, nom, categorie, COALESCE(actif, TRUE) FROM articles ORDER BY categorie, nom")
        return cur.fetchall()


def get_article_categories():
    with get_cursor() as cur:
        cur.execute("SELECT DISTINCT categorie FROM articles ORDER BY categorie")
        rows = [normalize_category(r[0]) for r in cur.fetchall()]
    return CATEGORIES + [c for c in rows if c not in CATEGORIES]


def article_exists(name, category, exclude_id=None):
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM articles WHERE LOWER(nom)=LOWER(%s) AND LOWER(categorie)=LOWER(%s) AND (%s IS NULL OR id <> %s)", (name.strip(), normalize_category(category), exclude_id, exclude_id))
        return cur.fetchone()[0] > 0


def add_article(name, category):
    with get_cursor(commit=True) as cur:
        cur.execute("INSERT INTO articles (nom, categorie, actif) VALUES (%s, %s, TRUE)", (name.strip(), normalize_category(category)))


def update_article(article_id, name, category, active):
    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE articles SET nom=%s, categorie=%s, actif=%s WHERE id=%s", (name.strip(), normalize_category(category), active, article_id))


def toggle_article(article_id, active):
    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE articles SET actif=%s WHERE id=%s", (active, article_id))


def delete_article(article_id):
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM daily_limits WHERE article_id = %s", (article_id,))
        cur.execute("DELETE FROM recurring_order_items WHERE article_id = %s", (article_id,))
        cur.execute("DELETE FROM articles WHERE id = %s", (article_id,))


def article_has_order_history(article_id):
    with get_cursor() as cur:
        cur.execute("SELECT EXISTS (SELECT 1 FROM order_items WHERE article_id = %s)", (article_id,))
        return cur.fetchone()[0]


def get_daily_limit(selected_date, article_id):
    with get_cursor() as cur:
        cur.execute("SELECT quantite_max FROM daily_limits WHERE date_jour = %s AND article_id = %s", (selected_date, article_id))
        row = cur.fetchone()
    return row[0] if row else None


def save_limits(selected_date, values):
    with get_cursor(commit=True) as cur:
        for article_id, value in values.items():
            cur.execute("DELETE FROM daily_limits WHERE date_jour = %s AND article_id = %s", (selected_date, article_id))
            if value > 0:
                cur.execute("INSERT INTO daily_limits (date_jour, article_id, quantite_max) VALUES (%s, %s, %s)", (selected_date, article_id, value))


def active_order_filter(order_alias="o"):
    order_date_expr = f"COALESCE({order_alias}.recurring_source_date, {order_alias}.date_commande, {order_alias}.order_date)"
    return f"NOT EXISTS (SELECT 1 FROM recurring_order_exceptions roe WHERE roe.recurring_order_id = {order_alias}.recurring_order_id AND roe.date_commande = {order_date_expr} AND roe.mode IN ('skip', 'deleted'))"

def get_total_already_ordered(selected_date, article_id, exclude_order_id=None):
    query = f"SELECT COALESCE(SUM(COALESCE(oi.quantite, oi.quantity, 0)), 0) FROM order_items oi JOIN orders o ON oi.order_id = o.id WHERE COALESCE(o.date_commande, o.order_date) = %s AND oi.article_id = %s AND {active_order_filter('o')}"
    params = [selected_date, article_id]
    if exclude_order_id is not None:
        query += " AND o.id <> %s"
        params.append(exclude_order_id)
    with get_cursor() as cur:
        cur.execute(query, tuple(params))
        return cur.fetchone()[0]


def get_order_for_edit(order_id):
    with get_cursor() as cur:
        cur.execute("SELECT id, COALESCE(prenom, first_name), COALESCE(nom, last_name), COALESCE(date_commande, order_date), COALESCE(commentaire, comment) FROM orders WHERE id = %s", (order_id,))
        order_row = cur.fetchone()
        cur.execute("SELECT article_id, COALESCE(quantite, quantity, 0), COALESCE(taille, '') FROM order_items WHERE order_id = %s", (order_id,))
        items, sizes = {}, {}
        for article_id, qty, size in cur.fetchall():
            items[article_id] = qty
            sizes[article_id] = size or ""
    return order_row, items, sizes


def insert_order_items(cur, order_id, items_to_save):
    for article_id, article_name, category, qty, size in items_to_save:
        cur.execute("INSERT INTO order_items (order_id, article_id, article_nom_snapshot, categorie_snapshot, quantite, item_name, category, quantity, taille) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)", (order_id, article_id, article_name, category, qty, article_name, category, qty, size or None))


def save_order(prenom, nom, selected_date, commentaire, user_id, items_to_save):
    with get_cursor(commit=True) as cur:
        cur.execute("INSERT INTO orders (prenom, nom, date_commande, commentaire, first_name, last_name, order_date, comment, created_by_user_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id", (prenom, nom, selected_date, commentaire, prenom, nom, selected_date, commentaire, user_id))
        order_id = cur.fetchone()[0]
        insert_order_items(cur, order_id, items_to_save)


def update_order(order_id, prenom, nom, selected_date, commentaire, items_to_save):
    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE orders SET prenom=%s, nom=%s, date_commande=%s, commentaire=%s, first_name=%s, last_name=%s, order_date=%s, comment=%s WHERE id=%s", (prenom, nom, selected_date, commentaire, prenom, nom, selected_date, commentaire, order_id))
        cur.execute("DELETE FROM order_items WHERE order_id = %s", (order_id,))
        insert_order_items(cur, order_id, items_to_save)


def delete_order(order_id):
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM orders WHERE id = %s", (order_id,))


def list_orders(selected_date=None):
    with get_cursor() as cur:
        if selected_date is None:
            cur.execute(f"SELECT id, COALESCE(prenom, first_name), COALESCE(nom, last_name), COALESCE(date_commande, order_date), COALESCE(commentaire, comment) FROM orders o WHERE {active_order_filter('o')} ORDER BY COALESCE(date_commande, order_date) DESC, id DESC")
        else:
            cur.execute(f"SELECT id, COALESCE(prenom, first_name), COALESCE(nom, last_name), COALESCE(date_commande, order_date), COALESCE(commentaire, comment) FROM orders o WHERE COALESCE(o.date_commande, o.order_date) = %s AND {active_order_filter('o')} ORDER BY id DESC", (selected_date,))
        return cur.fetchall()


def get_order_items(order_id):
    with get_cursor() as cur:
        cur.execute("SELECT COALESCE(categorie_snapshot, category), COALESCE(article_nom_snapshot, item_name), COALESCE(quantite, quantity, 0), COALESCE(taille, '') FROM order_items WHERE order_id = %s ORDER BY COALESCE(categorie_snapshot, category), COALESCE(article_nom_snapshot, item_name)", (order_id,))
        return cur.fetchall()


def get_recurring_orders_for_date(selected_date):
    with get_cursor() as cur:
        cur.execute("SELECT ro.id, ro.prenom, ro.nom, COALESCE(roe.mode, 'normal'), COALESCE(roe.commentaire, ro.commentaire, '') FROM recurring_orders ro LEFT JOIN recurring_order_exceptions roe ON roe.recurring_order_id = ro.id AND roe.date_commande = %s WHERE ro.actif = TRUE AND ro.weekday = %s AND (ro.pause_du IS NULL OR ro.pause_au IS NULL OR %s < ro.pause_du OR %s > ro.pause_au) ORDER BY ro.nom, ro.prenom", (selected_date, selected_date.weekday(), selected_date, selected_date))
        rows = cur.fetchall()
        result = []
        for recurring_id, prenom, nom, mode, commentaire in rows:
            if mode in ["skip", "deleted", "custom"]:
                continue
            cur.execute("SELECT roi.article_id, a.nom, a.categorie, roi.quantite, COALESCE(roi.taille, '') FROM recurring_order_items roi JOIN articles a ON a.id = roi.article_id WHERE roi.recurring_order_id = %s ORDER BY a.categorie, a.nom", (recurring_id,))
            result.append({"id": recurring_id, "prenom": prenom, "nom": nom, "commentaire": commentaire, "items": cur.fetchall()})
    return result

def recurrence_status_text(pause_du, pause_au):
    if pause_du and pause_au:
        return f"En pause du {pause_du} au {pause_au}"
    return "Active"

def set_recurrence_pause(recurring_id, pause_du, pause_au):
    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE recurring_orders SET pause_du = %s, pause_au = %s WHERE id = %s", (pause_du, pause_au, recurring_id))
        if pause_du and pause_au:
            cur.execute("DELETE FROM orders WHERE recurring_order_id = %s AND COALESCE(recurring_source_date, date_commande, order_date) BETWEEN %s AND %s", (recurring_id, pause_du, pause_au))

def clear_recurrence_pause(recurring_id):
    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE recurring_orders SET pause_du = NULL, pause_au = NULL WHERE id = %s", (recurring_id,))

def materialize_recurring_orders(selected_date, user_id):
    with get_cursor(commit=True) as cur:
        for recurring in get_recurring_orders_for_date(selected_date):
            cur.execute("SELECT id FROM orders WHERE recurring_order_id = %s AND recurring_source_date = %s", (recurring["id"], selected_date))
            if cur.fetchone():
                continue
            cur.execute("INSERT INTO orders (prenom, nom, date_commande, commentaire, first_name, last_name, order_date, comment, created_by_user_id, recurring_order_id, recurring_source_date) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id", (recurring["prenom"], recurring["nom"], selected_date, recurring["commentaire"], recurring["prenom"], recurring["nom"], selected_date, recurring["commentaire"], user_id, recurring["id"], selected_date))
            order_id = cur.fetchone()[0]
            items = []
            for article_id, name, category, qty, size in recurring["items"]:
                items.append((article_id, display_name(name, category, size), category, qty, size))
            insert_order_items(cur, order_id, items)

def list_recurrences():
    with get_cursor() as cur:
        cur.execute("SELECT id, prenom, nom, commentaire, weekday, pause_du, pause_au FROM recurring_orders WHERE actif = TRUE ORDER BY nom, prenom")
        return cur.fetchall()


def get_recurring_order_items(recurring_id):
    with get_cursor() as cur:
        cur.execute("SELECT a.categorie, a.nom, roi.quantite, COALESCE(roi.taille, '') FROM recurring_order_items roi JOIN articles a ON a.id = roi.article_id WHERE roi.recurring_order_id = %s ORDER BY a.categorie, a.nom", (recurring_id,))
        return cur.fetchall()


def create_recurrence(prenom, nom, commentaire, weekday, items_to_save):
    with get_cursor(commit=True) as cur:
        cur.execute("INSERT INTO recurring_orders (prenom, nom, commentaire, weekday, actif) VALUES (%s, %s, %s, %s, TRUE) RETURNING id", (prenom, nom, commentaire, weekday))
        recurring_id = cur.fetchone()[0]
        for article_id, qty, size in items_to_save:
            cur.execute("INSERT INTO recurring_order_items (recurring_order_id, article_id, quantite, taille) VALUES (%s, %s, %s, %s)", (recurring_id, article_id, qty, size or None))


def set_recurrence_exception(recurring_id, selected_date, mode):
    with get_cursor(commit=True) as cur:
        if mode in ["skip", "deleted"]:
            cur.execute("DELETE FROM orders WHERE recurring_order_id = %s AND COALESCE(recurring_source_date, date_commande, order_date) = %s", (recurring_id, selected_date))
        cur.execute("INSERT INTO recurring_order_exceptions (recurring_order_id, date_commande, mode, commentaire) VALUES (%s, %s, %s, NULL) ON CONFLICT (recurring_order_id, date_commande) DO UPDATE SET mode = EXCLUDED.mode", (recurring_id, selected_date, mode))

def get_recurring_order_for_edit(recurring_id):
    with get_cursor() as cur:
        cur.execute("SELECT id, prenom, nom, commentaire, weekday, actif, pause_du, pause_au FROM recurring_orders WHERE id = %s", (recurring_id,))
        recurring_row = cur.fetchone()
        cur.execute("SELECT article_id, quantite, COALESCE(taille, '') FROM recurring_order_items WHERE recurring_order_id = %s", (recurring_id,))
        items, sizes = {}, {}
        for article_id, qty, size in cur.fetchall():
            items[article_id] = qty
            sizes[article_id] = size or ""
    return recurring_row, items, sizes


def update_recurrence(recurring_id, prenom, nom, commentaire, weekday, items_to_save):
    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE recurring_orders SET prenom = %s, nom = %s, commentaire = %s, weekday = %s WHERE id = %s", (prenom, nom, commentaire, weekday, recurring_id))
        cur.execute("DELETE FROM recurring_order_items WHERE recurring_order_id = %s", (recurring_id,))
        for article_id, qty, size in items_to_save:
            cur.execute("INSERT INTO recurring_order_items (recurring_order_id, article_id, quantite, taille) VALUES (%s, %s, %s, %s)", (recurring_id, article_id, qty, size or None))


def deactivate_recurrence(recurring_id):
    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE recurring_orders SET actif = FALSE WHERE id = %s", (recurring_id,))


def ensure_week_override_order(recurring_id, selected_date, user_id):
    with get_cursor(commit=True) as cur:
        cur.execute("SELECT id FROM orders WHERE recurring_order_id = %s AND recurring_source_date = %s", (recurring_id, selected_date))
        existing = cur.fetchone()
        if existing:
            return existing[0]
        cur.execute("SELECT prenom, nom, COALESCE(commentaire, '') FROM recurring_orders WHERE id = %s", (recurring_id,))
        prenom, nom, commentaire = cur.fetchone()
        cur.execute("INSERT INTO orders (prenom, nom, date_commande, commentaire, first_name, last_name, order_date, comment, created_by_user_id, recurring_order_id, recurring_source_date) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id", (prenom, nom, selected_date, commentaire, prenom, nom, selected_date, commentaire, user_id, recurring_id, selected_date))
        order_id = cur.fetchone()[0]
        cur.execute("SELECT roi.article_id, a.nom, a.categorie, roi.quantite, COALESCE(roi.taille, '') FROM recurring_order_items roi JOIN articles a ON a.id = roi.article_id WHERE roi.recurring_order_id = %s", (recurring_id,))
        items = []
        for article_id, name, category, qty, size in cur.fetchall():
            items.append((article_id, display_name(name, category, size), category, qty, size))
        insert_order_items(cur, order_id, items)
        cur.execute("INSERT INTO recurring_order_exceptions (recurring_order_id, date_commande, mode, commentaire) VALUES (%s, %s, 'custom', NULL) ON CONFLICT (recurring_order_id, date_commande) DO UPDATE SET mode = EXCLUDED.mode", (recurring_id, selected_date))
        return order_id


def list_totals(selected_date):
    with get_cursor() as cur:
        cur.execute(f"SELECT COALESCE(oi.categorie_snapshot, oi.category), COALESCE(oi.article_nom_snapshot, oi.item_name), SUM(COALESCE(oi.quantite, oi.quantity, 0)) FROM order_items oi JOIN orders o ON oi.order_id = o.id WHERE COALESCE(o.date_commande, o.order_date) = %s AND {active_order_filter('o')} GROUP BY COALESCE(oi.categorie_snapshot, oi.category), COALESCE(oi.article_nom_snapshot, oi.item_name) ORDER BY COALESCE(oi.categorie_snapshot, oi.category), COALESCE(oi.article_nom_snapshot, oi.item_name)", (selected_date,))
        return cur.fetchall()

def generate_totals_pdf(data, selected_date):
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    pdf = canvas.Canvas(tmp_file.name, pagesize=A4)
    _, height = A4
    y = height - 40
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(50, y, f"Feuille de production - {selected_date}")
    y -= 30
    for categorie, articles in data.items():
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(50, y, categorie)
        y -= 18
        pdf.setFont("Helvetica", 11)
        for nom, qty in articles:
            pdf.drawString(70, y, f"{nom} : {qty}")
            y -= 14
            if y < 60:
                pdf.showPage(); y = height - 40
    pdf.save()
    return tmp_file.name


def generate_orders_pdf(rows, selected_date=None):
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    pdf = canvas.Canvas(tmp_file.name, pagesize=A4)
    _, height = A4
    y = height - 40
    title = f"Liste des commandes - {selected_date}" if selected_date is not None else "Liste de toutes les commandes"
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(50, y, title)
    y -= 28
    if not rows:
        pdf.setFont("Helvetica", 11)
        pdf.drawString(50, y, "Aucune commande a imprimer")
        pdf.save()
        return tmp_file.name
    for order_id, prenom, nom, dt, commentaire in rows:
        client = f"{prenom or ''} {nom or ''}".strip() or "Client"
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(50, y, f"Commande #{order_id} - {client} - {dt}")
        y -= 16
        pdf.setFont("Helvetica", 10)
        comment_line = f"Commentaire : {commentaire or '-'}"
        pdf.drawString(60, y, comment_line[:110])
        y -= 14
        for category, article_name, qty, _size in get_order_items(order_id):
            line = f"- {category} - {article_name} : {qty}"
            pdf.drawString(70, y, line[:105])
            y -= 13
            if y < 60:
                pdf.showPage()
                y = height - 40
        y -= 8
        if y < 60:
            pdf.showPage()
            y = height - 40
    pdf.save()
    return tmp_file.name


def list_label_containers(selected_date):
    with get_cursor() as cur:
        cur.execute(f"SELECT o.id, COALESCE(o.prenom, o.first_name), COALESCE(o.nom, o.last_name), COALESCE(oi.categorie_snapshot, oi.category), COALESCE(oi.article_nom_snapshot, oi.item_name), COALESCE(oi.quantite, oi.quantity, 0) FROM orders o JOIN order_items oi ON oi.order_id = o.id WHERE COALESCE(o.date_commande, o.order_date) = %s AND COALESCE(oi.quantite, oi.quantity, 0) > 0 AND {active_order_filter('o')} ORDER BY o.id, COALESCE(oi.categorie_snapshot, oi.category), COALESCE(oi.article_nom_snapshot, oi.item_name)", (selected_date,))
        rows = cur.fetchall()
    grouped = {}
    for order_id, prenom, nom, category, article_name, qty in rows:
        order = grouped.setdefault(order_id, {"client": f"{prenom or ''} {nom or ''}".strip(), "containers": []})
        if category in {"Pains", "Tartes"}:
            for _ in range(qty):
                order["containers"].append({"categorie": category, "items": [(article_name, 1)]})
        else:
            container = next((c for c in order["containers"] if c["categorie"] == category), None)
            if container is None:
                container = {"categorie": category, "items": []}
                order["containers"].append(container)
            container["items"].append((article_name, qty))
    labels = []
    for order in grouped.values():
        total = len(order["containers"])
        for index, container in enumerate(order["containers"], start=1):
            labels.append({"client": order["client"], "categorie": container["categorie"], "items": container["items"], "index": index, "total": total})
    return labels


def generate_labels_pdf(labels, selected_date):
    label_width = 62 * mm
    label_height = 100 * mm
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    pdf = canvas.Canvas(tmp_file.name, pagesize=(label_width, label_height))
    if not labels:
        pdf.setFont("Helvetica", 10)
        pdf.drawString(8 * mm, label_height - 15 * mm, "Aucune etiquette a generer")
        pdf.save(); return tmp_file.name
    for idx, label in enumerate(labels):
        if idx > 0:
            pdf.showPage(); pdf.setPageSize((label_width, label_height))
        y = label_height - 6 * mm
        pdf.roundRect(2 * mm, 2 * mm, label_width - 4 * mm, label_height - 4 * mm, 3 * mm)
        if LOGO_PATH.exists():
            pdf.drawImage(str(LOGO_PATH), 4 * mm, y - 12 * mm, width=12 * mm, height=12 * mm, preserveAspectRatio=True, mask="auto")
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(18 * mm, y - 8, BAKERY_NAME[:24])
        pdf.setFont("Helvetica", 6.5)
        pdf.drawString(18 * mm, y - 16, BAKERY_ADDRESS[:34])
        pdf.drawString(18 * mm, y - 23, BAKERY_PHONE)
        y -= 30 * mm
        pdf.line(4 * mm, y, label_width - 4 * mm, y)
        y -= 4 * mm
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(4 * mm, y - 10, (label["client"] or "Client")[:28])
        y -= 14
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(4 * mm, y - 10, label["categorie"][:28])
        y -= 14
        pdf.line(4 * mm, y, label_width - 4 * mm, y)
        y -= 12
        pdf.setFont("Helvetica", 8.5)
        for article_name, qty in label["items"]:
            line = f"- {article_name} : {qty}"
            for chunk_index in range(0, len(line), 34):
                if y < 20 * mm: break
                pdf.drawString(4 * mm, y, line[chunk_index:chunk_index+34])
                y -= 10
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawCentredString(label_width / 2, 9 * mm, f"{label['index']}/{label['total']}")
        pdf.setFont("Helvetica", 7)
        pdf.drawCentredString(label_width / 2, 5 * mm, f"QL-800 DK-11202 - {selected_date}")
    pdf.save(); return tmp_file.name


def trigger_pdf_print(pdf_bytes):
    b64 = base64.b64encode(pdf_bytes).decode("utf-8")
    components.html(f"""<script>
    const bytes = atob('{b64}');
    const arr = new Array(bytes.length);
    for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
    const blob = new Blob([new Uint8Array(arr)], {{type: 'application/pdf'}});
    const url = URL.createObjectURL(blob);
    const win = window.open(url, '_blank');
    if (win) {{ const p = () => {{ win.focus(); win.print(); }}; win.onload = p; setTimeout(p, 800); }}
    </script>""", height=0)


def print_pdf_button(label, pdf_path, key):
    if st.button(label, key=key, use_container_width=True):
        with open(pdf_path, "rb") as pdf_file:
            trigger_pdf_print(pdf_file.read())

def render_order_summary(articles_dict, categories):
    st.markdown('<div class="summary-card">', unsafe_allow_html=True)
    st.markdown('<div class="card-title">Resume de la commande</div>', unsafe_allow_html=True)
    total = 0
    has_items = False
    for category in categories:
        lines = []
        for article in articles_dict.get(category, []):
            qty = st.session_state.order_quantities.get(f"{category}|{article['id']}", 0)
            if qty > 0:
                item_name = display_name(article["nom"], category, st.session_state.article_sizes.get(size_key(category, article["id"]), ""))
                total += qty
                lines.append(f"{item_name} : {qty}")
        if lines:
            has_items = True
            st.write(f"**{category}**")
            for line in lines: st.write(f"- {line}")
    if not has_items: st.info("Aucun article selectionne.")
    st.write(f"**Total pieces : {total}**")
    st.markdown("</div>", unsafe_allow_html=True)


def render_quantity_control(prefix, article_id, item_key, qty, max_allowed=None):
    new_value = st.text_input("Quantite", value=str(qty), key=f"{prefix}_qty_{article_id}", label_visibility="collapsed")
    if new_value != str(qty):
        try: parsed = int(new_value)
        except ValueError: st.warning("Entre un nombre entier.")
        else:
            if parsed < 0: st.warning("La quantite ne peut pas etre negative.")
            elif max_allowed is not None and parsed > max_allowed: st.warning("La quantite depasse la limite autorisee.")
            else:
                st.session_state.order_quantities[item_key] = parsed
                st.rerun()


def render_tarte_size_selector(prefix, article_id, category):
    key = size_key(category, article_id)
    current = st.session_state.article_sizes.get(key, "")
    options = [""] + TARTE_SIZES
    selected = st.selectbox("Taille", options=options, index=options.index(current) if current in options else 0, key=f"{prefix}_size_{article_id}", format_func=lambda v: "Choisir taille" if v == "" else v)
    if selected != current:
        st.session_state.article_sizes[key] = selected
        st.rerun()


def collect_order_items(articles_dict, selected_date, exclude_order_id=None):
    items_to_save, errors = [], []
    for category, articles in articles_dict.items():
        for article in articles:
            article_id = article["id"]
            qty = st.session_state.order_quantities.get(f"{category}|{article_id}", 0)
            if qty <= 0:
                continue
            size = st.session_state.article_sizes.get(size_key(category, article_id), "") if category == "Tartes" else ""
            if category == "Tartes" and not size:
                errors.append(f"Choisis une taille pour {article['nom']}.")
                continue
            base_qty = get_total_already_ordered(selected_date, article_id, exclude_order_id)
            daily_limit = get_daily_limit(selected_date, article_id)
            if daily_limit is not None and base_qty + qty > daily_limit:
                errors.append(f"{article['nom']} depasse la limite autorisee.")
            else:
                items_to_save.append((article_id, display_name(article["nom"], category, size), category, qty, size))
    return items_to_save, errors


def collect_recurrence_items(articles_dict):
    items_to_save = []
    errors = []
    for category, articles in articles_dict.items():
        for article in articles:
            qty = st.session_state.order_quantities.get(f"{category}|{article['id']}", 0)
            if qty <= 0:
                continue
            size = st.session_state.article_sizes.get(size_key(category, article["id"]), "") if category == "Tartes" else ""
            if category == "Tartes" and not size:
                errors.append(f"Choisis une taille pour {article['nom']}.")
                continue
            items_to_save.append((article["id"], qty, size))
    return items_to_save, errors

def show_login_page():
    show_logo(300)
    _, center, _ = st.columns([1, 1.25, 1])
    with center:
        st.markdown("<div class='login-card'><div class='card-title'>Connexion</div><div class='card-subtitle'>Acces securise a l'application magasin, atelier et gestion des articles.</div></div>", unsafe_allow_html=True)
        st.markdown("".join([f"<span class='role-chip'>{u['username']} - {u['label']}</span>" for u in DEFAULT_USERS]), unsafe_allow_html=True)
        username = st.text_input("Utilisateur")
        password = st.text_input("Mot de passe", type="password")
        if st.button("Se connecter", use_container_width=True):
            user = login_user(username, password)
            if user:
                st.session_state.user = user
                st.session_state.page = "totaux" if user["role"] == "atelier" else "liste_articles" if user["role"] == "articles" else "accueil"
                st.rerun()
            st.error("Identifiants incorrects.")


def render_editor_common(prefix, title, prenom_default="", nom_default="", commentaire_default="", selected_date=None, weekday_default=None):
    articles_dict = get_articles()
    categories = CATEGORIES + [c for c in articles_dict if c not in CATEGORIES]
    if not categories:
        st.info("Aucun article actif.")
        return None
    ensure_order_quantities(articles_dict)
    if st.session_state.selected_category not in categories:
        st.session_state.selected_category = categories[0]
    st.title(title)
    c1, c2 = st.columns(2)
    with c1: prenom = st.text_input("Prenom", value=prenom_default, key=f"{prefix}_prenom")
    with c2: nom = st.text_input("Nom", value=nom_default, key=f"{prefix}_nom")
    commentaire = st.text_area("Commentaire", value=commentaire_default or "", key=f"{prefix}_commentaire")
    date_value = st.date_input("Date", value=selected_date, key=f"{prefix}_date") if selected_date is not None else None
    weekday_value = st.selectbox("Jour recurrent", options=list(range(7)), index=weekday_default if weekday_default is not None else 0, format_func=lambda v: WEEKDAYS[v], key=f"{prefix}_weekday") if weekday_default is not None else None
    st.subheader("Choisir une categorie")
    cat_cols = st.columns(min(len(categories), 5))
    for index, category in enumerate(categories):
        with cat_cols[index % len(cat_cols)]:
            if st.button(category, key=f"{prefix}_cat_{category}", use_container_width=True):
                st.session_state.selected_category = category
                st.rerun()
    active_category = st.session_state.selected_category
    left, right = st.columns([3.4, 1.25])
    with left:
        st.markdown(f"<div class='panel-card'><div class='card-title'>{active_category}</div>", unsafe_allow_html=True)
        article_cols = st.columns(2)
        for index, article in enumerate(articles_dict.get(active_category, [])):
            article_id = article["id"]
            item_key = f"{active_category}|{article_id}"
            qty = st.session_state.order_quantities.get(item_key, 0)
            with article_cols[index % len(article_cols)]:
                st.markdown("<div class='article-card'>", unsafe_allow_html=True)
                st.markdown(f"<div class='article-name'>{article['nom']}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='article-qty'>{qty}</div>", unsafe_allow_html=True)
                if active_category == "Tartes":
                    render_tarte_size_selector(prefix, article_id, active_category)
                render_quantity_control(prefix, article_id, item_key, qty)
                st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with right:
        render_order_summary(articles_dict, categories)
    return {"articles_dict": articles_dict, "categories": categories, "prenom": prenom, "nom": nom, "commentaire": commentaire, "date": date_value, "weekday": weekday_value}


def show_order_editor(mode="new"):
    is_edit = mode == "edit"
    order_id = st.session_state.edit_order_id if is_edit else None
    if is_edit:
        order_row, order_items, order_sizes = get_order_for_edit(order_id)
        if not order_row:
            st.error("Commande introuvable.")
            return
        load_key = f"edit_loaded_{order_id}"
        if not st.session_state.get(load_key):
            load_order_into_session(get_articles(), order_items, order_sizes)
            st.session_state[load_key] = True
        _, prenom_default, nom_default, date_default, commentaire_default = order_row
    else:
        prenom_default, nom_default, date_default, commentaire_default = "", "", date.today(), ""
    top1, top2 = st.columns(2)
    with top1:
        if st.button("Retour", use_container_width=True):
            if is_edit:
                st.session_state.edit_order_id = None; st.session_state.pop(f"edit_loaded_{order_id}", None); go_to_page("voir_commandes")
            go_to_page("accueil")
    with top2:
        if st.button("Recharger la commande" if is_edit else "Reinitialiser les quantites", use_container_width=True):
            if is_edit: load_order_into_session(get_articles(), order_items, order_sizes)
            else: reset_editor_form(mode, get_articles(), selected_category=CATEGORIES[0], selected_date=date.today())
            st.rerun()
    form = render_editor_common(mode, "Modifier la commande" if is_edit else "Nouvelle commande", prenom_default, nom_default, commentaire_default, date_default)
    if not is_edit:
        ensure_week_override = form["date"]
        if ensure_week_override: materialize_recurring_orders(ensure_week_override, st.session_state.user["id"])
    if form and st.button("Enregistrer la commande", key=f"{mode}_save_order", use_container_width=True):
        items_to_save, errors = collect_order_items(form["articles_dict"], form["date"], order_id if is_edit else None)
        if not form["nom"].strip(): errors.append("Le nom est obligatoire.")
        if not items_to_save: errors.append("La commande ne contient aucun article.")
        if errors:
            for error in errors: st.error(error)
        elif is_edit:
            update_order(order_id, form["prenom"].strip(), form["nom"].strip(), form["date"], form["commentaire"].strip(), items_to_save)
            st.session_state.flash_message = "Commande modifiee avec succes."
            st.session_state.edit_order_id = None; st.session_state.pop(f"edit_loaded_{order_id}", None)
            go_to_page("voir_commandes")
        else:
            save_order(form["prenom"].strip(), form["nom"].strip(), form["date"], form["commentaire"].strip(), st.session_state.user["id"], items_to_save)
            st.session_state.flash_message = "Commande enregistree avec succes."
            reset_editor_form(mode, form["articles_dict"], selected_category=form["categories"][0], selected_date=date.today())
            go_to_page("nouvelle_commande")

def show_orders_page():
    st.title("Voir les commandes")
    c1, c2 = st.columns([2,1])
    with c1: selected_date = st.date_input("Afficher les commandes du", value=date.today(), key="orders_filter_date")
    with c2: show_all = st.checkbox("Tout afficher", value=False, key="orders_show_all")
    if not show_all: materialize_recurring_orders(selected_date, st.session_state.user["id"])
    rows = list_orders(None if show_all else selected_date)
    pdf_label = "Imprimer les commandes affichees" if show_all else "Imprimer les commandes du jour"
    print_pdf_button(pdf_label, generate_orders_pdf(rows, None if show_all else selected_date), "print_orders")
    if not rows:
        st.info("Aucune commande trouvee.")
        return
    for order_id, prenom, nom, dt, commentaire in rows:
        with st.expander(f"Commande #{order_id} - {prenom} {nom} - {dt}"):
            a,b,c = st.columns([1,1,3])
            with a:
                if st.button("Modifier", key=f"edit_{order_id}", use_container_width=True): st.session_state.edit_order_id = order_id; go_to_page("modifier_commande")
            with b:
                if st.button("Supprimer", key=f"delete_{order_id}", use_container_width=True): delete_order(order_id); st.session_state.flash_message = "Commande supprimee."; st.rerun()
            with c: st.write(f"**Commentaire :** {commentaire or '-'}")
            for category, article_name, qty, _size in get_order_items(order_id): st.write(f"{category} - {article_name} : {qty}")


def show_recurrences_page():
    form = render_editor_common("rec_new", "Commandes recurrentes", weekday_default=0)
    if form and st.button("Creer la recurrence", use_container_width=True, key="create_recurrence_btn"):
        items_to_save, errors = collect_recurrence_items(form["articles_dict"])
        if not form["nom"].strip(): errors.append("Le nom est obligatoire.")
        if not items_to_save: errors.append("La recurrence ne contient aucun article.")
        if errors:
            for error in errors: st.error(error)
        else:
            create_recurrence(form["prenom"].strip(), form["nom"].strip(), form["commentaire"].strip(), form["weekday"], items_to_save)
            st.session_state.flash_message = "Commande recurrente creee avec succes."
            reset_editor_form("rec_new", form["articles_dict"], selected_category=form["categories"][0], weekday_value=0)
            st.rerun()
    st.divider(); st.subheader("Recurrences existantes")
    selected_date = st.date_input("Date concernee", value=date.today(), key="rec_selected_date")
    for recurring_id, prenom, nom, commentaire, weekday, pause_du, pause_au in list_recurrences():
        with st.expander(f"{prenom} {nom} - {WEEKDAYS[weekday]}"):
            st.caption(recurrence_status_text(pause_du, pause_au))
            for category, article_name, qty, size in get_recurring_order_items(recurring_id): st.write(f"{category} - {display_name(article_name, category, size)} : {qty}")
            st.write(f"Commentaire : {commentaire or '-'}")
            pause_from = st.date_input("Pause du", value=pause_du or selected_date, key=f"pause_from_{recurring_id}")
            pause_to = st.date_input("Pause au", value=pause_au or selected_date, key=f"pause_to_{recurring_id}")
            p1, p2 = st.columns(2)
            with p1:
                if st.button("Mettre en pause", key=f"pause_{recurring_id}", use_container_width=True):
                    if pause_from > pause_to:
                        st.error("La date de debut de pause doit etre avant la date de fin.")
                    else:
                        set_recurrence_pause(recurring_id, pause_from, pause_to)
                        st.session_state.flash_message = "Recurrence mise en pause."
                        st.rerun()
            with p2:
                if st.button("Reprendre maintenant", key=f"resume_{recurring_id}", use_container_width=True):
                    clear_recurrence_pause(recurring_id)
                    st.session_state.flash_message = "Recurrence reactivee."
                    st.rerun()
            a,b,c = st.columns(3)
            with a:
                if st.button("Modifier cette semaine", key=f"week_{recurring_id}", use_container_width=True): st.session_state.edit_order_id = ensure_week_override_order(recurring_id, selected_date, st.session_state.user["id"]); go_to_page("modifier_commande")
            with b:
                if st.button("Modifier pour toujours", key=f"edit_rec_{recurring_id}", use_container_width=True): st.session_state.edit_recurring_id = recurring_id; go_to_page("modifier_recurrence")
            with c:
                if st.button("Supprimer pour toujours", key=f"delete_rec_{recurring_id}", use_container_width=True): deactivate_recurrence(recurring_id); st.rerun()


def show_edit_recurrence_page():
    recurring_id = st.session_state.get("edit_recurring_id")
    if recurring_id is None: st.error("Aucune recurrence selectionnee."); return
    recurring_row, recurring_items, recurring_sizes = get_recurring_order_for_edit(recurring_id)
    if not recurring_row: st.error("Commande recurrente introuvable."); st.session_state.edit_recurring_id = None; return
    load_key = f"recurring_loaded_{recurring_id}"
    if not st.session_state.get(load_key):
        load_order_into_session(get_articles(), recurring_items, recurring_sizes)
        st.session_state[load_key] = True
    _, prenom_default, nom_default, commentaire_default, weekday_default, _, _pause_du, _pause_au = recurring_row
    a,b = st.columns(2)
    with a:
        if st.button("Retour aux recurrences", use_container_width=True): st.session_state.edit_recurring_id = None; st.session_state.pop(load_key, None); go_to_page("recurrences")
    with b:
        if st.button("Recharger le modele", use_container_width=True): load_order_into_session(get_articles(), recurring_items, recurring_sizes); st.rerun()
    form = render_editor_common("rec_edit", "Modifier la commande recurrente", prenom_default, nom_default, commentaire_default, weekday_default=weekday_default)
    if form and st.button("Enregistrer la recurrence", use_container_width=True, key="save_recurrence_btn"):
        items_to_save, errors = collect_recurrence_items(form["articles_dict"])
        if not form["nom"].strip(): errors.append("Le nom est obligatoire.")
        if not items_to_save: errors.append("La recurrence ne contient aucun article.")
        if errors:
            for error in errors: st.error(error)
        else:
            update_recurrence(recurring_id, form["prenom"].strip(), form["nom"].strip(), form["commentaire"].strip(), form["weekday"], items_to_save)
            st.session_state.flash_message = "Commande recurrente modifiee avec succes."
            st.session_state.edit_recurring_id = None; st.session_state.pop(load_key, None); go_to_page("recurrences")

def show_totals_page():
    st.title("Totaux")
    selected_date = st.date_input("Choisir une date", value=date.today(), key="totaux_date")
    materialize_recurring_orders(selected_date, st.session_state.user["id"])
    rows = list_totals(selected_date)
    if not rows: st.info("Aucune commande pour cette date."); return
    data, total_general = {}, 0
    for category, article_name, qty in rows:
        data.setdefault(category, []).append((article_name, qty)); total_general += qty
    st.write(f"**Total general : {total_general}**")
    for category, articles in data.items():
        st.markdown(f"<div class='panel-card'><div class='card-title'>{category}</div>", unsafe_allow_html=True)
        for article_name, qty in articles: st.write(f"{article_name} : {qty}")
        st.markdown("</div>", unsafe_allow_html=True)
    print_pdf_button("Imprimer les totaux", generate_totals_pdf(data, selected_date), "print_totaux")


def show_labels_page():
    st.title("Etiquettes")
    selected_date = st.date_input("Date des etiquettes", value=date.today(), key="labels_date")
    materialize_recurring_orders(selected_date, st.session_state.user["id"])
    labels = list_label_containers(selected_date)
    if not labels: st.info("Aucune etiquette a generer pour cette date."); return
    st.caption("Format die-cut Brother QL-800: DK-11202, 62 x 100 mm, une etiquette par contenant.")
    st.write(f"**Nombre d'etiquettes : {len(labels)}**")
    for label in labels:
        with st.expander(f"{label['client']} - {label['categorie']} ({label['index']}/{label['total']})"):
            for article_name, qty in label["items"]: st.write(f"{article_name} : {qty}")
    print_pdf_button("Imprimer les etiquettes", generate_labels_pdf(labels, selected_date), "print_labels")


def show_limits_page():
    st.title("Limites de commandes")
    selected_date = st.date_input("Date des limites", value=date.today(), key="limits_date")
    articles_dict = get_articles()
    values = {}
    for category, articles in articles_dict.items():
        st.markdown(f"<div class='panel-card'><div class='card-title'>{category}</div>", unsafe_allow_html=True)
        for article in articles:
            values[article["id"]] = st.number_input(article["nom"], min_value=0, value=get_daily_limit(selected_date, article["id"]) or 0, step=1, key=f"limit_{article['id']}")
        st.markdown("</div>", unsafe_allow_html=True)
    if st.button("Enregistrer les limites", use_container_width=True): save_limits(selected_date, values); st.success("Limites enregistrees.")


def show_articles_page():
    st.title("Gestion des articles")
    categories = get_article_categories(); name = st.text_input("Nom de l'article", key="new_article_name"); category = st.selectbox("Categorie", categories, key="new_article_category")
    if st.button("Ajouter l'article", use_container_width=True):
        if not name.strip(): st.error("Le nom est obligatoire.")
        elif article_exists(name, category): st.error("Cet article existe deja dans cette categorie.")
        else: add_article(name, category); st.success("Article ajoute."); st.rerun()
    for article_id, nom, categorie, actif in get_all_articles():
        c1,c2,c3,c4 = st.columns([3,1,1,1])
        with c1: st.write(f"{categorie} - {nom}")
        with c2: st.write("Actif" if actif else "Inactif")
        with c3:
            if st.button("On/Off", key=f"toggle_article_{article_id}", use_container_width=True): toggle_article(article_id, not actif); st.rerun()
        with c4:
            if st.button("Supprimer", key=f"delete_article_{article_id}", use_container_width=True):
                if article_has_order_history(article_id):
                    toggle_article(article_id, False)
                    st.session_state.flash_message = "Article deja utilise dans des commandes : il a ete desactive, pas supprime."
                else:
                    delete_article(article_id)
                    st.session_state.flash_message = "Article supprime."
                st.rerun()


def show_home_page():
    st.markdown("<div class='hero-card'><div class='card-title'>Espace magasin</div><div class='card-subtitle'>Choisis une action.</div></div>", unsafe_allow_html=True)
    pages = [("nouvelle_commande", "Nouvelle commande"), ("voir_commandes", "Voir les commandes"), ("recurrences", "Commandes recurrentes"), ("totaux", "Totaux"), ("etiquettes", "Etiquettes"), ("limites", "Limites")]
    cols = st.columns(len(pages))
    for col, (page_name, label) in zip(cols, pages):
        with col:
            if st.button(label, use_container_width=True): go_to_page(page_name)


def render_page():
    try:
        ensure_schema()
    except Exception as exc:
        show_database_error(exc)
        return
    init_session_state()
    if st.session_state.user is None: show_login_page(); return
    role = st.session_state.user["role"]
    if role == "atelier" and st.session_state.page != "totaux": st.session_state.page = "totaux"
    if role == "articles" and st.session_state.page != "liste_articles": st.session_state.page = "liste_articles"
    if st.session_state.flash_message: st.success(st.session_state.flash_message); st.session_state.flash_message = None
    show_sidebar(role)
    page = st.session_state.page
    if page == "accueil" and role == "magasin": show_home_page()
    elif page == "nouvelle_commande" and role == "magasin": show_order_editor("new")
    elif page == "voir_commandes" and role == "magasin": show_orders_page()
    elif page == "modifier_commande" and role == "magasin": show_order_editor("edit")
    elif page == "recurrences" and role == "magasin": show_recurrences_page()
    elif page == "modifier_recurrence" and role == "magasin": show_edit_recurrence_page()
    elif page == "totaux": show_totals_page()
    elif page == "etiquettes" and role == "magasin": show_labels_page()
    elif page == "limites" and role == "magasin": show_limits_page()
    elif page == "liste_articles" and role == "articles": show_articles_page()
    else: st.error("Acces refuse.")


def main():
    configure_page(); render_page()







