from datetime import date
import tempfile
import os
from pathlib import Path

import psycopg2
import streamlit as st
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

LOGO_PATH = Path(__file__).with_name("pain.png")

st.set_page_config(page_title="Boulangerie", layout="wide")
st.markdown(
    """
    <style>
    .stApp { background: linear-gradient(180deg, #f8f1e9 0%, #ecdcca 100%); color: #2b190f; }
    [data-testid="stSidebar"] { background: linear-gradient(180deg, #e2ccb6 0%, #d5b798 100%); }
    .stMarkdown, .stText, p, li, label, .stCaption { color: #2b190f; }
    h1, h2, h3 { color: #3a2113 !important; }
    .stButton > button {
        background: linear-gradient(180deg, #d8b18b 0%, #c79267 100%);
        color: #201109;
        border: 1px solid #996944;
        border-radius: 12px;
        font-weight: 700;
        box-shadow: 0 2px 6px rgba(80, 45, 20, 0.18);
    }
    .stButton > button:hover {
        background: linear-gradient(180deg, #cc9d72 0%, #b77f55 100%);
        color: #140b06;
        border-color: #7d5232;
    }
    .stTextInput input, .stTextArea textarea, .stDateInput input, .stNumberInput input {
        background-color: #fffdfa;
        border: 1px solid #b68863;
        color: #000000;
    }
    .stTextInput input::placeholder, .stTextArea textarea::placeholder {
        color: #8a6a54;
    }
    .stTextInput label, .stTextArea label, .stDateInput label, .stNumberInput label {
        color: #000000 !important;
    }
    .hero-card, .block-card, .article-card, .summary-card {
        border-radius: 18px;
        border: 1px solid #ba8d69;
        box-shadow: 0 8px 20px rgba(70, 40, 20, 0.09);
    }
    .hero-card {
        padding: 1.5rem;
        background: linear-gradient(135deg, #ead6c2 0%, #d8b596 100%);
        margin-bottom: 1rem;
    }
    .block-card, .article-card {
        padding: 1rem;
        background: #fff8ef;
        margin-bottom: 1rem;
    }
    .summary-card {
        padding: 1rem;
        background: linear-gradient(180deg, #f3e2d0 0%, #e6c8a8 100%);
        position: sticky;
        top: 1rem;
    }
    .article-title, .summary-title { font-weight: 700; color: #3f2414; }
    .article-title { min-height: 44px; }
    </style>
    """,
    unsafe_allow_html=True,
)

def get_secret(key, default=None):
    env_value = os.getenv(key)
    if env_value is not None:
        return env_value

    try:
        return st.secrets[key]
    except Exception:
        return default


def get_connection():
    database_url = get_secret("DATABASE_URL")
    if database_url:
        return psycopg2.connect(
            database_url,
            sslmode=get_secret("DB_SSLMODE", "require"),
            connect_timeout=10,
        )

    required_keys = ["DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_PORT"]
    config = {key: get_secret(key) for key in required_keys}
    missing_keys = [key for key, value in config.items() if value in (None, "")]
    if missing_keys:
        raise KeyError(
            "Clés manquantes pour Supabase : "
            + ", ".join(missing_keys)
            + ". Ajoute-les dans .streamlit/secrets.toml ou dans les variables d'environnement."
        )

    return psycopg2.connect(
        host=config["DB_HOST"],
        dbname=config["DB_NAME"],
        user=config["DB_USER"],
        password=config["DB_PASSWORD"],
        port=config["DB_PORT"],
        sslmode=get_secret("DB_SSLMODE", "require"),
        connect_timeout=10,
    )


def ensure_schema():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            role TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id SERIAL PRIMARY KEY,
            nom TEXT NOT NULL,
            categorie TEXT NOT NULL,
            actif BOOLEAN NOT NULL DEFAULT TRUE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            prenom TEXT NOT NULL,
            nom TEXT NOT NULL,
            date_commande DATE NOT NULL,
            commentaire TEXT,
            created_by_user_id INTEGER,
            recurring_order_id INTEGER,
            recurring_source_date DATE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id SERIAL PRIMARY KEY,
            order_id INTEGER NOT NULL,
            article_id INTEGER NOT NULL,
            article_nom_snapshot TEXT NOT NULL,
            categorie_snapshot TEXT NOT NULL,
            quantite INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY (article_id) REFERENCES articles(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_limits (
            id SERIAL PRIMARY KEY,
            date_jour DATE NOT NULL,
            article_id INTEGER NOT NULL,
            quantite_max INTEGER NOT NULL,
            UNIQUE (date_jour, article_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recurring_orders (
            id SERIAL PRIMARY KEY,
            prenom TEXT NOT NULL,
            nom TEXT NOT NULL,
            commentaire TEXT,
            weekday INTEGER NOT NULL,
            actif BOOLEAN NOT NULL DEFAULT TRUE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recurring_order_items (
            id SERIAL PRIMARY KEY,
            recurring_order_id INTEGER NOT NULL,
            article_id INTEGER NOT NULL,
            quantite INTEGER NOT NULL,
            FOREIGN KEY (recurring_order_id) REFERENCES recurring_orders(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recurring_order_exceptions (
            id SERIAL PRIMARY KEY,
            recurring_order_id INTEGER NOT NULL,
            date_commande DATE NOT NULL,
            mode TEXT NOT NULL,
            commentaire TEXT,
            UNIQUE (recurring_order_id, date_commande),
            FOREIGN KEY (recurring_order_id) REFERENCES recurring_orders(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS recurring_order_id INTEGER")
    cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS recurring_source_date DATE")
    cursor.execute(
        """
        INSERT INTO users (username, password, role)
        SELECT %s, %s, %s
        WHERE NOT EXISTS (
            SELECT 1 FROM users WHERE username = %s
        )
        """,
        ("admin", "admin123", "articles", "admin"),
    )
    cursor.execute(
        """
        UPDATE users
        SET password = %s, role = %s
        WHERE username = %s
        """,
        ("admin123", "articles", "admin"),
    )
    conn.commit()
    cursor.close()
    conn.close()


def generate_pdf(data, selected_date):
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
        y -= 20
        pdf.setFont("Helvetica", 11)
        for nom, qty in articles:
            pdf.drawString(70, y, f"{nom} : {qty}")
            y -= 15
    pdf.save()
    return tmp_file.name


def login(username, password):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, role FROM users WHERE username = %s AND password = %s", (username, password))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    return user


def get_articles(cursor):
    cursor.execute("SELECT id, nom, categorie FROM articles WHERE actif = TRUE ORDER BY categorie, nom")
    rows = cursor.fetchall()
    result = {}
    for article_id, nom, categorie in rows:
        result.setdefault(categorie, []).append({"id": article_id, "nom": nom})
    return result


def get_all_articles(cursor):
    cursor.execute("SELECT id, nom, categorie, actif FROM articles ORDER BY categorie, nom")
    return cursor.fetchall()


def get_article_categories(cursor):
    cursor.execute("SELECT DISTINCT categorie FROM articles ORDER BY categorie")
    return [row[0] for row in cursor.fetchall()]


def article_is_referenced(cursor, article_id):
    cursor.execute("SELECT EXISTS (SELECT 1 FROM order_items WHERE article_id = %s)", (article_id,))
    in_orders = cursor.fetchone()[0]
    cursor.execute("SELECT EXISTS (SELECT 1 FROM recurring_order_items WHERE article_id = %s)", (article_id,))
    in_recurring = cursor.fetchone()[0]
    return in_orders or in_recurring


def get_daily_limit(cursor, selected_date, article_id):
    cursor.execute("SELECT quantite_max FROM daily_limits WHERE date_jour = %s AND article_id = %s", (selected_date, article_id))
    row = cursor.fetchone()
    return row[0] if row else None


def get_total_already_ordered(cursor, selected_date, article_id):
    cursor.execute(
        """
        SELECT COALESCE(SUM(oi.quantite), 0)
        FROM order_items oi JOIN orders o ON oi.order_id = o.id
        WHERE o.date_commande = %s AND oi.article_id = %s
        """,
        (selected_date, article_id),
    )
    return cursor.fetchone()[0]


def get_order_for_edit(order_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, prenom, nom, date_commande, commentaire FROM orders WHERE id = %s", (order_id,))
    order_row = cursor.fetchone()
    cursor.execute("SELECT article_id, quantite FROM order_items WHERE order_id = %s", (order_id,))
    items = {article_id: qty for article_id, qty in cursor.fetchall()}
    cursor.close()
    conn.close()
    return order_row, items


def get_recurring_order_for_edit(recurring_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, prenom, nom, commentaire, weekday, actif FROM recurring_orders WHERE id = %s",
        (recurring_id,),
    )
    recurring_row = cursor.fetchone()
    cursor.execute(
        "SELECT article_id, quantite FROM recurring_order_items WHERE recurring_order_id = %s",
        (recurring_id,),
    )
    items = {article_id: qty for article_id, qty in cursor.fetchall()}
    cursor.close()
    conn.close()
    return recurring_row, items


def delete_order(order_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM order_items WHERE order_id = %s", (order_id,))
    cursor.execute("DELETE FROM orders WHERE id = %s", (order_id,))
    conn.commit()
    cursor.close()
    conn.close()


def init_session_state():
    defaults = {
        "user": None,
        "flash_message": None,
        "page": "accueil",
        "selected_category": None,
        "order_quantities": {},
        "edit_order_id": None,
        "edit_recurring_id": None,
        "recurring_target_date": None,
        "edit_article_id": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_order_quantities(articles_dict):
    st.session_state.order_quantities = {}
    for categorie, articles in articles_dict.items():
        for article in articles:
            st.session_state.order_quantities[f"{categorie}|{article['id']}"] = 0


def ensure_order_quantities(articles_dict):
    for categorie, articles in articles_dict.items():
        for article in articles:
            st.session_state.order_quantities.setdefault(f"{categorie}|{article['id']}", 0)


def load_order_into_session(articles_dict, order_items):
    reset_order_quantities(articles_dict)
    for categorie, articles in articles_dict.items():
        for article in articles:
            st.session_state.order_quantities[f"{categorie}|{article['id']}"] = order_items.get(article["id"], 0)


def set_qty(item_key, value):
    st.session_state.order_quantities[item_key] = max(int(value), 0)


def go_to_page(page_name):
    st.session_state.page = page_name
    st.rerun()


def logout():
    st.session_state.user = None
    st.session_state.page = "accueil"
    st.session_state.selected_category = None
    st.session_state.order_quantities = {}
    st.session_state.edit_order_id = None
    st.rerun()


def show_logo(width=260):
    left, center, right = st.columns([1, 2, 1])
    with center:
        if LOGO_PATH.exists():
            st.image(str(LOGO_PATH), width=width)


def render_order_summary(articles_dict, categories, message):
    st.markdown('<div class="summary-card">', unsafe_allow_html=True)
    st.markdown('<div class="summary-title">Résumé de la commande</div>', unsafe_allow_html=True)
    total = 0
    for categorie in categories:
        lines = []
        for article in articles_dict[categorie]:
            qty = st.session_state.order_quantities.get(f"{categorie}|{article['id']}", 0)
            if qty > 0:
                lines.append((article["nom"], qty))
                total += qty
        if lines:
            st.write(f"**{categorie}**")
            for article_name, qty in lines:
                st.write(f"{article_name} : {qty}")
    if total == 0:
        st.info(message)
    st.write(f"**Total pièces : {total}**")
    st.markdown("</div>", unsafe_allow_html=True)


def render_quantity_control(prefix, article_id, article_name, item_key, qty, base_qty, daily_limit):
    input_key = f"{prefix}_qty_{article_id}"
    if input_key not in st.session_state or st.session_state[input_key] != str(qty):
        st.session_state[input_key] = str(qty)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c1:
        if st.button("-", key=f"{prefix}_minus_{article_id}", use_container_width=True):
            set_qty(item_key, max(qty - 1, 0))
            st.rerun()
    with c2:
        raw = st.text_input("Quantité", key=input_key, label_visibility="collapsed")
        try:
            new_value = max(int(raw), 0)
        except ValueError:
            new_value = qty
        if raw != str(qty):
            if daily_limit is not None and base_qty + new_value > daily_limit:
                st.warning(f"Limite atteinte pour {article_name}.")
            else:
                set_qty(item_key, new_value)
                st.rerun()
    with c3:
        if st.button("+", key=f"{prefix}_plus_{article_id}", use_container_width=True):
            if daily_limit is not None and base_qty + qty + 1 > daily_limit:
                st.warning(f"Limite atteinte pour {article_name}.")
            else:
                set_qty(item_key, qty + 1)
                st.rerun()


def get_recurring_orders_for_date(selected_date):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT ro.id, ro.prenom, ro.nom, COALESCE(roe.mode, 'normal'), COALESCE(roe.commentaire, ro.commentaire, '')
        FROM recurring_orders ro
        LEFT JOIN recurring_order_exceptions roe ON roe.recurring_order_id = ro.id AND roe.date_commande = %s
        WHERE ro.actif = TRUE AND ro.weekday = %s
        ORDER BY ro.nom, ro.prenom
        """,
        (selected_date, selected_date.weekday()),
    )
    result = []
    for recurring_id, prenom, nom, mode, commentaire in cursor.fetchall():
        if mode in ["skip", "deleted", "custom"]:
            continue
        cursor.execute(
            """
            SELECT roi.article_id, a.nom, a.categorie, roi.quantite
            FROM recurring_order_items roi
            JOIN articles a ON a.id = roi.article_id
            WHERE roi.recurring_order_id = %s
            ORDER BY a.categorie, a.nom
            """,
            (recurring_id,),
        )
        result.append({"id": recurring_id, "prenom": prenom, "nom": nom, "commentaire": commentaire, "items": cursor.fetchall()})
    cursor.close()
    conn.close()
    return result


def materialize_recurring_orders(selected_date, user_id):
    conn = get_connection()
    cursor = conn.cursor()
    created = 0
    for recurring in get_recurring_orders_for_date(selected_date):
        cursor.execute("SELECT id FROM orders WHERE recurring_order_id = %s AND recurring_source_date = %s", (recurring["id"], selected_date))
        if cursor.fetchone():
            continue
        cursor.execute(
            """
            INSERT INTO orders (prenom, nom, date_commande, commentaire, created_by_user_id, recurring_order_id, recurring_source_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (recurring["prenom"], recurring["nom"], selected_date, recurring["commentaire"], user_id, recurring["id"], selected_date),
        )
        order_id = cursor.fetchone()[0]
        for article_id, article_name, categorie, qty in recurring["items"]:
            cursor.execute("INSERT INTO order_items (order_id, article_id, article_nom_snapshot, categorie_snapshot, quantite) VALUES (%s, %s, %s, %s, %s)", (order_id, article_id, article_name, categorie, qty))
        created += 1
    conn.commit()
    cursor.close()
    conn.close()
    return created


def ensure_recurring_orders_materialized(selected_date):
    if st.session_state.user is None:
        return 0
    return materialize_recurring_orders(selected_date, st.session_state.user["id"])


def ensure_week_override_order(recurring_id, selected_date, user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM orders WHERE recurring_order_id = %s AND recurring_source_date = %s",
        (recurring_id, selected_date),
    )
    existing = cursor.fetchone()
    if existing:
        order_id = existing[0]
    else:
        cursor.execute(
            """
            SELECT ro.prenom, ro.nom, COALESCE(ro.commentaire, '')
            FROM recurring_orders ro
            WHERE ro.id = %s
            """,
            (recurring_id,),
        )
        prenom, nom, commentaire = cursor.fetchone()
        cursor.execute(
            """
            INSERT INTO orders (prenom, nom, date_commande, commentaire, created_by_user_id, recurring_order_id, recurring_source_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (prenom, nom, selected_date, commentaire, user_id, recurring_id, selected_date),
        )
        order_id = cursor.fetchone()[0]
        cursor.execute(
            """
            SELECT roi.article_id, a.nom, a.categorie, roi.quantite
            FROM recurring_order_items roi
            JOIN articles a ON a.id = roi.article_id
            WHERE roi.recurring_order_id = %s
            """,
            (recurring_id,),
        )
        for article_id, article_name, categorie, qty in cursor.fetchall():
            cursor.execute(
                """
                INSERT INTO order_items (order_id, article_id, article_nom_snapshot, categorie_snapshot, quantite)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (order_id, article_id, article_name, categorie, qty),
            )

    cursor.execute(
        """
        INSERT INTO recurring_order_exceptions (recurring_order_id, date_commande, mode, commentaire)
        VALUES (%s, %s, 'custom', NULL)
        ON CONFLICT (recurring_order_id, date_commande)
        DO UPDATE SET mode = EXCLUDED.mode
        """,
        (recurring_id, selected_date),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return order_id


def show_sidebar(role):
    st.sidebar.markdown(f"**Connecté en :** {role}")
    if role == "atelier":
        pages = [("totaux", "Totaux")]
    elif role == "articles":
        pages = [("liste_articles", "Liste d'articles")]
    else:
        pages = [
            ("accueil", "Accueil"),
            ("nouvelle_commande", "Nouvelle commande"),
            ("voir_commandes", "Voir les commandes"),
            ("recurrences", "Commandes récurrentes"),
            ("totaux", "Totaux"),
            ("limites", "Limites de commandes"),
        ]
    for page_name, label in pages:
        if st.sidebar.button(label, use_container_width=True, key=f"nav_{page_name}"):
            go_to_page(page_name)
    if st.sidebar.button("Se déconnecter", use_container_width=True):
        logout()


def show_home(role):
    show_logo(320)
    st.markdown('<div class="hero-card"><div class="summary-title">Accueil</div>Choisissez la page à ouvrir.</div>', unsafe_allow_html=True)
    pages = [("nouvelle_commande", "Nouvelle commande"), ("voir_commandes", "Voir les commandes"), ("recurrences", "Commandes récurrentes"), ("totaux", "Totaux"), ("limites", "Limites de commandes")]
    cols = st.columns(len(pages))
    for col, (page_name, label) in zip(cols, pages):
        with col:
            if st.button(label, use_container_width=True):
                go_to_page(page_name)
    if role != "magasin":
        st.info("Le rôle atelier n'a accès qu'aux totaux.")


def show_articles_page():
    st.title("Liste d'articles")
    conn = get_connection()
    cursor = conn.cursor()
    categories = get_article_categories(cursor)

    with st.expander("Ajouter un article", expanded=True):
        nom = st.text_input("Nom de l'article", key="new_article_name")
        if categories:
            categorie = st.selectbox("Catégorie", options=categories, key="new_article_category")
        else:
            categorie = st.text_input("Catégorie", key="new_article_category")
        if st.button("Ajouter l'article", use_container_width=True):
            if not nom.strip() or not categorie.strip():
                st.error("Le nom et la catégorie sont obligatoires.")
            else:
                cursor.execute(
                    "SELECT COUNT(*) FROM articles WHERE LOWER(nom) = LOWER(%s) AND LOWER(categorie) = LOWER(%s)",
                    (nom.strip(), categorie.strip()),
                )
                if cursor.fetchone()[0] > 0:
                    st.error("Cet article existe déjà dans cette catégorie.")
                else:
                    cursor.execute(
                        """
                        INSERT INTO articles (nom, categorie, actif)
                        VALUES (%s, %s, TRUE)
                        """,
                        (nom.strip(), categorie.strip()),
                    )
                    conn.commit()
                    st.success("Article ajouté.")
                    st.rerun()

    st.subheader("Articles existants")
    rows = get_all_articles(cursor)
    if not rows:
        st.info("Aucun article enregistré.")
    else:
        current_category = None
        for article_id, nom, categorie, actif in rows:
            if categorie != current_category:
                if current_category is not None:
                    st.markdown("</div>", unsafe_allow_html=True)
                st.markdown(f'<div class="block-card"><div class="summary-title">{categorie}</div>', unsafe_allow_html=True)
                current_category = categorie
            c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
            with c1:
                st.write(f"{nom}")
            with c2:
                st.write("Actif" if actif else "Inactif")
            with c3:
                label = "Désactiver" if actif else "Réactiver"
                if st.button(label, key=f"toggle_article_{article_id}", use_container_width=True):
                    cursor.execute("UPDATE articles SET actif = %s WHERE id = %s", (not actif, article_id))
                    conn.commit()
                    st.rerun()
            with c4:
                if st.button("Modifier", key=f"edit_article_{article_id}", use_container_width=True):
                    st.session_state.edit_article_id = article_id
                    st.rerun()
            if st.button("Supprimer définitivement", key=f"delete_article_{article_id}", use_container_width=True):
                if article_is_referenced(cursor, article_id):
                    cursor.execute("UPDATE articles SET actif = FALSE WHERE id = %s", (article_id,))
                    conn.commit()
                    st.warning("Cet article était déjà utilisé dans des commandes. Il a été désactivé au lieu d'être supprimé.")
                    st.rerun()
                else:
                    cursor.execute("DELETE FROM daily_limits WHERE article_id = %s", (article_id,))
                    cursor.execute("DELETE FROM articles WHERE id = %s", (article_id,))
                    conn.commit()
                    st.success("Article supprimé.")
                    st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

        edit_article_id = st.session_state.get("edit_article_id")
        if edit_article_id is not None:
            st.subheader("Modifier un article")
            cursor.execute("SELECT nom, categorie, actif FROM articles WHERE id = %s", (edit_article_id,))
            article_row = cursor.fetchone()
            if article_row:
                edit_nom, edit_categorie, edit_actif = article_row
                edit_col1, edit_col2 = st.columns(2)
                with edit_col1:
                    new_nom = st.text_input("Nom", value=edit_nom, key="edit_article_name")
                with edit_col2:
                    category_options = categories if categories else [edit_categorie]
                    if edit_categorie not in category_options:
                        category_options = category_options + [edit_categorie]
                    new_categorie = st.selectbox(
                        "Catégorie",
                        options=category_options,
                        index=category_options.index(edit_categorie),
                        key="edit_article_category",
                    )
                active_value = st.checkbox("Article actif", value=edit_actif, key="edit_article_active")
                save_col, cancel_col = st.columns(2)
                with save_col:
                    if st.button("Enregistrer la modification", use_container_width=True):
                        if not new_nom.strip() or not new_categorie.strip():
                            st.error("Le nom et la catégorie sont obligatoires.")
                        else:
                            cursor.execute(
                                """
                                SELECT COUNT(*)
                                FROM articles
                                WHERE LOWER(nom) = LOWER(%s)
                                  AND LOWER(categorie) = LOWER(%s)
                                  AND id <> %s
                                """,
                                (new_nom.strip(), new_categorie.strip(), edit_article_id),
                            )
                            if cursor.fetchone()[0] > 0:
                                st.error("Un article avec ce nom existe déjà dans cette catégorie.")
                            else:
                                cursor.execute(
                                    """
                                    UPDATE articles
                                    SET nom = %s, categorie = %s, actif = %s
                                    WHERE id = %s
                                    """,
                                    (new_nom.strip(), new_categorie.strip(), active_value, edit_article_id),
                                )
                                conn.commit()
                                st.session_state.edit_article_id = None
                                st.success("Article modifié.")
                                st.rerun()
                with cancel_col:
                    if st.button("Annuler", use_container_width=True):
                        st.session_state.edit_article_id = None
                        st.rerun()

    cursor.close()
    conn.close()


def save_order(cursor, prenom, nom, date_commande, commentaire, user_id, items_to_save):
    cursor.execute("INSERT INTO orders (prenom, nom, date_commande, commentaire, created_by_user_id) VALUES (%s, %s, %s, %s, %s) RETURNING id", (prenom, nom, date_commande, commentaire, user_id))
    order_id = cursor.fetchone()[0]
    for article_id, article_name, categorie, qty in items_to_save:
        cursor.execute("INSERT INTO order_items (order_id, article_id, article_nom_snapshot, categorie_snapshot, quantite) VALUES (%s, %s, %s, %s, %s)", (order_id, article_id, article_name, categorie, qty))


def show_order_editor(mode="new"):
    is_edit = mode == "edit"
    st.title("Modifier la commande" if is_edit else "Nouvelle commande")
    conn = get_connection()
    cursor = conn.cursor()
    articles_dict = get_articles(cursor)
    categories = list(articles_dict.keys())
    if not categories:
        st.warning("Aucun article actif n'est disponible.")
        cursor.close()
        conn.close()
        return
    ensure_order_quantities(articles_dict)
    if st.session_state.selected_category not in categories:
        st.session_state.selected_category = categories[0]

    order_id = st.session_state.edit_order_id if is_edit else None
    order_items = {}
    if is_edit:
        order_row, order_items = get_order_for_edit(order_id)
        if not order_row:
            st.error("Commande introuvable.")
            cursor.close()
            conn.close()
            return
        load_key = f"edit_loaded_{order_id}"
        if not st.session_state.get(load_key):
            load_order_into_session(articles_dict, order_items)
            st.session_state[load_key] = True
        _, prenom_default, nom_default, date_default, commentaire_default = order_row
    else:
        prenom_default, nom_default, date_default, commentaire_default = "", "", date.today(), ""

    t1, t2 = st.columns(2)
    with t1:
        if st.button("Retour", use_container_width=True):
            if is_edit:
                st.session_state.edit_order_id = None
                st.session_state.pop(f"edit_loaded_{order_id}", None)
                go_to_page("voir_commandes")
            go_to_page("accueil")

    c1, c2 = st.columns(2)
    with c1:
        prenom = st.text_input("Prénom", value=prenom_default, key=f"{mode}_prenom")
    with c2:
        nom = st.text_input("Nom", value=nom_default, key=f"{mode}_nom")
    date_commande = st.date_input("Date de la commande", value=date_default, key=f"{mode}_date")
    commentaire = st.text_area("Commentaire", value=commentaire_default or "", key=f"{mode}_commentaire")
    if not is_edit:
        ensure_recurring_orders_materialized(date_commande)

    cat_cols = st.columns(min(len(categories), 5))
    for index, categorie in enumerate(categories):
        with cat_cols[index % len(cat_cols)]:
            if st.button(categorie, key=f"{mode}_cat_{categorie}", use_container_width=True):
                st.session_state.selected_category = categorie
                st.rerun()

    left, right = st.columns([3, 1])
    with left:
        active_category = st.session_state.selected_category
        st.subheader(active_category)
        display_cols = st.columns(3)
        for index, article in enumerate(articles_dict[active_category]):
            article_id = article["id"]
            article_name = article["nom"]
            item_key = f"{active_category}|{article_id}"
            qty = st.session_state.order_quantities.get(item_key, 0)
            daily_limit = get_daily_limit(cursor, date_commande, article_id)
            base_qty = get_total_already_ordered(cursor, date_commande, article_id)
            if is_edit:
                base_qty = max(base_qty - order_items.get(article_id, 0), 0)
            with display_cols[index % len(display_cols)]:
                st.markdown(f'<div class="article-card"><div class="article-title">{article_name}</div>', unsafe_allow_html=True)
                st.caption(f"Base : {base_qty}" if daily_limit is None else f"Base : {base_qty} / Limite : {daily_limit}")
                render_quantity_control(mode, article_id, article_name, item_key, qty, base_qty, daily_limit)
                st.markdown("</div>", unsafe_allow_html=True)
    with right:
        render_order_summary(articles_dict, categories, "Aucun article sélectionné pour le moment.")

    if st.button("Enregistrer les modifications" if is_edit else "Enregistrer la commande", use_container_width=True):
        errors = []
        items_to_save = []
        if not prenom.strip():
            errors.append("Le prénom est obligatoire.")
        if not nom.strip():
            errors.append("Le nom est obligatoire.")
        for categorie, articles in articles_dict.items():
            for article in articles:
                article_id = article["id"]
                qty = st.session_state.order_quantities.get(f"{categorie}|{article_id}", 0)
                if qty > 0:
                    base_qty = get_total_already_ordered(cursor, date_commande, article_id)
                    if is_edit:
                        base_qty = max(base_qty - order_items.get(article_id, 0), 0)
                    daily_limit = get_daily_limit(cursor, date_commande, article_id)
                    if daily_limit is not None and base_qty + qty > daily_limit:
                        errors.append(f"{article['nom']} dépasse la limite.")
                    else:
                        items_to_save.append((article_id, article["nom"], categorie, qty))
        if not items_to_save:
            errors.append("La commande ne contient aucun article.")
        if errors:
            for error in errors:
                st.error(error)
        else:
            if is_edit:
                cursor.execute("UPDATE orders SET prenom=%s, nom=%s, date_commande=%s, commentaire=%s WHERE id=%s", (prenom.strip(), nom.strip(), date_commande, commentaire.strip(), order_id))
                cursor.execute("DELETE FROM order_items WHERE order_id = %s", (order_id,))
                for article_id, article_name, categorie, qty in items_to_save:
                    cursor.execute("INSERT INTO order_items (order_id, article_id, article_nom_snapshot, categorie_snapshot, quantite) VALUES (%s, %s, %s, %s, %s)", (order_id, article_id, article_name, categorie, qty))
                st.session_state.flash_message = "Commande modifiée avec succès."
                st.session_state.edit_order_id = None
                st.session_state.pop(f"edit_loaded_{order_id}", None)
            else:
                save_order(cursor, prenom.strip(), nom.strip(), date_commande, commentaire.strip(), st.session_state.user["id"], items_to_save)
                st.session_state.flash_message = "Commande enregistrée avec succès."
            conn.commit()
            reset_order_quantities(articles_dict)
            st.session_state.selected_category = categories[0]
            cursor.close()
            conn.close()
            go_to_page("voir_commandes" if is_edit else "nouvelle_commande")
    cursor.close()
    conn.close()


def show_orders_page():
    st.title("Voir les commandes")
    if st.button("Retour à l'accueil"):
        go_to_page("accueil")
    conn = get_connection()
    cursor = conn.cursor()
    filter_col1, filter_col2 = st.columns([2, 1])
    with filter_col1:
        selected_date = st.date_input("Afficher les commandes du", value=date.today(), key="orders_filter_date")
    with filter_col2:
        show_all = st.checkbox("Tout afficher", value=False, key="orders_show_all")
    if not show_all:
        ensure_recurring_orders_materialized(selected_date)

    if show_all:
        cursor.execute(
            "SELECT id, prenom, nom, date_commande, commentaire FROM orders ORDER BY date_commande DESC, id DESC"
        )
    else:
        cursor.execute(
            """
            SELECT id, prenom, nom, date_commande, commentaire
            FROM orders
            WHERE date_commande = %s
            ORDER BY id DESC
            """,
            (selected_date,),
        )
    rows = cursor.fetchall()
    if not rows:
        if show_all:
            st.info("Aucune commande enregistrée.")
        else:
            st.info(f"Aucune commande enregistrée pour le {selected_date}.")
        cursor.close()
        conn.close()
        return
    for order_id, prenom, nom, date_commande, commentaire in rows:
        with st.expander(f"Commande #{order_id} - {prenom} {nom} - {date_commande}"):
            b1, b2, b3 = st.columns([1, 1, 3])
            with b1:
                if st.button("Modifier", key=f"edit_{order_id}", use_container_width=True):
                    st.session_state.edit_order_id = order_id
                    go_to_page("modifier_commande")
            with b2:
                if st.button("Supprimer", key=f"delete_{order_id}", use_container_width=True):
                    cursor.close()
                    conn.close()
                    delete_order(order_id)
                    st.session_state.flash_message = "Commande supprimée."
                    st.rerun()
            with b3:
                st.write(f"**Commentaire :** {commentaire or '-'}")
            cursor.execute("SELECT categorie_snapshot, article_nom_snapshot, quantite FROM order_items WHERE order_id = %s ORDER BY categorie_snapshot, article_nom_snapshot", (order_id,))
            for categorie, article_name, qty in cursor.fetchall():
                st.write(f"{categorie} - {article_name} : {qty}")
    cursor.close()
    conn.close()


def show_recurrences_page():
    st.title("Commandes récurrentes")
    conn = get_connection()
    cursor = conn.cursor()
    articles_dict = get_articles(cursor)
    categories = list(articles_dict.keys())
    weekdays = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    with st.expander("Nouvelle commande récurrente"):
        prenom = st.text_input("Prénom", key="rec_prenom")
        nom = st.text_input("Nom", key="rec_nom")
        commentaire = st.text_area("Commentaire", key="rec_commentaire")
        weekday = st.selectbox("Jour", options=list(range(7)), format_func=lambda x: weekdays[x], key="rec_weekday")
        recurring_qty = {}
        for categorie in categories:
            st.write(f"**{categorie}**")
            for article in articles_dict[categorie]:
                recurring_qty[article["id"]] = st.number_input(article["nom"], min_value=0, value=0, step=1, key=f"rec_qty_{article['id']}")
        if st.button("Créer la récurrence", use_container_width=True):
            cursor.execute("INSERT INTO recurring_orders (prenom, nom, commentaire, weekday, actif) VALUES (%s, %s, %s, %s, TRUE) RETURNING id", (prenom.strip(), nom.strip(), commentaire.strip(), weekday))
            recurring_id = cursor.fetchone()[0]
            for categorie in categories:
                for article in articles_dict[categorie]:
                    qty = recurring_qty[article["id"]]
                    if qty > 0:
                        cursor.execute("INSERT INTO recurring_order_items (recurring_order_id, article_id, quantite) VALUES (%s, %s, %s)", (recurring_id, article["id"], qty))
            conn.commit()
            st.success("Commande récurrente créée.")
            st.rerun()

    selected_date = st.date_input("Date concernée", value=date.today(), key="rec_selected_date")
    cursor.execute("SELECT id, prenom, nom, commentaire, weekday FROM recurring_orders WHERE actif = TRUE ORDER BY nom, prenom")
    for recurring_id, prenom, nom, commentaire, weekday in cursor.fetchall():
        with st.expander(f"{prenom} {nom} - {weekdays[weekday]}"):
            cursor.execute(
                """
                SELECT a.categorie, a.nom, roi.quantite
                FROM recurring_order_items roi JOIN articles a ON a.id = roi.article_id
                WHERE roi.recurring_order_id = %s
                ORDER BY a.categorie, a.nom
                """,
                (recurring_id,),
            )
            for categorie, article_name, qty in cursor.fetchall():
                st.write(f"{categorie} - {article_name} : {qty}")
            st.write(f"Commentaire : {commentaire or '-'}")
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                if st.button("Ignorer cette semaine", key=f"skip_{recurring_id}", use_container_width=True):
                    cursor.execute(
                        """
                        INSERT INTO recurring_order_exceptions (recurring_order_id, date_commande, mode, commentaire)
                        VALUES (%s, %s, 'skip', NULL)
                        ON CONFLICT (recurring_order_id, date_commande)
                        DO UPDATE SET mode = EXCLUDED.mode
                        """,
                        (recurring_id, selected_date),
                    )
                    conn.commit()
                    st.rerun()
            with c2:
                if st.button("Modifier cette semaine", key=f"one_week_{recurring_id}", use_container_width=True):
                    order_id = ensure_week_override_order(recurring_id, selected_date, st.session_state.user["id"])
                    st.session_state.edit_order_id = order_id
                    st.session_state.recurring_target_date = selected_date
                    go_to_page("modifier_commande")
            with c3:
                if st.button("Modifier pour toujours", key=f"edit_forever_{recurring_id}", use_container_width=True):
                    st.session_state.edit_recurring_id = recurring_id
                    go_to_page("modifier_recurrence")
            with c4:
                if st.button("Supprimer pour toujours", key=f"forever_{recurring_id}", use_container_width=True):
                    cursor.execute("UPDATE recurring_orders SET actif = FALSE WHERE id = %s", (recurring_id,))
                    conn.commit()
                    st.rerun()
    cursor.close()
    conn.close()


def show_edit_recurrence_page():
    st.title("Modifier la commande récurrente")

    recurring_id = st.session_state.edit_recurring_id
    if recurring_id is None:
        st.error("Aucune commande récurrente sélectionnée.")
        return

    conn = get_connection()
    cursor = conn.cursor()
    articles_dict = get_articles(cursor)
    categories = list(articles_dict.keys())
    recurring_row, recurring_items = get_recurring_order_for_edit(recurring_id)

    if not recurring_row:
        cursor.close()
        conn.close()
        st.session_state.edit_recurring_id = None
        st.error("Commande récurrente introuvable.")
        return

    load_key = f"recurring_loaded_{recurring_id}"
    if not st.session_state.get(load_key):
        load_order_into_session(articles_dict, recurring_items)
        st.session_state[load_key] = True

    _, prenom_default, nom_default, commentaire_default, weekday_default, _ = recurring_row
    weekdays = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

    top1, top2 = st.columns(2)
    with top1:
        if st.button("Retour aux récurrences", use_container_width=True):
            st.session_state.edit_recurring_id = None
            st.session_state.pop(load_key, None)
            go_to_page("recurrences")
    with top2:
        if st.button("Recharger le modèle", use_container_width=True):
            load_order_into_session(articles_dict, recurring_items)
            st.rerun()

    c1, c2 = st.columns(2)
    with c1:
        prenom = st.text_input("Prénom", value=prenom_default, key=f"rec_edit_prenom_{recurring_id}")
    with c2:
        nom = st.text_input("Nom", value=nom_default, key=f"rec_edit_nom_{recurring_id}")
    commentaire = st.text_area("Commentaire", value=commentaire_default or "", key=f"rec_edit_commentaire_{recurring_id}")
    weekday = st.selectbox("Jour récurrent", options=list(range(7)), index=weekday_default, format_func=lambda x: weekdays[x], key=f"rec_edit_weekday_{recurring_id}")

    if st.session_state.selected_category not in categories:
        st.session_state.selected_category = categories[0]

    cat_cols = st.columns(min(len(categories), 5))
    for index, categorie in enumerate(categories):
        with cat_cols[index % len(cat_cols)]:
            if st.button(categorie, key=f"rec_edit_cat_{categorie}", use_container_width=True):
                st.session_state.selected_category = categorie
                st.rerun()

    left, right = st.columns([3, 1])
    with left:
        active_category = st.session_state.selected_category
        st.subheader(active_category)
        display_cols = st.columns(3)
        for index, article in enumerate(articles_dict[active_category]):
            article_id = article["id"]
            article_name = article["nom"]
            item_key = f"{active_category}|{article_id}"
            qty = st.session_state.order_quantities.get(item_key, 0)
            with display_cols[index % len(display_cols)]:
                st.markdown(f'<div class="article-card"><div class="article-title">{article_name}</div>', unsafe_allow_html=True)
                render_quantity_control("rec_edit", article_id, article_name, item_key, qty, 0, None)
                st.markdown("</div>", unsafe_allow_html=True)
    with right:
        render_order_summary(articles_dict, categories, "Aucun article sélectionné pour cette récurrence.")

    if st.button("Enregistrer la récurrence", use_container_width=True):
        items_to_save = []
        for categorie, articles in articles_dict.items():
            for article in articles:
                qty = st.session_state.order_quantities.get(f"{categorie}|{article['id']}", 0)
                if qty > 0:
                    items_to_save.append((article["id"], qty))

        if not prenom.strip() or not nom.strip():
            st.error("Le prénom et le nom sont obligatoires.")
        elif not items_to_save:
            st.error("La récurrence ne contient aucun article.")
        else:
            cursor.execute(
                """
                UPDATE recurring_orders
                SET prenom = %s, nom = %s, commentaire = %s, weekday = %s
                WHERE id = %s
                """,
                (prenom.strip(), nom.strip(), commentaire.strip(), weekday, recurring_id),
            )
            cursor.execute("DELETE FROM recurring_order_items WHERE recurring_order_id = %s", (recurring_id,))
            for article_id, qty in items_to_save:
                cursor.execute(
                    "INSERT INTO recurring_order_items (recurring_order_id, article_id, quantite) VALUES (%s, %s, %s)",
                    (recurring_id, article_id, qty),
                )
            conn.commit()
            st.session_state.flash_message = "Commande récurrente modifiée avec succès."
            st.session_state.edit_recurring_id = None
            st.session_state.pop(load_key, None)
            cursor.close()
            conn.close()
            go_to_page("recurrences")

    cursor.close()
    conn.close()


def show_totals_page():
    st.title("Totaux")
    conn = get_connection()
    cursor = conn.cursor()
    selected_date = st.date_input("Choisir une date", value=date.today(), key="totaux_date")
    ensure_recurring_orders_materialized(selected_date)
    cursor.execute(
        """
        SELECT categorie_snapshot, article_nom_snapshot, SUM(quantite)
        FROM order_items oi JOIN orders o ON oi.order_id = o.id
        WHERE o.date_commande = %s
        GROUP BY categorie_snapshot, article_nom_snapshot
        ORDER BY categorie_snapshot, article_nom_snapshot
        """,
        (selected_date,),
    )
    rows = cursor.fetchall()
    if not rows:
        st.info("Aucune commande pour cette date.")
        cursor.close()
        conn.close()
        return
    data = {}
    total_general = 0
    for categorie, article_name, qty in rows:
        data.setdefault(categorie, []).append((article_name, qty))
        total_general += qty
    st.write(f"**Total général : {total_general}**")
    for categorie, articles in data.items():
        st.markdown(f'<div class="block-card"><div class="summary-title">{categorie}</div>', unsafe_allow_html=True)
        for article_name, qty in articles:
            st.write(f"{article_name} : {qty}")
        st.markdown("</div>", unsafe_allow_html=True)
    if st.button("Générer le PDF"):
        pdf_path = generate_pdf(data, selected_date)
        with open(pdf_path, "rb") as pdf_file:
            st.download_button("Télécharger le PDF", pdf_file, file_name=f"production_{selected_date}.pdf", mime="application/pdf")
    cursor.close()
    conn.close()


def show_limits_page():
    st.title("Limites de commandes")
    conn = get_connection()
    cursor = conn.cursor()
    articles_dict = get_articles(cursor)
    selected_date = st.date_input("Date des limites", value=date.today(), key="limits_date")
    values = {}
    for categorie, articles in articles_dict.items():
        st.markdown(f'<div class="block-card"><div class="summary-title">{categorie}</div>', unsafe_allow_html=True)
        for article in articles:
            values[article["id"]] = st.number_input(article["nom"], min_value=0, value=get_daily_limit(cursor, selected_date, article["id"]) or 0, step=1, key=f"limit_{article['id']}")
        st.markdown("</div>", unsafe_allow_html=True)
    if st.button("Enregistrer les limites", use_container_width=True):
        for article_id, value in values.items():
            cursor.execute("DELETE FROM daily_limits WHERE date_jour = %s AND article_id = %s", (selected_date, article_id))
            if value > 0:
                cursor.execute("INSERT INTO daily_limits (date_jour, article_id, quantite_max) VALUES (%s, %s, %s)", (selected_date, article_id, value))
        conn.commit()
        st.success("Limites enregistrées.")
    cursor.close()
    conn.close()


def show_login_page():
    show_logo(300)
    st.title("Connexion")
    username = st.text_input("Utilisateur")
    password = st.text_input("Mot de passe", type="password")
    if st.button("Se connecter"):
        user = login(username, password)
        if user:
            st.session_state.user = {"id": user[0], "role": user[1]}
            if user[1] == "atelier":
                st.session_state.page = "totaux"
            elif user[1] == "articles":
                st.session_state.page = "liste_articles"
            else:
                st.session_state.page = "accueil"
            st.rerun()
        st.error("Identifiants incorrects.")


ensure_schema()
init_session_state()

if st.session_state.user is None:
    show_login_page()
else:
    role = st.session_state.user["role"]
    if role not in ["magasin", "atelier", "articles"]:
        st.error("Rôle non autorisé.")
        st.stop()
    if st.session_state.flash_message:
        st.success(st.session_state.flash_message)
        st.session_state.flash_message = None
    if role == "atelier" and st.session_state.page != "totaux":
        st.session_state.page = "totaux"
        st.rerun()
    if role == "articles" and st.session_state.page != "liste_articles":
        st.session_state.page = "liste_articles"
        st.rerun()
    show_sidebar(role)
    if st.session_state.page == "accueil":
        show_home(role)
    elif st.session_state.page == "nouvelle_commande" and role == "magasin":
        show_order_editor("new")
    elif st.session_state.page == "voir_commandes" and role == "magasin":
        show_orders_page()
    elif st.session_state.page == "modifier_commande" and role == "magasin":
        show_order_editor("edit")
    elif st.session_state.page == "recurrences" and role == "magasin":
        show_recurrences_page()
    elif st.session_state.page == "modifier_recurrence" and role == "magasin":
        show_edit_recurrence_page()
    elif st.session_state.page == "totaux":
        show_totals_page()
    elif st.session_state.page == "limites" and role == "magasin":
        show_limits_page()
    elif st.session_state.page == "liste_articles" and role == "articles":
        show_articles_page()
    else:
        st.error("Accès refusé.")
