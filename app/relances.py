"""Préparation et envoi des relances.

Préparation (à partir de la file du jour) :
- une relance par facture et par étape, une seule fois : clé d'idempotence « facture | étape | échéance »
  avec contrainte UNIQUE en base (le canal n'en fait volontairement pas partie : la même étape n'est
  jamais envoyée deux fois, même sur deux canaux) ;
- un seul message par client et par jour : ses factures sont regroupées dans un « lot d'envoi » ;
- le ton du message est celui de l'étape la plus avancée du lot ;
- le lot part en validation humaine si une seule de ses factures l'exige, ou si le contrôle de ton échoue ;
- l'étape R5 ne produit pas de message client : c'est un dossier d'escalade remis au responsable.

Envoi : seuls les lots entièrement validés partent, par le connecteur (bac à sable par défaut).
La revalidation juste avant l'envoi et la reprise après interruption sont traitées en phase 5.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime, time, timezone

from app import etat as moteur
from app import garde_fous, gabarits, journal, parametres, priorisation, verrous
from app.connecteurs import Connecteur, Envoi, connecteur_par_defaut
from app.db import transaction
from app.erreurs import ErreurMetier
from app.montants import formater
from app.references import formater_reference

CANAUX_TELEPHONE = ("sms", "whatsapp")


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def choisir_canal(client: sqlite3.Row) -> tuple[str, str] | None:
    """Canal préféré s'il est joignable, sinon le premier canal joignable. None : aucun contact."""
    def destinataire(canal: str) -> str | None:
        return client["telephone"] if canal in CANAUX_TELEPHONE else client["email"]

    ordre = [client["canal_prefere"]] + [c for c in ("whatsapp", "sms", "email") if c != client["canal_prefere"]]
    for canal in ordre:
        if destinataire(canal):
            return canal, destinataire(canal)
    return None


def cle_idempotence(facture_id: int, etape: str, echeance: str) -> str:
    return f"F{facture_id}|{etape}|{echeance}"


def cle_lot(client_id: int, jour: str, nature: str) -> str:
    return f"C{client_id}|{jour}|{nature}"


def _verifier_arret_urgence(conn) -> None:
    if parametres.lire(conn, "arret_urgence"):
        raise ErreurMetier("ARRET_URGENCE", "Arrêt d'urgence actif : aucune relance n'est préparée ni envoyée")


def _note_escalade(client: sqlite3.Row, priorites: list[priorisation.Priorite]) -> str:
    lignes = [f"Dossier d'escalade (R5) - client {client['code']} {client['nom']}",
              "À remettre au responsable du recouvrement : aucun message automatique n'est envoyé au client.", ""]
    for p in priorites:
        e = p.facture
        lignes.append(f"- {e.numero} : {e.jours_retard} j de retard, solde {formater(e.solde, e.devise, e.decimales)}"
                      f", réf. {formater_reference(e.reference_paiement)}")
        lignes.append(f"  {p.explication}")
    return "\n".join(lignes)


def preparer(conn: sqlite3.Connection, auteur: str = "systeme") -> dict:
    """Crée les relances dues aujourd'hui. Idempotent : relancée, la préparation ne crée rien de plus."""
    resume = {"lots": 0, "relances": 0, "a_valider": 0, "validees": 0, "deja_preparees": 0, "ignorees": []}
    with transaction(conn):
        _verifier_arret_urgence(conn)
        ctx = moteur.contexte(conn)
        jour = ctx.reference.isoformat()
        entreprise = parametres.lire(conn, "entreprise")
        file, _ = priorisation.file_du_jour(conn, ctx=ctx)

        groupes: dict[tuple, list[priorisation.Priorite]] = defaultdict(list)
        for p in file:
            e = p.facture
            if conn.execute("SELECT 1 FROM relances WHERE cle_idempotence = ?",
                            (cle_idempotence(e.id, p.etape["etape"], e.date_echeance),)).fetchone():
                resume["deja_preparees"] += 1
                continue
            nature = "escalade" if p.etape["etape"] == "R5" else "message"
            groupes[(e.client_id, nature)].append(p)

        for (client_id, nature), priorites in sorted(groupes.items()):
            lot = cle_lot(client_id, jour, nature)
            if conn.execute("SELECT 1 FROM relances WHERE lot_envoi = ? AND statut <> 'annulee'", (lot,)).fetchone():
                resume["ignorees"] += [{"facture_id": p.facture.id, "code": "CLIENT_DEJA_TRAITE_AUJOURDHUI",
                                        "motif": "Un message a déjà été préparé aujourd'hui pour ce client"}
                                       for p in priorites]
                continue
            client = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
            raisons = sorted({r for p in priorites for r in p.raisons_validation})
            if nature == "escalade":
                canal, texte = client["canal_prefere"], _note_escalade(client, priorites)
                validation, raisons = True, ["escalade R5 : dossier remis au responsable"]
            else:
                choix = choisir_canal(client)
                if choix is None:
                    resume["ignorees"] += [{"facture_id": p.facture.id, "code": "SANS_CONTACT",
                                            "motif": "Aucun téléphone ni e-mail : à traiter par un humain"}
                                           for p in priorites]
                    continue
                canal = choix[0]
                etape_ton = max(p.etape["etape"] for p in priorites)
                lignes = [gabarits.LigneFacture(p.facture.numero, p.facture.date_emission, p.facture.date_echeance,
                                                p.facture.jours_retard, p.facture.solde, p.facture.devise,
                                                p.facture.decimales, p.facture.reference_paiement)
                          for p in sorted(priorites, key=lambda p: (p.facture.date_echeance, p.facture.numero))]
                mixte = len({p.etape["etape"] for p in priorites}) > 1
                message = gabarits.rendre(etape_ton, canal, client["nom"], lignes, entreprise, etapes_mixtes=mixte)
                texte = (f"Objet : {message.objet}\n\n" if message.objet else "") + message.texte
                ecarts = gabarits.controler_ton(message.texte)
                if len(message.texte) > gabarits.LONGUEUR_MAX[canal]:
                    ecarts.append(f"message trop long pour {canal} ({len(message.texte)} caractères)")
                raisons += [f"contrôle du message : {e}" for e in ecarts]
                validation = bool(raisons)
            statut = "a_valider" if validation else "validee"
            for p in priorites:
                e = p.facture
                cle = cle_idempotence(e.id, p.etape["etape"], e.date_echeance)
                rid = conn.execute(
                    "INSERT INTO relances (facture_id, client_id, etape, canal, periode, cle_idempotence, statut,"
                    " motif_validation, message, version_facture, solde_prepare, lot_envoi, date_preparation)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (e.id, client_id, p.etape["etape"], canal, e.date_echeance, cle, statut,
                     "; ".join(raisons) or None, texte, e.version, e.solde, lot, jour)).lastrowid
                journal.ajouter(conn, acteur=auteur, type_acteur="systeme", action="preparation_relance",
                                objet_type="relance", objet_id=rid,
                                apres={"facture_id": e.id, "numero": e.numero, "etape": p.etape["etape"], "canal": canal,
                                       "lot": lot, "statut": statut, "solde": e.solde, "score": str(p.score),
                                       "explication": p.explication, "raisons": raisons},
                                regle=f"SEQUENCE_{p.etape['etape']}" + ("+VALIDATION_HUMAINE" if validation else ""))
                resume["relances"] += 1
                resume["a_valider" if validation else "validees"] += 1
            resume["lots"] += 1
    return resume


def _dans_la_plage(conn, maintenant: datetime | None) -> bool:
    if not parametres.lire(conn, "controle_heures_envoi"):
        return True
    plage = parametres.lire(conn, "heures_envoi")
    heure = (maintenant or datetime.now()).time()
    return time.fromisoformat(plage["debut"]) <= heure <= time.fromisoformat(plage["fin"])


def _decouper(texte: str) -> tuple[str | None, str]:
    if texte.startswith("Objet : "):
        objet, _, corps = texte.partition("\n\n")
        return objet.removeprefix("Objet : "), corps
    return None, texte


def envoyer(conn: sqlite3.Connection, auteur: str = "systeme", connecteur: Connecteur | None = None,
            maintenant: datetime | None = None) -> dict:
    """Envoie les lots entièrement validés, un par un, sous verrou.

    1. reprise des lots interrompus (garde_fous.reprendre) ;
    2. pour chaque lot validé, dans une transaction : revalidation (état réel, message), puis passage
       « en cours d'envoi » et enregistrement du message sortant ;
    3. appel du connecteur (hors transaction) ;
    4. dans une transaction : « envoyé » + accusé + journal.
    Une coupure entre 2 et 4 est rattrapée par l'étape 1 au lancement suivant, sans second envoi.
    """
    _verifier_arret_urgence(conn)
    if not _dans_la_plage(conn, maintenant):
        plage = parametres.lire(conn, "heures_envoi")
        raise ErreurMetier("HORS_PLAGE_HORAIRE", f"Envoi autorisé entre {plage['debut']} et {plage['fin']} seulement")
    connecteur = connecteur or connecteur_par_defaut()
    detenteur = verrous.nouveau_detenteur()
    if not verrous.acquerir(conn, "envoi", detenteur):
        raise ErreurMetier("TRAITEMENT_EN_COURS", "Un envoi est déjà en cours : réessayez dans un instant")
    try:
        resume = {"envoyes": 0, "echecs": 0, "annules": 0, "lots": [], "reprise": garde_fous.reprendre(conn, connecteur)}
        lots = [r["lot_envoi"] for r in conn.execute(
            "SELECT lot_envoi FROM relances WHERE statut NOT IN ('annulee') GROUP BY lot_envoi"
            " HAVING sum(statut <> 'validee') = 0 ORDER BY min(id)")]
        for lot in lots:
            _envoyer_lot(conn, lot, auteur, connecteur, resume)
        return resume
    finally:
        verrous.liberer(conn, "envoi", detenteur)


def _envoyer_lot(conn, lot: str, auteur: str, connecteur: Connecteur, resume: dict) -> None:
    with transaction(conn):
        _verifier_arret_urgence(conn)
        relances = conn.execute("SELECT * FROM relances WHERE lot_envoi = ? AND statut <> 'annulee' ORDER BY id",
                                (lot,)).fetchall()
        if not relances or any(r["statut"] != "validee" for r in relances):
            return  # modifié entre-temps
        raisons = garde_fous.revalider_lot(conn, relances)
        if raisons:
            garde_fous.annuler_lot(conn, lot, raisons, "systeme", "systeme", "REVALIDATION_AVANT_ENVOI")
            resume["annules"] += 1
            return
        client = conn.execute("SELECT * FROM clients WHERE id = ?", (relances[0]["client_id"],)).fetchone()
        escalade = relances[0]["etape"] == "R5"
        canal = "email" if escalade else relances[0]["canal"]
        destinataire = "responsable recouvrement (interne)" if escalade else (
            client["email"] if canal == "email" else client["telephone"])
        conn.execute("UPDATE relances SET statut = 'en_cours_envoi', maj_le = ? WHERE lot_envoi = ? AND statut = 'validee'",
                     (_maintenant(), lot))
        existant = conn.execute("SELECT id FROM messages_sortants WHERE cle_envoi = ?", (lot,)).fetchone()
        if existant:  # nouvel essai après une reprise ou un échec : même clé d'envoi, même ligne
            message_id = existant["id"]
            conn.execute("UPDATE messages_sortants SET statut = 'en_attente', contenu = ?, destinataire = ?"
                         " WHERE id = ?", (relances[0]["message"], destinataire, message_id))
        else:
            message_id = conn.execute(
                "INSERT INTO messages_sortants (cle_envoi, client_id, canal, destinataire, contenu, statut)"
                " VALUES (?,?,?,?,?, 'en_attente')",
                (lot, client["id"], canal, destinataire, relances[0]["message"])).lastrowid
        conn.execute("UPDATE relances SET message_id = ? WHERE lot_envoi = ? AND statut = 'en_cours_envoi'",
                     (message_id, lot))
    objet, corps = _decouper(relances[0]["message"])
    try:
        accuse = connecteur.envoyer(Envoi(lot, canal, destinataire, objet, corps))
    except Exception as exc:  # panne du fournisseur : on trace, on n'invente rien
        with transaction(conn):
            conn.execute("UPDATE messages_sortants SET statut = 'echec', accuse = ? WHERE id = ?",
                         (str(exc)[:200], message_id))
            conn.execute("UPDATE relances SET statut = 'echec', maj_le = ? WHERE lot_envoi = ? AND statut = 'en_cours_envoi'",
                         (_maintenant(), lot))
            journal.ajouter(conn, acteur=auteur, type_acteur="systeme", action="echec_envoi", objet_type="message",
                            objet_id=message_id, apres={"lot": lot, "erreur": str(exc)[:200]}, regle="ENVOI")
        resume["echecs"] += 1
        return
    with transaction(conn):
        conn.execute("UPDATE messages_sortants SET statut = 'envoye', accuse = ?, envoye_le = ? WHERE id = ?",
                     (accuse, _maintenant(), message_id))
        conn.execute("UPDATE relances SET statut = 'envoyee', maj_le = ?, date_envoi = ?"
                     " WHERE lot_envoi = ? AND statut = 'en_cours_envoi'",
                     (_maintenant(), parametres.date_du_jour(conn).isoformat(), lot))
        journal.ajouter(conn, acteur=auteur, type_acteur="systeme", action="envoi_relance", objet_type="message",
                        objet_id=message_id,
                        apres={"lot": lot, "canal": canal, "accuse": accuse, "connecteur": connecteur.nom,
                               "relances": [r["id"] for r in relances],
                               "factures": [r["facture_id"] for r in relances]},
                        regle="ENVOI")
    resume["envoyes"] += 1
    resume["lots"].append(lot)


def reessayer(conn: sqlite3.Connection, lot: str, auteur: str) -> None:
    """Remet en file un lot en échec (panne du fournisseur). Il sera revalidé avant le nouvel envoi."""
    with transaction(conn):
        n = conn.execute("UPDATE relances SET statut = 'validee', maj_le = ? WHERE lot_envoi = ? AND statut = 'echec'",
                         (_maintenant(), lot)).rowcount
        if not n:
            raise ErreurMetier("NON_APPLICABLE", "Aucune relance en échec dans ce lot")
        journal.ajouter(conn, acteur=auteur, type_acteur="humain", action="nouvel_essai_envoi", objet_type="lot",
                        objet_id=lot, regle="ENVOI")
