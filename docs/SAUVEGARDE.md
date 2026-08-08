# Guide de sauvegarde et restauration — PIE Manager

## Sommaire

1. [Stratégie de sauvegarde recommandée](#1-stratégie-de-sauvegarde-recommandée)
2. [Où sont stockées les données](#2-où-sont-stockées-les-données)
3. [Sauvegarde depuis l'interface](#3-sauvegarde-depuis-linterface)
4. [Sauvegarde manuelle en ligne de commande](#4-sauvegarde-manuelle-en-ligne-de-commande)
5. [Sauvegarde de la machine Podman — Windows uniquement](#5-sauvegarde-de-la-machine-podman--windows-uniquement)
6. [Sauvegarde de la machine Podman — macOS](#6-sauvegarde-de-la-machine-podman--macos)
7. [Restauration depuis l'interface](#7-restauration-depuis-linterface)
8. [Restauration manuelle en ligne de commande](#8-restauration-manuelle-en-ligne-de-commande)

---

## 1. Stratégie de sauvegarde recommandée

PIE Manager propose deux niveaux de sauvegarde complémentaires.

### Sauvegarde logique — quotidienne (tous OS)

La sauvegarde logique est un fichier `.dump` contenant l'intégralité de la base de données. C'est la sauvegarde de référence.

| Quand | Pourquoi |
|---|---|
| **Chaque jour** | Fausse manip sur les données → restauration immédiate |
| **Avant chaque mise à jour** | L'installateur le rappelle automatiquement |
| **Après une saisie importante** | Transactions, prix manuels, modifications de configuration |

Le fichier `.dump` (quelques Mo) est indépendant de la machine, de WSL2 et de Podman. Il peut être restauré sur n'importe quelle installation de PIE Manager, y compris sur une machine différente. Il est conseillé de le stocker dans un répertoire synchronisé (cloud personnel, clé USB dédiée).

### Sauvegarde de la machine — avant une mise à jour (Windows et macOS)

Sur Windows et macOS, les données vivent à l'intérieur d'une Podman Machine (une VM — WSL2 sur Windows, hyperviseur natif d'Apple sur macOS). Une sauvegarde supplémentaire de cette machine protège contre les problèmes de migration lors d'une mise à jour logicielle.

Voir les sections [Sauvegarde de la machine Podman — Windows](#5-sauvegarde-de-la-machine-podman--windows-uniquement) et [Sauvegarde de la machine Podman — macOS](#6-sauvegarde-de-la-machine-podman--macos).

### Tableau récapitulatif

| Fréquence | Action | Durée | Protège contre |
|---|---|---|---|
| **Quotidien** | Télécharger sauvegarde depuis l'UI | 2 secondes | Fausse manip données |
| **Avant chaque upgrade (Windows)** | `wsl --export` | 5–10 min | Migration DB échouée |
| **Avant chaque upgrade (macOS)** | Sauvegarde logique renforcée (pas d'export machine natif — voir [Sauvegarde de la machine Podman — macOS](#6-sauvegarde-de-la-machine-podman--macos)) | 2 secondes | Migration DB échouée |
| **Archivage mensuel** | Conserver 1 sauvegarde par mois | — | Historique long terme |

---

## 2. Où sont stockées les données

Toutes les données de PIE Manager sont dans la base de données PostgreSQL 16, stockée dans le volume Podman `pie-manager_postgres_data`.

Ce volume est géré par Podman et persiste indépendamment du cycle de vie des containers :

- `podman compose down` — **conserve** les données (volume intact)
- `podman compose down --volumes` — **supprime** les données (irréversible)

**Sur Linux**, le volume est dans `~/.local/share/containers/storage/volumes/` — directement accessible sur le système de fichiers.

**Sur Windows**, le volume est à l'intérieur de la Podman Machine (distribution WSL2 `podman-machine-default`), dans son disque virtuel `.vhdx`. Il est accessible depuis l'Explorateur via :
```
\\wsl.localhost\podman-machine-default\home\user\.local\share\containers\storage\volumes\pie-manager_postgres_data\
```

> ⚠️ Sur Windows, supprimer la distribution WSL2 `podman-machine-default` **détruit irrémédiablement** le volume et toutes les données. La sauvegarde logique quotidienne est donc indispensable.

**Sur macOS**, le volume est de la même façon à l'intérieur de la Podman Machine — mais celle-ci utilise l'hyperviseur natif d'Apple, pas WSL2, et n'est donc **pas accessible directement depuis le Finder**. Pour l'atteindre, il faut passer par la VM elle-même :
```bash
podman machine ssh
# puis, dans le shell de la VM :
ls ~/.local/share/containers/storage/volumes/pie-manager_postgres_data/
```

> ⚠️ Sur macOS comme sur Windows, supprimer la Podman Machine (`podman machine rm`) **détruit irrémédiablement** le volume et toutes les données. La sauvegarde logique quotidienne est donc indispensable.

Le format de sauvegarde est `.dump` — format binaire compressé de `pg_dump`. Il est plus compact et plus fiable pour la restauration que le format SQL texte.

---

## 3. Sauvegarde depuis l'interface

C'est la méthode recommandée. Elle ne nécessite pas d'accès au terminal.

1. Ouvrir PIE Manager
2. Naviguer vers **Administration système** (menu de navigation)
3. Cliquer sur **Télécharger une sauvegarde**
4. Le fichier `pie-backup-YYYY-MM-DD.dump` est téléchargé dans `~/Downloads/`

La sauvegarde est effectuée par le backend via `pg_dump`, puis transmise directement au navigateur.

> Sur Linux avec WebKitGTK (fenêtre native), le fichier est enregistré dans `~/Downloads/` automatiquement avec une notification de bureau.

---

## 4. Sauvegarde manuelle en ligne de commande

Pour automatiser la sauvegarde ou la lancer sans interface graphique :

```bash
# Sauvegarder via l'API (recommandé)
PORT=$(grep APP_PORT ~/.local/share/pie-manager/.env | cut -d= -f2)
curl -o ~/Downloads/pie-backup-$(date +%Y-%m-%d).dump \
  "http://localhost:${PORT}/api/admin/backup"
```

### Sauvegarde directe via pg_dump (accès container)

```bash
podman exec pie-manager_backend_1 pg_dump \
  -h postgres -U pie -d pie_db \
  --format=custom --compress=9 \
  -f /tmp/backup.dump && \
podman cp pie-manager_backend_1:/tmp/backup.dump \
  ~/Downloads/pie-backup-$(date +%Y-%m-%d).dump
```

> Note : utiliser le container **backend** (qui dispose de `pg_dump` v16) et non le container postgres directement.

---

## 5. Sauvegarde de la machine Podman — Windows uniquement

Sur Windows, cette sauvegarde protège contre les problèmes lors d'une mise à jour logicielle (migration de base de données, changement d'architecture). Elle capture l'intégralité de la VM WSL2 incluant les volumes Podman.

### Avant une mise à jour

```powershell
# 1. Arrêter la machine Podman
podman machine stop

# 2. Exporter la machine (5-10 min, fichier de 2-5 Go)
wsl --export podman-machine-default "C:\Backups\podman-machine-$(Get-Date -Format 'yyyyMMdd').tar"

# 3. Redémarrer la machine
podman machine start

# 4. Effectuer la mise à jour normalement
```

### En cas de problème — restaurer la machine

```powershell
# Supprimer la machine corrompue
podman machine rm
wsl --unregister podman-machine-default

# Réimporter la sauvegarde
wsl --import podman-machine-default `
  "$env:LOCALAPPDATA\Packages\RedHat.Podman_...\LocalState" `
  "C:\Backups\podman-machine-20260601.tar"

# Redémarrer la machine
podman machine start
```

### Ce que cette sauvegarde protège

| Protège contre | Ne protège pas contre |
|---|---|
| Migration Alembic échouée | Perte du fichier `.tar` lui-même |
| Mise à jour qui casse les containers | Désinstallation de WSL2 après la mise à jour |
| Mauvaise image Docker déployée | Corruption du disque Windows |

> WSL2 ne supporte pas les snapshots natifs. `wsl --export` est l'équivalent le plus proche.

---

## 6. Sauvegarde de la machine Podman — macOS

**Contrairement à Windows, Podman n'a pas d'équivalent à `wsl --export` sur macOS** — il n'existe pas de commande officielle unique pour exporter/importer l'intégralité d'une Podman Machine sur cette plateforme. En conséquence :

> **La sauvegarde logique quotidienne (`.dump`, voir [Stratégie de sauvegarde recommandée](#1-stratégie-de-sauvegarde-recommandée) et [Sauvegarde depuis l'interface](#3-sauvegarde-depuis-linterface)) est la protection principale et suffisante sur macOS** — pas juste un complément comme sur Windows. En cas de problème avec la Podman Machine elle-même (VM corrompue, mise à jour cassée), la solution la plus simple et la plus fiable est de **réinstaller l'installateur** (`./pie-manager-darwin-arm64 install`, recrée une Podman Machine saine) puis de **restaurer la dernière sauvegarde `.dump`** — plutôt que de tenter de récupérer la VM elle-même.

### Localiser les fichiers de la machine (optionnel, pour sauvegarde avancée)

Podman documente l'emplacement de la configuration de la machine dans `$XDG_CONFIG_HOME/containers/podman/machine/` (par défaut `~/.config/containers/podman/machine/` sur macOS). L'emplacement exact du disque virtuel dépend de la version de Podman et du fournisseur de VM utilisé (`libkrun` ou `applehv`) — pour l'obtenir de façon fiable sans dépendre d'un chemin codé en dur :

```bash
podman machine inspect
```

Cette commande affiche notamment le chemin du disque virtuel de la machine active. Pour une sauvegarde avancée (optionnelle, en complément de la sauvegarde `.dump`) :

```bash
# 1. Arrêter la machine Podman
podman machine stop

# 2. Copier le disque virtuel (chemin obtenu via `podman machine inspect` ci-dessus)
cp <chemin-du-disque> ~/Backups/podman-machine-$(date +%Y%m%d).raw

# 3. Redémarrer la machine
podman machine start
```

### Ce que la sauvegarde logique protège (macOS)

| Protège contre | Ne protège pas contre |
|---|---|
| Fausse manipulation sur les données | Perte du fichier `.dump` lui-même |
| Migration Alembic échouée (via réinstallation + restauration) | Corruption matérielle du disque Mac |

---

## 7. Restauration depuis l'interface

> **Attention** : la restauration remplace intégralement la base de données actuelle. Faites une sauvegarde avant de restaurer.

1. Ouvrir PIE Manager
2. Naviguer vers **Administration système**
3. Dans la section **Restaurer une sauvegarde**, cliquer sur **Choisir un fichier**
4. Sélectionner le fichier `.dump`
5. Cliquer sur **Restaurer**

La restauration utilise `pg_restore` : en cas d'erreur, l'opération est annulée et la base reste intacte.

---

## 8. Restauration manuelle en ligne de commande

### Via l'API

```bash
PORT=$(grep APP_PORT ~/.local/share/pie-manager/.env | cut -d= -f2)
curl -X POST "http://localhost:${PORT}/api/admin/restore" \
  -F "file=@~/Downloads/pie-backup-2026-01-15.dump"
```

### Directement via pg_restore

```bash
# Copier le fichier dans le container backend (qui a pg_restore v16)
podman cp ~/Downloads/pie-backup-2026-01-15.dump \
  pie-manager_backend_1:/tmp/backup.dump

# Restaurer via le backend
podman exec -e PGPASSWORD=pie_password pie-manager_backend_1 \
  pg_restore -h postgres -U pie -d pie_db \
  --no-owner --clean --if-exists \
  /tmp/backup.dump
```

### Restauration sur une nouvelle machine

1. Installer PIE Manager sur la nouvelle machine (voir [INSTALLATION.md](INSTALLATION.md))
2. Attendre que les services démarrent
3. Restaurer la sauvegarde via l'interface ou l'API
