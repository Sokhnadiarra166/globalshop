"""Démonstration des fonctionnalités du sujet : inscription d'un client, création d'un
produit, consultation du catalogue distribué, passage de commande (transaction distribuée)."""
import sys
import uuid
from decimal import Decimal

from commande import passer_commande
from common import StockInsuffisant, connecter

sys.stdout.reconfigure(encoding="utf-8")


def titre(texte):
    print(f"\n--- {texte} ---")


def main():
    conn = connecter()
    suffixe = uuid.uuid4().hex[:6]

    titre("1. Inscription d'un client (région asie)")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO clients (region, nom, email) VALUES ('asie', %s, %s) RETURNING id",
            (f"Client démo {suffixe}", f"demo-{suffixe}@globalshop.test"),
        )
        client_id = cur.fetchone()[0]
    conn.commit()
    print(f"Client créé : asie/{client_id}")

    titre("2. Création d'un produit (région afrique, prix 49.90, stock 5)")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO produits (region, nom, prix, stock) "
            "VALUES ('afrique', %s, 49.90, 5) RETURNING id",
            (f"Produit démo {suffixe}",),
        )
        produit_id = cur.fetchone()[0]
    conn.commit()
    print(f"Produit créé : afrique/{produit_id}")

    titre("3. Consultation du catalogue (lecture distribuée sur les 4 régions)")
    with conn.cursor() as cur:
        cur.execute("SELECT region, count(*), sum(stock) FROM produits "
                    "WHERE nom NOT LIKE '%test%' GROUP BY region ORDER BY region")
        for region, nb, stock in cur.fetchall():
            print(f"  {region:<10} {nb:>4} produit(s)   stock total : {stock}")
        cur.execute("SELECT region, nom, prix, stock FROM produits "
                    "WHERE nom NOT LIKE '%test%' ORDER BY region, nom LIMIT 8")
        print("  Extrait :")
        for region, nom, prix, stock in cur.fetchall():
            print(f"    {region:<10} {nom:<28} {prix:>8} €  stock {stock}")
    conn.commit()

    titre("4. Commande de 2 exemplaires : stock en afrique, commande et facture en asie")
    statut, reessais = passer_commande(
        conn, ("asie", client_id), [("afrique", produit_id, 2)])
    with conn.cursor() as cur:
        cur.execute("SELECT stock FROM produits WHERE region = 'afrique' AND id = %s",
                    (produit_id,))
        stock = cur.fetchone()[0]
        cur.execute(
            """SELECT count(*), coalesce(sum(montant), 0) FROM factures
                WHERE region = 'asie' AND commande_id IN
                  (SELECT id FROM commandes WHERE region = 'asie' AND client_id = %s)""",
            (client_id,))
        nb_factures, montant = cur.fetchone()
    conn.commit()
    print(f"  Statut : {statut} | stock restant : {stock} (attendu 3) | "
          f"factures : {nb_factures} | montant : {montant} (attendu 99.80)")

    titre("5. Commande de 10 exemplaires alors qu'il en reste 3 : refus attendu")
    try:
        passer_commande(conn, ("asie", client_id), [("afrique", produit_id, 10)])
        print("  ERREUR : la commande aurait dû être refusée")
        return 1
    except StockInsuffisant:
        print("  Commande refusée : stock insuffisant (aucune survente)")

    ok = stock == 3 and nb_factures == 1 and montant == Decimal("99.80")
    print("\n" + ("=== FONCTIONNALITÉS OK ===" if ok else "=== FONCTIONNALITÉS EN ÉCHEC ==="))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())