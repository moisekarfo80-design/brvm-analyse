"""Test sur le passe (2021-2025) de la methode simplifiee : dividende + prix, relatifs au marche."""
import sys, math, statistics as st, datetime as dt
sys.path.insert(0, '/home/claude/backtest')
from donnees_boc import SNAP, OPERATIONS_CAPITAL
import os
if os.environ.get('LONG') == '1':
    from donnees_boc_anciens import convertir
    SNAP.update(convertir())

def num(x):
    x = x.strip()
    if x in ('', 'SP', 'NC'): return None
    return float(x)

def parse(snap):
    out = {}
    for line in snap['data'].strip().splitlines():
        s, cours, div, date, rdt, per = (line.split(';') + [''] * 6)[:6]
        out[s] = dict(cours=num(cours), div=num(div), date=dt.date.fromisoformat(date) if date.strip() else None,
                      rdt=num(rdt), per=num(per))
    return out

DATES = sorted(SNAP)
D = {d: parse(SNAP[d]) for d in DATES}
lin = lambda x, a, b: max(0.0, min(100.0, 100 * (x - a) / (b - a)))

def note(r, ref, t):
    """Note simplifiee 0-100 (dividende 25 + prix 20, relatifs au marche)."""
    frais = r['date'] is not None and (t - r['date']).days <= 430      # dividende verse dans les ~14 derniers mois
    rdt = (r['div'] / r['cours']) if (frais and r['div'] and r['cours']) else 0.0
    per = r['per'] if (r['per'] and 0 < r['per'] < 60) else None
    payout = rdt * per if per else None
    dur = 1.0 if payout is None or payout <= 0.8 else 0.8 if payout <= 1.0 else 0.5
    if rdt > 2.5 * ref['rdt'] / 100: dur = min(dur, 0.5)               # rendement anormal : dividende exceptionnel ou cours non ajuste
    s_div = lin(rdt, 0.5 * ref['rdt'] / 100, 1.5 * ref['rdt'] / 100) * dur
    s_valo = lin(-per, -1.6 * ref['per'], -0.6 * ref['per']) if per else 0.0
    return (25 * s_div + 20 * s_valo) / 45, rdt, per

def etoiles(n): return 5 if n >= 80 else 4 if n >= 65 else 3 if n >= 50 else 2 if n >= 35 else 1

def periodes(exclure=True):
    rows = []
    for i in range(len(DATES) - 1):
        t0, t1 = DATES[i], DATES[i + 1]
        a, b = D[t0], D[t1]; d0, d1 = dt.date.fromisoformat(t0), dt.date.fromisoformat(t1)
        ref = SNAP[t0]
        for s, r in a.items():
            if s not in b or r['cours'] is None or b[s]['cours'] is None: continue
            p0, p1 = r['cours'], b[s]['cours']
            dv = b[s]['div'] if (b[s]['date'] and d0 < b[s]['date'] <= d1) else 0.0
            ret = (p1 + dv) / p0 - 1
            prix = p1 / p0 - 1
            flag = None
            if (t0, s) in OPERATIONS_CAPITAL: flag = 'opération sur le capital (BRVM)'
            elif prix < -0.45 or prix > 4.0: flag = 'variation extrême à vérifier'
            n, rdt, per = note(r, ref, d0)
            mom = None; div_prec = None
            if i > 0 and s in D[DATES[i - 1]] and D[DATES[i - 1]][s]['cours']:
                ratio = p0 / D[DATES[i - 1]][s]['cours']
                if 0.55 <= ratio <= 4.0:            # pas de fractionnement probable entre les deux bulletins
                    mom = ratio - 1
                    div_prec = D[DATES[i - 1]][s]['div']
            rows.append(dict(t0=t0, s=s, ret=ret, prix=prix, note=n, et=etoiles(n), rdt=rdt, per=per, mom=mom,
                             flag=flag, div=r['div'], date=r['date'], div_prec=div_prec))
    return [x for x in rows if not (exclure and x['flag'])], [x for x in rows if x['flag']]

def lab(t0):
    i = DATES.index(t0); a, b = dt.date.fromisoformat(t0), dt.date.fromisoformat(DATES[i + 1])
    y = (a + (b - a) / 2).year
    return f"{y}*" if (b - a).days < 300 else str(y)

def moy(xs): return sum(xs) / len(xs) if xs else float('nan')

def strat(rows, cle, n=10, rev=True, filtre=None):
    res = []
    for t0 in DATES[:-1]:
        pool = [x for x in rows if x['t0'] == t0 and (filtre is None or filtre(x))]
        pool = [x for x in pool if cle(x) is not None]
        top = sorted(pool, key=cle, reverse=rev)[:n]
        res.append((t0, moy([x['ret'] for x in top]), [x['s'] for x in top]))
    return res

def cumul(rs): return math.prod(1 + r for r in rs) - 1

if __name__ == '__main__':
    rows, exclus = periodes()
    print(f"Observations : {len(rows)} action-années retenues, {len(exclus)} écartées")
    import collections; print('   par année :', dict(collections.Counter(lab(x['t0']) for x in exclus)))
    for x in exclus[:0]: print(f"   écartée : {x['s']:<6} {lab(x['t0'])}  prix {x['prix']*100:+.0f} %  ({x['flag']})")
    ew = {t0: moy([x['ret'] for x in rows if x['t0'] == t0]) for t0 in DATES[:-1]}
    comp = {DATES[i]: SNAP[DATES[i + 1]]['composite'] / SNAP[DATES[i]]['composite'] - 1 for i in range(len(DATES) - 1)}
    S = {
        'Méthode (note dividende + prix)': strat(rows, lambda x: x['note']),
        'Rendement seul (le plus élevé)': strat(rows, lambda x: x['rdt'] if x['rdt'] > 0 else None),
        'PER seul (le plus bas)': strat(rows, lambda x: -x['per'] if x['per'] else None),
        'Tendance (hausse passée)': strat(rows, lambda x: x['mom']),
        'Pire note (contrôle)': strat(rows, lambda x: x['note'], rev=False),
    }
    print("\nRendement total par année (cours + dividendes), portefeuilles de 10 actions à parts égales :")
    an = [lab(t) for t in DATES[:-1]]
    print(f"{'Stratégie':<34}" + ''.join(f"{a:>8}" for a in an) + f"{'Moy.':>8}{'Cumul':>9}{'Ann. ≥ moy.':>12}")
    def ligne(nom, vals):
        bat = sum(1 for t, v in zip(DATES[:-1], vals) if not math.isnan(v) and v >= ew[t])
        vv = [v for v in vals if not math.isnan(v)]
        print(f"{nom:<34}" + ''.join(f"{v*100:>7.1f}%" if not math.isnan(v) else f"{'—':>8}" for v in vals) + f"{moy(vv)*100:>7.1f}%{cumul(vv)*100:>8.0f}%{bat:>8}/{len(vv)}")
    for nom, res in S.items(): ligne(nom, [r for _, r, _ in res])
    ligne('Moyenne du marché (toutes, égales)', [ew[t] for t in DATES[:-1]])
    print(f"{'Indice BRVM Composite (cours seuls)':<34}" + ''.join(f"{comp[t]*100:>7.1f}%" for t in DATES[:-1]) + f"{moy(list(comp.values()))*100:>7.1f}%{cumul(list(comp.values()))*100:>8.0f}%")

    print("\nRendement moyen l'année suivante selon les étoiles (méthode simplifiée) :")
    for e in (5, 4, 3, 2, 1):
        xs = [x['ret'] for x in rows if x['et'] == e]
        if xs: print(f"   {'★'*e:<6} {len(xs):>3} obs.  moyenne {moy(xs)*100:+6.1f} %  médiane {st.median(xs)*100:+6.1f} %  part en perte {sum(1 for v in xs if v < 0)/len(xs)*100:4.0f} %")

    def rangs(v):
        o = sorted(range(len(v)), key=lambda i: v[i]); r = [0] * len(v)
        for k, i in enumerate(o): r[i] = k
        return r
    print("\nCorrélation de rang note / rendement suivant, par année :")
    for t0 in DATES[:-1]:
        xs = [x for x in rows if x['t0'] == t0]
        a, b = rangs([x['note'] for x in xs]), rangs([x['ret'] for x in xs])
        print(f"   {lab(t0)} : {st.correlation(a, b):+.2f}  ({len(xs)} actions)")

    # calibrage des fourchettes a 1 an (log-normale, volatilite 30 %)
    sig = 0.30; dessous = dessus = 0
    for x in rows:
        mu = math.log(1 + x['rdt']) - sig ** 2 / 2
        lo, hi = math.exp(mu - 1.036 * sig) - 1, math.exp(mu + 1.036 * sig) - 1
        dessous += x['ret'] < lo; dessus += x['ret'] > hi
    print(f"\nFourchettes à 1 an (15e-85e centiles, volatilité 30 %) : {dessous/len(rows)*100:.0f} % des cas sous la fourchette, {dessus/len(rows)*100:.0f} % au-dessus (attendu 15 % / 15 %)")

    # signal d'alerte : dividende en baisse de 25 % ou plus
    al = [x for x in rows if x['div_prec'] and x['div'] and x['date'] and (dt.date.fromisoformat(x['t0']) - x['date']).days <= 430 and x['div'] <= 0.75 * x['div_prec']]
    if al:
        ecart = [x['ret'] - ew[x['t0']] for x in al]
        print(f"\nSignal « dividende en baisse ≥ 25 % » : {len(al)} cas, écart moyen à la moyenne du marché l'année suivante {moy(ecart)*100:+.1f} points ; {sum(1 for e in ecart if e < 0)} sur {len(al)} ont fait moins bien")
        for x in al[:0]: print(f"   {x['s']:<6} {int(x['t0'][:4])+1} : dividende {x['div_prec']} -> {x['div']}, rendement suivant {x['ret']*100:+.0f} % (marché {ew[x['t0']]*100:+.0f} %)")
    # occasion : 4 etoiles ou plus et cours en baisse de 10 % ou plus sur l'annee ecoulee
    oc = [x for x in rows if x['et'] >= 4 and x['mom'] is not None and x['mom'] <= -0.10]
    if oc:
        ecart = [x['ret'] - ew[x['t0']] for x in oc]
        print(f"\nSignal « occasion » (≥ 4 étoiles et cours −10 % ou plus) : {len(oc)} cas, écart moyen {moy(ecart)*100:+.1f} points ; {sum(1 for e in ecart if e > 0)} sur {len(oc)} ont fait mieux que le marché")

    print("\nPortefeuilles choisis par la méthode :")
    for t0, r, top in S['Méthode (note dividende + prix)']: print(f"   {lab(t0)} : {', '.join(top)}  -> {r*100:+.1f} %")

    # sensibilite : sans exclure les cas extremes
    rows_all, _ = periodes(exclure=False)
    m = strat(rows_all, lambda x: x['note']); ew2 = [moy([x['ret'] for x in rows_all if x['t0'] == t]) for t in DATES[:-1]]
    print(f"\nSensibilité, sans écarter les cas extrêmes : méthode {moy([r for _, r, _ in m])*100:.1f} %/an contre marché {moy(ew2)*100:.1f} %/an")
