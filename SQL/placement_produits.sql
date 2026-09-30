ALTER PARTITION afrique OF TABLE globalshop.produits CONFIGURE ZONE USING
  num_replicas = 3, constraints = '{"+region=afrique": 1}', lease_preferences = '[[+region=afrique]]';

ALTER PARTITION europe OF TABLE globalshop.produits CONFIGURE ZONE USING
  num_replicas = 3, constraints = '{"+region=europe": 1}', lease_preferences = '[[+region=europe]]';

ALTER PARTITION amerique OF TABLE globalshop.produits CONFIGURE ZONE USING
  num_replicas = 3, constraints = '{"+region=amerique": 1}', lease_preferences = '[[+region=amerique]]';

ALTER PARTITION asie OF TABLE globalshop.produits CONFIGURE ZONE USING
  num_replicas = 3, constraints = '{"+region=asie": 1}', lease_preferences = '[[+region=asie]]';