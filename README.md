# PIE Manager

**Portefeuille Investissement Épargne** — Application de suivi de portefeuille d'investissement auto-hébergée.

PIE Manager permet de suivre plusieurs portefeuilles d'investissement depuis une interface web locale, sans dépendance à un service tiers. Toutes les données restent sur votre machine.

---

## Fonctionnalités

- **Multi-portefeuille** — suivi de plusieurs portefeuilles (foyers fiscaux séparés)
- **Positions et titres** — actions, ETF, devises, or, SICAV
- **Dashboard** — vue synthétique de la valeur totale, répartition par compte et par pool
- **Plus-values (CUMP/WACOP)** — calcul automatique des plus-values latentes et réalisées
- **Rééquilibrage** — outil de rééquilibrage par rapport aux allocations cibles
- **Prix manuels** — saisie manuelle des prix pour les produits non cotés
- **Synchronisation Yahoo Finance** — mise à jour des cours toutes les 15 minutes
- **Snapshots journaliers** — historique de valorisation (jours ouvrés)
- **Sauvegarde et restauration** — depuis l'interface d'administration

---

## Prérequis

| Élément | Détail |
|---------|--------|
| Système | Linux (Fedora, Ubuntu ou compatible) |
| Podman | `podman` et `podman-compose` ou `podman compose` (plugin) |

> **Windows** : supporté via WSL2 + Podman Desktop. Voir [docs/INSTALLATION.md](docs/INSTALLATION.md).

---

## Installation rapide

```bash
gh release download --repo lautou/pie-manager --pattern 'pie-manager-linux-amd64' --dir ~/Downloads/ --clobber
chmod +x ~/Downloads/pie-manager-linux-amd64
~/Downloads/pie-manager-linux-amd64 install
```

L'installateur demande votre token GitHub, télécharge les images, configure les services et ouvre l'application.

Après l'installation, l'application est accessible via l'icône GNOME ou :

```bash
pie-manager start
```

Pour le guide d'installation détaillé : [docs/INSTALLATION.md](docs/INSTALLATION.md).

---

## Mise à jour

Même commande que l'installation initiale. L'installateur détecte la version existante et propose de faire une sauvegarde avant de mettre à jour.

```bash
~/Downloads/pie-manager-linux-amd64 install
```

---

## Désinstallation

```bash
# Arrêter et supprimer les containers
podman compose -f ~/.local/share/pie-manager/compose-prod.yaml down --volumes

# Supprimer les fichiers installés
rm -rf ~/.local/share/pie-manager
rm -f ~/.local/bin/pie-manager
rm -f ~/.local/share/applications/pie-manager.desktop
rm -f ~/.local/share/icons/hicolor/scalable/apps/pie-manager.svg
rm -f ~/.local/share/icons/hicolor/64x64/apps/pie-manager.png
rm -rf ~/.config/pie-manager
```

---

## Stack technique

| Couche | Technologie |
|--------|-------------|
| Frontend | React 18 + TypeScript + PatternFly 5 |
| Backend | Python FastAPI + SQLAlchemy 2.0 async + Celery |
| Base de données | PostgreSQL 16 |
| Cache / Queue | Redis 7 |
| Déploiement | Podman Compose + Nginx |
| Installateur | Go (binaire statique, aucun prérequis) |

---

## Architecture

En production, un seul port est exposé (14943 par défaut, détection automatique si occupé). Nginx sert de point d'entrée unique et route les requêtes vers le frontend et le backend. Les containers backend et frontend n'ont pas de port exposé directement.

```
Navigateur / Fenêtre native
        │
        ▼
   nginx :14943
   ├── /api/* → backend :8000 (FastAPI)
   └── /*     → frontend (Nginx statique)
```

Les images sont versionnées et publiées sur GitHub Container Registry (`ghcr.io/lautou/pie-manager-*`).

---

## Développement

```bash
# Démarrer tous les services en mode développement
podman compose up -d

# Reconstruire le backend après une modification
podman compose up -d --build backend

# Accéder à la base de données
podman exec pie-manager_postgres_1 psql -U pie -d pie_db
```

Frontend accessible sur `http://localhost:5173`, backend sur `http://localhost:8000`.

---

## Sauvegarde

L'interface d'administration (Administration système → Télécharger une sauvegarde) permet de télécharger une sauvegarde complète de la base de données au format `.dump`.

Guide détaillé : [docs/SAUVEGARDE.md](docs/SAUVEGARDE.md).

---

---

## Sécurité et signature de code

Les binaires Windows sont signés par [SignPath Foundation](https://signpath.org), qui fournit gratuitement des services de signature de code aux projets open source.

[![Signed by SignPath Foundation](https://signpath.org/assets/badges/signpath-oss-badge.svg)](https://signpath.org)

---

## Licence

[AGPL-3.0-or-later](LICENSE) — Copyright © 2025-2026 Laurent Tourreau.
