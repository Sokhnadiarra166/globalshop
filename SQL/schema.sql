CREATE DATABASE IF NOT EXISTS globalshop;
USE globalshop;

CREATE TABLE clients (
    region  STRING NOT NULL CHECK (region IN ('afrique','europe','amerique','asie')),
    id      UUID NOT NULL DEFAULT gen_random_uuid(),
    nom     STRING NOT NULL,
    email   STRING NOT NULL,
    cree_le TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (region, id)
);

CREATE TABLE produits (
    region  STRING NOT NULL CHECK (region IN ('afrique','europe','amerique','asie')),
    id      UUID NOT NULL DEFAULT gen_random_uuid(),
    nom     STRING NOT NULL,
    prix    DECIMAL(10,2) NOT NULL CHECK (prix >= 0),
    stock   INT NOT NULL CHECK (stock >= 0),
    PRIMARY KEY (region, id)
);

CREATE TABLE commandes (
    region         STRING NOT NULL,
    id             UUID NOT NULL DEFAULT gen_random_uuid(),
    client_id      UUID NOT NULL,
    produit_region STRING NOT NULL,
    produit_id     UUID NOT NULL,
    quantite       INT NOT NULL CHECK (quantite > 0),
    statut         STRING NOT NULL DEFAULT 'CONFIRMEE',
    cree_le        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (region, id),
    FOREIGN KEY (region, client_id) REFERENCES clients (region, id),
    FOREIGN KEY (produit_region, produit_id) REFERENCES produits (region, id)
);

CREATE TABLE factures (
    region      STRING NOT NULL,
    id          UUID NOT NULL DEFAULT gen_random_uuid(),
    commande_id UUID NOT NULL,
    montant     DECIMAL(12,2) NOT NULL,
    emise_le    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (region, id),
    FOREIGN KEY (region, commande_id) REFERENCES commandes (region, id)
);