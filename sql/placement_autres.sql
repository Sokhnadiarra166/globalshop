ALTER TABLE globalshop.clients PARTITION BY LIST (region) (PARTITION afrique VALUES IN ('afrique'), PARTITION europe VALUES IN ('europe'), PARTITION amerique VALUES IN ('amerique'), PARTITION asie VALUES IN ('asie'));
ALTER PARTITION afrique OF TABLE globalshop.clients CONFIGURE ZONE USING num_replicas = 3, constraints = '{"+region=afrique": 1}', lease_preferences = '[[+region=afrique]]';
ALTER PARTITION europe OF TABLE globalshop.clients CONFIGURE ZONE USING num_replicas = 3, constraints = '{"+region=europe": 1}', lease_preferences = '[[+region=europe]]';
ALTER PARTITION amerique OF TABLE globalshop.clients CONFIGURE ZONE USING num_replicas = 3, constraints = '{"+region=amerique": 1}', lease_preferences = '[[+region=amerique]]';
ALTER PARTITION asie OF TABLE globalshop.clients CONFIGURE ZONE USING num_replicas = 3, constraints = '{"+region=asie": 1}', lease_preferences = '[[+region=asie]]';

ALTER TABLE globalshop.commandes PARTITION BY LIST (region) (PARTITION afrique VALUES IN ('afrique'), PARTITION europe VALUES IN ('europe'), PARTITION amerique VALUES IN ('amerique'), PARTITION asie VALUES IN ('asie'));
ALTER PARTITION afrique OF TABLE globalshop.commandes CONFIGURE ZONE USING num_replicas = 3, constraints = '{"+region=afrique": 1}', lease_preferences = '[[+region=afrique]]';
ALTER PARTITION europe OF TABLE globalshop.commandes CONFIGURE ZONE USING num_replicas = 3, constraints = '{"+region=europe": 1}', lease_preferences = '[[+region=europe]]';
ALTER PARTITION amerique OF TABLE globalshop.commandes CONFIGURE ZONE USING num_replicas = 3, constraints = '{"+region=amerique": 1}', lease_preferences = '[[+region=amerique]]';
ALTER PARTITION asie OF TABLE globalshop.commandes CONFIGURE ZONE USING num_replicas = 3, constraints = '{"+region=asie": 1}', lease_preferences = '[[+region=asie]]';

ALTER TABLE globalshop.factures PARTITION BY LIST (region) (PARTITION afrique VALUES IN ('afrique'), PARTITION europe VALUES IN ('europe'), PARTITION amerique VALUES IN ('amerique'), PARTITION asie VALUES IN ('asie'));
ALTER PARTITION afrique OF TABLE globalshop.factures CONFIGURE ZONE USING num_replicas = 3, constraints = '{"+region=afrique": 1}', lease_preferences = '[[+region=afrique]]';
ALTER PARTITION europe OF TABLE globalshop.factures CONFIGURE ZONE USING num_replicas = 3, constraints = '{"+region=europe": 1}', lease_preferences = '[[+region=europe]]';
ALTER PARTITION amerique OF TABLE globalshop.factures CONFIGURE ZONE USING num_replicas = 3, constraints = '{"+region=amerique": 1}', lease_preferences = '[[+region=amerique]]';
ALTER PARTITION asie OF TABLE globalshop.factures CONFIGURE ZONE USING num_replicas = 3, constraints = '{"+region=asie": 1}', lease_preferences = '[[+region=asie]]';

