# ARPPSD — Application de gestion associative (Flask/Python)

Application complète de gestion pour l'**Association des Relais Polyvalents
du Poste de Santé de Darou Khoudoss** (Sénégal) : membres, cotisations,
caisse sociale, activités, documents, rapports, et permissions par rôle
(11 rôles configurables).

**Conçue et développée par Dame Diop**, étudiant en MPI (Mathématiques et
Physique-Informatique), avec l'assistance d'un outil d'IA pour
l'implémentation du code. Le projet répond à un besoin réel d'une
association de santé communautaire, depuis le recueil des besoins jusqu'au
déploiement.
📧 diopd2269@gmail.com

## Aperçu technique

- **100 % Python** côté serveur (Flask), templates HTML/Jinja2
- Base de données **SQLite** (module intégré à Python, zéro serveur externe)
- Authentification par mot de passe chiffré (Werkzeug), rôles et permissions
  entièrement configurables sans toucher au code
- Fonctionnalités : cartes de membre avec QR code, recherche globale,
  notifications internes, export PDF, sauvegarde en un clic

---

Application de gestion pour l'Association des Relais Polyvalents du Poste de
Santé de Darou Khoudoss. Écrite entièrement en **Python** (Flask), avec des
templates HTML simples — vous pouvez lire et modifier tout le code.

**Zéro dépendance fragile** : la base de données utilise `sqlite3`, un module
intégré à Python (aucune installation supplémentaire, aucune compilation).
Les bibliothèques externes nécessaires sont : Flask, python-dotenv, qrcode
(cartes de membre) et reportlab (export PDF) — toutes des paquets Python
purs, sans compilation requise, donc sans risque d'échec d'installation sur
Windows.

## Structure du projet

```
arppsd-flask/
├── app.py            → routes et logique de l'application (le fichier principal)
├── db.py              → accès à la base de données (SQLite pur, sans ORM)
├── constants.py        → rôles, permissions par défaut, mois
├── requirements.txt    → dépendances Python (minimales)
├── requirements-prod.txt → dépendances supplémentaires pour la mise en ligne
├── .env.example        → variables d'environnement à copier en .env
└── templates/           → pages HTML (Jinja2)
```

## 1. Tester en local (sur votre PC)

```bash
cd arppsd-flask
python -m venv venv
source venv/bin/activate        # Windows : venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Ouvrez ensuite **http://127.0.0.1:5000** dans votre navigateur.

Au premier lancement, une base de données `arppsd.db` (SQLite) est créée
automatiquement avec des données de démonstration clairement marquées « Démo »,
ainsi que 4 comptes de test avec mot de passe **`demo1234`** :
- Admin Démo (ADMINISTRATEUR)
- Aïda Ndiaye (SECRÉTAIRE)
- Moussa Diop (TRÉSORIÈRE)
- Fatou Sarr (MEMBRE)

Connectez-vous en choisissant un nom dans la liste déroulante, puis en tapant
`demo1234`. Une fois vos vrais membres ajoutés (avec leurs propres mots de
passe), pensez à désactiver ou supprimer ces comptes de démonstration.

## Authentification

- Chaque membre a un **mot de passe chiffré** (via `werkzeug.security`, déjà
  inclus avec Flask — aucune dépendance supplémentaire).
- La **fonction** (rôle) d'un membre est fixée dans sa fiche, gérée par
  l'administrateur/secrétaire — un membre ne peut pas se l'attribuer lui-même.
- Chaque membre peut changer son propre mot de passe via **Mon compte**.
- L'administrateur peut réinitialiser le mot de passe de n'importe quel membre
  depuis sa fiche (bouton "Réinitialiser le mot de passe").


## 2. Comprendre le code (repères pour vous, en Python)

- **`app.py`** : chaque `@app.route(...)` est une page ou une action.
  Ex. `/membres` liste les membres, `/membres/nouveau` ajoute un membre.
- **`db.py`** : toutes les fonctions qui lisent/écrivent dans la base de
  données (`get_members()`, `insert_member()`, etc.) — du SQL classique,
  pas d'ORM à apprendre.
- **`constants.py`** : la liste des rôles et les permissions par défaut de
  chaque rôle — modifiable directement dans le code, ou via Paramètres dans
  l'appli (les deux fonctionnent).
- Les fichiers dans `templates/` affichent les données ; ils utilisent Jinja2
  (proche de Python : `{% for m in membres %}`, `{{ m.nom }}`, etc.)

## 3. Mettre en ligne gratuitement (Render)

Render est un hébergeur gratuit qui fonctionne nativement avec Python/Flask.

1. Créez un dépôt GitHub et envoyez-y tous les fichiers de `arppsd-flask/`.
2. Allez sur **render.com**, créez un compte gratuit (connexion via GitHub).
3. **New > Web Service**, sélectionnez votre dépôt `arppsd-app`.
4. Renseignez :
   - **Build Command** : `pip install -r requirements-prod.txt`
   - **Start Command** : `gunicorn app:app --bind 0.0.0.0:$PORT`
5. Dans **Environment**, ajoutez la variable `SECRET_KEY` (une valeur secrète
   de votre choix).
6. Cliquez sur **Create Web Service**. Après quelques minutes, Render vous
   donne un lien du type `https://arppsd-app.onrender.com`.

**Important pour la persistance des données en ligne** : sur le plan gratuit
de Render, le fichier SQLite peut être effacé à chaque redéploiement (le
disque n'est pas garanti permanent). Pour une association qui grandit, il
faudra migrer vers une vraie base de données hébergée (ex. PostgreSQL gratuit
sur Render ou Supabase) — dites-le-moi le moment venu, l'adaptation du code
reste simple.

## 4. Sauvegarder vos données

Copiez régulièrement le fichier `arppsd.db` (ex. vers Google Drive) tant que
vous êtes en local ou sur un hébergement gratuit sans disque permanent.

## Fonctionnalités

- Membres, cotisations, caisse sociale, activités, annonces, rapports,
  permissions par rôle (11 rôles), journal d'activité.
- Authentification par mot de passe personnel (chiffré) par membre.
- **Documents** : téléversement de vrais fichiers (PDF, photos, etc. —
  20 Mo max par fichier), stockés dans le dossier `uploads/` (créé
  automatiquement, non inclus dans le zip).
- **Carte de membre numérique** avec QR code, imprimable (fiche membre →
  "Carte de membre").
- **Recherche globale** (barre en haut de chaque page) : membres, activités,
  annonces, documents.
- **Notifications internes** (icône 🔔 en haut) : nouvelle annonce, nouvelle
  activité, cotisation enregistrée (pour le membre concerné).
- **Export PDF** des rapports (page Rapports → "Télécharger le rapport en PDF").

## Documents : stockage local ou Google Drive

Par défaut, les documents téléversés sont stockés dans le dossier `uploads/`
(local). Pour éviter de perdre ces fichiers sur un hébergement gratuit sans
disque persistant (comme Render), vous pouvez activer le stockage sur
**Google Drive** — gratuit jusqu'à 15 Go.

Pour l'activer, définissez ces deux variables d'environnement sur votre
hébergeur :
- `GOOGLE_SERVICE_ACCOUNT_JSON` : le contenu complet du fichier JSON de la
  clé du compte de service Google (copié-collé tel quel, sur une seule
  variable)
- `GOOGLE_DRIVE_FOLDER_ID` : l'identifiant du dossier Drive partagé avec ce
  compte de service (visible dans l'URL du dossier)

Sans ces variables, l'application continue de fonctionner normalement avec
le stockage local — rien à changer si vous ne voulez pas utiliser Drive.

**Bonus important** : si ces deux variables sont configurées, l'application
sauvegarde **aussi automatiquement toute la base de données** (membres,
cotisations, etc.) sur ce même dossier Google Drive après chaque
modification, et la restaure automatiquement si elle venait à disparaître
(par exemple après un redéploiement sur un hébergement sans disque
persistant). Avec Google Drive activé, plus besoin de copier `arppsd.db`
à la main — les deux alertes de persistance disparaissent du tableau de
bord admin.

## À savoir

- Tout reste gratuit tant que l'association reste petite.
- Les fichiers de documents sont stockés localement dans `uploads/` — pensez à
  les inclure dans vos sauvegardes en plus de `arppsd.db`.
