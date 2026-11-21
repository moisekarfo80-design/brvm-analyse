"""Tests sans internet : fausse page BRVM -> collecte -> analyse. Lancer : python serveur/test_serveur.py"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import requests

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import analyse  # noqa: E402
import collecte  # noqa: E402

PAGE = """<html><body><table><thead><tr><th>Symbole</th><th>Nom</th><th>Volume</th><th>Cours veille (FCFA)</th>
<th>Cours Ouverture (FCFA)</th><th>Cours Clôture (FCFA)</th><th>Variation (%)</th></tr></thead><tbody>{lignes}
<tr><td>Total</td><td></td><td></td><td></td><td></td><td></td><td></td></tr></tbody></table></body></html>"""


class Reponse:
    def __init__(self, texte):
        self.text, self.encoding, self.apparent_encoding = texte, "utf-8", "utf-8"

    def raise_for_status(self):
        pass


def fausse_page(hausse=1.0, anomalie=None):
    ref = json.loads((collecte.REFERENCE).read_text())
    lignes = []
    for s in ref["actions"]:
        if ref["actions"][s].get("suspendue"):
            continue
        dernier = [l for l in open(collecte.HISTORIQUE) if l.split(";")[1] == s]
        if not dernier:
            continue
        veille = float(dernier[-1].split(";")[2])
        clo = round(veille * hausse)
        var = (clo / veille - 1) * 100
        if s == anomalie:
            var = 25.0
        lignes.append(f"<tr><td>{s}</td><td>{s} SA</td><td>1 250</td><td>{veille:,.0f}</td><td>{veille:,.0f}</td>"
                      f"<td>{clo:,.0f}</td><td>{var:.2f}".replace(",", " ").replace(".", ",") + "</td></tr>")
    return PAGE.format(lignes="".join(lignes))


def verifier(cond, texte):
    print(("  OK   " if cond else "  ECHEC") + " " + texte)
    return cond


def main():
    tmp = Path(tempfile.mkdtemp())
    shutil.copytree(ICI.parent / "donnees", tmp / "donnees")
    (tmp / "docs" / "data").mkdir(parents=True)
    for m in (collecte,):
        m.HISTORIQUE, m.STATUT, m.REFERENCE = tmp / "donnees/historique.csv", tmp / "donnees/statut_collecte.json", tmp / "donnees/reference.json"
    analyse.D, analyse.SORTIE = tmp / "donnees", tmp / "docs/data/resultats.json"
    ok = True
    sys.argv = ["collecte.py", "--forcer"]

    analyse.main()
    per_avant = json.loads(analyse.SORTIE.read_text())["marche"]["per"]
    print("1. Seance normale (+2 %, une ligne anormale)")
    page = fausse_page(1.02, anomalie="SGBC")
    requests.get = lambda *a, **k: Reponse(page)
    collecte.main()
    st = json.loads(collecte.STATUT.read_text())
    ok &= verifier(st["ok"] and st["nb_actions"] >= 40, f"{st['nb_actions']} actions lues, ligne Total ignoree")
    ok &= verifier([c["symbole"] for c in st["a_confirmer"]] == ["SGBC"], "variation de 25 % mise de cote")
    analyse.main()
    r = json.loads(analyse.SORTIE.read_text())
    ok &= verifier(r["date_cours"] == st["date"], "resultats a la date du jour")
    ok &= verifier(any(m["titre"].startswith("1 cours") for m in r["messages"]), "message 'cours a confirmer'")
    ok &= verifier(all(len(r["portefeuilles"][h]) == 10 for h in "lt mt ct".split()), "3 portefeuilles types de 10")
    for h in ("lt", "mt", "ct"):
        top = [a for a in r["actions"] if a["s"] in r["portefeuilles"][h]]
        ok &= verifier(sum(a["secteur"] == "Banques et finance" for a in top) <= 5
                       and max([sum(a.get("groupe") == g for a in top) for g in ("BOA", "Ecobank", "SIFCA")]) <= 3,
                       f"diversification respectee ({h})")
    ok &= verifier(abs(r["marche"]["per"] - per_avant * 1.02) < 0.2, f"PER du marche suit les cours ({r['marche']['per']})")
    ok &= verifier(all(1 <= e <= 5 for a in r["actions"] for e in a.get("etoiles", {}).values()), "etoiles entre 1 et 5")
    ok &= verifier(all(a["fiabilite"][h] <= 59 for a in r["actions"] if a.get("fiabilite") for h in a["fiabilite"]), "fiabilite plafonnee a 59")

    print("2. Le lendemain, meme page (jour ferie)")
    import datetime as dt
    hier = (dt.date.fromisoformat(st["date"]) - dt.timedelta(days=1)).isoformat()
    txt = collecte.HISTORIQUE.read_text().replace(st["date"], hier)
    collecte.HISTORIQUE.write_text(txt)
    collecte.main()
    st = json.loads(collecte.STATUT.read_text())
    ok &= verifier(not st["ok"] and any("pas de seance" in a for a in st["alertes"]), "detecte l'absence de seance")

    print("3. Site injoignable")
    def panne(*a, **k):
        raise requests.ConnectionError("refus")
    requests.get = panne
    collecte.time.sleep = lambda s: None
    collecte.main()
    analyse.main()
    r = json.loads(analyse.SORTIE.read_text())
    ok &= verifier(any(m["titre"] == "Cours du jour non récupérés" for m in r["messages"]), "message clair, rien ne plante")

    print("4. Site qui change de presentation")
    requests.get = lambda *a, **k: Reponse("<html><table><tr><th>A</th></tr><tr><td>1</td></tr></table></html>")
    collecte.main()
    st = json.loads(collecte.STATUT.read_text())
    ok &= verifier(any("non comprise" in a for a in st["alertes"]), "changement de page signale")

    print("5. Anti-clignotement des etoiles")
    e = {"lt": {"X": {"e": 3, "cand": 3, "n": 0}}}
    changements = []
    for i in range(6):
        notes = 67.5  # au-dela de 65 + 2
        brut = analyse.etoiles_brutes(notes)
        p = e["lt"]["X"]
        monte = brut > p["e"] and notes >= analyse.limite_haute(p["e"]) + 2
        cpt = p["n"] + 1 if monte and p["cand"] == brut else (1 if monte else 0)
        if cpt >= 5:
            p.update(e=brut, n=0)
        else:
            p.update(cand=brut if monte else p["e"], n=cpt)
        changements.append(p["e"])
    ok &= verifier(changements == [3, 3, 3, 3, 4, 4], f"passe a 4 etoiles a la 5e seance seulement {changements}")
    print("\nTOUS LES TESTS REUSSIS" if ok else "\nDES TESTS ONT ECHOUE")
    shutil.rmtree(tmp)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
