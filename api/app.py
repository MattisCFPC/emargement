# api/app.py

import os
import json
import base64
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from datetime import datetime, timedelta
import io
from dotenv import load_dotenv
import warnings
from urllib3.exceptions import NotOpenSSLWarning
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle
from reportlab.lib.units import mm
import logging

# Importations pour Firestore
from google.cloud import firestore
from google.oauth2 import service_account
import firebase_admin
from firebase_admin import credentials

# Ignorer les avertissements NotOpenSSLWarning (facultatif)
warnings.simplefilter('ignore', NotOpenSSLWarning)

# Charger les variables d'environnement depuis .env
load_dotenv()

# Configurations Flask
app = Flask(__name__, template_folder='../templates', static_folder='../static')
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')  # Pas de valeur par défaut

# Vérifier que la clé secrète est définie
if not app.config['SECRET_KEY']:
    raise ValueError("La variable d'environnement SECRET_KEY n'est pas définie.")

# Initialiser Firebase avec la clé décryptée
firebase_service_account_b64 = os.getenv('FIREBASE_SERVICE_ACCOUNT')
if not firebase_service_account_b64:
    raise ValueError("La variable d'environnement FIREBASE_SERVICE_ACCOUNT n'est pas définie.")

try:
    service_account_info = json.loads(base64.b64decode(firebase_service_account_b64))
except Exception as e:
    raise ValueError(f"Erreur lors du décodage de FIREBASE_SERVICE_ACCOUNT : {e}")

# Initialiser Firebase Admin SDK
cred = credentials.Certificate(service_account_info)
firebase_admin.initialize_app(cred)

# Créer les credentials pour google.cloud.firestore
credentials = service_account.Credentials.from_service_account_info(service_account_info)

# Initialiser Firestore avec les credentials appropriés
db = firestore.Client(credentials=credentials)

# Définir les options pour les sites et les formations
SITE_OPTIONS = [
    "Saint-Pierre",
    "Saint-André",
    "St-Pierre & St-André"
]

FORMATION_OPTIONS = [
    "TP CTRMP",
    "TP CLVUL",
    "TP CTRMTV",
    "TP CTCR",
    "Cariste d'entrepôt",
    "Conducteur d'engins de Chantier"
]

# Configurer le logging
logging.basicConfig(level=logging.DEBUG)

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/create_session', methods=['GET', 'POST'])
def create_session():
    if request.method == 'POST':
        site = request.form.get('site')
        formation = request.form.get('formation')

        # Validation des champs
        if site not in SITE_OPTIONS or formation not in FORMATION_OPTIONS:
            flash("Option de site ou de formation invalide.", "danger")
            logging.warning("Option de site ou de formation invalide.")
            return redirect(url_for('create_session'))

        # Obtenir le nombre actuel de sessions
        sessions_ref = db.collection('sessions')
        sessions_count = len(list(sessions_ref.stream()))
        session_number = sessions_count + 1

        # Créer une nouvelle session avec le numéro séquentiel
        session_ref = db.collection('sessions').document()
        session_data = {
            'session_number': session_number,
            'site': site,
            'formation': formation,
            'annule': False,
            'created_at': firestore.SERVER_TIMESTAMP
        }
        session_ref.set(session_data)
        logging.debug(f"Session créée avec l'ID {session_ref.id} et le numéro {session_number}.")
        session_id = session_ref.id

        # Ajouter les candidats
        noms = request.form.getlist('nom')
        prenoms = request.form.getlist('prenom')
        for nom, prenom in zip(noms, prenoms):
            if nom.strip() and prenom.strip():
                candidat_data = {
                    'nom': nom.strip(),
                    'prenom': prenom.strip(),
                    'session_id': session_id,
                    'created_at': firestore.SERVER_TIMESTAMP
                }
                db.collection('candidats').add(candidat_data)
                logging.debug(f"Candidat ajouté : {prenom} {nom}.")

        # Ajouter les périodes
        dates_debut = request.form.getlist('date_debut')
        dates_fin = request.form.getlist('date_fin')
        for date_debut, date_fin in zip(dates_debut, dates_fin):
            if date_debut and date_fin:
                try:
                    date_debut_dt = datetime.strptime(date_debut, '%Y-%m-%d').date()
                    date_fin_dt = datetime.strptime(date_fin, '%Y-%m-%d').date()
                    if date_debut_dt <= date_fin_dt:
                        nb_jours = (date_fin_dt - date_debut_dt).days + 1
                        heures = nb_jours * 7
                        periode_data = {
                            'date_debut': date_debut_dt.strftime('%d/%m/%Y'),
                            'date_fin': date_fin_dt.strftime('%d/%m/%Y'),
                            'heures': heures,
                            'session_id': session_id,
                            'created_at': firestore.SERVER_TIMESTAMP
                        }
                        db.collection('periodes').add(periode_data)
                        logging.debug(f"Période ajoutée : {date_debut} au {date_fin}, Heures : {heures}.")
                    else:
                        flash("Erreur : La date de début doit être antérieure ou égale à la date de fin.", "danger")
                        logging.warning("Date de début postérieure à la date de fin.")
                        return redirect(url_for('create_session'))
                except ValueError:
                    flash("Format de date invalide. Veuillez utiliser le format AAAA-MM-JJ.", "danger")
                    logging.warning("Format de date invalide.")
                    return redirect(url_for('create_session'))

        flash(f"Session créée avec succès. Numéro de session : {session_number}", "success")
        return redirect(url_for('success', session_number=session_number))
    else:
        return render_template('create_session.html', site_options=SITE_OPTIONS, formation_options=FORMATION_OPTIONS)

@app.route('/success')
def success():
    session_number = request.args.get('session_number')
    return render_template('success.html', session_number=session_number)

@app.route('/session/<string:session_id>', methods=['GET'])
def session_details(session_id):
    session_ref = db.collection('sessions').document(session_id)
    session = session_ref.get()
    if not session.exists:
        flash("Session non trouvée.", "danger")
        return redirect(url_for('list_sessions'))
    session_data = session.to_dict()
    session_data['id'] = session.id

    # Récupérer les candidats
    candidats_ref = db.collection('candidats').where('session_id', '==', session_id)
    candidats = []
    for doc in candidats_ref.stream():
        candidat = doc.to_dict()
        candidat['id'] = doc.id
        candidats.append(candidat)

    # Récupérer les périodes
    periodes_ref = db.collection('periodes').where('session_id', '==', session_id)
    periodes = []
    for doc in periodes_ref.stream():
        periode = doc.to_dict()
        periode['id'] = doc.id
        periodes.append(periode)

    return render_template('session_details.html', session=session_data, candidates=candidats, periodes=periodes)

@app.route('/delete_candidate/<string:candidate_id>', methods=['POST'])
def delete_candidate(candidate_id):
    candidate_ref = db.collection('candidats').document(candidate_id)
    candidate = candidate_ref.get()
    if not candidate.exists:
        flash("Candidat non trouvé.", "danger")
        return redirect(url_for('list_sessions'))
    
    session_id = candidate.to_dict()['session_id']
    candidate_ref.delete()
    flash("Candidat supprimé avec succès.", "success")
    return redirect(url_for('session_details', session_id=session_id))

@app.route('/sessions')
def list_sessions():
    sessions = []
    sessions_ref = db.collection('sessions').order_by('created_at', direction=firestore.Query.DESCENDING)
    for doc in sessions_ref.stream():
        session = doc.to_dict()
        session['id'] = doc.id
        sessions.append(session)
    return render_template('sessions.html', sessions=sessions)

@app.route('/delete_session/<string:session_id>', methods=['POST'])
def delete_session(session_id):
    session_ref = db.collection('sessions').document(session_id)
    session = session_ref.get()
    if not session.exists:
        flash("Session non trouvée.", "danger")
        return redirect(url_for('list_sessions'))
    
    # Supprimer tous les candidats liés
    candidats_ref = db.collection('candidats').where('session_id', '==', session_id)
    for doc in candidats_ref.stream():
        doc.reference.delete()
    
    # Supprimer toutes les périodes liées
    periodes_ref = db.collection('periodes').where('session_id', '==', session_id)
    for doc in periodes_ref.stream():
        doc.reference.delete()
    
    # Supprimer la session
    session_ref.delete()
    flash("Session supprimée avec succès.", "success")
    return redirect(url_for('list_sessions'))

@app.route('/cancel_session/<string:session_id>', methods=['POST'])
def cancel_session(session_id):
    session_ref = db.collection('sessions').document(session_id)
    session = session_ref.get()
    if not session.exists:
        flash("Session non trouvée.", "danger")
        return redirect(url_for('list_sessions'))
    
    session_data = session.to_dict()
    if session_data.get('annule', False):
        flash("La session est déjà annulée.", "info")
    else:
        session_ref.update({'annule': True})
        flash("La session a été annulée avec succès.", "success")
    
    return redirect(url_for('list_sessions'))

@app.route('/generate_attendance', methods=['GET', 'POST'])
def generate_attendance():
    sessions_ref = db.collection('sessions').order_by('session_number')
    sessions = []
    for doc in sessions_ref.stream():
        session = doc.to_dict()
        session['id'] = doc.id
        sessions.append(session)
    
    if request.method == 'POST':
        session_id = request.form.get('session_id')
        periode_id = request.form.get('periode_id')
        candidate_id = request.form.get('candidate_id')
        all_candidates = request.form.get('all_candidates')
        all_periodes = request.form.get('all_periodes')

        session_ref = db.collection('sessions').document(session_id)
        session = session_ref.get()
        if not session.exists:
            flash("Session invalide.", "danger")
            return redirect(url_for('generate_attendance'))
        session_data = session.to_dict()

        # Déterminer les périodes à utiliser
        if all_periodes:
            periodes_ref = db.collection('periodes').where('session_id', '==', session_id)
            periodes = [p.to_dict() for p in periodes_ref.stream()]
        else:
            periode_ref = db.collection('periodes').document(periode_id)
            periode = periode_ref.get()
            if not periode.exists:
                flash("Période invalide.", "danger")
                return redirect(url_for('generate_attendance'))
            periodes = [periode.to_dict()]

        # Déterminer les candidats à utiliser
        if all_candidates:
            candidats_ref = db.collection('candidats').where('session_id', '==', session_id)
            candidats = [c.to_dict() for c in candidats_ref.stream()]
        else:
            candidat_ref = db.collection('candidats').document(candidate_id)
            candidat = candidat_ref.get()
            if not candidat.exists:
                flash("Candidat invalide.", "danger")
                return redirect(url_for('generate_attendance'))
            candidats = [candidat.to_dict()]

        # Générer le PDF
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4

        for periode in periodes:
            try:
                date_debut_dt = datetime.strptime(periode.get('date_debut', '01/01/1970'), '%d/%m/%Y').date()
                date_fin_dt = datetime.strptime(periode.get('date_fin', '01/01/1970'), '%d/%m/%Y').date()
            except Exception as e:
                flash(f"Erreur de format de date dans la période : {e}", "danger")
                return redirect(url_for('generate_attendance'))
            
            for candidat in candidats:
                # Titre centré en gras
                p.setFont("Helvetica-Bold", 18)
                title = "FEUILLE D'ÉMARGEMENT CFA"
                title_width = p.stringWidth(title, "Helvetica-Bold", 18)
                p.drawString((width - title_width) / 2, height - 60, title)

                # Mettre à jour la position Y après le titre
                current_y = height - 60 - 20  # 20 points d'espace après le titre

                # Nom de la session en italique, centré
                p.setFont("Helvetica-Oblique", 14)
                session_title = f"Session {session_data.get('session_number', 'N/A')} - {session_data.get('formation', '')} {session_data.get('site', '')}"
                session_title_width = p.stringWidth(session_title, "Helvetica-Oblique", 14)
                p.drawString((width - session_title_width) / 2, current_y, session_title)

                # Mettre à jour la position Y après le titre de la session
                current_y -= 20  # 20 points d'espace après le titre de la session

                # Informations à gauche
                p.setFont("Helvetica", 10)
                p.drawString(50, current_y, f"Candidat : {candidat.get('prenom', '')} {candidat.get('nom', '')}")
                current_y -= 12  # Espace entre les lignes
                p.drawString(50, current_y, f"Période : du {periode.get('date_debut', '')} au {periode.get('date_fin', '')}")
                current_y -= 12
                p.drawString(50, current_y, f"Nombre d'heures à effectuer : {periode.get('heures', 0)}")
                current_y -= 15  # Espace supplémentaire avant le tableau

                # Tableau pour l'émargement avec une colonne "Signature CFA"
                data = [
                    ["Date", "Matin", "Observation(s)", "Après-midi", "Observation(s)", "Signature CFA"]
                ]
                for day in range(0, (date_fin_dt - date_debut_dt).days + 1):
                    date = date_debut_dt + timedelta(days=day)
                    data.append([
                        date.strftime('%d/%m/%Y'),
                        "",
                        "",
                        "",
                        "",
                        "",
                    ])

                # Déterminer la hauteur des lignes en fonction du nombre de dates
                nb_dates = len(data) - 1
                if nb_dates > 12:
                    row_height = 26  # Hauteur réduite pour plus de dates
                else:
                    row_height = 32  # Hauteur standard

                # Création du tableau avec une colonne supplémentaire et hauteur ajustée
                table = Table(data, colWidths=[60, 60, 80, 60, 80, 70], rowHeights=row_height)
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2FAC66")),  # Couleur d'en-tête
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 8),  # Taille de police réduite à 8
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.black),  # Réduction de l'épaisseur des lignes à 0.5
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),  # Centrer le texte horizontalement
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),  # Centrer le texte verticalement
                ]))
                table.wrapOn(p, width, height)

                # Calculer la position verticale disponible
                # Estimer la hauteur totale du tableau
                table_height = row_height * len(data)
                # Positionner le tableau en haut de la page, après les informations
                table_x = 50
                table_y = current_y - table_height  # Position dynamique basé sur current_y

                # Dessiner le tableau sans vérification de dépassement
                table.drawOn(p, table_x, table_y)

                # Mettre à jour current_y après le tableau
                current_y = table_y - 40  # Espace après le tableau

                # Ajouter "Certifié exact pour le CFA GH le :" et la date
                p.setFont("Helvetica", 10)
                cert_text = "Certifié exact pour le CFA GH le :"
                p.drawString(260, current_y, cert_text)

                # Ajouter un rectangle vide avec "Cachet de l'entreprise" en petit et italique
                # Définir les dimensions du rectangle
                rect_width = 200
                rect_height = 50
                rect_x = 50
                rect_y = current_y - 30  # Position ajustée selon l'espace disponible

                p.rect(rect_x, rect_y, rect_width, rect_height, stroke=1, fill=0)

                padding_x = 10  # Espacement horizontal depuis la gauche du rectangle
                padding_y = 10  # Espacement vertical depuis le haut du rectangle

                # Définir une taille de police réduite
                p.setFont("Helvetica-Oblique", 8)  # Taille de police réduite à 8

                cachet_text = "Cachet de l'entreprise"

                # Calculer la position `y` pour aligner le texte en haut à gauche
                text_x = rect_x + padding_x
                text_y = rect_y + rect_height - padding_y - 8  # 8 est la taille de la police

                p.drawString(text_x, text_y, cachet_text)

                # Passer à une nouvelle page
                p.showPage()

        # Sauvegarder et envoyer le PDF
        p.save()
        buffer.seek(0)
        return send_file(buffer, as_attachment=True, download_name="feuille_emargement.pdf", mimetype='application/pdf')
    else:
        return render_template('attendance_sheet.html', sessions=sessions)

@app.route('/session/<string:session_id>/edit_name', methods=['POST'])
def edit_session_name(session_id):
    session_ref = db.collection('sessions').document(session_id)
    session = session_ref.get()
    if not session.exists:
        flash("Session non trouvée.", "danger")
        return redirect(url_for('list_sessions'))
    
    new_name = request.form.get('new_name')
    
    # Séparer la formation et le site dans le champ de saisie
    if " - " in new_name:
        formation, site = new_name.split(" - ", 1)
        formation = formation.strip()
        site = site.strip()
        session_ref.update({
            'formation': formation,
            'site': site
        })
        flash("Nom et site de la session mis à jour avec succès.", "success")
    else:
        flash("Veuillez utiliser le format : 'Nom de la formation - Site'.", "warning")
    return redirect(url_for('list_sessions'))

@app.route('/get_periodes/<string:session_id>')
def get_periodes(session_id):
    periodes_ref = db.collection('periodes').where('session_id', '==', session_id)
    periodes_data = [
        {"id": p.id, "date_debut": p.to_dict().get('date_debut', ''), "date_fin": p.to_dict().get('date_fin', '')}
        for p in periodes_ref.stream()
    ]
    return jsonify({"periodes": periodes_data})

@app.route('/get_candidates/<string:session_id>')
def get_candidates(session_id):
    candidats_ref = db.collection('candidats').where('session_id', '==', session_id)
    candidates_data = [
        {"id": c.id, "nom": c.to_dict().get('nom', ''), "prenom": c.to_dict().get('prenom', '')}
        for c in candidats_ref.stream()
    ]
    return jsonify({"candidates": candidates_data})

@app.route('/session/<string:session_id>/add_candidate', methods=['POST'])
def add_candidate(session_id):
    session_ref = db.collection('sessions').document(session_id)
    session = session_ref.get()
    if not session.exists:
        flash("Session non trouvée.", "danger")
        return redirect(url_for('list_sessions'))
    
    nom = request.form.get('nom')
    prenom = request.form.get('prenom')

    if not nom or not prenom:
        flash("Le nom et le prénom du candidat sont requis.", "warning")
        return redirect(url_for('session_details', session_id=session_id))

    # Optionnel : vérifier si le candidat existe déjà dans la session
    candidats_ref = db.collection('candidats').where('session_id', '==', session_id)\
                                           .where('nom', '==', nom.strip())\
                                           .where('prenom', '==', prenom.strip())
    if list(candidats_ref.stream()):
        flash("Ce candidat est déjà inscrit dans cette session.", "info")
        return redirect(url_for('session_details', session_id=session_id))

    # Créer un nouveau candidat
    candidat_data = {
        'nom': nom.strip(),
        'prenom': prenom.strip(),
        'session_id': session_id,
        'created_at': firestore.SERVER_TIMESTAMP
    }
    db.collection('candidats').add(candidat_data)
    flash(f"Candidat {prenom} {nom} ajouté avec succès.", "success")
    return redirect(url_for('session_details', session_id=session_id))

#if __name__ == '__main__':
#    port = int(os.getenv("PORT", 5000))
#       app.run(host='0.0.0.0', port=port, debug=False)
