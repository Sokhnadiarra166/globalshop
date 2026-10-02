"""Test de charge : N acheteurs simultanés sur un même produit (stock limité).

Chaque acheteur ouvre sa propre connexion et lance sa propre transaction ; tous
démarrent au même instant (barrière). Le script crée son propre client et son
propre produit de test, et supprime les restes d'un ancien test interrompu.

Exemples :
    python tests/charge.py
    python tests/charge.py --acheteurs 50
    python tests/charge.py --mode naif          # contre-expérience (sans protection)
"""
import argparse
import json
import statistics
import sys
import threading
import time
import uuid
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from psycopg2 import extensions

from commande import passer_commande
from common import StockInsuffisant, connecter

sys.stdout.reconfigure(encoding="utf-8")

REGIONS = ["afrique", "europe", "amerique", "asie"]
PRIX = Decimal("25.00")
NOM_CLIENT_TEST = "Client test charge"
NOM_PRODUIT_TEST = "Produit test charge"


# ----------------------------------------------------------------- base de données

def requete(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        lignes = cur.fetchall()
    conn.commit()
    return lignes


def preparer(conn, region_client, region_produit, stock):
    """Crée un client et un produit de test. Retourne (client, produit)."""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO clients (region, nom, email)
               VALUES (%s, %s, 'charge@test.local') RETURNING id""",
            (region_client, NOM_CLIENT_TEST),
        )
        client_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO produits (region, nom, prix, stock)
               VALUES (%s, %s, %s, %s) RETURNING id""",
            (region_produit, NOM_PRODUIT_TEST, PRIX, stock),
        )
        produit_id = cur.fetchone()[0]
    conn.commit()
    return (region_client, client_id), (region_produit, produit_id)


def nettoyer_tout(conn):
    """Supprime TOUTES les données de test (reconnaissables à leur nom)."""
    condition = f"""client_id IN (SELECT id FROM clients WHERE nom = '{NOM_CLIENT_TEST}')
                    OR produit_id IN (SELECT id FROM produits WHERE nom = '{NOM_PRODUIT_TEST}')"""
    with conn.cursor() as cur:
        cur.execute(
            f"DELETE FROM factures WHERE commande_id IN "
            f"(SELECT id FROM commandes WHERE {condition})"
        )
        cur.execute(f"DELETE FROM commandes WHERE {condition}")
        cur.execute("DELETE FROM produits WHERE nom = %s", (NOM_PRODUIT_TEST,))
        cur.execute("DELETE FROM clients WHERE nom = %s", (NOM_CLIENT_TEST,))
    conn.commit()


# ------------------------------------------------------------------------ acheteurs

def premiere_ligne(e):
    texte = str(e).strip()
    return texte.splitlines()[0] if texte else ""


def ouvrir_connexion(mode, essais=3):
    """Ouvre une connexion et la « chauffe » avec une requête simple."""
    derniere = None
    for tentative in range(essais):
        try:
            conn = connecter()
            if mode == "naif":
                conn.set_isolation_level(extensions.ISOLATION_LEVEL_READ_COMMITTED)
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            conn.commit()
            return conn
        except Exception as e:
            derniere = e
            time.sleep(0.2 * (tentative + 1))
    raise derniere


def acheter_naif(conn, client, produit, quantite):
    """
    Achat SANS protection : lecture du stock, puis écriture de la valeur calculée
    par l'application (aucune condition dans le UPDATE), sous READ COMMITTED.
    Sert uniquement de contre-expérience pour montrer ce que l'anti-survente évite.
    """
    region_c, client_id = client
    region_p, produit_id = produit
    with conn.cursor() as cur:
        cur.execute(
            "SELECT stock FROM produits WHERE region = %s AND id = %s",
            (region_p, produit_id),
        )
        stock = cur.fetchone()[0]
        if stock < quantite:
            raise StockInsuffisant(f"{region_p}/{produit_id}")
        time.sleep(0.05)  # fenêtre de concurrence (traitement, réseau...)
        cur.execute(
            "UPDATE produits SET stock = %s WHERE region = %s AND id = %s",
            (stock - quantite, region_p, produit_id),
        )
        commande_id = str(uuid.uuid4())
        cur.execute(
            """INSERT INTO commandes
                   (region, id, client_id, produit_region, produit_id, quantite)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (region_c, commande_id, client_id, region_p, produit_id, quantite),
        )
        cur.execute(
            "INSERT INTO factures (region, commande_id, montant) VALUES (%s, %s, %s)",
            (region_c, commande_id, PRIX * quantite),
        )
    conn.commit()


def acheteur(numero, barriere, client, produit, quantite, mode, resultats, conns):
    # 1. Connexion + chauffe (en parallèle avec les autres acheteurs)
    conn, erreur = None, None
    try:
        conn = ouvrir_connexion(mode)
        conns[numero] = conn
    except Exception as e:
        erreur = f"Connexion impossible - {type(e).__name__}: {premiere_ligne(e)}"

    # 2. Tout le monde attend le « top » (la barrière libère tous les acheteurs)
    try:
        barriere.wait(timeout=120)
    except threading.BrokenBarrierError:
        pass

    # 3. Départ
    debut = time.perf_counter()
    issue, reessais = ("erreur", 0) if erreur else ("succes", 0)
    if erreur is None:
        try:
            if mode == "naif":
                acheter_naif(conn, client, produit, quantite)
            else:
                _, reessais = passer_commande(
                    conn, client, [(produit[0], produit[1], quantite)]
                )
        except StockInsuffisant as e:
            issue, reessais = "refus", getattr(e, "reessais", 0)
        except Exception as e:
            issue, reessais = "erreur", getattr(e, "reessais", 0)
            erreur = f"{type(e).__name__}: {premiere_ligne(e)}"
        if issue != "succes":
            try:
                conn.rollback()
            except Exception:
                pass
    resultats[numero] = dict(issue=issue, debut=debut, fin=time.perf_counter(),
                             reessais=reessais, erreur=erreur)


# ------------------------------------------------------------------------ affichage

def percentile(valeurs, p):
    s = sorted(valeurs)
    return s[max(0, min(len(s) - 1, round(p / 100 * (len(s) - 1))))]


def histogramme(valeurs_ms, classes=6, largeur=40):
    mini, maxi = min(valeurs_ms), max(valeurs_ms)
    if maxi - mini < 1e-9:
        return [f"  {mini:7.0f} ms | {'#' * largeur} {len(valeurs_ms)}"]
    pas = (maxi - mini) / classes
    comptes = [0] * classes
    for v in valeurs_ms:
        comptes[min(classes - 1, int((v - mini) / pas))] += 1
    plus = max(comptes)
    return [
        f"  {mini + k * pas:6.0f}-{mini + (k + 1) * pas:6.0f} ms | "
        f"{'#' * round(largeur * c / plus)} {c}"
        for k, c in enumerate(comptes)
    ]


# ---------------------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(description="Test de charge GlobalShop")
    p.add_argument("--acheteurs", type=int, default=100)
    p.add_argument("--stock", type=int, default=10)
    p.add_argument("--quantite", type=int, default=1)
    p.add_argument("--region-produit", choices=REGIONS, default="afrique")
    p.add_argument("--region-client", choices=REGIONS, default="europe")
    p.add_argument("--mode", choices=["normal", "naif"], default="normal")
    p.add_argument("--garder", action="store_true",
                   help="conserver les données de test après le test")
    args = p.parse_args()
    n, stock, quantite = args.acheteurs, args.stock, args.quantite

    print("=" * 66)
    print(f" TEST DE CHARGE | mode : {args.mode} | {n} acheteurs | stock : {stock}")
    print(f" client : {args.region_client} | produit : {args.region_produit}")
    print("=" * 66)

    # 0. Préparation (la connexion d'administration n'est PAS gardée ouverte)
    admin = connecter()
    nettoyer_tout(admin)  # restes d'un ancien test interrompu
    client, produit = preparer(admin, args.region_client, args.region_produit, stock)
    admin.close()
    print(f"Produit de test {produit[0]}/{produit[1]} créé (stock initial : {stock})")
    print(f"{n} acheteurs : connexions en parallèle puis départ simultané...")

    # 1. Départ simultané
    barriere = threading.Barrier(n)
    resultats = [None] * n
    conns = [None] * n
    threads = [
        threading.Thread(target=acheteur, args=(
            i, barriere, client, produit, quantite, args.mode, resultats, conns))
        for i in range(n)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for c in conns:
        if c is not None:
            try:
                c.close()
            except Exception:
                pass

    # 2. Mesures
    succes = sum(r["issue"] == "succes" for r in resultats)
    refus = sum(r["issue"] == "refus" for r in resultats)
    erreurs = sum(r["issue"] == "erreur" for r in resultats)
    ko_connexion = sum(
        1 for r in resultats if r["erreur"] and r["erreur"].startswith("Connexion"))
    durees = [(r["fin"] - r["debut"]) * 1000 for r in resultats]
    total = max(r["fin"] for r in resultats) - min(r["debut"] for r in resultats)
    reessais_total = sum(r["reessais"] for r in resultats)
    reessais_max = max(r["reessais"] for r in resultats)
    avec_reessai = sum(r["reessais"] > 0 for r in resultats)

    print("\n--- RÉSULTATS DES ACHETEURS ---")
    print(f"  Succès (commande acceptée) : {succes}")
    print(f"  Refus  (stock épuisé)      : {refus}")
    print(f"  Erreurs techniques         : {erreurs} (dont {ko_connexion} "
          f"connexions impossibles avant le départ)")
    if erreurs:
        for message, nb in Counter(
                r["erreur"] for r in resultats if r["erreur"]).most_common(3):
            print(f"      {nb} x {message}")

    print("\n--- PERFORMANCES ---")
    print(f"  Durée totale                : {total:.2f} s")
    print(f"  Débit                       : {n / total:.1f} requêtes/s")
    print(f"  Temps de réponse (ms)       : min {min(durees):.0f} | "
          f"médian {statistics.median(durees):.0f} | "
          f"p95 {percentile(durees, 95):.0f} | max {max(durees):.0f}")
    print(f"  Conflits absorbés (réessais): {reessais_total} au total, "
          f"{avec_reessai} acheteurs concernés, maximum {reessais_max} pour un seul")
    print("  Répartition des temps de réponse :")
    for ligne in histogramme(durees):
        print(ligne)

    # 3. Vérification dans la base (nouvelle connexion)
    verif = connecter()
    rc, _ = client
    rp, pid = produit
    stock_final = requete(
        verif, "SELECT stock FROM produits WHERE region = %s AND id = %s", produit
    )[0][0]
    nb_cmd, qte_vendue = requete(
        verif,
        """SELECT count(*), coalesce(sum(quantite), 0) FROM commandes
            WHERE produit_region = %s AND produit_id = %s""",
        produit,
    )[0]
    nb_fact, montant = requete(
        verif,
        """SELECT count(*), coalesce(sum(montant), 0) FROM factures
            WHERE region = %s AND commande_id IN
              (SELECT id FROM commandes
                WHERE region = %s AND produit_region = %s AND produit_id = %s)""",
        (rc, rc, rp, pid),
    )[0]
    verif.close()
    qte_vendue = int(qte_vendue)

    # Les achats en erreur n'ont pas forcément échoué côté base : on contrôle donc
    # d'abord la cohérence de la base, puis le détail des acheteurs.
    attendu = min(n, stock // quantite)
    controles = [
        ("Aucune survente", qte_vendue <= stock,
         f"{qte_vendue} vendus pour un stock de {stock}"),
        ("Stock final cohérent avec les ventes", stock_final == stock - qte_vendue,
         f"{stock_final} (attendu {stock - qte_vendue})"),
        ("Commandes enregistrées = commandes acceptées", nb_cmd == succes,
         f"{nb_cmd} en base, {succes} acceptées"),
        ("Factures = commandes", nb_fact == nb_cmd, f"{nb_fact} (attendu {nb_cmd})"),
        ("Montant facturé correct", montant == PRIX * quantite * nb_cmd,
         f"{montant} (attendu {PRIX * quantite * nb_cmd})"),
        ("Commandes acceptées = stock disponible", succes == attendu,
         f"{succes} (attendu {attendu})"),
        ("Refus = acheteurs - acceptées", refus == n - attendu,
         f"{refus} (attendu {n - attendu})"),
        ("Aucune erreur technique", erreurs == 0, f"{erreurs}"),
    ]
    print("\n--- VÉRIFICATION DANS LA BASE ---")
    for nom, ok, detail in controles:
        print(f"  [{'PASS ' if ok else 'ECHEC'}] {nom} : {detail}")
    integrite = all(ok for _, ok, _ in controles[:5])
    reussi = all(ok for _, ok, _ in controles)
    print(f"\n  Intégrité des données (5 premiers contrôles) : "
          f"{'GARANTIE' if integrite else 'VIOLÉE'}")
    if args.mode == "naif":
        print("  (mode naïf : des ECHEC sont ATTENDUS, c'est la contre-expérience)")
    print("\n" + ("=== TEST REUSSI ===" if reussi else "=== TEST EN ECHEC ==="))

    # 4. Sauvegarde des résultats pour le rapport
    dossier = Path("resultats")
    dossier.mkdir(exist_ok=True)
    fichier = dossier / f"charge_{args.mode}_{datetime.now():%Y%m%d_%H%M%S}.json"
    fichier.write_text(json.dumps({
        "parametres": vars(args),
        "acheteurs": dict(succes=succes, refus=refus, erreurs=erreurs,
                          connexions_impossibles=ko_connexion),
        "performances": dict(
            duree_s=round(total, 3), debit_rps=round(n / total, 1),
            ms_min=round(min(durees)), ms_median=round(statistics.median(durees)),
            ms_p95=round(percentile(durees, 95)), ms_max=round(max(durees)),
            reessais_total=reessais_total, acheteurs_avec_reessai=avec_reessai),
        "base": dict(stock_final=stock_final, commandes=nb_cmd, factures=nb_fact,
                     montant=montant),
        "integrite_garantie": integrite,
        "controles": [dict(nom=nom, ok=ok, detail=detail)
                      for nom, ok, detail in controles],
    }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"Résultats enregistrés : {fichier}")

    # 5. Nettoyage (nouvelle connexion, 3 essais)
    if not args.garder:
        for _ in range(3):
            try:
                c = connecter()
                nettoyer_tout(c)
                c.close()
                print("Données de test supprimées.")
                break
            except Exception as e:
                time.sleep(1)
        else:
            print("Nettoyage impossible : il sera fait au prochain lancement.")
    return 0 if reussi else 1


if __name__ == "__main__":
    sys.exit(main())