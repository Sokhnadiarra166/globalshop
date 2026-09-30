# GlobalShop : base de données distribuée résiliente

## Architecture
Cluster CockroachDB de 4 nœuds (Afrique, Europe, Amérique, Asie), partitionné par région (clé primaire `(region, id)`), 3 copies par donnée.
(on va ajouter le schéma d'architecture plus tard quand on termine.)

## Prérequis
- Docker Desktop
- Python 3 et `pip install psycopg2-binary` (pour les tests)

## Démarrage
docker compose up -d
(étapes d'initialisation à compléter une fois automatisées)

## Structure du dépôt
- docker-compose.yml : le cluster
- SQL/ : schéma, données de test, placement par région, fonctionnalités
- tests/ : test de concurrence (100 achats)

## Tests
Comment lancer `python tests/test_concurrence.py` et quel résultat attendre (10 succès, 90 refus, stock final 0).

