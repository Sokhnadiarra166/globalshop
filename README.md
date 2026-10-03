# GlobalShop : base de données distribuée résiliente

## Architecture

Cluster CockroachDB de 4 nœuds répartis par région :

* Afrique
* Europe
* Amérique
* Asie

Les données sont partitionnées par région avec une clé primaire `(region, id)` et bénéficient de 3 copies pour assurer la résilience du cluster.

> Le schéma d'architecture sera ajouté ultérieurement.

## Prérequis

* Docker Desktop
* Python 3
* Git Bash ou WSL sous Windows

Installer les dépendances Python depuis la racine du projet :

```bash
pip install -r requirements.txt
```

Le fichier `requirements.txt` contient les dépendances nécessaires aux tests, notamment `psycopg2-binary`.

## Démarrage

Prérequis : Docker Desktop doit être lancé.

```bash
git clone https://github.com/Sokhnadiarra166/globalshop.git
cd globalshop
docker compose up -d
```

Attendre environ 2 minutes, puis vérifier l'initialisation :

```bash
docker compose logs init
```

Le message `Initialisation terminee.` confirme que le cluster, le schéma, le partitionnement et les données de test sont en place.

Interface web CockroachDB :

```text
http://localhost:8080
```

## Arrêt et reprise

Arrêter le cluster sans supprimer les données :

```bash
docker compose stop
```

Reprendre le cluster :

```bash
docker compose up -d
```

Repartir de zéro en supprimant les données :

```bash
docker compose down -v
```

## Structure du dépôt

* `docker-compose.yml` : configuration du cluster CockroachDB et de HAProxy
* `sql/` : schéma, données de test, placement par région et fonctionnalités
* `tests/` : tests de fonctionnalités, de charge et de chaos
* `resultats/` : résultats détaillés des tests au format JSON
* `docs/` : documentation et éléments graphiques du projet
* `demo.sh` : script de démonstration automatisée
* `requirements.txt` : dépendances Python nécessaires aux tests

## Tests

Le test de charge permet de vérifier le comportement du système lors de commandes concurrentes.

```bash
python tests/charge.py
```

Avec un stock initial de 10 unités et 100 acheteurs concurrents, le résultat attendu est :

* 10 commandes acceptées ;
* 90 commandes refusées faute de stock ;
* 0 erreur technique ;
* stock final égal à 0 ;
* intégrité des données garantie.

## Démonstration et tests

Le script `demo.sh` permet d'exécuter automatiquement les principales fonctionnalités et les tests de résilience.

```bash
bash demo.sh
```

Cette commande exécute :

* le démarrage et la vérification du cluster ;
* la démonstration des fonctionnalités principales ;
* le test de charge ;
* le test de chaos avec panne brutale d'un nœud.

**Durée : environ 4 à 5 minutes.**

Version rapide, sans chaos :

```bash
bash demo.sh --sans-chaos
```

Cette version exécute les fonctionnalités et le test de charge en environ **1 minute**.

Pour ajouter le scénario de perte de quorum :

```bash
bash demo.sh --avec-quorum
```

### Exécution manuelle

Sous Windows, utiliser **Git Bash** ou **WSL**.

Depuis la racine du projet :

```bash
python tests/demo_fonctionnalites.py
python tests/charge.py
python tests/chaos.py
```

Pour tester la perte de deux nœuds :

```bash
python tests/chaos.py --noeuds roach2,roach3
```

Les résultats détaillés sont enregistrés automatiquement dans `resultats/`.

