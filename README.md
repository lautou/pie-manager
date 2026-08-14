# PIE Manager

**Portefeuille Investissement Épargne** — Application de suivi de portefeuille d'investissement auto-hébergée.

PIE Manager permet de suivre plusieurs portefeuilles d'investissement depuis une interface web locale, sans dépendance à un service tiers. Toutes les données restent sur votre machine.

---

## Fonctionnalités

- **Multi-portefeuille** — suivi de plusieurs portefeuilles (foyers fiscaux séparés)
- **Positions et titres** — actions, ETF, devises, or, SICAV
- **Composition des ETF** — top 10 des avoirs et répartition sectorielle (clic sur un ticker)
- **Allocation réelle par pool** — recoupement des actions détenues en direct avec leur poids dans chaque ETF du pool, par secteur et par entreprise
- **Indicateurs macro** — croissance (actions/pétrole) et inflation (obligations/or) par zone géographique, zones entièrement configurables par l'utilisateur, écran indépendant du portefeuille
- **Performance des marchés** — classement Top 15 des pays dont la bourse a le plus progressé sur un an glissant, performance ajustée en EUR, univers de pays configurable
- **Dashboard** — vue synthétique de la valeur totale, répartition par compte et par pool
- **Plus-values (CUMP/WACOP)** — calcul automatique des plus-values latentes et réalisées
- **Rééquilibrage** — outil de rééquilibrage par rapport aux allocations cibles
- **Prix manuels** — saisie manuelle des prix pour les produits non cotés
- **Import Excel** — import en masse de transactions depuis un modèle Excel téléchargeable, avec prévisualisation, détection de doublons et validation avant import
- **Synchronisation Yahoo Finance** — mise à jour des cours toutes les 15 minutes
- **Snapshots journaliers** — historique de valorisation (jours ouvrés)
- **Sauvegarde et restauration** — depuis l'interface d'administration

---

## Prérequis

| Élément | Détail |
|---------|--------|
| Linux | Fedora, Ubuntu ou toute distribution compatible Podman |
| Windows | Windows 11 64-bit (WSL2 et Podman installés automatiquement) |
| macOS | Apple Silicon (arm64), macOS 14 Sonoma ou ultérieur (Podman installé automatiquement) |

---

## Installation rapide

### Linux (x86_64)

```bash
# Avec curl (recommandé — disponible sur toutes les distributions)
curl -LO https://github.com/lautou/pie-manager/releases/latest/download/pie-manager-linux-amd64
chmod +x pie-manager-linux-amd64
./pie-manager-linux-amd64 install
```

```bash
# Avec wget
wget https://github.com/lautou/pie-manager/releases/latest/download/pie-manager-linux-amd64
chmod +x pie-manager-linux-amd64
./pie-manager-linux-amd64 install
```

```bash
# Avec GitHub CLI (si gh est installé)
gh release download v1.0.0 --repo lautou/pie-manager \
  --pattern 'pie-manager-linux-amd64' --dir ~/Downloads/ --clobber
chmod +x ~/Downloads/pie-manager-linux-amd64
~/Downloads/pie-manager-linux-amd64 install
```

Après l'installation, l'application est accessible via l'icône GNOME ou :
```bash
pie-manager start
```

### Windows 11 (x86_64)

1. Télécharger [`pie-manager-windows-amd64.exe`](https://github.com/lautou/pie-manager/releases/latest/download/pie-manager-windows-amd64.exe) depuis la page des releases
2. Double-cliquer pour lancer
3. Si Windows SmartScreen bloque : cliquer **"Afficher plus" → "Exécuter quand même"**

L'installateur gère tout automatiquement : WSL2, Podman, images Docker, démarrage des services. Un redémarrage peut être nécessaire si WSL2 n'est pas encore installé — relancer simplement l'exe après.

Après l'installation, utiliser l'icône **PIE Manager** dans le menu Démarrer.

Pour le guide détaillé : [docs/INSTALLATION.md](docs/INSTALLATION.md).

### macOS (Apple Silicon)

```bash
curl -LO https://github.com/lautou/pie-manager/releases/latest/download/pie-manager-darwin-arm64
chmod +x pie-manager-darwin-arm64
xattr -d com.apple.quarantine pie-manager-darwin-arm64
./pie-manager-darwin-arm64 install
```

L'étape `xattr` est nécessaire une seule fois : le binaire n'est pas signé (voir "Sécurité et
signature de code" ci-dessous), et macOS Gatekeeper refuse sinon de l'exécuter en affichant
« impossible d'ouvrir » ou « fichier endommagé ».

L'installateur gère tout automatiquement : téléchargement et installation de Podman (paquet
officiel `.pkg`, mot de passe administrateur demandé une fois), configuration de la machine
Podman (VM légère via l'Hypervisor Framework d'Apple, aucun redémarrage requis), démarrage des
services. Après l'installation, lancer via **PIE Manager** dans `~/Applications` ou :
```bash
pie-manager start
```

Uniquement Apple Silicon (arm64) — les Mac Intel ne sont pas supportés (Apple abandonne
lui-même le support Intel dès macOS 27, prévu fin 2026).

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

macOS :
```bash
# Arrêter et supprimer les containers
podman compose -f ~/Library/Application\ Support/PieManager/compose-prod.yaml down --volumes

# Supprimer les fichiers installés
rm -rf ~/Library/Application\ Support/PieManager
rm -f ~/.local/bin/pie-manager
rm -rf ~/Applications/PIE\ Manager.app
launchctl unload ~/Library/LaunchAgents/com.pie-manager.podman-start.plist
rm -f ~/Library/LaunchAgents/com.pie-manager.podman-start.plist
```

---

## Stack technique

| Couche | Technologie |
|--------|-------------|
| Frontend | React 18 + TypeScript + PatternFly 5 |
| Backend | Python FastAPI + SQLAlchemy 2.0 async + PgQueuer |
| Base de données | PostgreSQL 16 |
| Déploiement | Podman Compose + HAProxy |
| Installateur | Go (binaire statique, aucun prérequis) |

---

## Architecture

En production, un seul port est exposé (14943 par défaut, détection automatique si occupé). HAProxy sert de point d'entrée unique et route les requêtes vers le frontend et le backend. Les containers backend et frontend n'ont pas de port exposé directement.

```
Navigateur / Fenêtre native
        │
        ▼
   haproxy :14943
   ├── /api/* → backend :8000 (FastAPI)
   └── /*     → frontend (Vite dev server)
```

Les images sont versionnées et publiées sur Quay.io (`quay.io/ltourreau/pie-manager-*`).

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

Les binaires Windows sont signés (Authenticode, horodatage RFC-3161) avec un certificat
auto-généré (`CN=PIEManager`) — [SignPath Foundation](https://signpath.org) (signature gratuite
pour l'open source) a refusé la demande faute d'audience suffisante sur ce dépôt. Un certificat
auto-généré n'a pas la réputation accumulée d'une autorité de certification reconnue : Windows
SmartScreen affichera donc quand même un avertissement au premier lancement : cliquez sur
**"Informations complémentaires" → "Exécuter quand même"** (voir la section Installation
ci-dessus).

Le binaire macOS n'est ni signé ni notarié — cela nécessiterait un compte Apple Developer
Program payant (99$/an), qui n'est pas utilisé pour ce projet. macOS Gatekeeper bloquera donc
le premier lancement ; la commande `xattr -d com.apple.quarantine` (voir la section
Installation ci-dessus) est le contournement documenté et sûr, à exécuter une seule fois.

Le code source est public et consultable dans son intégralité — vous pouvez vérifier ce qui
est exécuté sur votre machine avant de l'installer.

---

## Licence

[AGPL-3.0-or-later](LICENSE) — Copyright © 2025-2026 Laurent Tourreau.
