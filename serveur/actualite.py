"""Actualite des societes cotees : communiques et rapports publies sur brvm.org.

Pour chaque societe : liste des publications (titre, date, lien), classees par type :
resultats, dividende, assemblee, capital, suspension, dirigeants, autre.
Pour les publications recentes (moins de 400 jours) de type resultats ou dividende, le PDF est lu une seule fois :
- dividende : montant net par action et date de paiement ;
- resultats : la phrase qui donne l'evolution du resultat net (hausse / baisse en %).

Usage : python serveur/actualite.py [SYM ...] [--diag] [--tout]
Ecrit donnees/actualite.json : {symbole: [{date, titre, type, url, vu_le, detail?, sens?, dividende?, paiement?}]}.
Rien n'est invente : une information illisible reste vide.
"""
import datetime as dt
import json
import re
import subprocess
import sys
import tempfile
import time
from html import unescape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import bilans as B  # noqa: E402

SORTIE = B.RACINE / "donnees" / "actualite.json"
MOIS = {m: i + 1 for i, m in enumerate(["janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout", "septembre", "octobre", "novembre", "decembre"])}
TYPES = [
    ("suspension", r"suspension|reprise de cotation|radiation"),
    ("dividende", r"dividende|mise en paiement|coupon"),
    ("capital", r"augmentation de capital|fractionnement|split|regroupement|offre publique|\bopa\b|\bope\b|\bopr\b|cession|franchissement"),
    ("assemblee", r"convocation|assembl[ée]e|\bago\b|\bage\b|r[ée]solutions?|compte rendu"),
    ("dirigeants", r"nomination|d[ée]mission|directeur g[ée]n[ée]ral|\bdg\b|conseil d.administration|pr[ée]sident|d[ée]c[eè]s"),
    ("resultats", r"r[ée]sultats?|rapport d.activit|trimestre|semestre|semestriel|etats financiers|états financiers|rapport annuel|rapport financier|chiffre d.affaires|comptes"),
]
IMPORTANT = {"dividende", "resultats", "suspension", "capital", "dirigeants"}


def sans_accents(t):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def type_de(titre):
    t = titre.lower()
    for nom, motif in TYPES:
        if re.search(motif, t):
            return nom
    return "autre"


def date_de(texte):
    """Premiere date lisible : 12/11/2026, 2026-11-12, 12 novembre 2026, ou dossier /files/2026-11/."""
    t = sans_accents(texte.lower())
    m = re.search(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](20\d\d)\b", t)
    if m:
        try:
            return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            pass
    m = re.search(r"\b(20\d\d)-(\d{2})-(\d{2})\b", t)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})(?:er)?\s+(" + "|".join(MOIS) + r")\s+(20\d\d)\b", t)
    if m:
        try:
            return dt.date(int(m.group(3)), MOIS[m.group(2)], int(m.group(1))).isoformat()
        except ValueError:
            pass
    return None


def date_dossier(url):
    """Date lisible dans le lien : /files/20261116_-_... ou /files/2026-11/..."""
    m = re.search(r"/(20\d\d)(\d{2})(\d{2})[_-]", url)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            pass
    m = re.search(r"/files/(20\d\d)-(\d{2})/", url)
    return f"{m.group(1)}-{m.group(2)}-01" if m else None


def publications(url, pages=3, diag=False):
    """Publications d'une societe avec la date de la ligne quand le site la donne."""
    import requests
    out, vus = [], set()
    for p in range(pages):
        try:
            html = requests.get(url + (f"?page={p}" if p else ""), headers=B.ENTETES, timeout=40).text
        except Exception:
            break
        lignes = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
        trouve = False
        for i, tr in enumerate(lignes):
            m = re.search(r'<a href="([^"]+)"', tr)
            titre = re.search(r"<strong>(.*?)</strong>", tr, re.S)
            if not m or not titre:
                continue
            trouve = True
            if diag and p == 0 and i < 3:
                print("      ligne brute :", re.sub(r"\s+", " ", tr)[:400])
            u = m.group(1) if m.group(1).startswith("http") else "https://www.brvm.org" + m.group(1)
            if u in vus:
                continue
            vus.add(u)
            t = unescape(re.sub(r"<[^>]+>|\s+", " ", titre.group(1))).strip()
            cellules = " ".join(unescape(re.sub(r"<[^>]+>", " ", c)) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S))
            date = date_de(re.sub(re.escape(t), " ", cellules)) or date_dossier(u)
            out.append({"titre": t, "url": u, "date": date, "date_titre": date_de(t)})
        if not trouve:
            break
        time.sleep(0.7)
    return out


def texte(url, pages=6):
    contenu = B.pdf_depuis(url)
    if not contenu:
        return ""
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(contenu)
        f.flush()
        r = subprocess.run(["pdftotext", "-layout", "-l", str(pages), f.name, "-"], capture_output=True, text=True, timeout=120)
        t = r.stdout
        if len(t.strip()) < 200:  # document scanne : OCR des 2 premieres pages
            t = "\n".join(B.ocr_page(f.name, i) for i in (1, 2))
    return t


def lire_dividende(t):
    """Montant net par action et date de paiement dans un avis de dividende."""
    plat = re.sub(r"\s+", " ", t)
    montant = None
    for m in re.finditer(r"dividende[^.]{0,120}?net[^.]{0,60}?(\d{1,3}(?:[ .  ]\d{3})*(?:,\d+)?)\s*(?:F\s*CFA|FCFA|francs)", plat, re.I):
        v = float(m.group(1).replace(" ", "").replace(".", "").replace(" ", "").replace(" ", "").replace(",", "."))
        if 1 <= v <= 100000:
            montant = v
            break
    if montant is None:
        m = re.search(r"net[^.]{0,40}?(?:par action|/action)?[^.]{0,20}?(\d{1,3}(?:[ .]\d{3})*(?:,\d+)?)\s*(?:F\s*CFA|FCFA)", plat, re.I)
        if m:
            v = float(m.group(1).replace(" ", "").replace(".", "").replace(",", "."))
            montant = v if 1 <= v <= 100000 else None
    paiement = None
    m = re.search(r"(?:mise? en paiement|pay[ée]s?|paiement)[^.]{0,80}", plat, re.I)
    if m:
        paiement = date_de(m.group(0))
    return montant, paiement


def lire_resultats(t):
    """Phrase sur l'evolution du resultat net, et son sens (+1 hausse, -1 baisse)."""
    plat = re.sub(r"\s+", " ", t)
    for phrase in re.split(r"(?<=[.;])\s", plat):
        p = phrase.lower()
        if "résultat net" not in p and "resultat net" not in p and "bénéfice" not in p:
            continue
        if not re.search(r"\d+(?:,\d+)?\s?%", p):
            continue
        sens = 1 if re.search(r"hausse|progress|augment|amélior|ameliore|croissance|bond", p) else -1 if re.search(r"baisse|recul|diminu|repli|dégrad|degrad|chute|perte", p) else 0
        if sens:
            return phrase.strip()[:230], sens
    return None, 0


ANNONCES = {"communiques": None, "convocations-assemblees-generales": "assemblee", "changements-de-dirigeants": "dirigeants",
            "franchissements-de-seuil": "capital"}
DIVIDENDES = "https://www.brvm.org/fr/esv/paiement-de-dividendes"


def cellules(tr):
    return [unescape(re.sub(r"<[^>]+>|\s+", " ", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]


def annonces(section, pages, diag=False):
    """Lignes datees d'une rubrique « Annonces emetteurs » : date, societe, titre, PDF."""
    import requests
    out = []
    for p in range(pages):
        try:
            html = requests.get(f"https://www.brvm.org/fr/emetteurs/type-annonces/{section}" + (f"?page={p}" if p else ""), headers=B.ENTETES, timeout=40).text
        except Exception as e:
            print(f"  {section} page {p} illisible : {e.__class__.__name__}")
            break
        lignes = [tr for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S) if "<td" in tr]
        if diag and p == 0 and lignes:
            print(f"    {section} ligne brute :", re.sub(r"\s+", " ", lignes[0])[:300])
        n = 0
        for tr in lignes:
            c = cellules(tr)
            lien = re.search(r'href="([^"]+\.pdf)"', tr, re.I) or re.search(r'href="(/[^"]+)"', tr)
            date = next((date_de(x) for x in c if date_de(x)), None)
            titre = max(c, key=len) if c else ""
            if not titre or not date:
                continue
            u = lien.group(1) if lien else ""
            u = u if not u or u.startswith("http") else "https://www.brvm.org" + u
            societe = next((x for x in c if x and x != titre and not date_de(x) and "Télécharger" not in x), "")
            sym = B.symbole_de(societe) if societe else None
            sym = sym or B.symbole_de(titre.split(":")[0])
            out.append({"sym": sym, "date": date, "titre": titre, "url": u, "type": ANNONCES[section] or type_de(titre)})
            n += 1
        if not n:
            break
        time.sleep(0.8)
    return out


def dividendes(pages, diag=False):
    """Tableau officiel des paiements de dividendes : emetteur, exercice, paiement, ex-dividende, montant net."""
    import requests
    out = []
    for p in range(pages):
        try:
            html = requests.get(DIVIDENDES + (f"?page={p}" if p else ""), headers=B.ENTETES, timeout=40).text
        except Exception as e:
            print(f"  dividendes page {p} illisible : {e.__class__.__name__}")
            break
        lignes = [tr for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S) if "<td" in tr]
        if diag and p == 0 and lignes:
            print("    dividendes ligne brute :", re.sub(r"\s+", " ", lignes[0])[:300])
        n = 0
        for tr in lignes:
            c = [x for x in cellules(tr)]
            dates = [date_de(x) for x in c if date_de(x)]
            montants = [x for x in c if re.fullmatch(r"[\d  .,]+(?:\s*F\s*CFA|\s*FCFA)?", x) and re.search(r"\d", x) and not re.fullmatch(r"20\d\d", x.strip())]
            if not c or len(dates) < 1 or not montants:
                continue
            emetteur = c[0]
            sym = B.symbole_de(emetteur)
            exo = next((x for x in c if re.fullmatch(r"(?:Exercice\s*)?20\d\d", x)), "")
            m = montants[-1].replace("FCFA", "").replace("F CFA", "").replace(" ", "").replace(" ", "")
            m = float(m.replace(",", ".")) if m.count(".") <= 1 else float(m.replace(".", ""))
            paiement, exdiv = dates[0], dates[1] if len(dates) > 1 else None
            out.append({"sym": sym, "emetteur": emetteur, "exercice": re.sub(r"\D", "", exo) or None, "paiement": paiement,
                        "ex_dividende": exdiv, "dividende": m})
            n += 1
        if not n:
            break
        time.sleep(0.8)
    return out


def ajouter(actuel, sym, item, premier, auj):
    """Ajoute une publication si elle est nouvelle ; renvoie True si nouvelle."""
    if not sym:
        return False
    liste = actuel.setdefault(sym, [])
    cle = item.get("url") or f"{item['type']}|{item['date']}|{item['titre']}"
    for x in liste:
        if (x.get("url") or f"{x['type']}|{x['date']}|{x['titre']}") == cle:
            for k, v in item.items():
                x.setdefault(k, v)
            return False
    item["vu_le"] = "initial" if premier else auj.isoformat()
    liste.append(item)
    return True


def main():
    diag = "--diag" in sys.argv
    histo = "--historique" in sys.argv
    auj = dt.date.today()
    actuel = json.loads(SORTIE.read_text()) if SORTIE.exists() else {}
    if actuel and "version" not in actuel.get("_info", {}):  # ancien format (rapports sans date) : on repart de zero
        actuel = {}
    premier = not actuel
    pages = 40 if (premier or histo) else 2
    nouv = {}
    # 1. annonces datees
    for section in ANNONCES:
        lignes = annonces(section, pages, diag)
        sans = sum(1 for x in lignes if not x["sym"])
        print(f"  {section} : {len(lignes)} annonces ({sans} sans société reconnue)")
        for x in lignes:
            sym = x.pop("sym")
            if ajouter(actuel, sym, x, premier, auj):
                nouv[sym] = nouv.get(sym, 0) + 1
    # 2. dividendes officiels
    divs = dividendes(pages if (premier or histo) else 2, diag)
    print(f"  dividendes : {len(divs)} paiements ({sum(1 for x in divs if not x['sym'])} sans société reconnue)")
    for d in divs:
        sym = d.pop("sym")
        titre = f"Dividende {('exercice ' + d['exercice']) if d.get('exercice') else ''} : {fr_nb(d['dividende'])} FCFA net par action".replace("  ", " ")
        item = {"date": d["ex_dividende"] or d["paiement"], "titre": titre, "url": "", "type": "dividende", **{k: v for k, v in d.items() if k != "emetteur"}}
        if ajouter(actuel, sym, item, premier, auj):
            nouv[sym] = nouv.get(sym, 0) + 1
    # 3. rapports de resultats (pages « rapports » de chaque societe, date tiree du nom du fichier)
    pages_soc, _ = B.pages_societes()
    for sym, urls in sorted(pages_soc.items()):
        for u in urls:
            try:
                pubs = B.publications_societe(u, pages=8)
            except Exception:
                continue
            for p in pubs:
                d = date_dossier(p["url"]) or date_de(p["titre"])
                if not d or d < "2014-01-01":
                    continue
                if ajouter(actuel, sym, {"date": d, "titre": p["titre"], "url": p["url"], "type": type_de(p["titre"])}, premier, auj):
                    nouv[sym] = nouv.get(sym, 0) + 1
    # 4. lecture des documents recents (resultats : phrase sur le resultat net ; communiques : resume)
    limite = (auj - dt.timedelta(days=120)).isoformat()
    lus = 0
    for sym, liste in actuel.items():
        if sym.startswith("_"):
            continue
        liste.sort(key=lambda x: (x.get("date") or "0000", x["titre"]), reverse=True)
        for x in liste[:12]:
            if x.get("date", "") < limite or x.get("lu") or not x.get("url") or x["type"] not in ("resultats", "dividende", "autre", "capital", "suspension") or lus >= 80:
                continue
            try:
                t = texte(x["url"])
                ph, sens = lire_resultats(t)
                if ph:
                    x["detail"], x["sens"] = ph, sens
                lus += 1
            except Exception as e:
                print(f"    {sym} : lecture impossible ({e.__class__.__name__}) {x['titre'][:60]}")
            x["lu"] = True
        if diag:
            for x in liste[:3]:
                print(f"    {sym:<6} {x.get('date')} {x['type']:<10} {x['titre'][:70]} {('| ' + x['detail'][:80]) if x.get('detail') else ''}")
    actuel["_info"] = {"version": 2, "maj": auj.isoformat(), "documents_lus": lus}
    SORTIE.write_text(json.dumps(actuel, ensure_ascii=False, indent=0))
    print(f"Actualite : {len(actuel) - 1} societes, {sum(nouv.values())} nouvelle(s) publication(s), {lus} document(s) lu(s)")


def fr_nb(v):
    return (f"{v:,.4f}".rstrip("0").rstrip(".") if v % 1 else f"{v:,.0f}").replace(",", " ").replace(".", ",")


if __name__ == "__main__":
    main()
