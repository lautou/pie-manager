# Guide d'installation — PIE Manager

## Sommaire

1. [Prérequis détaillés](#1-prérequis-détaillés)
2. [Installation sur Linux](#2-installation-sur-linux)
3. [Installation sur Windows (WSL2)](#3-installation-sur-windows-wsl2)
4. [Premier démarrage](#4-premier-démarrage)
5. [Mise à jour](#5-mise-à-jour)
6. [Désinstallation complète](#6-désinstallation-complète)
7. [Dépannage](#7-dépannage)

---

## 1. Prérequis détaillés

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

## 2. Installation sur Linux

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
3. Connexion à `ghcr.io`
4. Téléchargement des images (backend, frontend, postgres, redis, nginx)
5. Écriture des fichiers de configuration dans `~/.local/share/pie-manager/`
6. Détection d'un port libre (14943 par défaut)
7. Création de l'icône GNOME et du raccourci
8. Démarrage des services

### Fichiers installés

```
~/.local/share/pie-manager/
├── compose-prod.yaml       Configuration des containers
├── nginx.conf              Configuration Nginx
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

## 3. Installation sur Windows (WSL2)

> Le support Windows est expérimental. L'environnement recommandé est Linux natif.

**Prérequis :**
- WSL2 activé et une distribution Linux installée (Ubuntu recommandé)
- [Podman Desktop](https://podman-desktop.io/) pour Windows installé et démarré

**Procédure :**

1. Ouvrir un terminal WSL2
2. Télécharger le binaire Linux (`pie-manager-linux-amd64`) dans WSL2
3. Lancer l'installation comme sur Linux

L'installateur détecte automatiquement WSL2 et vérifie que Podman est accessible depuis l'environnement WSL2.

---

## 4. Premier démarrage

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

## 5. Mise à jour

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

---

## 6. Désinstallation complète

### Arrêter et supprimer les containers et les volumes

```bash
podman compose -f ~/.local/share/pie-manager/compose-prod.yaml down --volumes
```

L'option `--volumes` supprime également les volumes de données (base de données). **Cette action est irréversible** — faites une sauvegarde avant.

### Supprimer les images Podman

```bash
podman rmi ghcr.io/lautou/pie-manager-backend:latest
podman rmi ghcr.io/lautou/pie-manager-frontend:latest
podman rmi postgres:16-alpine redis:7-alpine nginx:alpine
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

## 7. Dépannage

### Le port 14943 est déjà utilisé

L'installateur détecte automatiquement un port libre en partant de 14943. Si le port change, la nouvelle valeur est enregistrée dans `~/.local/share/pie-manager/.env`.

Pour vérifier le port actuel :
```bash
grep APP_PORT ~/.local/share/pie-manager/.env
```

### L'application ne démarre pas après un redémarrage

Les containers ne démarrent pas automatiquement au démarrage du système. Cliquer sur l'icône GNOME (ou lancer `pie-manager start`) redémarre les containers.

### Erreur lors du téléchargement des images (401 Unauthorized)


```bash
```

Puis relancer l'installation.

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
