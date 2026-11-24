#!/usr/bin/env python3
"""Analyse du soir : calcule les notes des trois horizons, la meteo de la bourse,
la fiabilite et les messages, puis ecrit docs/data/resultats.json (lu par l'application).

Regles reprises du plan (tests n°4 et n°5) :
- dividende et prix (PER) compares a la moyenne du marche ;
- poids : long terme dividende 20 / valorisation 25 ; moyen terme 20 / 30 ; court terme 20 / 15 / tendance 20 ;
- bilans (solidite, croissance) : affiches et expliques, mais HORS de la note. Test n°7 (22/11/2026) : aucune
  facon de les compter (poids fort, moyen, faible, filet de securite) ne fait mieux de facon fiable que 620 ;
- fiabilite : qualite des donnees (cours recent, PER connu, bilan lu, liquidite, actualite non suivie) ;
- dividende exceptionnel (> 2,5 fois le rendement moyen) et taux de distribution > 100 % penalises ;
- etoiles anti-clignotement (2 points au-dela de la limite pendant 5 seances) ;
- action peu echangee : une etoile de moins ;
- meteo : PER du marche <= 12,5 soleil, >= 18 pluie, sinon nuageux ;
- portefeuille type : 10 actions, 3 au plus par groupe, 5 au plus dans la finance.
"""
import csv
import datetime as dt
import json
import math
import statistics as st
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
D = RACINE / "donnees"
SORTIE = RACINE / "docs" / "data" / "resultats.json"

HORIZONS = {
    "lt": {"nom": "Long terme", "duree": "3 ans et plus", "div": 20, "valo": 25, "tend": 0, "qual": 0, "croi": 0,
           "manque": {"Actualité": 5}},
    "mt": {"nom": "Moyen terme", "duree": "6 à 18 mois", "div": 20, "valo": 30, "tend": 0, "qual": 0, "croi": 0,
           "manque": {"Actualité": 10}},
    "ct": {"nom": "Court terme", "duree": "moins de 6 mois", "div": 20, "valo": 15, "tend": 20, "qual": 0, "croi": 0,
           "manque": {"Actualité": 20}},
}
LIMITES = [(80, 5), (65, 4), (50, 3), (35, 2)]


def fr(x, d=1):
    return f"{x:.{d}f}".replace(".", ",")


NORME_SOLVA, MOYENNE_SOLVA = 11.5, 14.7   # Commission bancaire de l'UMOA, ratio de solvabilite total (2025)


def feu_solidite(s_qual, fiche):
    """Feu vert / orange / rouge : la societe est-elle solide ? (information, ne change pas la note)."""
    perte = next((d for d in fiche["drapeaux"] if d.startswith("En perte au dernier bilan")), None)
    sol = (fiche.get("solvabilite") or {}).get("ratio")
    pourquoi = []
    if s_qual is not None:
        pourquoi.append(f"solidité {round(s_qual)}/100")
    if sol is not None:
        pourquoi.append(f"solvabilité {fr(sol, 1)} %")
    if perte:
        pourquoi.append(perte[0].lower() + perte[1:])
    if s_qual is None and sol is None and not perte:
        return {"couleur": "gris", "mot": "Non mesurée", "pourquoi": "pas assez de chiffres dans les bilans"}
    if perte or (s_qual is not None and s_qual < 50) or (sol is not None and sol < NORME_SOLVA):
        c, m = "rouge", "Fragile"
    elif (s_qual is not None and s_qual < 75) or (sol is not None and sol < 13.0):
        c, m = "orange", "Moyenne"
    else:
        c, m = "vert", "Solide"
    return {"couleur": c, "mot": m, "pourquoi": ", ".join(pourquoi)}


ACTU = {}
LIB_ACTU = {"resultats": "Résultats publiés", "dividende": "Dividende annoncé", "assemblee": "Assemblée générale", "capital": "Opération sur le capital",
            "suspension": "Cotation suspendue ou reprise", "dirigeants": "Changement à la direction", "autre": "Publication"}


def actualite_de(s, jour):
    """Dernieres publications de la societe (2 ans), du plus recent au plus ancien."""
    limite = (jour - dt.timedelta(days=730)).isoformat()
    out = []
    for x in ACTU.get(s, []):
        if not x.get("date") or x["date"] < limite:
            continue
        out.append({k: x[k] for k in ("date", "titre", "type", "url", "detail", "sens", "dividende", "paiement") if x.get(k) is not None})
    return out[:8]


def lin(x, a, b):
    return max(0.0, min(100.0, 100 * (x - a) / (b - a)))


def etoiles_brutes(n):
    return next((e for lim, e in LIMITES if n >= lim), 1)


def limite_basse(e):
    return {5: 80, 4: 65, 3: 50, 2: 35, 1: -1e9}[e]


def limite_haute(e):
    return {5: 1e9, 4: 80, 3: 65, 2: 50, 1: 35}[e]


def charger():
    ref = json.loads((D / "reference.json").read_text())
    ops = json.loads((D / "operations_capital.json").read_text()) if (D / "operations_capital.json").exists() else {}
    statut = json.loads((D / "statut_collecte.json").read_text()) if (D / "statut_collecte.json").exists() else None
    etat = json.loads((D / "etat.json").read_text()) if (D / "etat.json").exists() else {}
    tout_bilans = json.loads((D / "bilans.json").read_text()) if (D / "bilans.json").exists() else {}
    bilans = tout_bilans.get("societes", {})
    historique = tout_bilans.get("historique", {})
    solva = json.loads((D / "solvabilite.json").read_text()) if (D / "solvabilite.json").exists() else {}
    global ACTU
    ACTU = json.loads((D / "actualite.json").read_text()) if (D / "actualite.json").exists() else {}
    if (D / "bilans_manuels.json").exists():  # chiffres saisis a la main quand le PDF est illisible
        for sym, b in json.loads((D / "bilans_manuels.json").read_text()).get("societes", {}).items():
            plus_recent = int(b.get("exercice", 0)) > int((bilans.get(sym) or {}).get("exercice", 0) or 0)
            if sym not in bilans or bilans[sym].get("statut") != "valide" or b.get("prioritaire") or plus_recent:
                bilans[sym] = dict(b, statut="valide", manuel=True)
    hist = {}
    with open(D / "historique.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter=";"):
            s = r["symbole"]
            c = float(r["cloture"])
            for op in ops.get(s, []):  # prix ajustes des fractionnements / actions gratuites
                if r["date"] < op["date"]:
                    c /= op["ratio"]
            v = float(r["volume"]) if r.get("volume") else None
            hist.setdefault(s, []).append((r["date"], c, v))
    for s in hist:
        hist[s].sort()
    return ref, ops, statut, etat, hist, bilans, historique, solva


def serie_resultats(h):
    """Resultat net par annee a partir des bilans valides de plusieurs exercices (et de leur colonne N-1)."""
    rn = {}
    for an, b in h.items():
        if b.get("statut") != "valide":
            continue
        x = (b.get("chiffres") or {}).get("rn") or {}
        if x.get("n") and not 1990 <= x["n"] <= 2035:  # une annee lue comme un montant ; 0 = ligne non lue
            rn[int(an)] = x["n"]
        if x.get("n1") and int(an) - 1 not in rn and not 1990 <= x["n1"] <= 2035:
            rn[int(an) - 1] = x["n1"]
    rn = dict(sorted(rn.items()))
    # unites differentes selon les annees (FCFA, milliers, millions) : on ramene tout a l'unite de l'annee la plus recente
    ref = next((v for a, v in sorted(rn.items(), reverse=True) if v), None)
    if ref:
        lref = math.log10(abs(ref))
        for a, v in rn.items():
            if v:
                k = min(range(-3, 4), key=lambda k: abs(math.log10(abs(v) * 1000 ** k) - lref))
                rn[a] = v * 1000 ** k
    # valeur isolee aberrante : plus de 8 fois l'ecart typique des autres annees (lecture douteuse)
    if len(rn) >= 4:
        for a in list(rn):
            autres = [abs(v) for b, v in rn.items() if b != a and v]
            med = st.median(autres) if autres else 0
            if med and abs(rn[a]) > 8 * med:
                del rn[a]
    return rn


def prix_a(serie, jour):
    """Dernier cours connu a la date 'jour' ou avant."""
    avant = [p for p in serie if p[0] <= jour]
    return avant[-1] if avant else None


def main():
    ref, ops, statut, etat, hist, bilans, historique, solva = charger()
    actions = ref["actions"]
    date_donnees = max(p[0] for s in hist for p in hist[s])
    jour = dt.date.fromisoformat(date_donnees)
    aujourd_hui = dt.datetime.now(dt.timezone.utc).date()
    messages = []

    # ---- marche : on fait evoluer le PER et le rendement moyens officiels avec les cours
    ratios = []
    for s, serie in hist.items():
        p0, p1 = prix_a(serie, ref["date"]), prix_a(serie, date_donnees)
        if p0 and p1 and p0[1] > 0:
            ratios.append(p1[1] / p0[1])
    r = st.median(ratios) if ratios else 1.0
    per_m, rdt_m = ref["per_marche"] * r, ref["rendement_marche"] / r
    meteo = ("soleil", 1.0) if per_m <= 12.5 else ("pluie", 0.5) if per_m >= 18 else ("nuageux", 0.8)

    # ---- tendance (12 mois, hors dernier mois)
    tend = {}
    for s, serie in hist.items():
        recent = prix_a(serie, (jour - dt.timedelta(days=30)).isoformat())
        ancien = prix_a(serie, (jour - dt.timedelta(days=365)).isoformat()) or serie[0]
        if recent and ancien and (dt.date.fromisoformat(recent[0]) - dt.date.fromisoformat(ancien[0])).days >= 150:
            tend[s] = recent[1] / ancien[1] - 1
    valeurs = sorted(tend.values())

    def pct(v):
        return 100 * sum(1 for x in valeurs if x < v) / max(1, len(valeurs) - 1)

    res = []
    for s, a in actions.items():
        serie = hist.get(s, [])
        dernier = serie[-1] if serie else None
        fiche = {"s": s, "nom": a["nom"], "secteur": a["secteur"], "pays": a["pays"], "groupe": a.get("groupe"),
                 "suspendue": a.get("suspendue", False), "drapeaux": [], "raisons": []}
        if a.get("suspendue") or not dernier:
            fiche["drapeaux"].append("Cotation suspendue")
            res.append(fiche)
            continue
        cours = dernier[1]
        if (jour - dt.date.fromisoformat(dernier[0])).days > 10:
            fiche["drapeaux"].append("Cours ancien")
        prec = serie[-2] if len(serie) > 1 else None
        fiche["cours"] = cours
        fiche["date_cours"] = dernier[0]
        recent = prec and (dt.date.fromisoformat(dernier[0]) - dt.date.fromisoformat(prec[0])).days <= 5
        fiche["var_jour"] = round((cours / prec[1] - 1) * 100, 2) if recent and dernier[0] == date_donnees else None
        if recent and (cours / prec[1] < 0.55 or cours / prec[1] > 1.8) and s not in ops:
            fiche["drapeaux"].append("Variation anormale : fractionnement possible, note suspendue")
            fiche["anomalie"] = True

        div, ddiv = a.get("dividende"), a.get("date_dividende")
        actu = actualite_de(s, jour)
        fiche["actualite"] = actu[:6]
        annonce = next((x for x in actu if x["type"] == "dividende" and x.get("dividende")), None)
        source_div = "bulletin"
        if annonce and (annonce.get("paiement") or annonce["date"]) > (ddiv or ""):
            div_annonce, ddiv_annonce = annonce["dividende"], annonce.get("paiement") or annonce["date"]
            # le tableau de la BRVM donne parfois le brut : meme rapport net / tableau que pour le dividende de reference
            meme = next((x for x in actu if x["type"] == "dividende" and x.get("dividende") and x.get("paiement") == ddiv), None)
            if meme and div and 0.8 <= div / meme["dividende"] <= 1.02:
                div_annonce *= div / meme["dividende"]
            for op in ops.get(s, []):
                if annonce["date"] < op["date"]:
                    div_annonce = div_annonce / op["ratio"]
            source_div = "communiqué"
        else:
            annonce = None
        frais = bool(div and ddiv and (jour - dt.date.fromisoformat(ddiv)).days <= 430)
        for op in ops.get(s, []):  # la reference (bulletin) est ajustee seulement si elle precede l'operation
            if frais and ref["date"] < op["date"]:
                div = div / op["ratio"]
        if annonce:  # dividende annonce par la societe, plus recent que le bulletin de reference
            div, ddiv, frais = div_annonce, ddiv_annonce, (jour - dt.date.fromisoformat(ddiv_annonce)).days <= 430
        fiche["dividende_source"] = source_div
        rdt = div / cours if frais else 0.0
        bpa = a.get("bpa")
        for op in ops.get(s, []):
            if bpa and ref["date"] < op["date"]:
                bpa = bpa / op["ratio"]
        per = cours / bpa if bpa and bpa > 0 else None
        per_ok = per if per and 0 < per < 60 else None
        payout = rdt * per_ok if per_ok else None
        dur = 1.0 if payout is None or payout <= 0.8 else 0.8 if payout <= 1.0 else 0.5
        exceptionnel = rdt > 2.5 * rdt_m / 100
        if exceptionnel:
            dur = min(dur, 0.5)
        s_div = lin(rdt, 0.5 * rdt_m / 100, 1.5 * rdt_m / 100) * dur
        s_valo = lin(-per_ok, -1.6 * per_m, -0.6 * per_m) if per_ok else 0.0
        s_tend = pct(tend[s]) if s in tend else None
        fiche.update(rendement=round(rdt * 100, 2), per=round(per, 2) if per else None,
                     dividende=round(div, 2) if frais else None, date_dividende=ddiv,
                     tendance=round(tend[s] * 100, 1) if s in tend else None)

        # raisons en francais simple
        if exceptionnel:
            fiche["raisons"].append(("attention", f"Dividende exceptionnel ({fr(rdt*100, 0)} %) : il ne se répétera sans doute pas"))
        elif not frais:
            fiche["raisons"].append(("moins", "Pas de dividende versé depuis plus d'un an"))
        elif rdt * 100 >= rdt_m:
            fiche["raisons"].append(("plus", f"Bon dividende : {fr(rdt*100)} % par an (moyenne {fr(rdt_m)} %)"))
        else:
            fiche["raisons"].append(("neutre", f"Dividende : {fr(rdt*100)} % par an (moyenne {fr(rdt_m)} %)"))
        if per_ok is None:
            fiche["raisons"].append(("moins", "Bénéfices trop faibles ou absents : prix impossible à juger"))
        elif per_ok <= 0.85 * per_m:
            fiche["raisons"].append(("plus", f"Prix raisonnable : PER {fr(per_ok)} (marché {fr(per_m)})"))
        elif per_ok >= 1.15 * per_m:
            fiche["raisons"].append(("moins", f"Action chère : PER {fr(per_ok)} (marché {fr(per_m)})"))
        else:
            fiche["raisons"].append(("neutre", f"Prix dans la moyenne : PER {fr(per_ok)} (marché {fr(per_m)})"))
        if payout and payout > 1:
            fiche["raisons"].append(("attention", "Distribue plus que ses bénéfices : dividende fragile"))
        if s in tend and tend[s] > 0.8:
            fiche["raisons"].append(("attention", f"A déjà beaucoup monté (+{fr(tend[s]*100, 0)} % en un an) : plus risqué"))

        # solidite et croissance (bilans annuels lus et controles)
        s_qual = s_croi = None
        sv = solva.get(s)
        if sv and int(sv.get("exercice", 0)) < jour.year - 2:
            sv = None
        b = bilans.get(s)
        if b and b.get("statut") == "valide" and int(b.get("exercice") or 0) < jour.year - 3:
            fiche["drapeaux"].append(f"Dernier bilan lisible trop ancien ({b.get('exercice')}) : non utilisé")
            b = None
        if b and b.get("statut") == "valide":
            r_ = b.get("ratios", {})
            comp = []
            if b.get("banque"):
                if "roe" in r_: comp.append(lin(r_["roe"], 0.05, 0.22))
                if "coef_exploitation" in r_: comp.append(lin(-r_["coef_exploitation"], -0.75, -0.40))
                if "cout_risque_pnb" in r_: comp.append(lin(-r_["cout_risque_pnb"], -0.35, 0.0))
            else:
                if "roe" in r_: comp.append(lin(r_["roe"], 0.0, 0.25))
                if "marge" in r_: comp.append(lin(r_["marge"], 0.0, 0.15))
                if "dette_cp" in r_: comp.append(lin(-r_["dette_cp"], -1.5, 0.0))
            # regularite sur plusieurs annees
            rns = {} if b.get("prioritaire") else serie_resultats(historique.get(s, {}))  # erreur connue : pas de serie automatique
            if b.get("serie_rn"):  # serie saisie a la main (source officielle) : complete et remplace la lecture automatique
                man = {int(k): v for k, v in b["serie_rn"].items()}
                ref_man = next(iter(man.values()))
                for an, v in list(rns.items()):  # meme unite que la saisie manuelle
                    if v:
                        k = min(range(-3, 4), key=lambda k: abs(math.log10(abs(v) * 1000 ** k) - math.log10(abs(ref_man))))
                        rns[an] = v * 1000 ** k
                rns = dict(sorted({**rns, **man}.items()))
            regul = cagr = None
            if len(rns) >= 3:
                benef = sum(1 for v in rns.values() if v > 0)
                regul = benef / len(rns)
                comp.append(lin(regul, 0.5, 1.0))
                ans = sorted(rns)
                v0, v1 = rns[ans[0]], rns[ans[-1]]
                if v0 > 0 and v1 > 0:
                    cagr = (v1 / v0) ** (1 / (ans[-1] - ans[0])) - 1
                fiche["resultats"] = [[a, round(v)] for a, v in rns.items()]
                if benef == len(rns):
                    fiche["raisons"].append(("plus", f"Bénéfice chaque année de {ans[0]} à {ans[-1]} ({benef} ans sur {len(rns)})"))
                else:
                    fiche["raisons"].append(("moins" if regul < 0.75 else "neutre", f"En perte {len(rns) - benef} année(s) sur {len(rns)} depuis {ans[0]}"))
                if cagr is not None:
                    fiche["raisons"].append(("plus" if cagr > 0.05 else "moins" if cagr < -0.03 else "neutre",
                                             f"Résultat : {'+' if cagr >= 0 else ''}{fr(cagr*100, 0)} % par an en moyenne de {ans[0]} à {ans[-1]}"))
            if sv:
                comp.append(lin(sv["ratio"], 11.5, 17.0))  # banques : assez de fonds propres pour encaisser des pertes
            if len(comp) >= 2:
                s_qual = st.mean(comp)
            comp = []
            if "croissance_resultat" in r_: comp.append(lin(r_["croissance_resultat"], -0.25, 0.25))
            if "croissance_activite" in r_: comp.append(lin(r_["croissance_activite"], -0.10, 0.15))
            if cagr is not None:
                comp.append(lin(cagr, -0.10, 0.15))
                comp.append(lin(cagr, -0.10, 0.15))  # la tendance sur plusieurs annees compte double
            if comp:
                s_croi = st.mean(comp)
            ex = b.get("exercice", "")
            if "roe" in r_:
                t = "plus" if r_["roe"] >= 0.15 else "moins" if r_["roe"] < 0.05 else "neutre"
                fiche["raisons"].append((t, f"Rentabilité des fonds propres : {fr(r_['roe']*100, 0)} % (exercice {ex})"))
            if b.get("banque") and "coef_exploitation" in r_:
                t = "plus" if r_["coef_exploitation"] <= 0.5 else "moins" if r_["coef_exploitation"] > 0.65 else "neutre"
                fiche["raisons"].append((t, f"Coûts de fonctionnement : {fr(r_['coef_exploitation']*100, 0)} % du produit net bancaire"))
            if not b.get("banque") and "dette_cp" in r_ and r_["dette_cp"] > 1:
                fiche["raisons"].append(("attention", f"Endettement élevé : dettes = {fr(r_['dette_cp'], 1)} fois les fonds propres"))
            rn_n = ((b.get("chiffres") or {}).get("rn") or {}).get("n")
            if rn_n is not None and rn_n < 0:
                fiche["drapeaux"].append(f"En perte au dernier bilan ({ex})")
                fiche["raisons"].append(("moins", f"Entreprise en perte en {ex}" + (" (perte réduite par rapport à l'année d'avant)" if r_.get("croissance_resultat", 0) > 0 else "")))
            elif r_.get("perte_precedente"):
                fiche["raisons"].append(("plus", f"Retour au bénéfice en {ex}"))
            elif "croissance_resultat" in r_:
                g = r_["croissance_resultat"]
                fiche["raisons"].append(("plus" if g > 0.05 else "moins" if g < -0.05 else "neutre",
                                         "Résultat net stable sur un an" if abs(g) < 0.005 else
                                         f"Résultat net {'en hausse' if g > 0 else 'en baisse'} : {'+' if g > 0 else ''}{fr(g*100, 0)} % sur un an"))
            fiche["bilan"] = {"exercice": ex, "source": b.get("url") or b.get("source"), "manuel": bool(b.get("manuel"))}
        elif b:
            fiche["drapeaux"].append("Bilan à confirmer : non utilisé")

        # solvabilite des banques (rapports annuels) puis feu de solidite
        if sv:
            ra = sv["ratio"]
            fiche["solvabilite"] = {"ratio": ra, "ratio_n1": sv.get("ratio_n1"), "exercice": sv["exercice"], "norme": NORME_SOLVA,
                                    "document": sv.get("document"), "source": sv.get("url"), "phrase": sv.get("phrase"),
                                    "approx": bool(sv.get("approx")), "periode": sv.get("periode") or f"fin d'année {sv['exercice']}"}
            t = "attention" if ra < NORME_SOLVA else "moins" if ra < 12.5 else "plus" if ra >= 14.7 else "neutre"
            fiche["raisons"].append((t, f"Solvabilité ({sv.get('periode') or sv['exercice']}) : {'plus de ' if sv.get('approx') else ''}{fr(ra, 1)} % (minimum exigé {fr(NORME_SOLVA, 1)} %, moyenne des banques de l'UMOA {fr(MOYENNE_SOLVA, 1)} %)"))
            if ra < NORME_SOLVA:
                fiche["drapeaux"].append(f"Solvabilité sous la norme ({fr(ra, 1)} %)")
        fiche["feu"] = feu_solidite(s_qual, fiche)

        # liquidite (a partir de l'historique collecte chaque soir)
        vols = [p for p in serie if p[2] is not None][-60:]
        if len(vols) >= 20:
            part = sum(1 for p in vols if p[2] > 0) / len(vols)
            valeur = st.mean(p[2] * p[1] for p in vols)
            fiche["liquidite"] = round(part * 100)
            if part < 0.5 or valeur < 1_000_000:
                fiche["drapeaux"].append("Peu échangée : difficile à revendre")
                fiche["peu_liquide"] = True

        fiche["notes"], fiche["fiabilite"] = {}, {}
        for h, w in HORIZONS.items():
            parts = [(w["div"], s_div), (w["valo"], s_valo), (w["tend"], s_tend), (w["qual"], s_qual), (w["croi"], s_croi)]
            parts = [(p, v) for p, v in parts if v is not None and p]
            poids = sum(p for p, _ in parts)
            total = sum(p * v for p, v in parts)
            fiche["notes"][h] = None if fiche.get("anomalie") else round(total / poids, 1)
            f_ = 100 - w["manque"].get("Actualité", 0)
            if per_ok is None: f_ -= 20
            if not fiche.get("bilan"): f_ -= 15
            if fiche.get("peu_liquide"): f_ -= 10
            if "Cours ancien" in fiche["drapeaux"]: f_ -= 20
            if w["tend"] and s_tend is None: f_ -= 10
            fiche["fiabilite"][h] = max(10, f_)
        # detail par critere pour l'ecran « Pourquoi cette note » (0-100)
        r1 = lambda v: None if v is None else round(v)
        fiche["criteres"] = {"div": r1(s_div), "valo": r1(s_valo), "tend": r1(s_tend), "qual": r1(s_qual),
                             "croi": r1(s_croi), "actu": None}
        res.append(fiche)

    # ---- etoiles anti-clignotement + fleches sur 1 mois
    et_prec = etat.get("etoiles", {})
    hist_notes = etat.get("notes", {})
    nouveau_et = {}
    for f in res:
        if not f.get("notes"):
            continue
        f["etoiles"], f["fleches"] = {}, {}
        for h, n in f["notes"].items():
            if n is None:
                continue
            brut = etoiles_brutes(n)
            p = et_prec.get(h, {}).get(f["s"])
            if p is None:
                e, cand, cpt = brut, brut, 0
            else:
                e, cand, cpt = p["e"], p.get("cand", p["e"]), p.get("n", 0)
                monte = brut > e and n >= limite_haute(e) + 2
                baisse = brut < e and n < limite_basse(e) - 2
                if monte or baisse:
                    cpt = cpt + 1 if cand == brut else 1
                    cand = brut
                    if cpt >= 5:
                        e, cpt = brut, 0
                else:
                    cand, cpt = e, 0
            nouveau_et.setdefault(h, {})[f["s"]] = {"e": e, "cand": cand, "n": cpt}
            f["etoiles"][h] = max(1, e - (1 if f.get("peu_liquide") else 0))
            vieux = [x for x in hist_notes.get(f["s"], []) if x[0] <= (jour - dt.timedelta(days=28)).isoformat()]
            if vieux and vieux[-1][1].get(h) is not None:
                f["fleches"][h] = round(n - vieux[-1][1][h], 1)
        lst = [x for x in hist_notes.get(f["s"], []) if x[0] != date_donnees]
        lst.append([date_donnees, f["notes"]])
        hist_notes[f["s"]] = lst[-90:]

    # ---- classements et portefeuilles types diversifies
    notees = [f for f in res if f.get("notes") and not f.get("anomalie")]
    classements, portefeuilles = {}, {}
    finance = "Banques et finance"
    for h in HORIZONS:
        ordre = sorted(notees, key=lambda f: -f["notes"][h])
        classements[h] = [f["s"] for f in ordre]
        top, g, nf = [], {}, 0
        for f in ordre:
            if f.get("peu_liquide"):
                continue
            gg = f.get("groupe")
            if gg and g.get(gg, 0) >= 3:
                continue
            if f["secteur"] == finance and nf >= 5:
                continue
            if gg:
                g[gg] = g.get(gg, 0) + 1
            nf += f["secteur"] == finance
            top.append(f["s"])
            if len(top) == 10:
                break
        portefeuilles[h] = top

    # ---- fiabilite globale et messages
    fiabs = [f["fiabilite"]["lt"] for f in res if f.get("fiabilite")]
    fiab = round(st.mean(fiabs)) if fiabs else 59
    nb_bilans = sum(1 for f in res if f.get("bilan"))
    if statut is None:
        messages.append({"type": "info", "titre": "Première mise à jour", "texte": "Les cours viennent du bulletin officiel du " + dt.date.fromisoformat(ref["date"]).strftime("%d/%m/%Y") + ". La collecte automatique commencera ce soir."})
    elif not statut.get("ok"):
        fiab -= 15
        detail = "; ".join(statut.get("alertes", [])) or "raison inconnue"
        messages.append({"type": "alerte", "titre": "Cours du jour non récupérés", "texte": f"Je n'ai pas pu lire les cours ce soir ({detail}). Les notes utilisent les derniers cours connus, du {jour:%d/%m/%Y}. Je réessaie demain, tu n'as rien à faire."})
    else:
        nb = statut.get("nb_actions", 0)
        conf = statut.get("a_confirmer", [])
        if conf:
            fiab -= min(10, len(conf) * 2)
            messages.append({"type": "alerte", "titre": f"{len(conf)} cours à confirmer", "texte": "Ces cours semblent anormaux et ont été mis de côté : " + ", ".join(c["symbole"] for c in conf) + "."})
        for a in statut.get("alertes", []):
            if "week-end" not in a:
                messages.append({"type": "info", "titre": "Remarque sur la collecte", "texte": a})
        if nb:
            messages.append({"type": "info", "titre": "Collecte terminée", "texte": f"{nb} actions mises à jour ce soir."})
    retard = (aujourd_hui - jour).days
    if retard > 4:
        fiab -= 20
        messages.append({"type": "alerte", "titre": "Données anciennes", "texte": f"Les derniers cours datent du {jour:%d/%m/%Y} ({retard} jours)."})
    age_ref = (aujourd_hui - dt.date.fromisoformat(ref["date"])).days
    if age_ref > 120:
        fiab -= 10
        messages.append({"type": "faire", "titre": "Dividendes et bénéfices à mettre à jour", "texte": f"La liste des dividendes et des bénéfices date de {age_ref} jours. Les nouveaux dividendes ne sont pas encore pris en compte."})
    anomalies = [f["nom"] for f in res if f.get("anomalie")]
    if anomalies:
        messages.append({"type": "alerte", "titre": "Variation anormale", "texte": "Note suspendue (fractionnement d'actions possible) : " + ", ".join(anomalies) + "."})
    sans = [f["nom"] for f in res if f.get("notes") and not f.get("bilan")]
    messages.append({"type": "info", "titre": f"Bilans lus : {nb_bilans} sociétés sur {len([f for f in res if f.get('notes')])}",
                     "texte": ("Les bilans sont montrés dans chaque fiche (solidité, croissance, pertes), mais ils ne changent pas la note : sur 10 ans, les compter n'a pas amélioré les résultats. " if nb_bilans else "")
                     + (f"Pas encore de bilan validé pour : {', '.join(sans[:12])}{' …' if len(sans) > 12 else ''}. " if sans else "")
                     + "L'actualité (communiqués officiels) est montrée dans chaque fiche, sans changer la note pour l'instant."})
    # nouvelles publications importantes (4 derniers jours) : l'application ne montre que celles de ton portefeuille
    limite = (jour - dt.timedelta(days=4)).isoformat()
    for f in res:
        for x in ACTU.get(f["s"], [])[:10]:
            vu = x.get("vu_le", "initial")
            if vu == "initial" or vu < limite or x["type"] not in ("resultats", "dividende", "suspension", "capital", "dirigeants"):
                continue
            texte = x.get("detail") or (f"{fr(x['dividende'], 0)} FCFA net par action" + (f", payé le {dt.date.fromisoformat(x['paiement']).strftime('%d/%m/%Y')}" if x.get("paiement") else "") if x.get("dividende") else x["titre"])
            messages.append({"type": "alerte" if x["type"] in ("suspension", "capital") or x.get("sens") == -1 else "info",
                             "titre": f"{f['nom']} : {LIB_ACTU[x['type']].lower()}", "texte": texte, "s": f["s"], "actu": True, "url": x["url"]})

    sortie = {
        "version": 1,
        "maj": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "date_cours": date_donnees,
        "marche": {"per": round(per_m, 2), "rendement": round(rdt_m, 2), "composite_ref": ref["composite"],
                   "variation_depuis_ref": round((r - 1) * 100, 2), "ref_date": ref["date"]},
        "meteo": {"code": meteo[0], "part_actions": meteo[1]},
        "fiabilite": max(0, fiab),
        "horizons": {h: {"nom": w["nom"], "duree": w["duree"], "manque": w["manque"],
                         "mesure": w["div"] + w["valo"] + w["tend"] + w["qual"] + w["croi"],
                         "bilans": w["qual"] + w["croi"]} for h, w in HORIZONS.items()},
        "projections": json.loads((D / "projections.json").read_text()) if (D / "projections.json").exists() else None,
        "classements": classements,
        "portefeuilles": portefeuilles,
        "actions": res,
        "messages": messages,
        "sources": [ref["source"], "Cours quotidiens : brvm.org"],
    }
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps(sortie, ensure_ascii=False, separators=(",", ":")))
    (D / "etat.json").write_text(json.dumps({"etoiles": nouveau_et, "notes": hist_notes}, ensure_ascii=False, separators=(",", ":")))
    print(f"Analyse au {date_donnees} : meteo {meteo[0]} (PER {per_m:.1f}), fiabilite {max(0, fiab)}, "
          f"{len(notees)} actions notees ; top long terme : {', '.join(portefeuilles['lt'][:5])}")


if __name__ == "__main__":
    main()
