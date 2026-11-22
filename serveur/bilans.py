#!/usr/bin/env python3
"""Lecture automatique des etats financiers annuels publies sur brvm.org.

Pour chaque societe : trouve le PDF « Etats financiers - Exercice AAAA », le telecharge,
en sort le texte (ou le lit par reconnaissance de caracteres s'il est scanne), extrait
les chiffres cles de l'annee et de l'annee precedente, puis les CONTROLE :
  - total actif = total passif ;
  - resultat net identique dans le bilan et le compte de resultat (quand les deux sont lus) ;
  - chiffres plausibles (capitaux propres, rentabilite, croissance).
Un chiffre qui ne passe pas les controles n'est pas utilise : la societe reste « a confirmer ».

Resultat : donnees/bilans.json. Lance par .github/workflows/bilans.yml (chaque lundi et a la main).
Usage local : python serveur/bilans.py fichier.pdf [SYMBOLE]   -> lit un PDF et affiche le resultat
"""
import datetime as dt
import json
import math
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SORTIE = RACINE / "donnees" / "bilans.json"
REFERENCE = RACINE / "donnees" / "reference.json"
LISTE = "https://www.brvm.org/fr/type-document/etats-financiers?page={}"
ENTETES = {"User-Agent": "Mozilla/5.0 (compatible; brvm-analyse/1.0; usage personnel)"}

# --------------------------------------------------------------------------- texte
def texte_pdf(chemin, pages_max=40, garder=None):
    """Texte page par page ; une page sans texte exploitable est lue par OCR (tesseract, francais)."""
    import pdfplumber
    pages, ocr = [], 0
    with pdfplumber.open(chemin) as pdf:
        n = min(len(pdf.pages), pages_max)
        for i in range(n):
            t = pdf.pages[i].extract_text() or ""
            illisible = t.count("(cid:") > 20 or sum(c.isdigit() for c in t) < 60
            if illisible:
                t2 = ocr_page(chemin, i + 1)
                if sum(c.isdigit() for c in t2) > sum(c.isdigit() for c in t.replace("(cid:", "")):
                    t, ocr = t2, ocr + 1
            pages.append(t)
            if garder:
                Path(garder).write_text("\n=====PAGE=====\n".join(pages))
            if i >= 7 and trouve_assez("\n".join(pages)):
                break
    return pages, ocr


def texte_pdftotext(chemin, pages_max=40):
    try:
        r = subprocess.run(["pdftotext", "-layout", "-l", str(pages_max), str(chemin), "-"], capture_output=True, text=True, timeout=180)
        return [p for p in r.stdout.split("\f")]
    except Exception:
        return []


COMMUNIQUE = re.compile(
    r"(chiffre d.affaires|r[ée]sultat net|produit net bancaire|b[ée]n[ée]fice net)[^0-9\n]{0,40}?(-?\d[\d ]*(?:,\d+)?)\s*(milliards?|millions?)"
    r"[^%\n]{0,90}?(hausse|progression|augmentation|croissance|baisse|recul|repli|diminution)\s+(?:de\s+)?(\d+(?:,\d+)?)\s?%", re.I)


def lire_communique(pages):
    """Communiques ecrits en phrases : « Resultat net : 4,663 milliards FCFA, en progression de 31 % »."""
    out = {}
    for m in COMMUNIQUE.finditer(" ".join(pages).replace("\n", " ")):
        cle = {"c": "ca", "r": "rn", "p": "pnb", "b": "rn"}[m.group(1)[0].lower()]
        if cle in out:
            continue
        n = float(m.group(2).replace(" ", "").replace(",", ".")) * (1e9 if m.group(3).lower().startswith("milliard") else 1e6)
        g = float(m.group(5).replace(",", ".")) / 100 * (-1 if m.group(4).lower() in ("baisse", "recul", "repli", "diminution") else 1)
        if g <= -1:
            continue
        out[cle] = {"n": round(n), "n1": round(n / (1 + g)), "ligne": m.group(0)[:140], "pos": [-1, m.start()]}
    return out


def ocr_page(chemin, numero):
    with tempfile.TemporaryDirectory() as d:
        base = Path(d) / "p"
        subprocess.run(["pdftoppm", "-r", "250", "-gray", "-png", "-f", str(numero), "-l", str(numero), str(chemin), str(base)],
                       capture_output=True, timeout=120)
        imgs = sorted(Path(d).glob("p*.png"))
        if not imgs:
            return ""
        r = subprocess.run(["tesseract", str(imgs[0]), "-", "-l", "fra", "--psm", "6"], capture_output=True, text=True, timeout=180)
        return r.stdout


def trouve_assez(texte):
    t = texte.lower()
    return ("résultat net" in t or "resultat net" in t or "résultat de l'exercice" in t) and ("total" in t)


# --------------------------------------------------------------------------- nombres
NB_BRUT = re.compile(r"[-(]?\d[\d .,  ']*\d[)]?|[-(]?\d[)]?")


def normaliser(segment):
    """Uniformise les ecritures : 18,426,899,479 -> 18 426 899 479 ; 1 197,1 (milliards) -> montant x1000 isole ;
    retire les pourcentages (colonnes de variation) et les numeros de notes du type 4.1"""
    s = segment.replace("\u202f", " ").replace("\u00a0", " ").replace("’", "'")
    s = re.sub(r"\(?-?\s?\d+(?:[.,]\d+)?\s?,?%\)?", " | ", s)                    # 10,4% (40,7,%) 17%
    s = re.sub(r"(?<![\d,])(\d{1,3})((?:,\d{3})+)(?![\d,])", lambda m: m.group(1) + m.group(2).replace(",", " "), s)
    s = re.sub(r"(?<![\d.])\d{1,2}\.\d{1,2}(?![\d.])", " ", s)                       # notes 4.1, 4.10

    def dec(m):
        entier = m.group(1).replace(" ", "")
        frac = (m.group(2) + "00")[:3]
        signe = "-" if m.group(0).lstrip().startswith(("-", "(")) else ""
        return f" | {signe}{int(entier + frac)} | "
    s = re.sub(r"[-(]?\s?(\d{1,3}(?: \d{3})*),(\d{1,2})(?!\d)\)?", dec, s)           # 1 197,1 -> | 1197100 |
    return s


def nombres(segment):
    """Nombres d'un morceau de ligne. Les montants sont ecrits par groupes de 3 chiffres separes par
    des espaces ; deux montants voisins ne sont separes que par un espace. On essaie tous les decoupages
    possibles et on garde le plus vraisemblable : 2 montants (N et N-1) ou 4 (brut, amort., N, N-1),
    de tailles comparables, jamais plus de 100 000 milliards. Un signe -, une parenthese ou un
    separateur de cellule (| ] [) impose le debut d'un nouveau montant."""
    seg = normaliser(segment)
    jetons = []  # (chiffres, debut_force, negatif)
    for m in re.finditer(r"([-(|\]\[]?)\s?(\d+)", seg):
        avant = seg[max(0, m.start() - 3):m.start()]
        force = bool(m.group(1)) or "   " in avant or not jetons
        jetons.append((m.group(2), force, m.group(1) in ("-", "(")))
    if not jetons:
        return []
    n = len(jetons)
    meilleur = {"cout": None, "d": []}

    def explorer(i, acc):
        if len(acc) > 6:
            return
        if i == n:
            grands = [abs(x) for x in acc if abs(x) >= 1000] or [1]
            cout = 0.3 * sum(abs(math.log10(a) - math.log10(b)) for a, b in zip(grands, grands[1:]))
            nb_grands = sum(1 for x in acc if abs(x) >= 1000)
            cout += {1: 1.0, 2: 0.0, 3: 0.8, 4: 0.4}.get(nb_grands, 1.5) + 0.2 * (len(acc) - nb_grands)
            cout += 6 * sum(1 for x in acc if abs(x) >= 10 ** 14)
            if meilleur["cout"] is None or cout < meilleur["cout"]:
                meilleur.update(cout=cout, d=list(acc))
            return
        chiffres, _, neg = jetons[i]
        if len(chiffres) > 1 and chiffres[0] == "0":  # « 097 » ne peut pas commencer un montant
            return
        for k in range(i + 1, n + 1):
            if k > i + 1:
                ch, force, _ = jetons[k - 1]
                if force or len(ch) % 3:
                    break
            v = int("".join(j[0] for j in jetons[i:k]))
            explorer(k, acc + [-v if neg else v])

    if n > 18:  # ligne trop longue : decoupage simple par groupes de 3
        return [int(x) for x in re.findall(r"\d+", seg)]
    explorer(0, [])
    return meilleur["d"]


# --------------------------------------------------------------------------- champs
CHAMPS_ENTREPRISE = {
    "ca": [r"^\s*XB\b", r"chiffre d.affaires"],
    "rn": [r"^\s*XI\b", r"r[ée]sultat net de l.exercice", r"r[ée]sultat net\b"],
    "cp": [r"^\s*CP\b", r"total capitaux propres"],
    "dettes_fin": [r"^\s*DD\b", r"total dettes financi[èe]res"],
    "ebe": [r"^\s*XD\b", r"exc[ée]dent brut d.exploitation"],
    "total_actif": [r"^\s*BZ\b", r"total actif\b(?!\s*(circ|immo))"],
    "total_passif": [r"^\s*DZ\b", r"total passif\b"],
}
CHAMPS_BANQUE = {
    "pnb": [r"produit net bancaire"],
    "rn": [r"r[ée]sultat de l.exercice", r"r[ée]sultat net", r"b[ée]n[ée]fice ou perte"],
    "cp": [r"total (des )?capitaux propres", r"capitaux propres et ressources assimil"],
    "charges_gen": [r"charges g[ée]n[ée]rales d.exploitation"],
    "cout_risque": [r"co[ûu]t du risque"],
    "total_actif": [r"total ?de ?l.?actif", r"total actif"],
    "total_passif": [r"total ?du ?passif", r"total passif"],
}


def valeurs_apres(ligne, debut):
    """Nombres situes apres le libelle, jusqu'au prochain libelle (cas des bilans sur deux colonnes)."""
    reste = ligne[debut:]
    m = re.search(r"[A-Za-zÀ-ÿ]{3,}", reste)
    seg = reste[: m.start()] if m and re.search(r"\d", reste[: m.start()]) else reste
    seg = re.sub(r"\([A-Z0-9 +\-àé]+\)", " ", seg)  # retire les references du type (XG+XH+RQ+RS)
    vals = [v for v in nombres(seg) if abs(v) >= 1000 or v == 0]
    if len(vals) == 3 and abs(vals[0] - vals[1] - vals[2]) <= 0.002 * max(map(abs, vals)):
        vals = vals[:2]  # N, N-1, variation
    return vals


def extraire(pages):
    texte = "\n".join(pages)
    banque = bool(re.search(r"produit net bancaire", texte, re.I))
    champs = CHAMPS_BANQUE if banque else CHAMPS_ENTREPRISE
    lignes = texte.splitlines()
    out = {}
    for cle, motifs in champs.items():
        for motif in motifs:
            for i, l in enumerate(lignes):
                m = re.search(motif, l, re.I)
                if not m:
                    continue
                vals = valeurs_apres(l, m.end())
                suivante = lignes[i + 1] if i + 1 < len(lignes) else ""
                if not vals and not re.search(r"[A-Za-zÀ-ÿ]{4,}", suivante):  # chiffres seuls sur la ligne suivante
                    vals = [v for v in nombres(suivante) if abs(v) >= 1000 or v == 0][:2]
                if len(vals) >= 2:
                    out[cle] = {"n": vals[-2], "n1": vals[-1], "ligne": l.strip()[:140], "pos": [i, m.start()]}
                    break
                if len(vals) == 1 and cle not in out:
                    out[cle] = {"n": vals[0], "n1": None, "ligne": l.strip()[:140], "pos": [i, m.start()]}
            if cle in out and out[cle]["n1"] is not None:
                break
    # resultat net : deux lectures possibles (bilan et compte de resultat)
    rn_lus, vues = [], set()
    for motif in champs["rn"]:
        for i, l in enumerate(lignes):
            m = re.search(motif, l, re.I)
            if m and i not in vues:  # chaque ligne une seule fois : une ligne ne se confirme pas elle-meme
                v = valeurs_apres(l, m.end())
                if len(v) >= 2:
                    vues.add(i)
                    rn_lus.append((v[-2], v[-1]))
    return banque, out, rn_lus


SUSPECT = re.compile(r"(?<![\d])\d{1,2} \d{1,2} \d{3}(?!\d)|(?<![\d])\d \d \d{3}(?!\d)")


def controler(banque, ch, rn_lus):
    ok, pb = [], []
    ch = {k: v for k, v in ch.items() if v.get("n1") is not None}  # une ligne incomplete ne sert pas aux controles
    ta, tp = ch.get("total_actif"), ch.get("total_passif")
    if ta and tp and ta.get("pos") != tp.get("pos"):  # deux endroits differents (deux colonnes d'une meme ligne : accepte)
        if abs(ta["n"] - tp["n"]) <= 0.005 * max(abs(ta["n"]), 1):
            ok.append("total actif = total passif")
        else:
            pb.append("total actif different du total passif")
    if len(rn_lus) >= 2 and any(rn_lus[i] == rn_lus[j] for i in range(len(rn_lus)) for j in range(i + 1, len(rn_lus))):
        ok.append("resultat net identique sur deux lignes differentes")
    rn, cp = ch.get("rn"), ch.get("cp")
    base = ch.get("pnb") if banque else ch.get("ca")
    manquants = [nom for nom, v in (("resultat net", rn), ("capitaux propres", cp),
                                     ("PNB" if banque else "chiffre d'affaires", base)) if not v]
    if not rn:
        pb.append("resultat net introuvable")
    if rn and cp and cp["n"] > 0 and abs(rn["n"]) > 1.2 * cp["n"]:
        pb.append("resultat net incoherent avec les capitaux propres")
    if rn and base and base["n"] > 0 and abs(rn["n"]) > base["n"]:
        pb.append("resultat net superieur au chiffre d'affaires / PNB")
    if cp and ta and ta["n"] and cp["n"] > ta["n"]:
        pb.append("capitaux propres superieurs au total du bilan")
    # variations extremes : plus probablement une erreur de lecture qu'une realite
    base1 = (ch.get("pnb") if banque else ch.get("ca")) or {}
    if base and base1.get("n1") and base1["n1"] > 0 and abs(base["n"] / base1["n1"] - 1) > 0.8:
        pb.append("activite qui varie de plus de 80 % : a verifier")
    if rn and rn.get("n1") and rn["n1"] > 0 and rn["n"] > 0 and (rn["n"] / rn["n1"] - 1 > 4 or rn["n"] / rn["n1"] - 1 < -0.99):
        pb.append("resultat net qui varie enormement : a verifier")
    # faux espaces dans les chiffres (« 4 65 981 1 8 595 275 ») sur une ligne utilisee
    for k, v in ch.items():
        if SUSPECT.search(normaliser(v.get("ligne", ""))):
            pb.append(f"chiffres mal espaces sur la ligne « {k} » : lecture douteuse")
            break
    # colonnes en deux monnaies : croissances identiques de l'activite et du resultat
    if base and rn and base.get("n1") and rn.get("n1") and base["n1"] > 0 and rn["n1"] > 0:
        if abs((base["n"] / base["n1"]) - (rn["n"] / rn["n1"])) < 0.0005 and abs(base["n"] / base["n1"] - 1) > 0.02:
            pb.append("activite et resultat varient exactement pareil : colonnes melangees ?")
    ebe = ch.get("ebe")
    if ebe and base and base["n"] > 0 and abs(ebe["n"]) > base["n"]:
        pb.append("excedent brut superieur au chiffre d'affaires")
    statut = "valide" if ok and not pb else "a confirmer"
    return statut, ok, pb + [f"{m} non publie ou non lu" for m in manquants if m != "resultat net"] if statut != "valide" else pb, manquants


def ratios(banque, ch):
    g = lambda k, p="n": (ch.get(k) or {}).get(p)
    r = {}
    rn, cp = g("rn"), g("cp")
    if rn is not None and cp and cp > 0:
        r["roe"] = rn / cp
    base, base1 = (g("pnb"), g("pnb", "n1")) if banque else (g("ca"), g("ca", "n1"))
    if base and rn is not None:
        r["marge"] = rn / base
    if base and base1 and base1 > 0:
        r["croissance_activite"] = base / base1 - 1
    rn1 = g("rn", "n1")
    if rn is not None and rn >= 0 and rn1 and rn1 > 0:
        r["croissance_resultat"] = rn / rn1 - 1
    elif rn is not None and rn1 and rn1 > 0 and rn < 0:
        r["croissance_resultat"] = -1.0  # passage du benefice a la perte
    elif rn is not None and rn1 is not None and rn1 <= 0:
        # depart en perte : retour au benefice = tres bien ; perte reduite = bien ; perte aggravee = mal
        r["croissance_resultat"] = 0.5 if rn > 0 else (0.15 if rn > rn1 else -0.5)
        r["perte_precedente"] = 1
    if banque:
        if g("charges_gen") and base:
            r["coef_exploitation"] = abs(g("charges_gen")) / base
        if g("cout_risque") is not None and base:
            r["cout_risque_pnb"] = abs(g("cout_risque")) / base
    else:
        if g("dettes_fin") is not None and cp and cp > 0:
            r["dette_cp"] = g("dettes_fin") / cp
        if g("ebe") is not None and base:
            r["marge_ebe"] = g("ebe") / base
    return {k: round(v, 4) for k, v in r.items()}


MOTS_DIAG = re.compile(r"r[ée]sultat|b[ée]n[ée]fice|capitaux propres|chiffre d.affaires|produit net|total|revenus|ventes|"
                       r"charges g[ée]n|co[ûu]t du risque|^\s*(XB|XI|CP|BZ|DZ|DD|XD)\b", re.I)


def evaluer(pages):
    banque, ch, rn_lus = extraire(pages)
    ch = {k: v for k, v in ch.items() if v.get("n1") is not None}
    statut, ok, pb, manquants = controler(banque, ch, rn_lus)
    score = (2 if statut == "valide" else 0) + len(ok) + 0.2 * len(ch) - 0.5 * len(pb)
    score -= 0.05 * len(SUSPECT.findall(normaliser("\n".join(pages))))
    return score, banque, ch, statut, ok, pb, manquants


def lire_pdf(chemin, diag=False):
    pages, ocr = texte_pdf(chemin)
    essais = [("pdfplumber/ocr", pages)]
    pt = texte_pdftotext(chemin)
    if sum(c.isdigit() for c in "".join(pt)) > 200:
        essais.append(("pdftotext", pt))
    resultats = [(evaluer(p), nom, p) for nom, p in essais]
    (score, banque, ch, statut, ok, pb, manquants), outil, pages = max(resultats, key=lambda x: x[0][0])
    communique = False
    if statut != "valide":  # dernier recours : communique ecrit en phrases
        cm = lire_communique(pages)
        if "rn" in cm and ("ca" in cm or "pnb" in cm):
            rn, base = cm["rn"], cm.get("pnb") or cm.get("ca")
            if 0 < abs(rn["n"]) < base["n"]:
                ch, statut, communique = {**cm}, "valide", True
                ok, pb, manquants = ["chiffres repris du communique officiel (croissance seulement)"], [], ["capitaux propres"]
                banque = "pnb" in cm
    if diag:
        lignes = [l.strip()[:150] for p in pages for l in p.splitlines() if MOTS_DIAG.search(l)]
        print("    --- lignes vues (%d pages, %d en OCR) ---" % (len(pages), ocr))
        for l in lignes[:45]:
            print("    | " + l)
    if diag:
        print(f"    outil retenu : {outil}{' + communique' if communique else ''}")
    rat = ratios(banque, ch)
    if communique:  # sans bilan detaille : seulement la croissance
        rat = {k: v for k, v in rat.items() if k.startswith("croissance")}
    return {"banque": banque, "pages_ocr": ocr, "manquants": manquants, "outil": outil, "communique": communique, "chiffres": {k: {"n": v["n"], "n1": v["n1"]} for k, v in ch.items()},
            "lignes_lues": {k: v["ligne"] for k, v in ch.items()}, "statut": statut, "controles_ok": ok,
            "problemes": pb, "ratios": rat}


# --------------------------------------------------------------------------- site BRVM
ALIAS = {  # mots du titre de la publication -> symbole
    "SICABLE": "CABC", "FILTISAC": "FTSC", "NEI": "NEIC", "NESTLE": "NTLC", "SEMC": "SEMC", "EVIOSYS": "SEMC",
    "SITAB": "STBC", "SMB": "SMBC", "SOLIBRA": "SLBC", "UNILEVER": "UNLC", "UNIWAX": "UNXC", "SUCRIVOIRE": "SCRC",
    "SICOR": "SICC", "SOGB": "SOGC", "SAPH": "SPHC", "PALM": "PALC", "ABJ": "ABJC", "SERVAIR": "ABJC", "BERNABE": "BNBC",
    "CFAO": "CFAC", "TRACTAFRIC": "PRSC", "VIVO": "SHEC", "SHELL": "SHEC", "TOTALENERGIES MARKETING CI": "TTLC",
    "TOTALENERGIES MARKETING SN": "TTLS", "TOTAL CI": "TTLC", "TOTAL SN": "TTLS", "SONATEL": "SNTS", "ORANGE CI": "ORAC",
    "ONATEL": "ONTBF", "CIE": "CIEC", "SODE": "SDCC", "SODECI": "SDCC", "AGL": "SDSC", "BOLLORE": "SDSC",
    "AIR LIQUIDE": "SIVC", "SETAO": "STAC", "LNB": "LNBB", "LOTERIE": "LNBB", "BOA BF": "BOABF", "BOA BURKINA": "BOABF",
    "BOA BN": "BOAB", "BOA BENIN": "BOAB", "BOA CI": "BOAC", "BOA ML": "BOAM", "BOA MALI": "BOAM", "BOA NG": "BOAN",
    "BOA NIGER": "BOAN", "BOA SN": "BOAS", "BOA SENEGAL": "BOAS", "CORIS": "CBIBF", "ECOBANK CI": "ECOC", "ECOBANK COTE": "ECOC",
    "ETI": "ETIT", "ECOBANK TRANSNATIONAL": "ETIT", "SGB": "SGBC", "SOCIETE GENERALE": "SGBC", "SIB": "SIBC",
    "NSIA": "NSBC", "BICI": "BICC", "BIIC": "BICB", "ORAGROUP": "ORGT", "SAFCA": "SAFC", "BBG": "BBGC", "AFRICA GLOBAL LOGISTICS": "SDSC", "AFRICA GLOGAL LOGISTICS": "SDSC",
}


def symbole_de(titre):
    t = titre.upper().replace("É", "E").replace("È", "E").replace("Ô", "O")
    for nom in sorted(ALIAS, key=len, reverse=True):
        if re.search(r"(^|[^A-Z])" + re.escape(nom) + r"([^A-Z]|$)", t):
            return ALIAS[nom]
    return None


def lister_publications(exercice, pages=30):
    import requests
    from html import unescape
    pubs = []
    for p in range(pages):
        try:
            html = requests.get(LISTE.format(p), headers=ENTETES, timeout=40).text
        except Exception as e:
            print("  liste page", p, "illisible :", e)
            continue
        liens = re.findall(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>(.*?)</a>', html, re.S | re.I)
        titres = re.findall(r'<a[^>]+href="(/fr/[^"]+)"[^>]*>([^<]*Etats? financiers[^<]*)</a>', html, re.I)
        for url, txt in liens:
            pubs.append((unescape(re.sub("<[^>]+>", "", txt)).strip() or url.rsplit("/", 1)[-1], url))
        for url, txt in titres:
            pubs.append((unescape(txt).strip(), url))
        time.sleep(1)
    vus, res = set(), []
    for titre, url in pubs:
        nom = (titre + " " + url).lower()
        if f"exercice_{exercice}" not in nom.replace(" ", "_").replace("-", "_") and f"exercice {exercice}" not in nom:
            continue
        if "trimestre" in nom or "semestre" in nom:
            continue
        if url in vus:
            continue
        vus.add(url)
        res.append({"titre": titre, "url": url if url.startswith("http") else "https://www.brvm.org" + url,
                    "symbole": symbole_de(titre + " " + url.rsplit("/", 1)[-1].replace("_", " ").replace("-", " "))})
    return res


INDEX_SOCIETES = "https://www.brvm.org/fr/rapports-societe-cotes"


SLUGS = {  # pages « rapports » de brvm.org -> symbole (verifie a la main)
    "air-liquide-ci": "SIVC", "bank-africa-bf": "BOABF", "bank-africa-bn": "BOAB", "bank-africa-ci": "BOAC",
    "bank-africa-ml": "BOAM", "bank-africa-ng": "BOAN", "bank-africa-sn": "BOAS", "bbgci": "BBGC", "bernabe-ci": "BNBC",
    "bici-ci": "BICC", "biic": "BICB", "bollore-transport-logistics": "SDSC", "cfao-motors-ci": "CFAC", "cie-ci": "CIEC",
    "coris-bank-international": "CBIBF", "cote-divoire-telecom": "ORAC", "ecobank-ci": "ECOC", "ecobank-tg": "ETIT",
    "filtisac-ci": "FTSC", "lnb": "LNBB", "sgci": "SGBC",
}


def pages_societes():
    """Pages « rapports » de chaque societe cotee : {symbole: url}."""
    import requests
    from html import unescape
    res, autres = {}, []
    for p in range(5):
        try:
            html = requests.get(f"https://www.brvm.org/fr/rapports-societes-cotees?page={p}", headers=ENTETES, timeout=40).text
        except Exception as e:
            print("  index illisible :", e)
            continue
        liens = re.findall(r'href="/fr/rapports-societe-cotes/([a-z0-9\-]+)">([^<]+)</a>', html)
        if not liens:
            break
        for slug, nom in liens:
            nom = unescape(nom).strip()
            sym = SLUGS.get(slug) or symbole_de(nom)
            if sym and sym not in res:
                res[sym] = f"{INDEX_SOCIETES}/{slug}"
            elif not sym:
                autres.append(f"{slug}={nom[:30]}")
        time.sleep(1)
    return res, autres


def publications_societe(url, pages=6):
    """Toutes les publications (titre, lien PDF) d'une societe, toutes annees confondues."""
    import requests
    from html import unescape
    out, vus = [], set()
    for p in range(pages):
        try:
            html = requests.get(url + (f"?page={p}" if p else ""), headers=ENTETES, timeout=40).text
        except Exception:
            break
        lignes = re.findall(r'<strong>(.*?)</strong>\s*</td>\s*<td[^>]*>\s*<a href="([^"]+)"', html, re.S)
        if not lignes:
            break
        for t, u in lignes:
            u = u if u.startswith("http") else "https://www.brvm.org" + u
            if u not in vus:
                vus.add(u)
                out.append({"titre": unescape(re.sub(r"\s+", " ", t)).strip(), "url": u})
        time.sleep(0.7)
    return out


def annuels(pubs, exercice):
    """Publications annuelles (etats financiers ou rapport annuel) d'un exercice donne."""
    out = []
    for p in pubs:
        n = (p["titre"] + " " + p["url"].rsplit("/", 1)[-1]).lower().replace("_", " ").replace("-", " ")
        if not re.search(rf"exercice\s*(clos[^0-9]*)?{exercice}\b|\b{exercice}\b.*(etats|états) financiers|(etats|états) financiers.*\b{exercice}\b", n):
            continue
        if re.search(r"trimestre|semestre|semestriel|attestation|convocation|avis|dividende|resolution|résolution", n):
            continue
        if not re.search(r"etats|états|financi|rapport d.activit[ée]s? annuel|rapport annuel|comptes", n):
            continue
        out.append(p)
    return out


def preference(pub):
    n = (pub["titre"] + pub["url"]).lower()
    score = 0
    score += 3 if "approuv" in n else 0
    score += 2 if "annule" in n else 0
    score += 1 if "syscohada" in n else 0
    score -= 2 if "ifrs" in n and "syscohada" not in n else 0
    score -= 3 if "communiqu" in n and "etats" not in n else 0
    score -= 4 if "rapport annuel" in n or "rapport_annuel" in n or "rapport d" in n else 0
    score -= 4 if "attestation" in n else 0
    return score


def pdf_depuis(url):
    import requests
    r = requests.get(url, headers=ENTETES, timeout=60)
    if url.lower().endswith(".pdf") or r.headers.get("content-type", "").startswith("application/pdf"):
        return r.content
    m = re.search(r'href="([^"]+\.pdf)"', r.text, re.I)
    if not m:
        return None
    u = m.group(1)
    u = u if u.startswith("http") else "https://www.brvm.org" + u
    return requests.get(u, headers=ENTETES, timeout=60).content


def main():
    if len(sys.argv) > 1 and sys.argv[1].lower().endswith(".pdf"):
        print(json.dumps(lire_pdf(sys.argv[1]), ensure_ascii=False, indent=1))
        return
    nums = [a for a in sys.argv[1:] if a.isdigit()]
    exercice = int(nums[0]) if nums else dt.date.today().year - 1
    actuel = json.loads(SORTIE.read_text()) if SORTIE.exists() else {"societes": {}}
    pubs = lister_publications(exercice)
    print(f"{len(pubs)} publications « Exercice {exercice} » trouvees")
    if "--diag" in sys.argv:
        for p in pubs:
            print(f"  PUB {p['symbole'] or '?':<6} {p['titre'][:110]}")
    par_sym = {}
    for p in pubs:
        if p["symbole"]:
            par_sym.setdefault(p["symbole"], []).append(p)
        else:
            print("  societe non reconnue :", p["titre"][:90])
    for sym, lst in sorted(par_sym.items()):
        lst.sort(key=preference, reverse=True)
        deja = actuel["societes"].get(sym)
        if "--tout" not in sys.argv and deja and deja.get("exercice") == exercice and deja.get("url") == lst[0]["url"] and deja.get("statut") == "valide":
            continue
        res = None
        for p in lst[:3]:
            try:
                contenu = pdf_depuis(p["url"])
                if not contenu:
                    continue
                with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
                    f.write(contenu)
                    f.flush()
                    r = lire_pdf(f.name, diag="--diag" in sys.argv)
                r.update(exercice=exercice, url=p["url"], titre=p["titre"], lu_le=dt.date.today().isoformat())
                if res is None or (r["statut"] == "valide" and res["statut"] != "valide"):
                    res = r
                if r["statut"] == "valide":
                    break
            except Exception as e:
                print(f"  {sym} : erreur {e.__class__.__name__} {str(e)[:100]}")
        if res:
            actuel["societes"][sym] = res
            print(f"  {sym:<6} {res['statut']:<12} ocr {res['pages_ocr']:>2}  {', '.join(res['problemes']) or 'ok'}  {res['ratios']}")
        time.sleep(1)
    actuel["maj"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    SORTIE.write_text(json.dumps(actuel, ensure_ascii=False, indent=1))
    v = sum(1 for s in actuel["societes"].values() if s["statut"] == "valide")
    print(f"Bilans : {v} valides, {len(actuel['societes']) - v} a confirmer")





def test_pages():
    """Diagnostic : pages des societes et publications trouvees (sans rien lire)."""
    pages, inconnues = pages_societes()
    print(f"{len(pages)} societes reconnues ; autres pages (obligations, fonds, inconnues) : {inconnues}")
    for sym, url in sorted(pages.items())[:60]:
        pubs = publications_societe(url, pages=3)
        par_an = {an: len(annuels(pubs, an)) for an in range(2021, 2026)}
        print(f"  {sym:<6} {url.rsplit('/', 1)[-1]:<28} {len(pubs):>3} publications ; annuelles {par_an}")
        if sym in ("SGBC", "SNTS"):
            for p in pubs[:8]:
                print("      -", p["titre"][:100])


if __name__ == "__main__":
    if "--pages" in sys.argv:
        test_pages()
    else:
        main()
