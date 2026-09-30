USE globalshop;

INSERT INTO clients (region, nom, email)
SELECT t.r, 'Client ' || t.r || ' ' || s.g, 'client' || s.g || '.' || t.r || '@globalshop.test'
FROM (VALUES ('afrique'),('europe'),('amerique'),('asie')) AS t(r),
     generate_series(1, 250) AS s(g);

INSERT INTO produits (region, nom, prix, stock)
SELECT t.r, 'Produit ' || t.r || ' ' || s.g, round((random()*100 + 5)::numeric, 2), 100
FROM (VALUES ('afrique'),('europe'),('amerique'),('asie')) AS t(r),
     generate_series(1, 50) AS s(g);

INSERT INTO produits (region, id, nom, prix, stock)
VALUES ('afrique', '00000000-0000-0000-0000-000000000001', 'Produit test Black Friday', 50.00, 10);