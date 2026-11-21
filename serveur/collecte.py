#!/usr/bin/env python3
"""Collecte du soir : lit les cours des actions sur le site officiel de la BRVM,
controle chaque ligne et les ajoute a donnees/historique.csv.

Ne s'arrete jamais en erreur : en cas de probleme, il ecrit donnees/statut_collecte.json
pour que l'analyse affiche un message clair dans l'application, puis rend la main.
Lance chaque soir par GitHub Actions (.github/workflows/quotidien.yml).
"""
import csv
import datetime as dt
import json
import re
import sys
import time
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

RACINE = Path(__file__).resolve().parent.parent
HISTORIQUE = RACINE / "donnees" / "historique.csv"
STATUT = RACINE / "donnees" / "statut_collecte.json"
REFERENCE = RACINE / "donnees" / "reference.json"

SOURCES = ["https://www.brvm.org/fr/cours-actions/0", "https://www.brvm.org/fr/cours-actions/-1"]
ENTETES = {"User-Agent": "Mozilla/5.0 (compatible; brvm-analyse/1.0; usage personnel, 1 requete par jour)",
           "Accept-Language": "fr-FR,fr;q=0.9"}
LIMITE_VARIATION, TOLERANCE = 7.5, 0.15
NB_MIN, NB_MAX = 35, 60
COLONNES = {
    "symbole": [["symbole"], ["code"], ["ticker"]],
    "nom": [["nom"], ["libell"], ["soci"]],
    "volume": [["volume"]],
    "cours_veille": [["veille"], ["précédent"], ["precedent"]],
    "cloture": [["clôture"], ["cloture"], ["dernier"]],
    "variation": [["variation"], ["var"]],
}


def en_nombre(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("\xa0", "").replace(" ", "").replace(" ", "").replace("%", "").replace(",", ".")
    s = re.sub(r"[^0-9.\-]", "", s)
    try:
        return float(s) if s not in ("", "-", ".", "-.") else None
    except ValueError:
        return None


def telecharger():
    erreurs = []
    for url in SOURCES:
        for essai in range(3):
            try:
                r = requests.get(url, headers=ENTETES, timeout=40)
                r.raise_for_status()
                r.encoding = r.apparent_encoding or "utf-8"
                return url, r.text, erreurs
            except requests.RequestException as e:
                erreurs.append(f"{url} essai {essai + 1} : {e.__class__.__name__} {str(e)[:120]}")
                time.sleep(8)
    return None, None, erreurs


def extraire(html):
    tableaux = pd.read_html(StringIO(html), thousands=None, decimal=",")
    candidats = []
    for t in tableaux:
        if isinstance(t.columns, pd.MultiIndex):
            t.columns = [" ".join(str(x) for x in c if "Unnamed" not in str(x)).strip() for c in t.columns]
        noms = " ".join(str(c).lower() for c in t.columns)
        if ("symbole" in noms or "code" in noms) and any(m in noms for m in ("cours", "clôture", "cloture")):
            candidats.append(t)
    if not candidats:
        raise ValueError("tableau des cours non reconnu ; colonnes vues : "
                         + " | ".join(str(list(t.columns))[:150] for t in tableaux[:4]))
    brut = max(candidats, key=len)
    corr, prises = {}, set()
    for cle, variantes in COLONNES.items():
        for mots in variantes:
            c = next((c for c in brut.columns if c not in prises and all(m in str(c).lower() for m in mots)), None)
            if c is not None:
                corr[cle] = c
                prises.add(c)
                break
    if "symbole" not in corr or "cloture" not in corr:
        raise ValueError(f"colonnes indispensables introuvables : {list(brut.columns)}")
    df = pd.DataFrame({"symbole": brut[corr["symbole"]].astype(str).str.strip().str.upper()})
    for cle in ("volume", "cours_veille", "cloture", "variation"):
        df[cle] = brut[corr[cle]].map(en_nombre) if cle in corr else None
    df = df[df["symbole"].str.match(r"^[A-Z]{3,6}$", na=False)]
    df = df[~df["symbole"].isin(["TOTAL", "TOTAUX", "SOMME"])]
    df = df[df[["volume", "cours_veille", "cloture"]].notna().any(axis=1)]
    return df.reset_index(drop=True)


def lire_historique():
    if not HISTORIQUE.exists():
        return []
    with open(HISTORIQUE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter=";"))


def controler(df, derniers):
    a_confirmer = []
    for _, l in df.iterrows():
        pb = []
        if not l["cloture"] or l["cloture"] <= 0:
            pb.append("cours absent")
        if l["variation"] is not None and abs(l["variation"]) > LIMITE_VARIATION + TOLERANCE:
            pb.append(f"variation {l['variation']} % hors limite")
        if l["cours_veille"] and l["cloture"] and l["variation"] is not None:
            recalc = (l["cloture"] / l["cours_veille"] - 1) * 100
            if abs(recalc - l["variation"]) > TOLERANCE:
                pb.append("variation incoherente")
        if pb:
            a_confirmer.append({"symbole": l["symbole"], "motif": ", ".join(pb)})
    alertes = []
    if not NB_MIN <= len(df) <= NB_MAX:
        alertes.append(f"{len(df)} actions lues (attendu {NB_MIN} a {NB_MAX})")
    communs = [(derniers[s], c) for s, c in zip(df["symbole"], df["cloture"]) if s in derniers]
    if len(communs) >= 20 and sum(a == b for a, b in communs) >= 0.95 * len(communs):
        alertes.append("cours identiques a la seance precedente : pas de seance aujourd'hui (jour ferie ?)")
    return a_confirmer, alertes


def tester():
    """Lit le site et affiche ce qui est compris, sans rien enregistrer."""
    url, html, erreurs = telecharger()
    for e in erreurs:
        print("  essai rate :", e)
    if html is None:
        print("RESULTAT TEST : site injoignable depuis ce serveur")
        return
    print(f"Page recue de {url} ({len(html)} caracteres)")
    try:
        df = extraire(html)
    except Exception as e:
        print("RESULTAT TEST : page recue mais non comprise :", e)
        print(html[:1500])
        return
    a_confirmer, alertes = controler(df, {})
    print(df.head(12).to_string(index=False))
    print(f"RESULTAT TEST : {len(df)} actions lues, {len(a_confirmer)} a confirmer, alertes : {alertes or 'aucune'}")


def main():
    if "--test" in sys.argv:
        return tester()
    aujourd_hui = dt.datetime.now(dt.timezone.utc).date()
    statut = {"date": aujourd_hui.isoformat(), "heure": dt.datetime.now(dt.timezone.utc).strftime("%H:%M"),
              "ok": False, "nb_actions": 0, "a_confirmer": [], "alertes": [], "erreurs": [], "source": None}
    if aujourd_hui.weekday() >= 5 and "--forcer" not in sys.argv:
        statut.update(ok=True, alertes=["week-end : pas de seance"])
        STATUT.write_text(json.dumps(statut, ensure_ascii=False, indent=1))
        print("Week-end, rien a collecter.")
        return
    url, html, erreurs = telecharger()
    statut["erreurs"] = erreurs[-3:]
    if html is None:
        statut["alertes"].append("site de la BRVM injoignable")
        STATUT.write_text(json.dumps(statut, ensure_ascii=False, indent=1))
        print("ECHEC : site injoignable", *erreurs, sep="\n  ")
        return
    try:
        df = extraire(html)
    except Exception as e:  # le site a change de presentation
        statut["alertes"].append(f"page lue mais non comprise : {str(e)[:200]}")
        STATUT.write_text(json.dumps(statut, ensure_ascii=False, indent=1))
        print("ECHEC lecture :", e)
        return

    hist = lire_historique()
    derniers = {}
    for r in hist:  # derniere cloture enregistree AVANT aujourd'hui
        if r["date"] < aujourd_hui.isoformat():
            derniers[r["symbole"]] = float(r["cloture"])
    a_confirmer, alertes = controler(df, derniers)
    connus = set(json.loads(REFERENCE.read_text())["actions"])
    nouveaux = sorted(set(df["symbole"]) - connus)
    if nouveaux:
        alertes.append("actions inconnues (nouvelles cotations ?) : " + ", ".join(nouveaux))

    pas_de_seance = any("pas de seance" in a for a in alertes)
    exclus = {a["symbole"] for a in a_confirmer}
    if not pas_de_seance:
        hist = [r for r in hist if r["date"] != aujourd_hui.isoformat()]
        for _, l in df.iterrows():
            if l["symbole"] in exclus or not l["cloture"]:
                continue
            hist.append({"date": aujourd_hui.isoformat(), "symbole": l["symbole"], "cloture": f"{l['cloture']:g}",
                         "volume": "" if l["volume"] is None else f"{l['volume']:g}", "source": "brvm.org"})
        with open(HISTORIQUE, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["date", "symbole", "cloture", "volume", "source"], delimiter=";")
            w.writeheader()
            w.writerows(hist)
    statut.update(ok=not pas_de_seance, nb_actions=int(len(df)), a_confirmer=a_confirmer, alertes=alertes, source=url)
    STATUT.write_text(json.dumps(statut, ensure_ascii=False, indent=1))
    print(f"{len(df)} actions lues, {len(a_confirmer)} a confirmer, alertes : {alertes or 'aucune'}")


if __name__ == "__main__":
    main()
