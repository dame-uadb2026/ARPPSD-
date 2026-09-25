"""
Intégration optionnelle avec Google Drive pour stocker les documents de
façon permanente, même sur un hébergement gratuit sans disque persistant
(comme Render).

Fonctionnement :
- Si les variables d'environnement GOOGLE_SERVICE_ACCOUNT_JSON et
  GOOGLE_DRIVE_FOLDER_ID sont définies, les nouveaux documents sont
  envoyés sur Google Drive au lieu du disque local.
- Si elles ne sont pas définies (ou si la bibliothèque n'est pas
  installée), l'application continue de fonctionner normalement en
  utilisant le stockage local classique — rien ne casse.
"""
import io
import json
import os

SCOPES = ["https://www.googleapis.com/auth/drive"]


def is_configured():
    """Renvoie True si les identifiants Google Drive sont bien fournis."""
    return bool(os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")) and bool(
        os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
    )


def _get_service():
    """Construit le client Google Drive, ou None si indisponible pour
    une raison quelconque (bibliothèque absente, identifiants invalides...).
    Ne lève jamais d'exception : l'appelant doit gérer le cas None en
    revenant au stockage local."""
    if not is_configured():
        return None
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        return None
    try:
        info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception:
        return None


def upload_bytes(fileobj, filename, mimetype="application/octet-stream"):
    """Envoie un objet fichier en mémoire (BytesIO) vers Google Drive.
    Utilisé pour les documents ET pour les sauvegardes complètes.
    Renvoie l'ID du fichier créé, ou None en cas d'échec."""
    service = _get_service()
    if service is None:
        return None
    try:
        from googleapiclient.http import MediaIoBaseUpload
        folder_id = os.environ["GOOGLE_DRIVE_FOLDER_ID"]
        fileobj.seek(0)
        media = MediaIoBaseUpload(fileobj, mimetype=mimetype, resumable=False)
        created = service.files().create(
            body={"name": filename, "parents": [folder_id]},
            media_body=media,
            fields="id",
        ).execute()
        return created.get("id")
    except Exception:
        return None


def upload_file(file_storage, filename):
    """Envoie un fichier (objet Flask FileStorage) sur Google Drive.
    Renvoie l'ID du fichier créé, ou None en cas d'échec."""
    file_storage.stream.seek(0)
    return upload_bytes(
        file_storage.stream, filename,
        mimetype=file_storage.mimetype or "application/octet-stream",
    )


def download_file(file_id):
    """Télécharge un fichier depuis Google Drive. Renvoie un objet
    BytesIO prêt à lire, ou None en cas d'échec."""
    service = _get_service()
    if service is None:
        return None
    try:
        from googleapiclient.http import MediaIoBaseDownload
        request = service.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        buf.seek(0)
        return buf
    except Exception:
        return None


def delete_file(file_id):
    """Supprime un fichier sur Google Drive. N'échoue jamais bruyamment."""
    service = _get_service()
    if service is None:
        return
    try:
        service.files().delete(fileId=file_id).execute()
    except Exception:
        pass


def find_file_id_by_name(filename):
    """Cherche un fichier par son nom exact dans le dossier configuré.
    Renvoie son ID s'il existe, sinon None. N'échoue jamais bruyamment."""
    service = _get_service()
    if service is None:
        return None
    try:
        folder_id = os.environ["GOOGLE_DRIVE_FOLDER_ID"]
        query = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
        results = service.files().list(q=query, fields="files(id)", pageSize=1).execute()
        files = results.get("files", [])
        return files[0]["id"] if files else None
    except Exception:
        return None


def backup_db_file(local_path, filename="arppsd_backup.db"):
    """Envoie une copie de la base de données locale vers Google Drive,
    en remplaçant la sauvegarde précédente si elle existe. Appelé après
    chaque action qui modifie des données, pour ne jamais perdre plus
    qu'une poignée de secondes de travail en cas de redéploiement.
    N'échoue jamais bruyamment : un problème réseau ou de configuration
    ne doit jamais empêcher l'application de répondre normalement."""
    if not is_configured() or not os.path.exists(local_path):
        return
    try:
        existing_id = find_file_id_by_name(filename)
        with open(local_path, "rb") as f:
            buf = io.BytesIO(f.read())
        if existing_id:
            delete_file(existing_id)
        upload_bytes(buf, filename, mimetype="application/x-sqlite3")
    except Exception:
        pass


def restore_db_file_if_missing(local_path, filename="arppsd_backup.db"):
    """Au démarrage de l'application : si la base de données locale
    n'existe pas encore (cas d'un nouveau déploiement sur un disque
    éphémère), tente de la récupérer depuis la dernière sauvegarde sur
    Google Drive. Si aucune sauvegarde n'existe encore, ou en cas
    d'échec, ne fait rien — une base vide sera créée normalement."""
    if os.path.exists(local_path) or not is_configured():
        return
    try:
        file_id = find_file_id_by_name(filename)
        if not file_id:
            return
        buf = download_file(file_id)
        if buf is None:
            return
        with open(local_path, "wb") as f:
            f.write(buf.read())
    except Exception:
        pass
