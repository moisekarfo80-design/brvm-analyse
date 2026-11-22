"""Fourchettes de gains tirees du test 2016-2025 (modele simple : rendement annuel median et ecart observe).
mal / bien = 1 chance sur 5 de faire moins bien / mieux. Frais SA2IF compris pour le portefeuille."""
import json, math, statistics as st, variantes_bilans as V
TC, S = V.TC, V.S
T = TC.T
def modele(rs):
    l = [math.log(1 + r) for r in rs]
    return {"median": round(st.median(rs), 4), "sigma": round(st.pstdev(l), 4), "cas": len(rs),
            "perte": round(sum(r < 0 for r in rs) / len(rs), 2)}
v, _ = TC.run(lambda x: x['n20'])
out = {"source": "Test 2016-2025 de la méthode : 10 actions, météo de la bourse, frais SA2IF",
       "z": 0.84, "portefeuille": modele(v[:-1]), "etoiles": {}}
for nom, es in (("haut", (4, 5)), ("milieu", (2, 3)), ("bas", (1,))):
    m = modele([x['ret'] for x in V.ROWS if S.etoiles(x['n20']) in es and x['t0'] != T[-1]])
    for e in es: out["etoiles"][str(e)] = dict(m, groupe=nom)
p = out["portefeuille"]
for N in (1, 3, 5):
    mu = math.log(1 + p["median"]); s = p["sigma"]
    f = lambda k: 50000 * math.exp(N * mu + k * 0.84 * s * math.sqrt(N))
    print(f"50 000 sur {N} an(s) : mal {f(-1):,.0f}  probable {f(0):,.0f}  bien {f(1):,.0f}")
print(json.dumps(out, ensure_ascii=False))
json.dump(out, open('/home/claude/brvm-depot/donnees/projections.json', 'w'), ensure_ascii=False, indent=1)
