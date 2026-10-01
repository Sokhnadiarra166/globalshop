"""Vérifications de la phase 2 : commande, facture, refus, idempotence, atomicité."""
import uuid

from commande import id_ligne, passer_commande
from common import StockInsuffisant, connecter


def requete(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        lignes = cur.fetchall()
    conn.commit()
    return lignes


def lire_stock(conn, region, produit_id):
    return requete(
        conn,
        "SELECT stock FROM produits WHERE region = %s AND id = %s",
        (region, produit_id),
    )[0][0]


def nb_commandes(conn, region_client, commande_id):
    return requete(
        conn,
        "SELECT count(*) FROM commandes WHERE region = %s AND id = %s",
        (region_client, commande_id),
    )[0][0]


def nb_factures(conn, region_client, commande_id):
    return requete(
        conn,
        "SELECT count(*) FROM factures WHERE region = %s AND commande_id = %s",
        (region_client, commande_id),
    )[0][0]


conn = connecter()

clients = requete(conn, "SELECT region, id FROM clients LIMIT 1")
assert clients, "Aucun client dans la base (vérifie seed.sql)"
client = clients[0]
region_client = client[0]

# Un produit par région : celui qui a le plus de stock (au moins 3).
produits = requete(
    conn,
    """
    SELECT DISTINCT ON (region) region, id, stock, prix
      FROM produits
     WHERE stock >= 3
     ORDER BY region, stock DESC
    """,
)
assert produits, "Aucun produit avec au moins 3 en stock (vérifie seed.sql)"
r1, p1, _, prix1 = produits[0]

# 1. Commande simple : stock, commande et facture
panier = str(uuid.uuid4())
avant = lire_stock(conn, r1, p1)
statut, reessais = passer_commande(conn, client, [(r1, p1, 1)], panier_id=panier)
apres = lire_stock(conn, r1, p1)
cid = id_ligne(panier, 0)
montants = requete(
    conn,
    "SELECT montant FROM factures WHERE region = %s AND commande_id = %s",
    (region_client, cid),
)
facture_ok = bool(montants) and montants[0][0] == prix1
print(f"1. Commande simple : {statut} | stock {avant} -> {apres} | "
      f"commande : {nb_commandes(conn, region_client, cid)} | facture correcte : {facture_ok}")
print("   (attendu : OK | baisse de 1 | commande : 1 | facture correcte : True)")

# 2. Stock insuffisant : refus, stock inchangé
courant = lire_stock(conn, r1, p1)
try:
    passer_commande(conn, client, [(r1, p1, courant + 1000)])
    print("2. ERREUR : la commande aurait dû être refusée")
except StockInsuffisant:
    inchange = lire_stock(conn, r1, p1) == courant
    print(f"2. Refus correct | stock inchangé : {inchange} (attendu : True)")

# 3. Idempotence : rejouer le même panier ne décrémente pas deux fois
panier = str(uuid.uuid4())
passer_commande(conn, client, [(r1, p1, 1)], panier_id=panier)
milieu = lire_stock(conn, r1, p1)
statut, _ = passer_commande(conn, client, [(r1, p1, 1)], panier_id=panier)
inchange = lire_stock(conn, r1, p1) == milieu
cid = id_ligne(panier, 0)
print(f"3. Rejeu du même panier : {statut} | stock inchangé : {inchange} | "
      f"commandes : {nb_commandes(conn, region_client, cid)} (attendu : DEJA_TRAITEE, True, 1)")

# Les tests 4 et 5 demandent des produits dans au moins 2 régions
if len(produits) >= 2:
    r2, p2, s2, _ = produits[1]

    # 4. Atomicité : la 2e ligne est impossible, TOUT doit être annulé
    a1, a2 = lire_stock(conn, r1, p1), lire_stock(conn, r2, p2)
    panier = str(uuid.uuid4())
    try:
        passer_commande(conn, client, [(r1, p1, 1), (r2, p2, s2 + 1000)],
                        panier_id=panier)
        print("4. ERREUR : la commande aurait dû être refusée")
    except StockInsuffisant:
        stocks_ok = lire_stock(conn, r1, p1) == a1 and lire_stock(conn, r2, p2) == a2
        rien_ecrit = all(
            nb_commandes(conn, region_client, id_ligne(panier, i)) == 0
            for i in range(2)
        )
        print(f"4. Panier {r1} + {r2} refusé : stocks inchangés : {stocks_ok} | "
              f"aucune commande créée : {rien_ecrit} (attendu : True, True)")

    # 5. Commande réussie sur 2 régions : tout est validé ensemble
    a1, a2 = lire_stock(conn, r1, p1), lire_stock(conn, r2, p2)
    panier = str(uuid.uuid4())
    statut, _ = passer_commande(conn, client, [(r1, p1, 1), (r2, p2, 1)],
                                panier_id=panier)
    b1, b2 = lire_stock(conn, r1, p1), lire_stock(conn, r2, p2)
    ids = [id_ligne(panier, i) for i in range(2)]
    commandes = sum(nb_commandes(conn, region_client, i) for i in ids)
    factures = sum(nb_factures(conn, region_client, i) for i in ids)
    print(f"5. Panier {r1} + {r2} : {statut} | stocks -{a1 - b1} et -{a2 - b2} | "
          f"commandes : {commandes} | factures : {factures}")
    print("   (attendu : OK | -1 et -1 | commandes : 2 | factures : 2)")
else:
    print("4-5. Ignorés : un seul produit utilisable dans la base")

conn.close()
print("=== PHASE 2 TERMINEE ===")