# app.py

from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime, timedelta
import io
import os
import uuid
from urllib.parse import urlparse

# Importations pour la génération de PDF avec ReportLab
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle
from reportlab.lib.units import mm

# Configurations Flask et SQLAlchemy
app = Flask(__name__)

# Définir le répertoire de base absolu
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Configuration de l'URI de la base de données avec un chemin absolu
DATABASE_URI = os.getenv('DATABASE_URI')
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URI
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'votre_clé_secrète')
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Afficher le chemin absolu de la base de données utilisée (pour debug)
parsed_url = urlparse(DATABASE_URI)
if parsed_url.scheme == 'sqlite':
    db_path = os.path.abspath(os.path.join(parsed_url.netloc, parsed_url.path))
    print(f"Chemin absolu de la base de données SQLite utilisée : {db_path}")
else:
    print("La base de données utilisée n'est pas SQLite.")

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

# Modèles de base (Session, Candidate, Periode)
class Session(db.Model):
    __tablename__ = 'session'
    id = db.Column(db.Integer, primary_key=True)
    code_session = db.Column(db.String(50), nullable=False, unique=True, default=lambda: f"CS-{uuid.uuid4().hex[:6].upper()}")
    site = db.Column(db.String(100), nullable=False)
    formation = db.Column(db.String(200), nullable=False)
    annule = db.Column(db.Boolean, default=False)
    candidats = db.relationship('Candidate', back_populates='session', lazy=True, cascade="all, delete-orphan")
    periodes = db.relationship('Periode', back_populates='session', lazy=True, cascade="all, delete-orphan")

    def get_display_name(self):
        return f"{self.id} - {self.formation} {self.site}"

class Candidate(db.Model):
    __tablename__ = 'candidate'
    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(100), nullable=False)
    prenom = db.Column(db.String(100), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey('session.id'), nullable=False)
    session = db.relationship('Session', back_populates='candidats')

    def __repr__(self):
        return f"<Candidate {self.prenom} {self.nom}>"

class Periode(db.Model):
    __tablename__ = 'periode'
    id = db.Column(db.Integer, primary_key=True)
    date_debut = db.Column(db.Date, nullable=False)
    date_fin = db.Column(db.Date, nullable=False)
    heures = db.Column(db.Integer, nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey('session.id'), nullable=False)
    session = db.relationship('Session', back_populates='periodes')

    def __repr__(self):
        return f"<Periode {self.date_debut} - {self.date_fin}>"

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
            return redirect(url_for('create_session'))

        # Créer une nouvelle session avec le code_session généré automatiquement
        session_obj = Session(site=site, formation=formation)
        db.session.add(session_obj)
        db.session.commit()

        # Ajouter les candidats
        candidats_data = zip(request.form.getlist('nom'), request.form.getlist('prenom'))
        for nom, prenom in candidats_data:
            if nom.strip() and prenom.strip():
                candidat = Candidate(nom=nom, prenom=prenom, session=session_obj)
                db.session.add(candidat)

        # Ajouter les périodes
        periodes_data = zip(request.form.getlist('date_debut'), request.form.getlist('date_fin'))
        for date_debut, date_fin in periodes_data:
            if date_debut and date_fin:
                try:
                    date_debut_dt = datetime.strptime(date_debut, '%Y-%m-%d').date()
                    date_fin_dt = datetime.strptime(date_fin, '%Y-%m-%d').date()
                    if date_debut_dt <= date_fin_dt:
                        nb_jours = (date_fin_dt - date_debut_dt).days + 1
                        heures = nb_jours * 7
                        periode = Periode(date_debut=date_debut_dt, date_fin=date_fin_dt, heures=heures, session=session_obj)
                        db.session.add(periode)
                    else:
                        flash("Erreur : La date de début doit être antérieure ou égale à la date de fin.", "danger")
                        return redirect(url_for('create_session'))
                except ValueError:
                    flash("Format de date invalide. Veuillez utiliser le format AAAA-MM-JJ.", "danger")
                    return redirect(url_for('create_session'))

        db.session.commit()
        flash("Session créée avec succès.", "success")
        return redirect(url_for('success'))
    else:
        return render_template('create_session.html', site_options=SITE_OPTIONS, formation_options=FORMATION_OPTIONS)

@app.route('/success')
def success():
    return render_template('success.html')

@app.route('/session/<int:session_id>', methods=['GET'])
def session_details(session_id):
    session_obj = Session.query.get_or_404(session_id)
    candidates = session_obj.candidats
    return render_template('session_details.html', session=session_obj, candidates=candidates)

@app.route('/delete_candidate/<int:candidate_id>', methods=['POST'])
def delete_candidate(candidate_id):
    candidate = Candidate.query.get_or_404(candidate_id)
    db.session.delete(candidate)
    db.session.commit()
    flash("Candidat supprimé avec succès.", "success")
    return redirect(url_for('session_details', session_id=candidate.session_id))

@app.route('/sessions')
def list_sessions():
    sessions = Session.query.all()
    return render_template('sessions.html', sessions=sessions)

@app.route('/delete_session/<int:session_id>', methods=['POST'])
def delete_session(session_id):
    session_obj = Session.query.get_or_404(session_id)
    db.session.delete(session_obj)
    db.session.commit()
    flash("Session supprimée avec succès.", "success")
    return redirect(url_for('list_sessions'))

@app.route('/cancel_session/<int:session_id>', methods=['POST'])
def cancel_session(session_id):
    session_obj = Session.query.get_or_404(session_id)
    if session_obj.annule:
        flash("La session est déjà annulée.", "info")
    else:
        session_obj.annule = True
        db.session.commit()
        flash("La session a été annulée avec succès.", "success")
    return redirect(url_for('list_sessions'))

@app.route('/generate_attendance', methods=['GET', 'POST'])
def generate_attendance():
    sessions = Session.query.all()
    if request.method == 'POST':
        session_id = request.form.get('session_id')
        periode_id = request.form.get('periode_id')
        candidate_id = request.form.get('candidate_id')
        all_candidates = request.form.get('all_candidates')
        all_periodes = request.form.get('all_periodes')

        session_obj = Session.query.get(session_id)

        if not session_obj:
            flash("Session invalide.", "danger")
            return redirect(url_for('generate_attendance'))

        # Déterminer les périodes à utiliser
        if all_periodes:
            periodes = session_obj.periodes
        else:
            periode = Periode.query.get(periode_id)
            if not periode:
                flash("Période invalide.", "danger")
                return redirect(url_for('generate_attendance'))
            periodes = [periode]

        # Déterminer les candidats à utiliser
        if all_candidates:
            candidats = session_obj.candidats
        else:
            candidat = Candidate.query.get(candidate_id)
            if not candidat:
                flash("Candidat invalide.", "danger")
                return redirect(url_for('generate_attendance'))
            candidats = [candidat]

        # Générer le PDF
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4

        for periode in periodes:
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
                session_title = session_obj.get_display_name()
                session_title_width = p.stringWidth(session_title, "Helvetica-Oblique", 14)
                p.drawString((width - session_title_width) / 2, current_y, session_title)

                # Mettre à jour la position Y après le titre de la session
                current_y -= 20  # 20 points d'espace après le titre de la session

                # Informations à gauche
                p.setFont("Helvetica", 10)
                p.drawString(50, current_y, f"Candidat : {candidat.prenom} {candidat.nom}")
                current_y -= 12  # Espace entre les lignes
                p.drawString(50, current_y, f"Période : du {periode.date_debut.strftime('%d/%m/%Y')} au {periode.date_fin.strftime('%d/%m/%Y')}")
                current_y -= 12
                p.drawString(50, current_y, f"Nombre d'heures à effectuer : {periode.heures}")
                current_y -= 15  # Espace supplémentaire avant le tableau

                # Tableau pour l'émargement avec une colonne "Signature CFA"
                data = [
                    ["Date", "Matin", "Observation(s)", "Après-midi", "Observation(s)", "Signature", "Signature CFA"]
                ]
                for day in range(0, (periode.date_fin - periode.date_debut).days + 1):
                    date = periode.date_debut + timedelta(days=day)
                    data.append([
                        date.strftime('%d/%m/%Y'),
                        "",
                        "",
                        "",
                        "",
                        "",
                        ""
                    ])

                # Déterminer la hauteur des lignes en fonction du nombre de dates
                nb_dates = len(data) - 1
                if nb_dates > 12:
                    row_height = 26  # Hauteur réduite pour plus de dates
                else:
                    row_height = 32  # Hauteur standard

                # Création du tableau avec une colonne supplémentaire et hauteur ajustée
                table = Table(data, colWidths=[60, 60, 80, 60, 80, 70, 70], rowHeights=row_height)
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

@app.route('/session/<int:session_id>/edit_name', methods=['POST'])
def edit_session_name(session_id):
    session = Session.query.get_or_404(session_id)
    new_name = request.form.get('new_name')
    
    # Séparer la formation et le site dans le champ de saisie
    if " - " in new_name:
        formation, site = new_name.split(" - ", 1)
        session.formation = formation.strip()
        session.site = site.strip()
        db.session.commit()
        flash("Nom et site de la session mis à jour avec succès.", "success")
    else:
        flash("Veuillez utiliser le format : 'Nom de la formation - Site'.", "warning")
    return redirect(url_for('list_sessions'))

@app.route('/get_periodes/<int:session_id>')
def get_periodes(session_id):
    periodes = Periode.query.filter_by(session_id=session_id).all()
    periodes_data = [
        {"id": p.id, "date_debut": p.date_debut.strftime('%d/%m/%Y'), "date_fin": p.date_fin.strftime('%d/%m/%Y')}
        for p in periodes
    ]
    return jsonify({"periodes": periodes_data})

@app.route('/get_candidates/<int:session_id>')
def get_candidates(session_id):
    candidates = Candidate.query.filter_by(session_id=session_id).all()
    candidates_data = [{"id": c.id, "nom": c.nom, "prenom": c.prenom} for c in candidates]
    return jsonify({"candidates": candidates_data})

@app.route('/session/<int:session_id>/add_candidate', methods=['POST'])
def add_candidate(session_id):
    session_obj = Session.query.get_or_404(session_id)
    nom = request.form.get('nom')
    prenom = request.form.get('prenom')

    if not nom or not prenom:
        flash("Le nom et le prénom du candidat sont requis.", "warning")
        return redirect(url_for('session_details', session_id=session_id))

    # Optionnel : vérifier si le candidat existe déjà dans la session
    existing_candidate = Candidate.query.filter_by(nom=nom.strip(), prenom=prenom.strip(), session_id=session_id).first()
    if existing_candidate:
        flash("Ce candidat est déjà inscrit dans cette session.", "info")
        return redirect(url_for('session_details', session_id=session_id))

    # Créer un nouveau candidat
    new_candidate = Candidate(nom=nom.strip(), prenom=prenom.strip(), session=session_obj)
    db.session.add(new_candidate)

    try:
        db.session.commit()
        flash(f"Candidat {prenom} {nom} ajouté avec succès.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Erreur lors de l'ajout du candidat : {e}", "danger")

    return redirect(url_for('session_details', session_id=session_id))


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
