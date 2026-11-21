#!/usr/bin/env python3
"""Analyse du soir : calcule les notes des trois horizons, la meteo de la bourse,
la fiabilite et les messages, puis ecrit docs/data/resultats.json (lu par l'application).

Regles reprises du plan (tests n°4 et n°5) :
- dividende et prix (PER) compares a la moyenne du marche ;
- poids : long terme dividende 20 / valorisation 25 ; moyen terme 20 / 30 ; court terme 20 / 15 / tendance 20 ;
- familles non encore mesurees (qualite, croissance, actualite) : fiabilite plafonnee a 59 ;
- dividende exceptionnel (> 2,5 fois le rendement moyen) et taux de distribution > 100 % penalises ;
- etoiles anti-clignotement (2 points au-dela de la limite pendant 5 seances) ;
- action peu echangee : une etoile de moins ;
- meteo : PER du marche <= 12,5 soleil, >= 18 pluie, sinon nuageux ;
- portefeuille type : 10 actions, 3 au plus par groupe, 5 au plus dans la finance.
"""
import csv
import datetime as dt
import json
import statistics as st
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
D = RACINE / "donnees"
SORTIE = RACINE / "docs" / "data" / "resultats.json"

HORIZONS = {
    "lt": {"nom": "Long terme", "duree": "3 ans et plus", "div": 20, "valo": 25, "tend": 0,
           "manque": {"Solidité de l'entreprise": 30, "Croissance des résultats": 20, "Actualité": 5}},
    "mt": {"nom": "Moyen terme", "duree": "6 à 18 mois", "div": 20, "valo": 30, "tend": 0,
           "manque": {"Solidité de l'entreprise": 20, "Croissance des résultats": 20, "Actualité": 10}},
    "ct": {"nom": "Court terme", "duree": "moins de 6 mois", "div": 20, "valo": 15, "tend": 20,
           "manque": {"Solidité de l'entreprise": 10, "Croissance des résultats": 15, "Actualité": 20}},
}
LIMITES = [(80, 5), (65, 4), (50, 3), (35, 2)]


def fr(x, d=1):
    return f"{x:.{d}f}".replace(".", ",")


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
    return ref, ops, statut, etat, hist


def prix_a(serie, jour):
    """Dernier cours connu a la date 'jour' ou avant."""
    avant = [p for p in serie if p[0] <= jour]
    return avant[-1] if avant else None


def main():
    ref, ops, statut, etat, hist = charger()
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
        frais = bool(div and ddiv and (jour - dt.date.fromisoformat(ddiv)).days <= 430)
        for op in ops.get(s, []):  # la reference (bulletin) est ajustee seulement si elle precede l'operation
            if frais and ref["date"] < op["date"]:
                div = div / op["ratio"]
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
            poids = w["div"] + w["valo"] + (w["tend"] if s_tend is not None else 0)
            total = w["div"] * s_div + w["valo"] * s_valo + (w["tend"] * s_tend if s_tend is not None else 0)
            fiche["notes"][h] = None if fiche.get("anomalie") else round(total / poids, 1)
            fiche["fiabilite"][h] = min(59, poids)
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
    fiab = 59
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
    messages.append({"type": "info", "titre": "Notes provisoires", "texte": "Les notes mesurent pour l'instant le dividende, le prix et la tendance. La solidité, la croissance et l'actualité seront ajoutées avec la lecture des bilans. En attendant, la fiabilité reste plafonnée."})

    sortie = {
        "version": 1,
        "maj": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "date_cours": date_donnees,
        "marche": {"per": round(per_m, 2), "rendement": round(rdt_m, 2), "composite_ref": ref["composite"],
                   "variation_depuis_ref": round((r - 1) * 100, 2), "ref_date": ref["date"]},
        "meteo": {"code": meteo[0], "part_actions": meteo[1]},
        "fiabilite": max(0, fiab),
        "horizons": {h: {"nom": w["nom"], "duree": w["duree"], "manque": w["manque"],
                         "mesure": w["div"] + w["valo"] + w["tend"]} for h, w in HORIZONS.items()},
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
