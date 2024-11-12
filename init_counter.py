# init_counter.py

import os
import json
import base64
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

# Charger les variables d'environnement depuis .env
load_dotenv()

# Initialiser Firebase avec la clé décryptée
firebase_service_account_b64 = os.getenv('FIREBASE_SERVICE_ACCOUNT')
if not firebase_service_account_b64:
    raise ValueError("La variable d'environnement FIREBASE_SERVICE_ACCOUNT n'est pas définie.")

service_account_info = json.loads(base64.b64decode(firebase_service_account_b64))
cred = credentials.Certificate(service_account_info)
firebase_admin.initialize_app(cred)

# Initialiser Firestore
db = firestore.client()

def initialize_counter():
    sessions_ref = db.collection('sessions')
    counter_ref = db.collection('counters').document('sessions')

    # Compter le nombre de sessions existantes
    count = sum(1 for _ in sessions_ref.stream())

    # Mettre à jour le compteur
    counter_ref.set({'current': count}, merge=True)
    print(f"Compteur initialisé à {count} sessions.")

if __name__ == "__main__":
    initialize_counter()
