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


def main():
    seuls = [a for a in sys.argv[1:] if re.fullmatch(r"[A-Z]{3,6}", a)]
    diag = "--diag" in sys.argv
    auj = dt.date.today()
    actuel = json.loads(SORTIE.read_text()) if SORTIE.exists() else {}
    premier = not actuel
    pages, _ = B.pages_societes()
    nb_nouv = 0
    for sym, urls in sorted(pages.items()):
        if seuls and sym not in seuls:
            continue
        connus = {x["url"]: x for x in actuel.get(sym, [])}
        liste = []
        for u in urls:
            try:
                liste += publications(u, diag=diag and sym == sorted(pages)[0])
            except Exception as e:
                print(f"  {sym} : erreur {e.__class__.__name__}")
        nouv = 0
        for p in liste:
            ancien = connus.get(p["url"])
            item = ancien or {"titre": p["titre"], "url": p["url"], "type": type_de(p["titre"]),
                              "vu_le": "initial" if premier else auj.isoformat()}
            item["date"] = p["date"] or p["date_titre"] or (ancien or {}).get("date")
            if not ancien:
                nouv += 1
            ref = item["date"] or (item["vu_le"] if item["vu_le"] != "initial" else None)
            recent = bool(ref) and ref >= (auj - dt.timedelta(days=400)).isoformat()
            if recent and item["type"] in ("dividende", "resultats") and "lu" not in item:
                try:
                    t = texte(item["url"])
                    if item["type"] == "dividende":
                        mt, pay = lire_dividende(t)
                        if mt:
                            item["dividende"], item["paiement"] = mt, pay
                    else:
                        ph, sens = lire_resultats(t)
                        if ph:
                            item["detail"], item["sens"] = ph, sens
                    item["lu"] = True
                except Exception as e:
                    print(f"    {sym} : lecture impossible ({e.__class__.__name__}) {item['titre'][:60]}")
            connus[p["url"]] = item
        tous = sorted(connus.values(), key=lambda x: (x.get("date") or "0000", x["titre"]), reverse=True)
        actuel[sym] = tous[:40]
        nb_nouv += nouv
        d0 = tous[0] if tous else None
        print(f"  {sym:<6} {len(liste):>3} publications, {nouv} nouvelle(s)" + (f" | derniere : {d0.get('date')} {d0['type']} : {d0['titre'][:70]}" if d0 else ""))
        for x in tous[:6]:
            if diag and (x.get("detail") or x.get("dividende")):
                print(f"      {x.get('date')} {x['type']} : {x.get('dividende') or ''} {x.get('paiement') or ''} {x.get('detail') or ''}"[:200])
        SORTIE.write_text(json.dumps(actuel, ensure_ascii=False, indent=1))
    sans_date = sum(1 for v in actuel.values() for x in v if not x.get("date"))
    print(f"Actualite : {len(actuel)} societes, {nb_nouv} nouvelle(s) publication(s), {sans_date} sans date")


if __name__ == "__main__":
    main()
