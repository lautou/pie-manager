# Guide de sauvegarde et restauration — PIE Manager

## Sommaire

1. [Stratégie de sauvegarde recommandée](#1-stratégie-de-sauvegarde-recommandée)
2. [Où sont stockées les données](#2-où-sont-stockées-les-données)
3. [Sauvegarde depuis l'interface](#3-sauvegarde-depuis-linterface)
4. [Sauvegarde manuelle en ligne de commande](#4-sauvegarde-manuelle-en-ligne-de-commande)
5. [Sauvegarde complète du dossier d'installation — Windows](#5-sauvegarde-complète-du-dossier-dinstallation--windows)
6. [Sauvegarde de la machine Podman — macOS](#6-sauvegarde-de-la-machine-podman--macos)
7. [Restauration depuis l'interface](#7-restauration-depuis-linterface)
8. [Restauration manuelle en ligne de commande](#8-restauration-manuelle-en-ligne-de-commande)
9. [Migration entre versions majeures de PostgreSQL](#9-migration-entre-versions-majeures-de-postgresql)

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

Le fichier `.dump` (quelques Mo) est indépendant de la machine et de la plateforme. Il peut être restauré sur n'importe quelle installation de PIE Manager, y compris sur une machine différente. Il est conseillé de le stocker dans un répertoire synchronisé (cloud personnel, clé USB dédiée).

### Sauvegarde de la machine — avant une mise à jour (macOS uniquement)

Sur macOS, les données vivent à l'intérieur d'une Podman Machine (une VM utilisant l'hyperviseur natif d'Apple). Une sauvegarde supplémentaire de cette machine protège contre les problèmes de migration lors d'une mise à jour logicielle — voir [Sauvegarde de la machine Podman — macOS](#6-sauvegarde-de-la-machine-podman--macos).

Sur Windows, l'app native (distribuée via le Microsoft Store) n'utilise ni VM ni containers —
les données PostgreSQL vivent directement sur le disque, dans `%USERPROFILE%\PieManager\`. Il
n'y a donc pas de "machine" à sauvegarder séparément ; voir
[Sauvegarde complète du dossier d'installation — Windows](#5-sauvegarde-complète-du-dossier-dinstallation--windows)
pour une sauvegarde optionnelle allant au-delà du `.dump` quotidien.

### Tableau récapitulatif

| Fréquence | Action | Durée | Protège contre |
|---|---|---|---|
| **Quotidien** | Télécharger sauvegarde depuis l'UI | 2 secondes | Fausse manip données |
| **Avant chaque upgrade (Windows)** | Sauvegarde logique (voir section 3) — copie optionnelle du dossier `%USERPROFILE%\PieManager\` en complément | 2 secondes | Migration DB échouée |
| **Avant chaque upgrade (macOS)** | Sauvegarde logique renforcée (pas d'export machine natif — voir [Sauvegarde de la machine Podman — macOS](#6-sauvegarde-de-la-machine-podman--macos)) | 2 secondes | Migration DB échouée |
| **Archivage mensuel** | Conserver 1 sauvegarde par mois | — | Historique long terme |

---

## 2. Où sont stockées les données

Toutes les données de PIE Manager sont dans la base de données PostgreSQL 18, stockée dans le volume Podman `pie-manager_postgres_data`.

Ce volume est géré par Podman et persiste indépendamment du cycle de vie des containers :

- `podman compose down` — **conserve** les données (volume intact)
- `podman compose down --volumes` — **supprime** les données (irréversible)

**Sur Linux**, le volume est dans `~/.local/share/containers/storage/volumes/` — directement accessible sur le système de fichiers.

**Sur Windows**, l'app native (distribuée via le Microsoft Store) n'utilise ni VM ni Podman —
les données PostgreSQL sont directement sur le disque, accessibles depuis l'Explorateur :
```
%USERPROFILE%\PieManager\pgdata\
```
Ce dossier n'est jamais placé sous `AppData`/`LocalAppData` : Windows y effectue une
réinitialisation transparente au moindre repackaging MSIX, ce qui effacerait les données à
chaque mise à jour de l'app. `%USERPROFILE%\PieManager\` survit aussi à une désinstallation —
les données restent en place tant qu'elles ne sont pas supprimées manuellement.

> ⚠️ Supprimer `%USERPROFILE%\PieManager\pgdata\` **détruit irrémédiablement** les données. La sauvegarde logique quotidienne est donc indispensable.

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

> Note : utiliser le container **backend** (qui dispose de `pg_dump` v18) et non le container postgres directement.

**Sur Windows (app native)** : ces méthodes en ligne de commande ne s'appliquent pas — il n'y a
ni `.env` ni containers Podman. Le port de l'app est choisi dynamiquement à chaque lancement et
n'est pas exposé dans un fichier prévu pour être lu de l'extérieur. La sauvegarde depuis
l'interface (section 3) est donc la méthode recommandée et pratiquement la seule sur Windows.

---

## 5. Sauvegarde complète du dossier d'installation — Windows

L'app native Windows n'a pas de "machine" à sauvegarder — pas de VM, pas de containers. La
sauvegarde logique quotidienne (`.dump`, section 3) est déjà la protection principale et
suffisante, exactement comme sur macOS avec Podman Machine hors service. Pour une sauvegarde
plus large, allant au-delà des seules données PostgreSQL (utile avant une mise à jour majeure,
ou pour un archivage complet), copier l'intégralité du dossier d'installation :

```powershell
# 1. Fermer PIE Manager (sinon Postgres a des fichiers ouverts)

# 2. Copier tout le dossier d'installation
Copy-Item -Recurse "$env:USERPROFILE\PieManager" "C:\Backups\PieManager-$(Get-Date -Format 'yyyyMMdd')"

# 3. Relancer PIE Manager normalement
```

### En cas de problème — restaurer le dossier

```powershell
# Fermer PIE Manager, puis :
Remove-Item -Recurse -Force "$env:USERPROFILE\PieManager"
Copy-Item -Recurse "C:\Backups\PieManager-20260601" "$env:USERPROFILE\PieManager"
# Relancer PIE Manager
```

### Ce que cette sauvegarde protège

| Protège contre | Ne protège pas contre |
|---|---|
| Migration Alembic échouée | Perte de la copie elle-même |
| Mise à jour Store qui casse le backend/Postgres bundlés | Corruption du disque Windows |

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
# Copier le fichier dans le container backend (qui a pg_restore v18)
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

---

## 9. Migration entre versions majeures de PostgreSQL

Une mise à jour de PIE Manager peut, occasionnellement, changer la version majeure de PostgreSQL utilisée (par exemple 16 → 18). Contrairement à une mise à jour normale, **PostgreSQL refuse de démarrer directement sur des données écrites par une version majeure différente** — ce n'est pas un bug, c'est une règle stricte de compatibilité de PostgreSQL lui-même.

**Bonne nouvelle : l'installateur détecte cette situation automatiquement** et refuse de procéder tant que la migration n'a pas été faite manuellement — il ne touche jamais à vos données existantes sans confirmation.

> Cette détection automatique concerne l'installateur Linux/macOS (basé sur Podman). L'app
> native Windows embarque une version fixe de PostgreSQL par mise à jour Store et n'a pas
> encore de détection équivalente — en cas de doute avant une mise à jour Windows, faites
> systématiquement une sauvegarde `.dump` au préalable (section 3).

### Ce qui se passe concrètement

Si vous lancez une mise à jour qui nécessite une nouvelle version majeure de PostgreSQL, l'installateur affiche un message du type :

```
✗ PostgreSQL major version mismatch: your data is on PostgreSQL 16, but PIE Manager
  X.Y.Z requires PostgreSQL 18.
```

et s'arrête immédiatement, sans rien modifier.

### Procédure de migration

1. **Si l'ancienne version de PIE Manager tourne encore**, ouvrez-la et allez dans **Administration système → Télécharger une sauvegarde**. Conservez précieusement le fichier `.dump` téléchargé (voir [Sauvegarde depuis l'interface](#3-sauvegarde-depuis-linterface)).
2. Arrêtez PIE Manager, puis supprimez l'ancien volume de données indiqué dans le message de l'installateur :
   ```bash
   podman volume rm pie-manager_postgres_data
   ```
3. Relancez l'installateur — il démarre alors sur une base neuve, avec la nouvelle version de PostgreSQL.
4. Une fois l'application démarrée, allez dans **Administration système → Restaurer une sauvegarde** et sélectionnez le fichier `.dump` de l'étape 1 (voir [Restauration depuis l'interface](#7-restauration-depuis-linterface)).

Cette procédure garantit qu'aucune donnée n'est perdue — le volume supprimé à l'étape 2 n'est retiré qu'après confirmation que la sauvegarde de l'étape 1 est bien en votre possession.
