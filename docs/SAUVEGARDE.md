# Guide de sauvegarde et restauration — PIE Manager

## Sommaire

1. [Où sont stockées les données](#1-où-sont-stockées-les-données)
2. [Sauvegarde depuis l'interface](#2-sauvegarde-depuis-linterface)
3. [Sauvegarde manuelle en ligne de commande](#3-sauvegarde-manuelle-en-ligne-de-commande)
4. [Restauration depuis l'interface](#4-restauration-depuis-linterface)
5. [Restauration manuelle en ligne de commande](#5-restauration-manuelle-en-ligne-de-commande)
6. [Fréquence recommandée](#6-fréquence-recommandée)

---

## 1. Où sont stockées les données

Toutes les données de PIE Manager sont dans la base de données PostgreSQL 16, stockée dans le volume Podman `pie-manager_postgres_data`.

Ce volume est géré par Podman et persiste indépendamment du cycle de vie des containers :

- `podman compose down` — **conserve** les données (volume intact)
- `podman compose down --volumes` — **supprime** les données (irréversible)

Le volume est physiquement stocké dans le répertoire de données Podman de l'utilisateur (généralement `~/.local/share/containers/storage/volumes/`).

Le format de sauvegarde est `.dump` — format binaire compressé de `pg_dump` (format custom). Il est plus compact et plus fiable pour la restauration que le format SQL texte.

---

## 2. Sauvegarde depuis l'interface

C'est la méthode recommandée. Elle ne nécessite pas d'accès au terminal.

1. Ouvrir PIE Manager
2. Naviguer vers **Administration système** (menu de navigation)
3. Cliquer sur **Télécharger une sauvegarde**
4. Le fichier `pie-manager-backup-YYYY-MM-DD.dump` est téléchargé dans `~/Downloads/`

La sauvegarde est effectuée par le backend via `pg_dump` depuis le container, puis transmise directement au navigateur.

> Si WebKitGTK est utilisé (fenêtre native), le fichier est enregistré dans `~/Downloads/` automatiquement. Une notification de bureau confirme le téléchargement.

---

## 3. Sauvegarde manuelle en ligne de commande

Pour automatiser la sauvegarde ou la lancer sans interface graphique :

```bash
# Sauvegarder via l'API (recommandé)
curl -o ~/Downloads/pie-manager-backup-$(date +%Y-%m-%d).dump \
  http://localhost:14943/api/admin/backup
```

Remplacer `14943` par le port configuré si différent :
```bash
PORT=$(grep APP_PORT ~/.local/share/pie-manager/.env | cut -d= -f2)
curl -o ~/Downloads/pie-manager-backup-$(date +%Y-%m-%d).dump \
  "http://localhost:${PORT}/api/admin/backup"
```

### Sauvegarde directe via pg_dump (accès container)

```bash
podman exec pie-manager_postgres_1 pg_dump \
  -U pie \
  -d pie_db \
  --format=custom \
  --compress=9 \
  > ~/Downloads/pie-manager-backup-$(date +%Y-%m-%d).dump
```

---

## 4. Restauration depuis l'interface

> **Attention** : la restauration remplace intégralement la base de données actuelle. Faites une sauvegarde de la base actuelle avant de restaurer.

1. Ouvrir PIE Manager
2. Naviguer vers **Administration système**
3. Dans la section **Restaurer une sauvegarde**, cliquer sur **Choisir un fichier**
4. Sélectionner le fichier `.dump`
5. Cliquer sur **Restaurer**

La restauration utilise `pg_restore --single-transaction` : en cas d'erreur, l'opération est annulée et la base reste intacte.

Après une restauration réussie, l'application recharge automatiquement les données.

---

## 5. Restauration manuelle en ligne de commande

### Via l'API

```bash
curl -X POST http://localhost:14943/api/admin/restore \
  -F "file=@~/Downloads/pie-manager-backup-2026-01-15.dump"
```

### Directement via pg_restore (accès container)

Cette méthode est utile si l'interface n'est pas accessible (par exemple, après une migration de machine).

**Étape 1 — Copier le fichier de sauvegarde dans le container :**
```bash
podman cp ~/Downloads/pie-manager-backup-2026-01-15.dump \
  pie-manager_postgres_1:/tmp/backup.dump
```

**Étape 2 — Vider la base et restaurer :**
```bash
# Vider la base (drop et recréation)
podman exec pie-manager_postgres_1 psql -U pie -d postgres \
  -c "DROP DATABASE IF EXISTS pie_db;" \
  -c "CREATE DATABASE pie_db OWNER pie;"

# Restaurer
podman exec pie-manager_postgres_1 pg_restore \
  -U pie \
  -d pie_db \
  --single-transaction \
  /tmp/backup.dump
```

**Étape 3 — Appliquer les migrations éventuelles :**

Si le fichier de sauvegarde est d'une version antérieure à la version installée, relancer le backend pour qu'il applique les migrations Alembic :

```bash
podman compose -f ~/.local/share/pie-manager/compose-prod.yaml restart backend
```

### Restauration sur une nouvelle machine

1. Installer PIE Manager sur la nouvelle machine (voir [INSTALLATION.md](INSTALLATION.md))
2. Attendre que les services démarrent
3. Restaurer la sauvegarde via l'interface ou l'API

---

## 6. Fréquence recommandée

| Situation | Fréquence conseillée |
|-----------|----------------------|
| Usage courant | Après chaque session de saisie |
| Avant une mise à jour | Systématiquement (l'installateur le rappelle) |
| Archivage mensuel | Conserver au moins la dernière sauvegarde du mois |

Les fichiers `.dump` sont compacts (quelques mégaoctets pour un portefeuille typique). Il est conseillé de les conserver dans un répertoire synchronisé (cloud personnel, clé USB dédiée).

PIE Manager ne propose pas de sauvegarde automatique planifiée — la sauvegarde est une action manuelle intentionnelle.
