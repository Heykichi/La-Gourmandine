import sqlite3
from datetime import date
import streamlit as st
import psycopg2

def get_connection():
    return psycopg2.connect(
        host=st.secrets["DB_HOST"],
        dbname=st.secrets["DB_NAME"],
        user=st.secrets["DB_USER"],
        password=st.secrets["DB_PASSWORD"],
        port=st.secrets["DB_PORT"],
        sslmode=st.secrets["DB_SSLMODE"],
    )

# 🔽 TEST TEMPORAIRE
st.set_page_config(page_title="Commandes Boulangerie", layout="wide")

st.write("Test connexion DB")

try:
    conn = get_connection()
    st.success("Connexion à Supabase réussie ✅")

    cur = conn.cursor()
    cur.execute("SELECT 1;")
    st.write(cur.fetchone())

    cur.close()
    conn.close()

except Exception as e:
    st.error("Erreur DB ❌")
    st.write(e)

st.markdown("""
<style>
.article-card {
    border: 1px solid #d9d9d9;
    border-radius: 18px;
    padding: 18px;
    margin-bottom: 16px;
    background: #fafafa;
    min-height: 220px;
}

.article-title {
    font-size: 24px;
    font-weight: 700;
    margin-bottom: 10px;
}

.article-help {
    font-size: 13px;
    color: #666;
    min-height: 40px;
}

.article-qty {
    text-align: center;
    font-size: 30px;
    font-weight: 700;
    margin: 12px 0;
}

.block-title {
    font-size: 20px;
    font-weight: 700;
    margin-top: 10px;
    margin-bottom: 8px;
}

.summary-box {
    border: 1px solid #ddd;
    border-radius: 16px;
    padding: 16px;
    background: #fcfcfc;
}
</style>
""", unsafe_allow_html=True)

# =========================================================
# BASE DE DONNÉES
# =========================================================
conn = sqlite3.connect("boulangerie.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prenom TEXT NOT NULL,
    nom TEXT NOT NULL,
    date_commande TEXT NOT NULL,
    commentaire TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    article_nom TEXT NOT NULL,
    categorie TEXT NOT NULL,
    quantite INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (order_id) REFERENCES orders (id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS daily_limits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date_jour TEXT NOT NULL,
    article_nom TEXT NOT NULL,
    categorie TEXT NOT NULL,
    quantite_max INTEGER NOT NULL,
    UNIQUE(date_jour, article_nom, categorie)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL,
    categorie TEXT NOT NULL
)
""")

conn.commit()

# Nettoyage des doublons anciens si présents
cursor.execute("""
DELETE FROM articles
WHERE id NOT IN (
    SELECT MIN(id)
    FROM articles
    GROUP BY nom, categorie
)
""")
conn.commit()


# =========================================================
# DONNÉES / FONCTIONS
# =========================================================
CATEGORIES = [
    "Viennoiseries",
    "Pistolets",
    "Pains",
    "Baguettes",
    "Frigo",
    "Tartes",
    "Gâteaux"
]


def seed_default_articles_if_empty():
    cursor.execute("SELECT COUNT(*) FROM articles")
    count = cursor.fetchone()[0]

    if count == 0:
        default_articles = [
            ("Croissant", "Viennoiseries"),
            ("Pain au chocolat", "Viennoiseries"),
            ("Couque raisin", "Viennoiseries"),
            ("Pistolet blanc", "Pistolets"),
            ("Pistolet gris", "Pistolets"),
            ("Pain blanc", "Pains"),
            ("Pain gris", "Pains"),
            ("Baguette blanche", "Baguettes"),
            ("Baguette grise", "Baguettes"),
            ("Sandwich club", "Frigo"),
            ("Tarte al djote", "Frigo"),
            ("Tarte pommes", "Tartes"),
            ("Tarte fraises", "Tartes"),
            ("Éclair chocolat", "Gâteaux"),
            ("Mille-feuille", "Gâteaux"),
        ]

        cursor.executemany("""
            INSERT INTO articles (nom, categorie)
            VALUES (?, ?)
        """, default_articles)
        conn.commit()


def get_articles():
    cursor.execute("""
        SELECT id, categorie, nom
        FROM articles
        ORDER BY categorie, nom
    """)
    rows = cursor.fetchall()

    result = {}
    for article_id, categorie, nom in rows:
        result.setdefault(categorie, []).append({
            "id": article_id,
            "nom": nom
        })

    return result


def get_total_deja_commande(date_commande, categorie, article_nom, exclude_order_id=None):
    if exclude_order_id is None:
        cursor.execute("""
            SELECT COALESCE(SUM(oi.quantite), 0)
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.id
            WHERE o.date_commande = ?
              AND oi.categorie = ?
              AND oi.article_nom = ?
        """, (str(date_commande), categorie, article_nom))
    else:
        cursor.execute("""
            SELECT COALESCE(SUM(oi.quantite), 0)
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.id
            WHERE o.date_commande = ?
              AND oi.categorie = ?
              AND oi.article_nom = ?
              AND o.id != ?
        """, (str(date_commande), categorie, article_nom, exclude_order_id))

    result = cursor.fetchone()
    return result[0] if result else 0


def get_limite_du_jour(date_commande, categorie, article_nom):
    cursor.execute("""
        SELECT quantite_max
        FROM daily_limits
        WHERE date_jour = ?
          AND categorie = ?
          AND article_nom = ?
    """, (str(date_commande), categorie, article_nom))
    result = cursor.fetchone()
    return result[0] if result else None


def delete_order(order_id):
    cursor.execute("DELETE FROM order_items WHERE order_id = ?", (order_id,))
    cursor.execute("DELETE FROM orders WHERE id = ?", (order_id,))
    conn.commit()


def get_order_items_dict(order_id):
    cursor.execute("""
        SELECT categorie, article_nom, quantite
        FROM order_items
        WHERE order_id = ?
    """, (order_id,))
    rows = cursor.fetchall()
    return {(cat, art): q for cat, art, q in rows}


def init_order_quantities():
    articles_dict = get_articles()

    if "order_quantities" not in st.session_state:
        st.session_state.order_quantities = {}

    for categorie, articles in articles_dict.items():
        for article_data in articles:
            article_id = article_data["id"]
            article_nom = article_data["nom"]
            item_key = f"{categorie}|{article_id}|{article_nom}"

            if item_key not in st.session_state.order_quantities:
                st.session_state.order_quantities[item_key] = 0


def reset_order_quantities():
    articles_dict = get_articles()

    if "order_quantities" not in st.session_state:
        st.session_state.order_quantities = {}

    for categorie, articles in articles_dict.items():
        for article_data in articles:
            article_id = article_data["id"]
            article_nom = article_data["nom"]
            item_key = f"{categorie}|{article_id}|{article_nom}"
            st.session_state.order_quantities[item_key] = 0


def change_qty(item_key, delta):
    current = st.session_state.order_quantities.get(item_key, 0)
    new_value = current + delta
    if new_value < 0:
        new_value = 0
    st.session_state.order_quantities[item_key] = new_value


seed_default_articles_if_empty()

# =========================================================
# ÉTAT
# =========================================================
if "page" not in st.session_state:
    st.session_state.page = "accueil"

if "edit_order_id" not in st.session_state:
    st.session_state.edit_order_id = None
    
if "edit_article_id" not in st.session_state:
    st.session_state.edit_article_id = None

if "selected_category" not in st.session_state:
    st.session_state.selected_category = None


# =========================================================
# PAGE ACCUEIL
# =========================================================
if st.session_state.page == "accueil":
    st.title("Application de commandes - Boulangerie")
    st.write("Choisissez une action.")

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        if st.button("Nouvelle commande", use_container_width=True):
            reset_order_quantities()
            st.session_state.page = "nouvelle_commande"
            st.rerun()

    with col2:
        if st.button("Voir les commandes", use_container_width=True):
            st.session_state.page = "voir_commandes"
            st.rerun()

    with col3:
        if st.button("Totaux du jour", use_container_width=True):
            st.session_state.page = "totaux"
            st.rerun()

    with col4:
        if st.button("Limites du jour", use_container_width=True):
            st.session_state.page = "limites"
            st.rerun()

    with col5:
        if st.button("Articles", use_container_width=True):
            st.session_state.page = "articles"
            st.rerun()


# =========================================================
# PAGE NOUVELLE COMMANDE
# =========================================================
elif st.session_state.page == "nouvelle_commande":
    st.title("Nouvelle commande")

    top1, top2 = st.columns([1, 1])

    with top1:
        if st.button("Retour à l'accueil", use_container_width=True):
            st.session_state.page = "accueil"
            st.rerun()

    with top2:
        if st.button("Réinitialiser les quantités", use_container_width=True):
            reset_order_quantities()
            st.rerun()

    prenom = st.text_input("Prénom")
    nom = st.text_input("Nom")
    date_commande = st.date_input("Date", value=date.today())
    commentaire = st.text_area("Commentaire")

    articles_dict = get_articles()

    if not articles_dict:
        st.warning("Aucun article n'existe encore. Va dans la page Articles pour en ajouter.")
    else:
        init_order_quantities()

        categories = [cat for cat in CATEGORIES if cat in articles_dict] + [
            cat for cat in articles_dict.keys() if cat not in CATEGORIES
        ]

        if st.session_state.selected_category not in categories:
            st.session_state.selected_category = categories[0]

        st.subheader("Choisir une catégorie")

        cat_cols = st.columns(min(len(categories), 7))
        for i, categorie in enumerate(categories):
            with cat_cols[i % len(cat_cols)]:
                if st.button(categorie, use_container_width=True, key=f"cat_btn_{categorie}"):
                    st.session_state.selected_category = categorie
                    st.rerun()

        st.divider()

        left_col, right_col = st.columns([3, 1])

        with left_col:
            categorie = st.session_state.selected_category
            st.subheader(categorie)

            articles = articles_dict.get(categorie, [])
            cols_per_row = 2

            for start in range(0, len(articles), cols_per_row):
                row_articles = articles[start:start + cols_per_row]
                cols = st.columns(cols_per_row)

                for col_index, article_data in enumerate(row_articles):
                    article_id = article_data["id"]
                    article = article_data["nom"]
                    item_key = f"{categorie}|{article_id}|{article}"

                    limite = get_limite_du_jour(date_commande, categorie, article)
                    deja_commande = get_total_deja_commande(date_commande, categorie, article)
                    qty = st.session_state.order_quantities.get(item_key, 0)

                    if limite is None:
                        aide = f"Déjà commandé : {deja_commande} | Pas de limite"
                    else:
                        restant = max(limite - deja_commande - qty, 0)
                        aide = f"Déjà commandé : {deja_commande} / Limite : {limite} / Restant après saisie : {restant}"

                    with cols[col_index]:
                        st.markdown('<div class="article-card">', unsafe_allow_html=True)
                        st.markdown(f'<div class="article-title">{article}</div>', unsafe_allow_html=True)
                        st.markdown(f'<div class="article-help">{aide}</div>', unsafe_allow_html=True)
                        st.markdown(f'<div class="article-qty">{qty}</div>', unsafe_allow_html=True)

                        c1, c2, c3 = st.columns([1, 2, 1])

                        with c1:
                            if st.button("−", key=f"minus_{article_id}", use_container_width=True):
                                change_qty(item_key, -1)
                                st.rerun()

                        with c2:
                            new_value = st.number_input(
                                "Quantité",
                                min_value=0,
                                value=qty,
                                step=1,
                                key=f"input_qty_{article_id}",
                                label_visibility="collapsed"
                            )
                            if new_value != qty:
                                if limite is not None:
                                    total_if_set = deja_commande + new_value
                                    if total_if_set > limite:
                                        st.warning(f"Limite atteinte pour {article}.")
                                    else:
                                        st.session_state.order_quantities[item_key] = new_value
                                        st.rerun()
                                else:
                                    st.session_state.order_quantities[item_key] = new_value
                                    st.rerun()

                        with c3:
                            if st.button("+", key=f"plus_{article_id}", use_container_width=True):
                                if limite is not None:
                                    total_si_plus = deja_commande + qty + 1
                                    if total_si_plus > limite:
                                        st.warning(f"Limite atteinte pour {article}.")
                                    else:
                                        change_qty(item_key, 1)
                                        st.rerun()
                                else:
                                    change_qty(item_key, 1)
                                    st.rerun()

                        st.markdown('</div>', unsafe_allow_html=True)

        with right_col:
            st.markdown('<div class="summary-box">', unsafe_allow_html=True)
            st.markdown('<div class="block-title">Résumé</div>', unsafe_allow_html=True)

            has_items = False
            total_articles = 0

            for cat in categories:
                lignes = []
                for article_data in articles_dict.get(cat, []):
                    article_id = article_data["id"]
                    article = article_data["nom"]
                    item_key = f"{cat}|{article_id}|{article}"
                    qty = st.session_state.order_quantities.get(item_key, 0)
                    if qty > 0:
                        lignes.append((article, qty))
                        total_articles += qty

                if lignes:
                    has_items = True
                    st.write(f"**{cat}**")
                    for article, qty in lignes:
                        st.write(f"- {article} : {qty}")

            if not has_items:
                st.info("Aucun article sélectionné.")

            st.write(f"**Total pièces : {total_articles}**")
            st.markdown('</div>', unsafe_allow_html=True)

        st.divider()

        if st.button("Enregistrer la commande", use_container_width=True):
            erreurs = []
            quantites_a_enregistrer = []

            if not prenom.strip():
                erreurs.append("Le prénom est obligatoire.")
            if not nom.strip():
                erreurs.append("Le nom est obligatoire.")

            for cat in categories:
                for article_data in articles_dict.get(cat, []):
                    article_id = article_data["id"]
                    article = article_data["nom"]
                    item_key = f"{cat}|{article_id}|{article}"
                    q = st.session_state.order_quantities.get(item_key, 0)

                    if q > 0:
                        limite = get_limite_du_jour(date_commande, cat, article)
                        deja_commande = get_total_deja_commande(date_commande, cat, article)

                        if limite is not None and (deja_commande + q) > limite:
                            erreurs.append(
                                f"{article} : demandé {q}, déjà commandé {deja_commande}, limite {limite}."
                            )

                        quantites_a_enregistrer.append((cat, article, q))

            if not quantites_a_enregistrer:
                erreurs.append("La commande ne contient aucun article.")

            if erreurs:
                for erreur in erreurs:
                    st.error(erreur)
            else:
                cursor.execute("""
                    INSERT INTO orders (prenom, nom, date_commande, commentaire)
                    VALUES (?, ?, ?, ?)
                """, (prenom.strip(), nom.strip(), str(date_commande), commentaire.strip()))

                order_id = cursor.lastrowid

                for cat, article, q in quantites_a_enregistrer:
                    cursor.execute("""
                        INSERT INTO order_items (order_id, article_nom, categorie, quantite)
                        VALUES (?, ?, ?, ?)
                    """, (order_id, article, cat, q))

                conn.commit()
                reset_order_quantities()
                st.success("Commande enregistrée avec succès.")
                st.rerun()


# =========================================================
# PAGE VOIR LES COMMANDES
# =========================================================
elif st.session_state.page == "voir_commandes":
    st.title("Commandes")

    if st.button("Retour à l'accueil"):
        st.session_state.page = "accueil"
        st.rerun()

    cursor.execute("""
        SELECT id, prenom, nom, date_commande, commentaire
        FROM orders
        ORDER BY date_commande DESC, id DESC
    """)
    commandes = cursor.fetchall()

    if not commandes:
        st.info("Aucune commande enregistrée.")
    else:
        for c in commandes:
            order_id, prenom, nom, date_cmd, commentaire = c

            with st.expander(f"Commande #{order_id} - {prenom} {nom} - {date_cmd}"):
                col1, col2 = st.columns(2)

                with col1:
                    if st.button("Modifier", key=f"edit_{order_id}", use_container_width=True):
                        st.session_state.edit_order_id = order_id
                        st.session_state.page = "modifier_commande"
                        st.rerun()

                with col2:
                    if st.button("Supprimer", key=f"delete_{order_id}", use_container_width=True):
                        delete_order(order_id)
                        st.success("Commande supprimée.")
                        st.rerun()

                st.write(f"**Commentaire :** {commentaire if commentaire else '-'}")

                cursor.execute("""
                    SELECT categorie, article_nom, quantite
                    FROM order_items
                    WHERE order_id = ?
                    ORDER BY categorie, article_nom
                """, (order_id,))
                items = cursor.fetchall()

                if not items:
                    st.write("Aucun article.")
                else:
                    current_cat = None
                    for cat, art, q in items:
                        if cat != current_cat:
                            st.write(f"**{cat}**")
                            current_cat = cat
                        st.write(f"- {art} : {q}")


# =========================================================
# PAGE MODIFIER COMMANDE
# =========================================================
elif st.session_state.page == "modifier_commande":
    st.title("Modifier la commande")

    if st.button("Retour aux commandes"):
        st.session_state.page = "voir_commandes"
        st.session_state.edit_order_id = None
        st.rerun()

    order_id = st.session_state.edit_order_id

    if order_id is None:
        st.error("Aucune commande sélectionnée.")
    else:
        cursor.execute("""
            SELECT prenom, nom, date_commande, commentaire
            FROM orders
            WHERE id = ?
        """, (order_id,))
        data = cursor.fetchone()

        if not data:
            st.error("Commande introuvable.")
        else:
            prenom_initial, nom_initial, date_initiale, commentaire_initial = data
            anciens_items = get_order_items_dict(order_id)

            prenom = st.text_input("Prénom", value=prenom_initial)
            nom = st.text_input("Nom", value=nom_initial)
            date_commande = st.date_input("Date", value=date.fromisoformat(date_initiale))
            commentaire = st.text_area("Commentaire", value=commentaire_initial if commentaire_initial else "")

            articles_dict = get_articles()
            categories = [cat for cat in CATEGORIES if cat in articles_dict] + [
                cat for cat in articles_dict.keys() if cat not in CATEGORIES
            ]

            if not articles_dict:
                st.warning("Aucun article n'existe encore.")
            else:
                quantites = {}

                for cat in categories:
                    if cat not in articles_dict:
                        continue

                    st.subheader(cat)

                    for article_data in articles_dict[cat]:
                        article = article_data["nom"]
                        valeur = anciens_items.get((cat, article), 0)

                        limite = get_limite_du_jour(date_commande, cat, article)
                        deja_commande = get_total_deja_commande(
                            date_commande, cat, article, exclude_order_id=order_id
                        )

                        if limite is None:
                            aide = f"Autres commandes du jour : {deja_commande} | Pas de limite"
                        else:
                            restant = max(limite - deja_commande - valeur, 0)
                            aide = f"Autres commandes : {deja_commande} / Limite : {limite} / Restant : {restant}"

                        quantites[(cat, article)] = st.number_input(
                            article,
                            min_value=0,
                            value=valeur,
                            step=1,
                            key=f"edit_{order_id}_{cat}_{article}"
                        )
                        st.caption(aide)

                if st.button("Enregistrer les modifications", use_container_width=True):
                    erreurs = []

                    if not prenom.strip():
                        erreurs.append("Le prénom est obligatoire.")
                    if not nom.strip():
                        erreurs.append("Le nom est obligatoire.")

                    for (cat, article), q in quantites.items():
                        if q > 0:
                            limite = get_limite_du_jour(date_commande, cat, article)
                            deja_commande = get_total_deja_commande(
                                date_commande, cat, article, exclude_order_id=order_id
                            )

                            if limite is not None and (deja_commande + q) > limite:
                                erreurs.append(
                                    f"{article} : demandé {q}, autres commandes {deja_commande}, limite {limite}."
                                )

                    if erreurs:
                        for erreur in erreurs:
                            st.error(erreur)
                    else:
                        cursor.execute("""
                            UPDATE orders
                            SET prenom = ?, nom = ?, date_commande = ?, commentaire = ?
                            WHERE id = ?
                        """, (
                            prenom.strip(),
                            nom.strip(),
                            str(date_commande),
                            commentaire.strip(),
                            order_id
                        ))

                        cursor.execute("DELETE FROM order_items WHERE order_id = ?", (order_id,))

                        for (cat, article), q in quantites.items():
                            if q > 0:
                                cursor.execute("""
                                    INSERT INTO order_items (order_id, article_nom, categorie, quantite)
                                    VALUES (?, ?, ?, ?)
                                """, (order_id, article, cat, q))

                        conn.commit()
                        st.success("Commande mise à jour.")


# =========================================================
# PAGE TOTAUX
# =========================================================
elif st.session_state.page == "totaux":
    st.title("Totaux du jour")

    if st.button("Retour à l'accueil"):
        st.session_state.page = "accueil"
        st.rerun()

    d = st.date_input("Choisir une date", value=date.today())

    cursor.execute("""
        SELECT oi.categorie, oi.article_nom, SUM(oi.quantite)
        FROM order_items oi
        JOIN orders o ON oi.order_id = o.id
        WHERE o.date_commande = ?
        GROUP BY oi.categorie, oi.article_nom
        ORDER BY oi.categorie, oi.article_nom
    """, (str(d),))
    rows = cursor.fetchall()

    if not rows:
        st.info("Aucune commande pour cette date.")
    else:
        current_cat = None
        total_general = 0

        for cat, art, total in rows:
            if cat != current_cat:
                st.subheader(cat)
                current_cat = cat
            st.write(f"{art} : {total}")
            total_general += total

        st.divider()
        st.write(f"**Total général : {total_general}**")
        st.info("Pour imprimer : utilise l'impression du navigateur.")


# =========================================================
# PAGE LIMITES
# =========================================================
elif st.session_state.page == "limites":
    st.title("Limites du jour")

    if st.button("Retour à l'accueil"):
        st.session_state.page = "accueil"
        st.rerun()

    d = st.date_input("Date des limites", value=date.today(), key="date_limites")
    articles_dict = get_articles()

    if not articles_dict:
        st.warning("Aucun article n'existe encore. Va dans la page Articles pour en ajouter.")
    else:
        categories = [cat for cat in CATEGORIES if cat in articles_dict] + [
            cat for cat in articles_dict.keys() if cat not in CATEGORIES
        ]

        limites_saisies = {}

        for categorie in categories:
            if categorie not in articles_dict:
                continue

            st.subheader(categorie)

            for article_data in articles_dict[categorie]:
                article_id = article_data["id"]
                article = article_data["nom"]

                limite_existante = get_limite_du_jour(d, categorie, article)
                valeur_defaut = limite_existante if limite_existante is not None else 0

                limites_saisies[(categorie, article)] = st.number_input(
                    f"Limite - {article}",
                    min_value=0,
                    value=valeur_defaut,
                    step=1,
                    key=f"limite_{article_id}"
                )

        if st.button("Enregistrer les limites", use_container_width=True):
            for (categorie, article), quantite_max in limites_saisies.items():
                cursor.execute("""
                    DELETE FROM daily_limits
                    WHERE date_jour = ?
                      AND categorie = ?
                      AND article_nom = ?
                """, (str(d), categorie, article))

                if quantite_max > 0:
                    cursor.execute("""
                        INSERT INTO daily_limits (date_jour, article_nom, categorie, quantite_max)
                        VALUES (?, ?, ?, ?)
                    """, (str(d), article, categorie, quantite_max))

            conn.commit()
            st.success("Limites enregistrées.")


# =========================================================
# PAGE ARTICLES
# =========================================================
elif st.session_state.page == "articles":
    st.title("Gestion des articles")

    if st.button("Retour à l'accueil"):
        st.session_state.page = "accueil"
        st.session_state.edit_article_id = None
        st.rerun()

    st.subheader("Ajouter un article")

    nom = st.text_input("Nom de l'article")
    categorie = st.selectbox("Catégorie", CATEGORIES)

    if st.button("Ajouter l'article", use_container_width=True):
        if not nom.strip():
            st.error("Le nom de l'article est obligatoire.")
        else:
            cursor.execute("""
                SELECT COUNT(*)
                FROM articles
                WHERE nom = ? AND categorie = ?
            """, (nom.strip(), categorie))
            exists = cursor.fetchone()[0]

            if exists > 0:
                st.error("Cet article existe déjà dans cette catégorie.")
            else:
                cursor.execute("""
                    INSERT INTO articles (nom, categorie)
                    VALUES (?, ?)
                """, (nom.strip(), categorie))
                conn.commit()
                st.success("Article ajouté.")
                st.rerun()

    st.divider()
    st.subheader("Liste des articles")

    cursor.execute("""
        SELECT id, categorie, nom
        FROM articles
        ORDER BY categorie, nom
    """)
    rows = cursor.fetchall()

    if not rows:
        st.info("Aucun article enregistré.")
    else:
        current_cat = None
        for id_, cat, nom_article in rows:
            if cat != current_cat:
                st.write(f"**{cat}**")
                current_cat = cat

            col1, col2, col3 = st.columns([4, 2, 1])

            with col1:
                st.write(nom_article)

            with col2:
                if st.button("Modifier", key=f"edit_article_{id_}"):
                    st.session_state.edit_article_id = id_
                    st.rerun()

            with col3:
                if st.button("Supprimer", key=f"del_article_{id_}"):
                    cursor.execute("DELETE FROM articles WHERE id = ?", (id_,))
                    cursor.execute("""
                        DELETE FROM daily_limits
                        WHERE categorie = ? AND article_nom = ?
                    """, (cat, nom_article))
                    conn.commit()

                    if st.session_state.edit_article_id == id_:
                        st.session_state.edit_article_id = None

                    st.success("Article supprimé.")
                    st.rerun()

    if st.session_state.edit_article_id is not None:
        st.divider()
        st.subheader("Modifier l'article")

        cursor.execute("""
            SELECT nom, categorie
            FROM articles
            WHERE id = ?
        """, (st.session_state.edit_article_id,))
        data = cursor.fetchone()

        if not data:
            st.error("Article introuvable.")
            st.session_state.edit_article_id = None
        else:
            nom_actuel, categorie_actuelle = data

            new_nom = st.text_input("Nom", value=nom_actuel, key="edit_article_nom")

            index_categorie = CATEGORIES.index(categorie_actuelle) if categorie_actuelle in CATEGORIES else 0
            new_cat = st.selectbox(
                "Nouvelle catégorie",
                CATEGORIES,
                index=index_categorie,
                key="edit_article_cat"
            )

            col1, col2 = st.columns(2)

            with col1:
                if st.button("Enregistrer modification", use_container_width=True):
                    if not new_nom.strip():
                        st.error("Le nom de l'article est obligatoire.")
                    else:
                        cursor.execute("""
                            SELECT COUNT(*)
                            FROM articles
                            WHERE nom = ? AND categorie = ? AND id != ?
                        """, (new_nom.strip(), new_cat, st.session_state.edit_article_id))
                        exists = cursor.fetchone()[0]

                        if exists > 0:
                            st.error("Un article avec ce nom existe déjà dans cette catégorie.")
                        else:
                            # On récupère l'ancien nom/catégorie pour mettre aussi à jour les limites
                            cursor.execute("""
                                SELECT nom, categorie
                                FROM articles
                                WHERE id = ?
                            """, (st.session_state.edit_article_id,))
                            old_nom, old_cat = cursor.fetchone()

                            cursor.execute("""
                                UPDATE articles
                                SET nom = ?, categorie = ?
                                WHERE id = ?
                            """, (new_nom.strip(), new_cat, st.session_state.edit_article_id))

                            cursor.execute("""
                                UPDATE daily_limits
                                SET article_nom = ?, categorie = ?
                                WHERE article_nom = ? AND categorie = ?
                            """, (new_nom.strip(), new_cat, old_nom, old_cat))

                            conn.commit()
                            st.success("Article modifié.")
                            st.session_state.edit_article_id = None
                            st.rerun()

            with col2:
                if st.button("Annuler", use_container_width=True):
                    st.session_state.edit_article_id = None
                    st.rerun()
