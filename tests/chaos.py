"""Test de chaos : panne brutale d'un ou plusieurs nœuds pendant des écritures.

Des « ouvriers » passent des commandes en continu. À l'instant choisi, un nœud est
tué (SIGKILL), puis relancé. Les ouvriers se reconnectent et REJOUENT la même commande
(identifiant de panier identique) tant qu'elle n'est pas confirmée : l'idempotence
évite tout doublon.

À la fin, on compare ce que les clients ont vu confirmer avec ce qui est réellement
en base : aucune commande confirmée ne doit être perdue, aucune survente, et
commandes = factures.

Exemples (depuis la racine du projet) :
    python tests/chaos.py
    python tests/chaos.py --noeuds aucun                  # essai témoin (aucune panne)
    python tests/chaos.py --noeuds roach2,roach3          # perte du quorum
    python tests/chaos.py --kill-a 20 --redemarrer-a 70 --duree 100
    python tests/chaos.py --sans-redemarrage
"""
import argparse
import csv
import io
import json
import random
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from commande import id_ligne, passer_commande
from common import ProduitInconnu, StockInsuffisant, connecter

sys.stdout.reconfigure(encoding="utf-8")

RACINE = Path(__file__).resolve().parent.parent
REGIONS = ["afrique", "europe", "amerique", "asie"]
NOEUDS = ["roach1", "roach2", "roach3", "roach4"]
PRIX = Decimal("25.00")
STOCK = 100000          # stock très large : on teste la panne, pas l'épuisement
NOM_CLIENT = "Client test chaos"
NOM_PRODUIT = "Produit test chaos"
DELAI_GRACE = 60        # secondes laissées aux commandes en cours après la fin


# ------------------------------------------------------------------ outils base/docker

def connecter_chaos():
    """Connexion avec délai maximal par requête (une requête bloquée est annulée)."""
    conn = connecter()
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '10s'")
    conn.commit()
    return conn


def requete(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        lignes = cur.fetchall()
    conn.commit()
    return lignes


def docker(*args, timeout=60):
    """Lance une commande docker depuis la racine du projet. Retourne (code, sortie, erreur)."""
    try:
        r = subprocess.run(["docker", *args], capture_output=True, text=True,
                           timeout=timeout, cwd=RACINE)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def tuer(noeud, conteneurs):
    """Arrêt brutal (SIGKILL). `docker kill` est immédiat ; `docker compose kill` sert de secours."""
    if conteneurs.get(noeud):
        return docker("kill", conteneurs[noeud])
    return docker("compose", "kill", noeud)


def relancer(noeud, conteneurs):
    if conteneurs.get(noeud):
        return docker("start", conteneurs[noeud])
    return docker("compose", "start", noeud)


def etat_cluster(reference):
    """État des nœuds vu depuis le nœud `reference`, ou None si le cluster ne répond pas."""
    code, sortie, _ = docker("compose", "exec", "-T", reference, "./cockroach",
                             "node", "status", "--insecure", "--format=csv", timeout=60)
    if code != 0 or not sortie:
        return None
    try:
        lignes = list(csv.DictReader(io.StringIO(sortie)))
        return [(l["id"], l["locality"], l["is_available"], l["is_live"]) for l in lignes]
    except Exception:
        return None


def afficher_etat(titre, reference):
    etat = etat_cluster(reference)
    print(f"  {titre}")
    if etat is None:
        print("     (état indisponible : le cluster ne répond plus)")
        return
    for id_, loc, dispo, vivant in etat:
        print(f"     nœud {id_} | {loc:<16} | disponible : {dispo:<5} | vivant : {vivant}")


def attendre_cluster(reference, limite=120):
    """Attend que les 4 nœuds soient vivants. Retourne la durée d'attente, ou None."""
    debut = time.time()
    while time.time() - debut < limite:
        etat = etat_cluster(reference)
        if etat and len(etat) >= len(NOEUDS) and all(l[3] == "true" for l in etat):
            return time.time() - debut
        time.sleep(3)
    return None


def preparer(conn, produits_par_region):
    """Crée un client (Europe) et des produits à fort stock dans les 4 régions."""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO clients (region, nom, email)
               VALUES ('europe', %s, 'chaos@test.local') RETURNING id""",
            (NOM_CLIENT,),
        )
        client = ("europe", cur.fetchone()[0])
        produits = []
        for region in REGIONS:
            for _ in range(produits_par_region):
                cur.execute(
                    """INSERT INTO produits (region, nom, prix, stock)
                       VALUES (%s, %s, %s, %s) RETURNING id""",
                    (region, NOM_PRODUIT, PRIX, STOCK),
                )
                produits.append((region, cur.fetchone()[0]))
    conn.commit()
    return client, produits


def nettoyer(conn):
    """Supprime toutes les données de ce test (reconnaissables à leur nom)."""
    condition = (f"client_id IN (SELECT id FROM clients WHERE nom = '{NOM_CLIENT}') "
                 f"OR produit_id IN (SELECT id FROM produits WHERE nom = '{NOM_PRODUIT}')")
    with conn.cursor() as cur:
        cur.execute("DELETE FROM factures WHERE commande_id IN "
                    f"(SELECT id FROM commandes WHERE {condition})")
        cur.execute(f"DELETE FROM commandes WHERE {condition}")
        cur.execute("DELETE FROM produits WHERE nom = %s", (NOM_PRODUIT,))
        cur.execute("DELETE FROM clients WHERE nom = %s", (NOM_CLIENT,))
    conn.commit()


# ------------------------------------------------------------------------- ouvriers

def ouvrier(t0, fin, client, produits, confirmees, abandonnees, journal, erreurs):
    """Passe des commandes en continu ; rejoue la même commande après une panne."""
    conn = None
    while time.time() < fin:
        region, produit_id = random.choice(produits)
        panier = str(uuid.uuid4())
        tentatives = 0
        debut = time.time()
        while True:
            tentatives += 1
            try:
                if conn is None:
                    conn = connecter_chaos()
                statut, _ = passer_commande(conn, client, [(region, produit_id, 1)],
                                            panier_id=panier)
                confirmees[panier] = statut
                journal.append((time.time() - t0, statut, tentatives, time.time() - debut))
                break
            except (StockInsuffisant, ProduitInconnu):
                journal.append((time.time() - t0, "REFUS", tentatives, time.time() - debut))
                break
            except Exception as e:
                # Connexion perdue, délai dépassé ou résultat incertain : on se reconnecte
                # puis on REJOUE le même panier (l'idempotence évite tout doublon).
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = None
                texte = str(e).strip().splitlines()[0][:70] if str(e).strip() else ""
                code = getattr(e, "pgcode", "") or ""
                erreurs.append((time.time() - t0, f"{type(e).__name__} {code} {texte}".strip()))
                if time.time() > fin + DELAI_GRACE:
                    abandonnees.append(panier)
                    break
                time.sleep(0.5)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- analyse

def afficher_chronologie(oks, erreurs_t, evenements, duree_totale, pas=2):
    n = int(duree_totale // pas) + 1
    ok, ko = [0] * n, [0] * n
    for t in oks:
        ok[min(n - 1, int(t // pas))] += 1
    for t in erreurs_t:
        ko[min(n - 1, int(t // pas))] += 1
    maxi = max(ok) or 1
    print("   t (s)     commandes confirmées               confirmées  erreurs vues")
    for i in range(n):
        marques = " ".join(f"<-- {lib}" for t, lib in evenements
                           if min(n - 1, int(t // pas)) == i)
        barre = "#" * round(30 * ok[i] / maxi)
        print(f"  {i * pas:3d}-{(i + 1) * pas:3d}   {barre:<30}   {ok[i]:6d}   {ko[i]:6d}   {marques}")


def debit(oks, a, b):
    return sum(1 for t in oks if a <= t < b) / (b - a) if b > a else 0.0


def verifier(client, produits):
    """Compare la base à ce que les clients ont vu confirmer (avec réessais : le cluster
    peut être encore en train de se stabiliser)."""
    rc, cid = client
    for _ in range(5):
        try:
            conn = connecter()
            ids_base = {r[0] for r in requete(
                conn, "SELECT id FROM commandes WHERE region = %s AND client_id = %s",
                (rc, cid))}
            qte = int(requete(
                conn, "SELECT coalesce(sum(quantite), 0) FROM commandes "
                      "WHERE region = %s AND client_id = %s", (rc, cid))[0][0])
            nb_fact, montant = requete(
                conn, """SELECT count(*), coalesce(sum(montant), 0) FROM factures
                          WHERE region = %s AND commande_id IN
                            (SELECT id FROM commandes WHERE region = %s AND client_id = %s)""",
                (rc, rc, cid))[0]
            stock_total, stock_min = requete(
                conn, "SELECT coalesce(sum(stock), 0), coalesce(min(stock), 0) "
                      "FROM produits WHERE nom = %s", (NOM_PRODUIT,))[0]
            conn.close()
            return dict(ids_base=ids_base, qte=qte, nb_fact=int(nb_fact),
                        montant=montant, stock_total=int(stock_total),
                        stock_min=int(stock_min))
        except Exception:
            time.sleep(5)
    return None


# ------------------------------------------------------------------------------ main

def main():
    p = argparse.ArgumentParser(description="Test de chaos GlobalShop")
    p.add_argument("--noeuds", default="roach2",
                   help="nœud(s) à tuer, séparés par des virgules (ex. roach2,roach3), "
                        "ou « aucun » pour un essai témoin sans panne")
    p.add_argument("--ouvriers", type=int, default=16)
    p.add_argument("--duree", type=int, default=70, help="durée des écritures (s)")
    p.add_argument("--kill-a", type=int, default=15, help="instant de la panne (s)")
    p.add_argument("--redemarrer-a", type=int, default=45, help="instant du retour (s)")
    p.add_argument("--sans-redemarrage", action="store_true")
    p.add_argument("--produits-par-region", type=int, default=8)
    p.add_argument("--garder", action="store_true",
                   help="conserver les données de test après le test")
    args = p.parse_args()

    temoin = args.noeuds.strip().lower() == "aucun"   # essai témoin : aucune panne
    noeuds = [] if temoin else [x.strip() for x in args.noeuds.split(",") if x.strip()]
    if (not noeuds and not temoin) or any(x not in NOEUDS for x in noeuds):
        sys.exit(f"--noeuds doit contenir des noms parmi : {', '.join(NOEUDS)} "
                 f"(ou « aucun »)")
    if len(noeuds) >= len(NOEUDS):
        sys.exit("Il faut laisser au moins un nœud en vie.")
    redemarrer = None if args.sans_redemarrage else args.redemarrer_a
    if not 0 < args.kill_a < args.duree or (
            redemarrer is not None and not args.kill_a < redemarrer < args.duree):
        sys.exit("Les instants doivent respecter : 0 < kill-a < redemarrer-a < duree")
    reference = next(n for n in NOEUDS if n not in noeuds)
    etiquette = "temoin" if temoin else "-".join(noeuds)

    print("=" * 70)
    print(f" TEST DE CHAOS | panne de : "
          f"{'aucune (essai témoin)' if temoin else ', '.join(noeuds)} | "
          f"{args.ouvriers} ouvriers")
    print(f" panne à t={args.kill_a}s | retour à "
          f"{'jamais' if redemarrer is None else f't={redemarrer}s'} | durée {args.duree}s")
    print("=" * 70)

    # 0. Préparation
    admin = connecter()
    nettoyer(admin)
    client, produits = preparer(admin, args.produits_par_region)
    admin.close()
    print(f"{len(produits)} produits de test créés ({STOCK} en stock chacun), "
          f"client en région {client[0]}.")
    afficher_etat("État du cluster AVANT la panne :", reference)

    # Identifiants des conteneurs, résolus AVANT la panne (pour tuer sans délai)
    conteneurs = {}
    for n in noeuds:
        code, sortie, _ = docker("compose", "ps", "-q", n)
        conteneurs[n] = sortie.splitlines()[0] if code == 0 and sortie else None

    # 1. Écritures en continu
    confirmees, abandonnees, journal, erreurs = {}, [], [], []
    t0 = time.time()
    fin = t0 + args.duree
    threads = [threading.Thread(target=ouvrier, args=(
        t0, fin, client, produits, confirmees, abandonnees, journal, erreurs))
        for _ in range(args.ouvriers)]
    for t in threads:
        t.start()
    print(f"\n[t=  0.0s] {args.ouvriers} ouvriers au travail...")

    def attendre(instant):
        while time.time() < t0 + instant:
            time.sleep(0.05)

    evenements = []

    # 2. La panne (le marqueur est posé AU MOMENT de l'envoi de la commande)
    attendre(args.kill_a)
    if temoin:
        evenements.append((time.time() - t0, "TEMOIN (aucune panne)"))
        print(f"[t={time.time() - t0:5.1f}s] essai témoin : aucune panne provoquée")
    for n in noeuds:
        t = time.time() - t0
        code, _, err = tuer(n, conteneurs)
        evenements.append((t, f"PANNE {n}"))
        print(f"[t={t:5.1f}s] kill {n} -> "
              f"{'OK (arrêt brutal)' if code == 0 else 'ECHEC : ' + err}")
    time.sleep(3)
    if noeuds:
        afficher_etat(f"État du cluster à t={time.time() - t0:.0f}s (nœud(s) tué(s)) :",
                      reference)

    # 3. Le retour des nœuds
    if redemarrer is not None and noeuds:
        attendre(redemarrer)
        for n in noeuds:
            t = time.time() - t0
            code, _, err = relancer(n, conteneurs)
            evenements.append((t, f"RETOUR {n}"))
            print(f"[t={t:5.1f}s] start {n} -> "
                  f"{'OK' if code == 0 else 'ECHEC : ' + err}")

    for t in threads:
        t.join()
    duree_reelle = time.time() - t0
    print(f"[t={duree_reelle:5.1f}s] fin des écritures.")

    retour = None
    if redemarrer is not None:
        retour = attendre_cluster(reference)
        print("  Retour à 4 nœuds vivants : "
              + (f"{retour:.0f} s après la fin des écritures" if retour is not None
                 else "NON atteint après 120 s"))
        afficher_etat("État du cluster APRÈS le retour :", reference)

    # 4. Résultats côté clients
    oks = [j[0] for j in journal if j[1] in ("OK", "DEJA_TRAITEE")]
    rejoues = sum(1 for j in journal if j[2] > 1)
    deja = sum(1 for j in journal if j[1] == "DEJA_TRAITEE")
    types_erreurs = Counter(e[1] for e in erreurs)
    t_panne = args.kill_a
    t_retour = redemarrer if redemarrer is not None else args.duree

    print("\n--- CE QUE LES CLIENTS ONT VÉCU ---")
    print(f"  Commandes confirmées                 : {len(confirmees)}")
    print(f"  Commandes rejouées après une erreur  : {rejoues}")
    print(f"  dont déjà enregistrées avant la panne: {deja} "
          f"(la réponse s'est perdue, pas la commande)")
    print(f"  Commandes abandonnées                : {len(abandonnees)}")
    print(f"  Erreurs vues par les clients         : {len(erreurs)}")
    for message, nb in types_erreurs.most_common(4):
        print(f"      {nb:4d} x {message}")

    ecarts = [(b - a, a) for a, b in zip(sorted(oks), sorted(oks)[1:]) if b >= t_panne - 1]
    plus_long, depuis = max(ecarts) if ecarts else (0.0, 0.0)
    print("\n--- DISPONIBILITÉ ---")
    print(f"  Débit avant la panne    : {debit(oks, 0, t_panne):6.1f} commandes/s")
    print(f"  Débit pendant la panne  : {debit(oks, t_panne, t_retour):6.1f} commandes/s")
    if redemarrer is not None:
        print(f"  Débit après le retour   : {debit(oks, t_retour, args.duree):6.1f} commandes/s")
    print(f"  Plus longue interruption sans aucune commande confirmée : "
          f"{plus_long:.1f} s (à partir de t={depuis:.1f}s)")
    print("\n--- CHRONOLOGIE ---")
    afficher_chronologie(oks, [e[0] for e in erreurs], evenements, duree_reelle)

    # 5. Vérification dans la base
    print("\n--- VÉRIFICATION DANS LA BASE ---")
    base = verifier(client, produits)
    if base is None:
        print("  Impossible de lire la base (cluster indisponible).")
        if noeuds:
            print("  Redémarre les nœuds : docker compose start " + " ".join(noeuds))
        return 2
    ids_confirmees = {id_ligne(pan, 0) for pan in confirmees}
    ids_abandon = {id_ligne(pan, 0) for pan in abandonnees}
    perdues = ids_confirmees - base["ids_base"]
    jamais_confirmees = base["ids_base"] - ids_confirmees
    stock_initial = STOCK * len(produits)
    retire = stock_initial - base["stock_total"]
    controles = [
        ("Aucune commande confirmée n'a été perdue", len(perdues) == 0,
         f"{len(perdues)} perdue(s) sur {len(ids_confirmees)} confirmées"),
        ("Stock cohérent avec les ventes (aucune survente)", retire == base["qte"],
         f"{retire} unités retirées du stock, {base['qte']} vendues"),
        ("Commandes = factures", base["nb_fact"] == len(base["ids_base"]),
         f"{len(base['ids_base'])} commandes, {base['nb_fact']} factures"),
        ("Montant facturé correct", base["montant"] == PRIX * base["qte"],
         f"{base['montant']} (attendu {PRIX * base['qte']})"),
        ("Stock jamais négatif", base["stock_min"] >= 0, f"minimum {base['stock_min']}"),
    ]
    for nom, ok, detail in controles:
        print(f"  [{'PASS ' if ok else 'ECHEC'}] {nom} : {detail}")
    integrite = all(ok for _, ok, _ in controles)
    print(f"\n  Pour information :")
    print(f"    commandes en base jamais confirmées au client : {len(jamais_confirmees)} "
          f"(validées juste avant la panne, réponse perdue)")
    print(f"    commandes abandonnées retrouvées en base      : "
          f"{len(ids_abandon & base['ids_base'])} sur {len(ids_abandon)}")
    print("\n" + ("=== INTÉGRITÉ GARANTIE ===" if integrite else "=== INTÉGRITÉ VIOLÉE ==="))

    # 6. Sauvegarde des résultats
    dossier = Path("resultats")
    dossier.mkdir(exist_ok=True)
    fichier = dossier / f"chaos_{etiquette}_{datetime.now():%Y%m%d_%H%M%S}.json"
    fichier.write_text(json.dumps({
        "parametres": vars(args),
        "evenements": [dict(t=round(t, 1), evenement=lib) for t, lib in evenements],
        "clients": dict(confirmees=len(confirmees), rejouees=rejoues,
                        deja_enregistrees=deja, abandonnees=len(abandonnees),
                        erreurs_vues=len(erreurs),
                        types_erreurs=dict(types_erreurs.most_common())),
        "disponibilite": dict(
            debit_avant=round(debit(oks, 0, t_panne), 1),
            debit_pendant=round(debit(oks, t_panne, t_retour), 1),
            debit_apres=(round(debit(oks, t_retour, args.duree), 1)
                         if redemarrer is not None else None),
            interruption_max_s=round(plus_long, 1),
            retour_4_noeuds_s=None if retour is None else round(retour)),
        "base": dict(commandes=len(base["ids_base"]), factures=base["nb_fact"],
                     quantite_vendue=base["qte"], montant=base["montant"],
                     jamais_confirmees=len(jamais_confirmees)),
        "integrite_garantie": integrite,
        "controles": [dict(nom=nom, ok=ok, detail=detail) for nom, ok, detail in controles],
    }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"Résultats enregistrés : {fichier}")

    # 7. Nettoyage
    if redemarrer is None and noeuds:
        print("\nLe(s) nœud(s) est (sont) toujours arrêté(s). Pour le(s) relancer :")
        print("   docker compose start " + " ".join(noeuds))
    if not args.garder:
        for _ in range(3):
            try:
                c = connecter()
                nettoyer(c)
                c.close()
                print("Données de test supprimées.")
                break
            except Exception:
                time.sleep(2)
        else:
            print("Nettoyage impossible : il sera fait au prochain lancement.")
    return 0 if integrite else 1


if __name__ == "__main__":
    sys.exit(main())