import threading
import time
import psycopg2
from psycopg2 import errors

DSN = "postgresql://root@localhost:26257/globalshop?sslmode=disable"
PRODUIT = "00000000-0000-0000-0000-000000000001"
NB_ACHATS = 100
STOCK_INITIAL = 10

ACHAT = """
WITH maj AS (
  UPDATE produits SET stock = stock - 1
  WHERE region = 'afrique' AND id = %s::UUID AND stock >= 1
  RETURNING region, id
)
INSERT INTO commandes (region, client_id, produit_region, produit_id, quantite)
SELECT %s::STRING, %s::UUID, maj.region, maj.id, 1 FROM maj
"""

resultats = {"succes": 0, "refus": 0, "erreurs": 0}
verrou = threading.Lock()
depart = threading.Barrier(NB_ACHATS)


def preparer():
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("DELETE FROM commandes WHERE produit_id = %s::UUID", (PRODUIT,))
    cur.execute("UPDATE produits SET stock = %s WHERE region = 'afrique' AND id = %s::UUID",
                (STOCK_INITIAL, PRODUIT))
    cur.execute("SELECT region, id FROM clients LIMIT %s", (NB_ACHATS,))
    clients = cur.fetchall()
    conn.close()
    return clients


def acheter(region, client_id):
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    cur = conn.cursor()
    depart.wait()  # tous les threads partent en même temps
    statut = "erreurs"
    for _ in range(5):  # nouvelle tentative si conflit de sérialisation
        try:
            cur.execute(ACHAT, (PRODUIT, region, client_id))
            statut = "succes" if cur.rowcount == 1 else "refus"
            break
        except errors.SerializationFailure:
            time.sleep(0.05)
        except Exception as e:
            print("Erreur :", e)
            break
    conn.close()
    with verrou:
        resultats[statut] += 1


if __name__ == "__main__":
    clients = preparer()
    print(f"Départ : {NB_ACHATS} achats simultanés, stock initial = {STOCK_INITIAL}")
    debut = time.time()
    threads = [threading.Thread(target=acheter, args=(r, str(i))) for r, i in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    duree = time.time() - debut

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT stock FROM produits WHERE region = 'afrique' AND id = %s::UUID", (PRODUIT,))
    stock_final = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM commandes WHERE produit_id = %s::UUID", (PRODUIT,))
    nb_commandes = cur.fetchone()[0]

    print(f"Durée : {duree:.2f} s")
    print(f"Succès : {resultats['succes']} | Refus : {resultats['refus']} | Erreurs : {resultats['erreurs']}")
    print(f"Stock final : {stock_final} | Commandes créées : {nb_commandes}")
    print("OK : pas de survente" if stock_final >= 0 and nb_commandes == STOCK_INITIAL
          else "PROBLÈME : incohérence détectée")