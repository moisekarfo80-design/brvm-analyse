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
        if re.search(r"[≥>]|norme|minimum|minimal|exig|seuil|plancher|au moins|requis", avant):
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
            confiance = poids_ligne(bloc)
            if len(ans_l) >= 2 and exercice in ans_l and (exercice - 1) in ans_l and len(vals) >= 2:
                if ans_l.index(exercice) > ans_l.index(exercice - 1):
                    v_n, v_n1 = vals[1][1], vals[0][1]
                confiance += 2
            elif str(exercice) in bloc:
                confiance += 1
            elif re.search(r"\b(20[12]\d)\b", bloc) and str(exercice) not in bloc and len(vals) == 1:
                continue  # phrase sur une autre annee
            cand.append({"ratio": v_n, "ratio_n1": v_n1, "phrase": re.sub(r"\s+", " ", bloc)[:220], "page": ip + 1, "confiance": confiance})
    cand = [c for c in cand if c["confiance"] >= 3]
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


def pages_du_pdf(chemin, ocr_max=30):
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


def documents(pubs, exercice):
    """Rapports de l'exercice ou de l'annee suivante qui peuvent citer le ratio, les plus riches d'abord."""
    out = []
    for p in pubs:
        n = (p["titre"] + " " + p["url"].rsplit("/", 1)[-1]).lower().replace("_", " ").replace("-", " ")
        if not re.search(rf"\b({exercice}|{exercice + 1})\b", n):
            continue
        if re.search(r"convocation|avis de|attestation|resolution|résolution|dividende|projet", n):
            continue
        score = 0
        score += 6 if re.search(r"rapport annuel|rapport d.activit|rapport de gestion|pilier 3|pilier iii|informations? prudenti", n) else 0
        score += 3 if re.search(r"etats|états|financi", n) else 0
        score += 2 if re.search(r"communiqu|r[ée]sultats annuels", n) else 0
        score -= 2 if re.search(rf"\b{exercice + 1}\b", n) and not re.search(rf"\b{exercice}\b", n) else 0
        score -= 1 if re.search(r"trimestre|semestre|semestriel", n) else 0
        if score > 0:
            out.append((score, p))
    return [p for _, p in sorted(out, key=lambda x: -x[0])]


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
        if deja and deja.get("exercice", 0) >= exercice and "--tout" not in sys.argv:
            print(f"  {sym:<6} deja lu : {deja['ratio']} % ({deja['exercice']})")
            continue
        pubs = [p for u in pages.get(sym, []) for p in B.publications_societe(u)]
        trouve = None
        for ex in (exercice, exercice - 1):
            for doc in documents(pubs, ex)[:5]:
                try:
                    contenu = B.pdf_depuis(doc["url"])
                    if not contenu:
                        continue
                    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
                        f.write(contenu)
                        f.flush()
                        txt, ocr = pages_du_pdf(f.name)
                    if diag:
                        print(f"    {sym} {ex} : {doc['titre'][:80]} ({len(txt)} pages, {ocr} en OCR)")
                    r = chercher(txt, ex, diag)
                except Exception as e:
                    print(f"    {sym} : erreur {e.__class__.__name__} {str(e)[:80]}")
                    continue
                if r:
                    trouve = {**r, "exercice": ex, "document": doc["titre"], "url": doc["url"], "lu_le": dt.date.today().isoformat()}
                    break
            if trouve:
                break
        if trouve:
            actuel[sym] = trouve
            print(f"  {sym:<6} {trouve['ratio']} % ({trouve['exercice']}, {trouve['mentions']} mention(s)) : {trouve['phrase'][:110]}")
        else:
            print(f"  {sym:<6} non trouve ({len(pubs)} publications)")
        SORTIE.write_text(json.dumps(actuel, ensure_ascii=False, indent=1))
    print(f"Solvabilite lue pour {len(actuel)} banques sur {len(BANQUES)}")


if __name__ == "__main__":
    main()
