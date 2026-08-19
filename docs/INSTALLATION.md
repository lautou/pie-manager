# Guide d'installation — PIE Manager

## Sommaire

1. [Configuration système et empreinte ressources](#1-configuration-système-et-empreinte-ressources)
2. [Prérequis détaillés](#2-prérequis-détaillés)
3. [Installation sur Linux](#3-installation-sur-linux)
4. [Installation sur Windows 11](#4-installation-sur-windows-11)
5. [Installation sur macOS (Apple Silicon)](#5-installation-sur-macos-apple-silicon)
6. [Premier démarrage](#6-premier-démarrage)
7. [Mise à jour](#7-mise-à-jour)
8. [Désinstallation complète](#8-désinstallation-complète)
9. [Dépannage](#9-dépannage)

---

## 1. Configuration système et empreinte ressources

### Configuration minimale recommandée

| Ressource | Linux | Windows 11 | macOS |
|---|---|---|---|
| **CPU** | 2 cœurs | 2 cœurs (pas de VM — backend Python + PostgreSQL bundlés directement) | Apple Silicon (M1 ou ultérieur) |
| **RAM** | 2 Go | *non mesuré* (pas de couche VM/containers depuis le passage au launcher natif Store, voir §4) | 4 Go (Podman Machine ~2 Go) |
| **Disque** | 4 Go libres | *non mesuré* | 6 Go libres (VM Podman Machine incluse) |
| **OS** | Fedora 38+, Ubuntu 22.04+ | Windows 11 64-bit | macOS 14 Sonoma ou ultérieur |

### Empreinte en fonctionnement normal

Les mesures ci-dessous sont relevées avec **1 à 2 portefeuilles actifs**, prix synchronisés, aucune action utilisateur.

#### Linux (état de repos, app démarrée)

| Service | RAM | CPU repos | CPU synchro prix |
|---|---|---|---|
| postgres | ~50 Mo | ~0 % | ~1 % |
| backend (FastAPI) | ~150 Mo | ~0 % | ~5 % |
| pgq-worker (PgQueuer) | — | — | — |
| frontend (Vite) | ~200 Mo | ~0 % | ~0 % |
| haproxy | ~5 Mo | ~0 % | ~0 % |
| **Total** | *à re-mesurer* | *à re-mesurer* | *à re-mesurer* |

*Mesures non rafraîchies depuis le remplacement de Celery/Redis par PgQueuer (issue #66) — les
lignes `redis`/`worker (Celery)` ont disparu, mais `pgq-worker` n'a pas encore été mesuré
séparément.*

#### Windows 11 (état de repos, app démarrée)

Depuis le passage à la distribution Microsoft Store (launcher natif, voir §4), il n'y a plus de
VM ni de containers sur Windows — le backend Python et PostgreSQL tournent directement comme
processus natifs, lancés par une fenêtre WebView2. Le processus `VmmemWSL` et son empreinte
mémoire dédiée n'existent plus pour cette app.

| Processus | RAM | Disque |
|---|---|---|
| Backend Python + PostgreSQL (bundlés) | *non mesuré* | *non mesuré* |

*Chiffres à mesurer sur un premier passage d'utilisation réelle — voir aussi la vérification de
l'issue #82.*

#### macOS (état de repos, app démarrée)

Sur macOS, comme sur Windows, les containers tournent dans une **Podman Machine** — mais la VM sous-jacente utilise l'hyperviseur natif d'Apple (pas WSL2), sans couche de virtualisation intermédiaire à installer :

| Couche | RAM | Disque |
|---|---|---|
| Podman Machine (VM Fedora CoreOS) | ~400 Mo | ~4 Go (disque virtuel) |
| 5 containers PIE Manager | *non re-mesuré* | *non re-mesuré* |
| **Total** | **~1 Go** | **~4,5 Go** |

Contrairement à Windows, il n'y a pas de processus hôte unique consolidant toute la mémoire de la VM (pas d'équivalent `VmmemWSL`) — `podman machine info` donne l'état courant de la machine.

### Évolution du stockage dans le temps

| Durée d'utilisation | Données PostgreSQL | Disque total (Linux) | Disque total (Windows) | Disque total (macOS) |
|---|---|---|---|---|
| 1 mois (2 portefeuilles) | ~5 Mo | ~500 Mo | *non mesuré (launcher natif Store)* | ~4,5 Go |
| 6 mois | ~20 Mo | ~600 Mo | *non mesuré* | ~5 Go |
| 2 ans | ~80 Mo | ~800 Mo | *non mesuré* | ~5,3 Go |

La base de données reste légère — les prix historiques (yfinance) représentent l'essentiel du stockage. Les `.dump` de sauvegarde font généralement **300–500 Ko**.

### Impact des synchronisations

- **Toutes les 15 minutes** : PgQueuer synchronise les prix Yahoo Finance → pic CPU de 5–15 s
- **Au démarrage** : Alembic vérifie les migrations → 2–5 s de CPU supplémentaire
- **Régénération snapshots** (Admin) : CPU ~30 % pendant 10–30 s selon la plage de dates

---

## 2. Prérequis détaillés

### Podman

PIE Manager utilise Podman pour lancer les containers. Docker n'est pas supporté.

**Fedora :**
```bash
sudo dnf install -y podman podman-compose
```

**Ubuntu / Debian :**
```bash
sudo apt-get install -y podman
# Installer podman-compose (pip ou paquet système selon la distribution)
pip3 install --user podman-compose
```

Vérifier l'installation :
```bash
podman --version
podman-compose --version   # ou : podman compose version
```





---

## 3. Installation sur Linux

### Télécharger le binaire d'installation

```bash
gh release download --repo lautou/pie-manager --pattern 'pie-manager-linux-amd64' --dir ~/Downloads/ --clobber
chmod +x ~/Downloads/pie-manager-linux-amd64
```

Ou avec `curl` si vous n'avez pas `gh` :
```bash
curl -L https://github.com/lautou/pie-manager/releases/latest/download/pie-manager-linux-amd64 \
  -o ~/Downloads/pie-manager-linux-amd64
chmod +x ~/Downloads/pie-manager-linux-amd64
```

### Lancer l'installation

```bash
~/Downloads/pie-manager-linux-amd64 install
```

L'installateur effectue les étapes suivantes :

1. Vérification de Podman
2. Téléchargement des images (backend, frontend, postgres, HAProxy) depuis Quay.io
3. Écriture des fichiers de configuration dans `~/.local/share/pie-manager/`
4. Détection d'un port libre (14943 par défaut)
5. Création de l'icône GNOME et du raccourci
6. Démarrage des services

### Fichiers installés

```
~/.local/share/pie-manager/
├── compose-prod.yaml       Configuration des containers
├── haproxy.cfg             Configuration HAProxy
├── .env                    Port et version (APP_PORT, APP_VERSION)
├── pie-manager             Binaire (copie locale)
├── VERSION                 Version installée
└── wrapper.py              Fenêtre native GTK (si WebKitGTK disponible)

~/.local/bin/pie-manager           Lien symbolique vers le binaire
~/.local/share/applications/       Entrée bureau GNOME
~/.local/share/icons/hicolor/      Icône SVG et PNG
```

### Intégration bureau (fenêtre native)

Si Python 3 et WebKitGTK 2 (`gi`, `WebKit2 4.1`) sont installés sur votre système, l'application s'ouvre dans une fenêtre native GTK (1400 × 900) sans chrome de navigateur. Elle affiche un écran de chargement animé pendant le démarrage des containers.

Sans WebKitGTK, le navigateur par défaut est utilisé à la place.

---

## 4. Installation sur Windows 11

**Installer [PIE Manager depuis le Microsoft Store](https://apps.microsoft.com/detail/9PM8GPSMJG0N)** — un clic sur **Obtenir**, aucune installation manuelle.

**Prérequis :** Windows 11 64-bit — rien d'autre. Contrairement à l'ancien installateur (WSL2 +
Podman + containers), l'app Store est un launcher natif qui embarque directement son propre
backend Python et sa propre base PostgreSQL — pas de virtualisation, pas de containers à
télécharger.

**Ce que fait l'app au premier lancement :**

1. Initialisation de PostgreSQL (`initdb`) dans `%USERPROFILE%\PieManager\` — jamais sous
   `AppData`/`LocalAppData`, qui seraient effacés par Windows au moindre repackaging MSIX
2. Sélection dynamique d'un port libre
3. Application des migrations de base de données (Alembic)
4. Démarrage du backend (uvicorn) et ouverture de la fenêtre native (WebView2)

Aucun avertissement Windows SmartScreen : l'app est signée et certifiée par Microsoft dans le
cadre du processus de publication sur le Store.

**Icône menu Démarrer :** après installation, l'icône PIE Manager lance l'application
directement.

**Mises à jour :** automatiques via le Microsoft Store, comme n'importe quelle autre app Store —
pas de commande manuelle à relancer.

**Historique :** cette distribution Store remplace l'ancien installateur WSL2/Podman comme
méthode documentée pour Windows (issue #82). L'exécutable `pie-manager-windows-amd64.exe`
reste publié dans les releases GitHub pour compatibilité, mais n'est plus la voie recommandée —
voir la section « Sécurité et signature de code » du README pour le détail de cette voie
alternative.

---

## 5. Installation sur macOS (Apple Silicon)

**Uniquement Apple Silicon (arm64)** — les Mac Intel ne sont pas supportés (Apple abandonne lui-même le support Intel dès macOS 27, prévu fin 2026).

**Prérequis :** macOS 14 Sonoma ou ultérieur (le reste, y compris Podman, est installé automatiquement).

### Télécharger et lancer l'installateur

```bash
curl -LO https://github.com/lautou/pie-manager/releases/latest/download/pie-manager-darwin-arm64
chmod +x pie-manager-darwin-arm64
xattr -d com.apple.quarantine pie-manager-darwin-arm64
./pie-manager-darwin-arm64 install
```

La commande `xattr -d com.apple.quarantine` est nécessaire car le binaire n'est ni signé ni notarié (voir « Sécurité et signature de code » dans le README) — sans elle, macOS Gatekeeper refuse l'exécution en affichant « impossible d'ouvrir » ou « fichier endommagé ».

L'installateur effectue les étapes suivantes :

1. Installation de Podman via son paquet officiel (`.pkg` téléchargé depuis GitHub, pas Homebrew)
2. Initialisation et démarrage de la Podman Machine (VM légère via l'hyperviseur natif d'Apple, aucun redémarrage requis)
3. Téléchargement des images (backend, frontend, postgres, HAProxy)
4. Écriture des fichiers de configuration dans `~/Library/Application Support/PieManager/`
5. Détection d'un port libre (14943 par défaut)
6. Création du raccourci `PIE Manager.app` dans `~/Applications`
7. Configuration du démarrage automatique de la Podman Machine à la connexion (agent `launchd`)
8. Démarrage des services

### Fichiers installés

```
~/Library/Application Support/PieManager/
├── compose-prod.yaml       Configuration des containers
├── haproxy.cfg             Configuration HAProxy
├── .env                    Port et version (APP_PORT, APP_VERSION)
├── pie-manager             Binaire (copie locale)
└── VERSION                 Version installée

~/Library/LaunchAgents/com.pie-manager.podman-start.plist   Démarrage auto de la Podman Machine
~/Applications/PIE Manager.app                              Raccourci (lance le navigateur)
~/.local/bin/pie-manager                                    Lien symbolique vers le binaire
```

### Lancement de l'application

Contrairement à Linux (fenêtre native GTK optionnelle) et Windows (fenêtre WebView2 dédiée), macOS ouvre PIE Manager dans le **navigateur par défaut** — il n'existe pas d'équivalent léger et sans dépendance cgo à WebView2 pour macOS en v1.

---

## 6. Premier démarrage

Après l'installation, deux méthodes pour lancer l'application :

**Via l'icône GNOME** (recommandé) :
Chercher « PIE Manager » dans le lanceur d'applications.

**En ligne de commande :**
```bash
pie-manager start
```

Au premier démarrage, le backend applique les migrations de base de données avant d'accepter les connexions. Compter jusqu'à 90 secondes.

L'application est accessible à `http://localhost:14943` (ou le port détecté lors de l'installation).

---

## 7. Mise à jour

La mise à jour utilise la même commande que l'installation initiale. L'installateur détecte la version existante et affiche un avertissement de sauvegarde.

```bash
~/Downloads/pie-manager-linux-amd64 install
```

Déroulement :
1. L'installateur détecte la version installée
2. Affiche : `Updating: X.Y.Z → A.B.C`
3. Demande de faire une sauvegarde avant de continuer
4. Télécharge les nouvelles images
5. Redémarre les containers avec les nouvelles images

**Toujours faire une sauvegarde avant une mise à jour** :
`Administration système → Télécharger une sauvegarde`

Voir [SAUVEGARDE.md](SAUVEGARDE.md) pour le guide complet.

**Windows (Microsoft Store) :** mise à jour automatique via le Store, comme n'importe quelle
autre app — rien à faire manuellement.

---

## 8. Désinstallation complète

**Windows (Microsoft Store) :** Paramètres → Applications → PIE Manager → Désinstaller. Les
données restent dans `%USERPROFILE%\PieManager\` (choix délibéré pour survivre à une
désinstallation, voir CLAUDE.md) — les supprimer manuellement si un nettoyage complet est
voulu.

Les commandes ci-dessous concernent l'installation Linux/macOS (Podman) :

### Arrêter et supprimer les containers et les volumes

```bash
podman compose -f ~/.local/share/pie-manager/compose-prod.yaml down --volumes
```

L'option `--volumes` supprime également les volumes de données (base de données). **Cette action est irréversible** — faites une sauvegarde avant.

### Supprimer les images Podman

```bash
podman rmi quay.io/ltourreau/pie-manager-backend:latest
podman rmi quay.io/ltourreau/pie-manager-frontend:latest
podman rmi postgres:18-alpine haproxy:alpine
```

### Supprimer les fichiers installés

```bash
rm -rf ~/.local/share/pie-manager
rm -f ~/.local/bin/pie-manager
rm -f ~/.local/share/applications/pie-manager.desktop
rm -f ~/.local/share/icons/hicolor/scalable/apps/pie-manager.svg
rm -f ~/.local/share/icons/hicolor/64x64/apps/pie-manager.png
rm -rf ~/.config/pie-manager
```

### Rafraîchir le cache GNOME

```bash
update-desktop-database ~/.local/share/applications
gtk-update-icon-cache -f ~/.local/share/icons/hicolor
```

---

## 9. Dépannage

### Le port 14943 est déjà utilisé

L'installateur détecte automatiquement un port libre en partant de 14943. Si le port change, la nouvelle valeur est enregistrée dans `~/.local/share/pie-manager/.env`.

Pour vérifier le port actuel :
```bash
grep APP_PORT ~/.local/share/pie-manager/.env
```

### L'application ne démarre pas après un redémarrage

Les containers ne démarrent pas automatiquement au démarrage du système. Cliquer sur l'icône GNOME (ou lancer `pie-manager start`) redémarre les containers.

### Récupérer les journaux du backend

```bash
podman logs pie-manager_backend_1
podman logs pie-manager_worker_1
```

### Les données semblent perdues

Les données sont dans le volume Podman `pie-manager_postgres_data`. Ce volume n'est pas supprimé par `podman compose down` (sans `--volumes`). Si vous avez lancé `down --volumes`, les données sont perdues — restaurer depuis une sauvegarde.

Voir [SAUVEGARDE.md](SAUVEGARDE.md).

### Vérifier l'état des containers

```bash
podman compose -f ~/.local/share/pie-manager/compose-prod.yaml ps
```
