#!/usr/bin/env bash
# Démonstration complète de GlobalShop (base de données distribuée résiliente).
# Usage : bash demo.sh [--sans-chaos] [--avec-quorum]

cd "$(dirname "$0")" || exit 1

SANS_CHAOS=0
AVEC_QUORUM=0

for arg in "$@"; do
  case "$arg" in
    --sans-chaos) SANS_CHAOS=1 ;;
    --avec-quorum) AVEC_QUORUM=1 ;;
    *) echo "Option inconnue : $arg"; exit 1 ;;
  esac
done

etape() {
  echo
  echo "=================================================================="
  echo " $1"
  echo "=================================================================="
}

statut() {
  if [ "$1" -eq 0 ]; then
    echo "OK"
  else
    echo "ECHEC"
  fi
}

# --- Pré-requis ---------------------------------------------------------------
etape "0. Pré-requis"

command -v docker >/dev/null 2>&1 || {
  echo "Docker est introuvable."
  exit 1
}

docker info >/dev/null 2>&1 || {
  echo "Docker n'est pas démarré (lance Docker Desktop)."
  exit 1
}

PYTHON=""

for p in python3 python py; do
  if command -v "$p" >/dev/null 2>&1 &&
     "$p" -c "import psycopg2" >/dev/null 2>&1; then
    PYTHON="$p"
    break
  fi
done

[ -n "$PYTHON" ] || {
  echo "Python 3 avec psycopg2 introuvable."
  echo "Installe les dépendances avec : pip install -r requirements.txt"
  exit 1
}

echo "Docker OK | Python : $PYTHON"

# --- Cluster ------------------------------------------------------------------
etape "1. Démarrage du cluster (4 nœuds CockroachDB + HAProxy), une seule commande"

docker compose up -d || exit 1

echo "Attente de l'initialisation (schéma, placement par région, données)..."

for _ in $(seq 1 90); do
  docker compose logs init 2>/dev/null |
    grep -q "Initialisation terminee" && break
  sleep 3
done

docker compose logs init 2>/dev/null |
  grep -q "Initialisation terminee" ||
  {
    echo "Le cluster n'est pas initialisé après 4 minutes."
    exit 1
  }

# --- Stabilisation ------------------------------------------------------------
echo "Stabilisation du cluster (réplication des données initiales)..."

for _ in $(seq 1 40); do
  SOUS_REPLIQUEES=$(
    docker compose exec -T roach1 ./cockroach sql --insecure --format=csv \
      -e "SELECT count(*) FROM crdb_internal.ranges WHERE array_length(replicas, 1) < 3" \
      2>/dev/null |
      tail -n 1 |
      tr -d '\r'
  )

  [ "$SOUS_REPLIQUEES" = "0" ] && break

  sleep 3
done

sleep 15

docker compose exec -T roach1 ./cockroach node status --insecure 2>/dev/null |
  cut -c1-120

# --- Fonctionnalités ----------------------------------------------------------
etape "2. Fonctionnalités : inscription, produit, catalogue, commande distribuée"

"$PYTHON" tests/demo_fonctionnalites.py
R_FONC=$?

# --- Charge -------------------------------------------------------------------
etape "3. Test de charge : 100 achats simultanés sur un produit en stock limité (10)"

"$PYTHON" tests/charge.py
R_CHARGE=$?

# --- Chaos --------------------------------------------------------------------
R_CHAOS="-"
R_QUORUM="-"

if [ "$SANS_CHAOS" -eq 0 ]; then

  etape "4. Chaos : arrêt brutal d'un nœud pendant l'écriture, puis retour"

  sleep 30

  "$PYTHON" tests/chaos.py \
    --kill-a 15 \
    --redemarrer-a 45 \
    --duree 70

  R_CHAOS=$?

  if [ "$AVEC_QUORUM" -eq 1 ]; then

    etape "5. Chaos : perte de deux nœuds (perte du quorum), puis retour"

    sleep 60

    "$PYTHON" tests/chaos.py \
      --noeuds roach2,roach3 \
      --kill-a 15 \
      --redemarrer-a 45 \
      --duree 90

    R_QUORUM=$?

  fi
fi

# --- Bilan --------------------------------------------------------------------
etape "BILAN"

echo " Fonctionnalités            : $(statut $R_FONC)"
echo " Test de charge (100 achats): $(statut $R_CHARGE)"

if [ "$SANS_CHAOS" -eq 0 ]; then
  echo " Chaos, 1 nœud tué          : $(statut $R_CHAOS)"
  [ "$AVEC_QUORUM" -eq 1 ] &&
    echo " Chaos, 2 nœuds tués        : $(statut $R_QUORUM)"
fi

echo " Résultats détaillés        : dossier resultats/"

[ "$R_FONC" -eq 0 ] &&
[ "$R_CHARGE" -eq 0 ] &&
{
  [ "$R_CHAOS" = "-" ] || [ "$R_CHAOS" -eq 0 ]
} &&
{
  [ "$R_QUORUM" = "-" ] || [ "$R_QUORUM" -eq 0 ]
}

exit $?