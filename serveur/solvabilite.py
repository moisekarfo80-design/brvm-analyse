"""Lecture du ratio de solvabilite des banques cotees (rapports publies sur brvm.org).

Le ratio de solvabilite total = fonds propres effectifs / risques ponderes (Bale II/III UMOA).
Norme minimale dans l'UMOA : 11,5 %. Moyenne des banques de l'UMOA : 14,7 % fin 2025 (Commission bancaire).

Usage : python serveur/solvabilite.py [EXERCICE] [SYM ...] [--diag]
Ecrit donnees/solvabilite.json : {symbole: {exercice, ratio, ratio_n1, phrase, document, url, lu_le}}.
Rien n'est invente : si aucune phrase claire n'est trouvee, la banque reste « non lu ».
"""
import datetime as dt
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import bilans as B  # noqa: E402

SORTIE = B.RACINE / "donnees" / "solvabilite.json"
BANQUES = ["BICB", "BICC", "BOAB", "BOABF", "BOAC", "BOAM", "BOAN", "BOAS", "CBIBF", "ECOC", "ETIT", "NSBC", "ORGT",
           "SAFC", "SGBC", "SIBC"]
NORMES = {11.5, 11.25, 10.375, 9.5, 8.625, 8.0, 7.5, 6.625, 6.0, 5.0, 3.0, 100.0}

MOT = re.compile(r"solvabilit|fonds propres effectifs\s*/|\bCAR\b|capital adequacy|fonds propres (?:effectifs )?(?:sur|rapport[ée]s? aux) (?:les )?(?:risques|actifs) pond", re.I)
POURCENT = re.compile(r"(?<![\d,.])(\d{1,2}(?:[.,]\d{1,2})?)\s?%")
ANNEE = re.compile(r"\b(20[12]\d)\b")


def valeurs(texte):
    """Pourcentages d'une ligne, sans les normes reglementaires annoncees (≥ 11,5 %, norme de…)."""
    out = []
    norme_dans_ligne = re.search(r"norme|minimum|seuil|exig|r[ée]glementaire", texte, re.I)
    for m in POURCENT.finditer(texte):
        v = float(m.group(1).replace(",", "."))
        avant = texte[max(0, m.start() - 28):m.start()].lower()
        avant = avant[avant.rfind("%") + 1:] if "%" in avant else avant  # seulement depuis le pourcentage precedent
        if re.search(r"[≥>]|norme|minimum|minimal|\bmin\b|exig|seuil|plancher|au moins|requis|r[ée]glementaire", avant):
            continue
        if v in NORMES and norme_dans_ligne:
            continue
        if 4 <= v <= 60:
            out.append((m.start(), v))
    return out


def poids_ligne(l):
    t = l.lower()
    s = 0
    s += 3 if "solvabilit" in t else 0
    s += 2 if "total" in t or "global" in t else 0
    s -= 3 if re.search(r"\bt1\b|cet1|base|tier 1|noyau dur|de base|levier|liquidit|division|couverture|transformation", t) else 0
    s -= 2 if re.search(r"moyen(ne)? (du|des) (secteur|syst[eè]me|banques)|umoa|uemoa|secteur bancaire|zone", t) else 0
    return s


def chercher(pages, exercice, diag=False):
    """Meilleure mention du ratio de solvabilite total pour l'exercice. Renvoie dict ou None."""
    cand = []
    for ip, p in enumerate(pages):
        lignes = [l.strip() for l in p.splitlines()]
        entetes = [ANNEE.findall(l) for l in lignes]
        for i, l in enumerate(lignes):
            if not MOT.search(l):
                continue
            suite = [x for x in lignes[i + 1:i + 3] if not re.search(r"levier|liquidit|division|couverture|transformation|ratio", x, re.I)]
            bloc = l if valeurs(l) else " ".join([l] + suite[:2])
            vals = valeurs(bloc)
            if not vals:
                continue
            if diag:
                print("      |", bloc[:160])
            # ordre des colonnes : annees lues dans la ligne ou dans les 12 lignes au-dessus
            ans_l = ANNEE.findall(bloc)
            if len(ans_l) < 2:
                for k in range(i - 1, max(-1, i - 13), -1):
                    if len(set(entetes[k])) >= 2:
                        ans_l = entetes[k]
                        break
            ans_l = [int(a) for a in ans_l]
            v_n, v_n1 = vals[0][1], vals[1][1] if len(vals) > 1 else None
            if len(vals) >= 2 and re.search(r"\d\s*(bps|pb|pts|points?)\b|[+-]\s?\d+(?:[.,]\d+)?\s*(bps|pb|pts)", bloc[vals[1][0]:], re.I):
                v_n, v_n1 = vals[1][1], vals[0][1]  # « 15,8 %  16,3 %  +51 bps » : ancienne valeur puis nouvelle
            approx = False
            m_de = re.search(r"\bde\s+(\d{1,2}(?:[.,]\d{1,2})?)\s?%\s*(?:\S+\s+){0,4}?[àa]\s+(\d{1,2}(?:[.,]\d{1,2})?)\s?%", bloc)
            if m_de:  # « passe de 13,9 % a 14,4 % »
                v_n1, v_n = float(m_de.group(1).replace(",", ".")), float(m_de.group(2).replace(",", "."))
            elif re.search(r"(sup[ée]rieur|plus de|au-del[àa] de)\s+(?:à\s+)?" + re.escape(re.sub(r"\.0$", "", str(v_n)).replace(".", ",")), bloc):
                approx = True
            confiance = poids_ligne(bloc)
            an_phrase = exercice
            annees_bloc = sorted(set(int(a) for a in ANNEE.findall(bloc)))
            if len(ans_l) >= 2 and exercice in ans_l and (exercice - 1) in ans_l and len(vals) >= 2:
                if ans_l.index(exercice) > ans_l.index(exercice - 1):
                    v_n, v_n1 = vals[1][1], vals[0][1]
                confiance += 2
            elif str(exercice) in bloc:
                confiance += 1
            elif len(annees_bloc) == 1 and annees_bloc[0] != exercice:
                if annees_bloc[0] != exercice - 1 or len(vals) > 2:
                    continue  # phrase sur une autre annee
                an_phrase = annees_bloc[0]  # chiffre de l'annee d'avant, garde avec son annee
            cand.append({"ratio": v_n, "ratio_n1": v_n1, "approx": approx, "annee": an_phrase, "phrase": re.sub(r"\s+", " ", bloc)[:220], "page": ip + 1, "confiance": confiance})
    cand = [c for c in cand if c["confiance"] >= 3]
    if any(c["annee"] == exercice for c in cand):
        cand = [c for c in cand if c["annee"] == exercice]
    if not cand:
        return None
    # la valeur la plus souvent citee parmi les meilleures mentions
    best = max(c["confiance"] for c in cand)
    top = [c for c in cand if c["confiance"] >= best - 1]
    votes = {}
    for c in top:
        votes[c["ratio"]] = votes.get(c["ratio"], 0) + 1 + c["confiance"] / 10
    r = max(votes, key=votes.get)
    choix = max((c for c in top if c["ratio"] == r), key=lambda c: c["confiance"])
    choix["mentions"] = sum(1 for c in cand if c["ratio"] == r)
    return choix


def pages_du_pdf(chemin, ocr_max=50):
    """Texte complet (pdftotext) ; si le document est scanne, OCR des premieres pages."""
    try:
        r = subprocess.run(["pdftotext", "-layout", "-l", "250", str(chemin), "-"], capture_output=True, text=True, timeout=300)
        pages = r.stdout.split("\f")
    except Exception:
        pages = []
    if sum(len(p) for p in pages) > 1500 * max(1, min(len(pages), 10)) / 10:
        return pages, 0
    try:
        n = int(re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", str(chemin)], capture_output=True, text=True).stdout).group(1))
    except Exception:
        n = ocr_max
    return [B.ocr_page(chemin, i + 1) for i in range(min(n, ocr_max))], min(n, ocr_max)


PERIODES = [(r"1(er|[eè]re)? trimestre|premier trimestre", 1, "1er trimestre"),
            (r"1(er)? semestre|premier semestre|2[eè]?(me)? trimestre|deuxi[eè]me trimestre", 2, "1er semestre"),
            (r"3[eè]?(me)? trimestre|troisi[eè]me trimestre|9 mois|neuf mois", 3, "3e trimestre"),
            (r"2[eè]?(me)? semestre|deuxi[eè]me semestre|4[eè]?(me)? trimestre|quatri[eè]me trimestre", 4, "fin d'année")]


def periode(titre):
    """(annee, rang dans l'annee, libelle) d'une publication ; None si ce n'est pas un rapport utile."""
    n = titre.lower().replace("_", " ").replace("-", " ")
    if re.search(r"convocation|avis de|attestation|resolution|résolution|dividende|projet|nomination|franchissement", n):
        return None
    ans_doc = [int(a) for a in ANNEE.findall(n)]
    if not ans_doc:
        return None
    an = max(ans_doc)
    for motif, rang, lib in PERIODES:
        if re.search(motif, n):
            return an, rang, lib
    if re.search(r"rapport annuel|rapport d.activit[ée]s? annuel|etats|états|financi|exercice|r[ée]sultats annuels|rapport de gestion|communiqu", n):
        return an, 4, "fin d'année"
    return None


def documents(pubs, depuis):
    """Rapports publies depuis l'annee « depuis », du plus recent au plus ancien (les plus complets d'abord a egalite)."""
    out = []
    for p in pubs:
        per = periode(p["titre"] + " " + p["url"].rsplit("/", 1)[-1])
        if not per or per[0] < depuis or per[0] > dt.date.today().year:
            continue
        n = p["titre"].lower()
        riche = 2 if re.search(r"rapport annuel|rapport de gestion|pilier|prudenti", n) else 1 if re.search(r"activit", n) else 0
        out.append(((per[0], per[1], riche), {**p, "annee": per[0], "periode": f"{per[2]} {per[0]}"}))
    return [p for _, p in sorted(out, key=lambda x: x[0], reverse=True)]


def main():
    nums = [int(a) for a in sys.argv[1:] if a.isdigit()]
    exercice = nums[0] if nums else dt.date.today().year - 1
    seuls = [a for a in sys.argv[1:] if re.fullmatch(r"[A-Z]{3,6}", a)]
    diag = "--diag" in sys.argv
    actuel = json.loads(SORTIE.read_text()) if SORTIE.exists() else {}
    pages, _ = B.pages_societes()
    for sym in BANQUES:
        if seuls and sym not in seuls:
            continue
        deja = actuel.get(sym)
        recent = deja and (dt.date.today() - dt.date.fromisoformat(deja.get("lu_le", "2000-01-01"))).days < 28
        if recent and "--tout" not in sys.argv:
            print(f"  {sym:<6} deja lu : {deja['ratio']} % ({deja.get('periode', deja['exercice'])})")
            continue
        pubs = [p for u in pages.get(sym, []) for p in B.publications_societe(u)]
        trouve = None
        for doc in documents(pubs, exercice)[:9]:  # le chiffre le plus recent publie (rapport annuel ou trimestriel)
            try:
                contenu = B.pdf_depuis(doc["url"])
                if not contenu:
                    continue
                with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
                    f.write(contenu)
                    f.flush()
                    txt, ocr = pages_du_pdf(f.name)
                if diag:
                    print(f"    {sym} : {doc['titre'][:80]} [{doc['periode']}] ({len(txt)} pages, {ocr} en OCR)")
                r = chercher(txt, doc["annee"], diag)
            except Exception as e:
                print(f"    {sym} : erreur {e.__class__.__name__} {str(e)[:80]}")
                continue
            if r:
                vieux = r["annee"] < doc["annee"]
                trouve = {**r, "exercice": r["annee"], "periode": f"fin d'année {r['annee']}" if vieux else doc["periode"],
                          "document": doc["titre"], "url": doc["url"], "lu_le": dt.date.today().isoformat()}
                break
        if trouve:
            actuel[sym] = trouve
            print(f"  {sym:<6} {trouve['ratio']} % ({trouve['periode']}, {trouve['mentions']} mention(s)) : {trouve['phrase'][:110]}")
        else:
            print(f"  {sym:<6} non trouve ({len(pubs)} publications)")
        SORTIE.write_text(json.dumps(actuel, ensure_ascii=False, indent=1))
    print(f"Solvabilite lue pour {len(actuel)} banques sur {len(BANQUES)}")


if __name__ == "__main__":
    main()
