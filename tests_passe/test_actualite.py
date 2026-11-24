"""Test n°8 : l'actualite des dividendes (tableau officiel BRVM) ameliore-t-elle la note ?
Signal connu a la date t0 : dernier dividende paye (ex-dividende <= t0) compare au precedent."""
import json, io, contextlib, statistics as st
import variantes_bilans as V
TC, S = V.TC, V.S
A = json.load(open('actualite.json'))
OPS = json.load(open('/home/claude/brvm-depot/donnees/operations_capital.json'))

def divs(sym, t0):
    l = [x for x in A.get(sym, []) if x['type'] == 'dividende' and x.get('dividende') and (x.get('ex_dividende') or x['date']) <= t0]
    l.sort(key=lambda x: x.get('ex_dividende') or x['date'], reverse=True)
    out = []
    for x in l:
        v = x['dividende']
        for op in OPS.get(sym, []):
            if (x.get('ex_dividende') or x['date']) < op['date']:
                v /= op['ratio']
        out.append((x.get('ex_dividende') or x['date'], v, x.get('exercice') or (x.get('ex_dividende') or x['date'])[:4]))
    vus, uniq = set(), []
    for d in out:  # un seul dividende par exercice (le tableau contient des doublons)
        if d[2] not in vus:
            vus.add(d[2]); uniq.append(d)
    return uniq

def signal(x):
    d = divs(x['s'], x['t0'])
    if len(d) < 2 or d[0][0] < str(int(x['t0'][:4]) - 1) + x['t0'][4:]:
        return None  # pas de dividende recent connu
    return d[0][1] / d[1][1] - 1 if d[1][1] > 0 else None

for x in V.ROWS:
    x['g'] = signal(x)
cas = [x for x in V.ROWS if x['g'] is not None and x['t0'] != TC.T[-1]]
print(f"Cas avec signal : {len(cas)} sur {len([x for x in V.ROWS if x['t0'] != TC.T[-1]])}")
for nom, f in [("dividende en hausse > 10 %", lambda g: g > 0.10), ("stable (±10 %)", lambda g: -0.10 <= g <= 0.10), ("en baisse > 10 %", lambda g: g < -0.10)]:
    r = [x['ret'] for x in cas if f(x['g'])]
    print(f"  {nom:<28} {len(r):>4} cas, rendement médian l'année suivante {st.median(r)*100:+6.1f} %, en perte {sum(v<0 for v in r)/len(r)*100:4.0f} %")

def bonus(b, m):
    return lambda x: x['n20'] + (b if x['g'] is not None and x['g'] > 0.10 else -m if x['g'] is not None and x['g'] < -0.10 else 0)

VAR = {"Référence (dividende + prix)": lambda x: x['n20'], "Bonus +5 / malus -5": bonus(5, 5), "Bonus +10 / malus -10": bonus(10, 10),
       "Malus seul -10 (dividende coupé)": bonus(0, 10), "Bonus seul +10 (dividende en hausse)": bonus(10, 0)}
orig = TC.choisir
print(f"\n{'Façon':<38}" + "".join(f"{n:>9}" for n in (6, 8, 10, 12, 15)) + "   pire chute (10)")
for nom, cle in VAR.items():
    vals, pire10 = [], None
    for n in (6, 8, 10, 12, 15):
        TC.choisir = lambda pool, c, n0=10, n=n: orig(pool, c, n)
        v, _ = TC.run(cle); p, pire = TC.chemin(v); vals.append(p[-1])
        if n == 10: pire10 = pire
    TC.choisir = orig
    print(f"{nom:<38}" + "".join(f"{v:>9.0f}" for v in vals) + f"   {pire10*100:.0f} %")
