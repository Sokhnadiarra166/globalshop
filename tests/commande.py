"""Passage de commande : stock + commande + facture dans UNE transaction distribuée.

Dans le schéma, une ligne de `commandes` concerne UN produit. Un panier de plusieurs
produits devient donc plusieurs lignes `commandes` (et autant de factures), toutes
validées ou toutes annulées ensemble.
"""
import uuid

from common import ProduitInconnu, StockInsuffisant, executer_transaction


def id_ligne(panier_id, position):
    """Identifiant stable : rejouer le même panier redonne les mêmes identifiants."""
    return str(uuid.uuid5(uuid.UUID(panier_id), str(position)))


def _traiter(cur, panier_id, client, lignes):
    region_client, client_id = client
    # Ordre fixe : moins de conflits entre transactions concurrentes.
    lignes = sorted(lignes)
    ids = [id_ligne(panier_id, i) for i in range(len(lignes))]

    # 0. Idempotence : ce panier a-t-il déjà été enregistré ?
    #    (utile si la connexion tombe pendant le COMMIT : on peut rejouer sans doublon)
    cur.execute(
        "SELECT 1 FROM commandes WHERE region = %s AND id = %s",
        (region_client, ids[0]),
    )
    if cur.fetchone():
        return "DEJA_TRAITEE"

    for commande_id, (produit_region, produit_id, quantite) in zip(ids, lignes):
        # 1. Décrément atomique du stock : refusé si le stock est insuffisant.
        cur.execute(
            """
            UPDATE produits
               SET stock = stock - %s
             WHERE region = %s AND id = %s AND stock >= %s
         RETURNING prix
            """,
            (quantite, produit_region, produit_id, quantite),
        )
        ligne = cur.fetchone()
        if ligne is None:
            cur.execute(
                "SELECT 1 FROM produits WHERE region = %s AND id = %s",
                (produit_region, produit_id),
            )
            if cur.fetchone() is None:
                raise ProduitInconnu(f"{produit_region}/{produit_id}")
            # L'exception annule TOUTE la transaction, lignes précédentes comprises.
            raise StockInsuffisant(f"{produit_region}/{produit_id}")
        prix = ligne[0]

        # 2. La commande est stockée dans la région du client.
        cur.execute(
            """
            INSERT INTO commandes
                   (region, id, client_id, produit_region, produit_id, quantite, statut)
            VALUES (%s, %s, %s, %s, %s, %s, 'CONFIRMEE')
            """,
            (region_client, commande_id, client_id,
             produit_region, produit_id, quantite),
        )

        # 3. La facture suit la commande (même région).
        cur.execute(
            "INSERT INTO factures (region, commande_id, montant) VALUES (%s, %s, %s)",
            (region_client, commande_id, prix * quantite),
        )
    return "OK"


def passer_commande(conn, client, lignes, panier_id=None):
    """
    client : (region, client_id)
    lignes : liste de (region_produit, produit_id, quantite)
    panier_id : identifiant du panier (à réutiliser pour rejouer sans doublon)
    Retourne (statut, nombre_de_réessais).
    Lève StockInsuffisant ou ProduitInconnu si la commande est refusée.
    """
    if not lignes:
        raise ValueError("Le panier est vide")
    if any(quantite <= 0 for _, _, quantite in lignes):
        raise ValueError("Les quantités doivent être positives")
    panier_id = panier_id or str(uuid.uuid4())
    return executer_transaction(
        conn, lambda cur: _traiter(cur, panier_id, client, lignes)
    )