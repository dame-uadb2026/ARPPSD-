"""Constantes partagées : rôles, permissions par défaut, mois, etc."""

ROLES = [
    "ADMINISTRATEUR", "PRÉSIDENT", "VICE-PRÉSIDENT", "SECRÉTAIRE", "TRÉSORIÈRE",
    "SECRÉTAIRE ADMINISTRATIF", "COMMUNICATION", "ACTIVITÉS COMMUNAUTAIRES",
    "ORGANISATION", "COMMISSAIRE AUX COMPTES", "MEMBRE",
]

PERM_KEYS = [
    "manage_members", "manage_contributions", "manage_caisse", "manage_activities",
    "manage_announcements", "manage_documents", "manage_users", "view_finance", "view_audit_log",
]

PERM_LABELS = {
    "manage_members": "Gérer les membres",
    "manage_contributions": "Gérer les cotisations",
    "manage_caisse": "Gérer la caisse sociale",
    "manage_activities": "Gérer les activités",
    "manage_announcements": "Gérer les annonces",
    "manage_documents": "Gérer les documents",
    "manage_users": "Gérer les comptes/rôles",
    "view_finance": "Voir les informations financières",
    "view_audit_log": "Voir le journal d'activité",
}

DEFAULT_PERMISSIONS = {
    "ADMINISTRATEUR": {k: True for k in PERM_KEYS},
    "PRÉSIDENT": {"manage_members": False, "manage_contributions": False, "manage_caisse": False,
                  "manage_activities": True, "manage_announcements": True, "manage_documents": False,
                  "manage_users": False, "view_finance": True, "view_audit_log": True},
    "VICE-PRÉSIDENT": {"manage_members": False, "manage_contributions": False, "manage_caisse": False,
                        "manage_activities": False, "manage_announcements": False, "manage_documents": False,
                        "manage_users": False, "view_finance": True, "view_audit_log": False},
    "SECRÉTAIRE": {"manage_members": True, "manage_contributions": False, "manage_caisse": False,
                   "manage_activities": True, "manage_announcements": True, "manage_documents": True,
                   "manage_users": False, "view_finance": False, "view_audit_log": False},
    "TRÉSORIÈRE": {"manage_members": False, "manage_contributions": True, "manage_caisse": True,
                   "manage_activities": False, "manage_announcements": False, "manage_documents": False,
                   "manage_users": False, "view_finance": True, "view_audit_log": False},
    "SECRÉTAIRE ADMINISTRATIF": {"manage_members": True, "manage_contributions": False, "manage_caisse": False,
                                  "manage_activities": False, "manage_announcements": False, "manage_documents": True,
                                  "manage_users": False, "view_finance": False, "view_audit_log": False},
    "COMMUNICATION": {"manage_members": False, "manage_contributions": False, "manage_caisse": False,
                       "manage_activities": False, "manage_announcements": True, "manage_documents": False,
                       "manage_users": False, "view_finance": False, "view_audit_log": False},
    "ACTIVITÉS COMMUNAUTAIRES": {"manage_members": False, "manage_contributions": False, "manage_caisse": False,
                                  "manage_activities": True, "manage_announcements": False, "manage_documents": False,
                                  "manage_users": False, "view_finance": False, "view_audit_log": False},
    "ORGANISATION": {"manage_members": False, "manage_contributions": False, "manage_caisse": False,
                      "manage_activities": True, "manage_announcements": False, "manage_documents": False,
                      "manage_users": False, "view_finance": False, "view_audit_log": False},
    "COMMISSAIRE AUX COMPTES": {"manage_members": False, "manage_contributions": False, "manage_caisse": False,
                                 "manage_activities": False, "manage_announcements": False, "manage_documents": False,
                                 "manage_users": False, "view_finance": True, "view_audit_log": True},
    "MEMBRE": {k: False for k in PERM_KEYS},
}

MONTHS_FR = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
             "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]

DOC_CATEGORIES = [
    "Documents administratifs", "Statuts", "Règlement intérieur", "Procès-verbaux",
    "Listes de présence", "Rapports", "Documents du bureau", "Activités", "Photos", "Archives",
]
