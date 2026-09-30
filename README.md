# GlobalShop : base de données distribuée résiliente

## Architecture
Cluster CockroachDB de 4 nœuds (Afrique, Europe, Amérique, Asie), partitionné par région (clé primaire `(region, id)`), 3 copies par donnée.
(on va ajouter le schéma d'architecture plus tard quand on termine.)

## Prérequis
- Docker Desktop
- Python 3 et `pip install psycopg2-binary` (pour les tests)

## Démarrage
## Démarrage

Prérequis : Docker Desktop lancé.

    git clone https://github.com/Sokhnadiarra166/globalshop.git
    cd globalshop
    docker compose up -d

Attendre environ 2 minutes, puis vérifier :

    docker compose logs init

Le message "Initialisation terminee." confirme que le cluster, le schéma, le partitionnement et les données de test sont en place.

Interface web CockroachDB : http://localhost:8080

## Arrêt et reprise

    docker compose stop      # arrêt sans perte de données
    docker compose up -d     # reprise
    docker compose down -v   # repart de zéro (efface les données)

## Structure du dépôt
- docker-compose.yml : le cluster
- SQL/ : schéma, données de test, placement par région, fonctionnalités
- tests/ : test de concurrence (100 achats)

## Tests
Comment lancer `python tests/test_concurrence.py` et quel résultat attendre (10 succès, 90 refus, stock final 0).

