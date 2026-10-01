"""Outils communs : connexion au cluster, exceptions métier, transaction avec réessai."""
import random
import time

import psycopg2
from psycopg2 import extensions

# Connexion via HAProxy (port 26257) : il répartit entre les 4 nœuds.
DSN = dict(host="localhost", port=26257, user="root",
           dbname="globalshop", sslmode="disable", connect_timeout=5)

MAX_REESSAIS = 12
CODE_CONFLIT = "40001"  # CockroachDB : la transaction doit être rejouée


class StockInsuffisant(Exception):
    """Le stock ne permet pas de satisfaire la commande."""


class ProduitInconnu(Exception):
    """Le produit demandé n'existe pas."""


def connecter():
    conn = psycopg2.connect(**DSN)
    conn.set_isolation_level(extensions.ISOLATION_LEVEL_SERIALIZABLE)
    return conn


def executer_transaction(conn, travail, max_reessais=MAX_REESSAIS):
    """
    Exécute travail(curseur) dans UNE transaction.
    Si CockroachDB signale un conflit (code 40001), la transaction est annulée
    puis rejouée depuis le début, après une courte attente aléatoire.
    Retourne (résultat, nombre_de_réessais).
    """
    reessais = 0
    while True:
        try:
            with conn.cursor() as cur:
                resultat = travail(cur)
            conn.commit()
            return resultat, reessais
        except psycopg2.Error as e:
            _annuler(conn)
            if getattr(e, "pgcode", None) != CODE_CONFLIT or reessais >= max_reessais:
                raise
            reessais += 1
            time.sleep(random.uniform(0, min(1.0, 0.05 * 2 ** reessais)))
        except Exception:
            _annuler(conn)
            raise


def _annuler(conn):
    try:
        conn.rollback()
    except Exception:
        pass  # connexion déjà perdue (panne d'un nœud, par exemple)