USE globalshop;

-- 1. Inscription d'un client
INSERT INTO clients (region, nom, email)
VALUES ('afrique', 'Client Test', 'test@globalshop.test')
RETURNING id, region, nom;

-- 2. Création d'un produit
INSERT INTO produits (region, nom, prix, stock)
VALUES ('europe', 'Casque audio', 79.90, 25)
RETURNING id, region, nom, stock;

-- 3. Catalogue : lecture distribuée sur toutes les régions
SELECT region, count(*) AS nb_produits, sum(stock) AS stock_total
FROM produits GROUP BY region ORDER BY region;

-- 4. Commande : un client d'Europe achète le produit test d'Afrique
WITH maj AS (
  UPDATE produits SET stock = stock - 1
  WHERE region = 'afrique'
    AND id = '00000000-0000-0000-0000-000000000001'
    AND stock >= 1
  RETURNING region, id
)
INSERT INTO commandes (region, client_id, produit_region, produit_id, quantite)
SELECT 'europe', (SELECT id FROM clients WHERE region = 'europe' LIMIT 1),
       maj.region, maj.id, 1
FROM maj
RETURNING id, region, produit_region, statut;

-- Vérification du stock restant
SELECT nom, stock FROM produits
WHERE id = '00000000-0000-0000-0000-000000000001';