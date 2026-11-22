"""Test 2016-2026 des ameliorations : regularite du dividende, diversification, meteo de la bourse."""
import os, sys, math, datetime as dt
os.environ['LONG'] = '1'
sys.path.insert(0, '/home/claude/backtest')
import simulation as S

GROUPE = {**{s: 'BOA' for s in ('BOAB', 'BOABF', 'BOAC', 'BOAM', 'BOAN', 'BOAS')},
          'ECOC': 'Ecobank', 'ETIT': 'Ecobank', 'SNTS': 'Sonatel', 'ORAC': 'Sonatel',
          'PALC': 'SIFCA', 'SPHC': 'SIFCA', 'STBC': 'SITAB', 'TTLC': 'Total', 'TTLS': 'Total',
          'CIEC': 'Eranove', 'SDCC': 'Eranove', 'BICC': 'BNP', 'BICB': 'BIIC', 'CBIBF': 'Coris'}
FINANCE = {'BOAB', 'BOABF', 'BOAC', 'BOAM', 'BOAN', 'BOAS', 'ECOC', 'ETIT', 'SGBC', 'SIBC', 'NSBC', 'CBIBF',
           'BICC', 'BICB', 'ORGT', 'SAFC', 'LNBB'}
def secteur(s): return 'Finance' if s in FINANCE else 'Autres-' + s   # seul le secteur bancaire est assez grand pour peser

POIDS_DIV, POIDS_VALO = 20, 25   # nouveaux poids long terme (dividende 20, valorisation 25)
TAUX_RESERVE = 0.055             # placement de la reserve (obligations d'Etat UEMOA ~5,5-6,5 %/an)

def note(r, t0, d0, regulier):
    ref = S.SNAP[t0]
    frais = r['date'] is not None and (d0 - r['date']).days <= 430
    rdt = (r['div'] / r['cours']) if (frais and r['div'] and r['cours']) else 0.0
    per = r['per'] if (r['per'] and 0 < r['per'] < 60) else None
    payout = rdt * per if per else None
    dur = 1.0 if payout is None or payout <= 0.8 else 0.8 if payout <= 1.0 else 0.5
    if rdt > 2.5 * ref['rdt'] / 100: dur = min(dur, 0.5)
    if regulier is not None and not regulier: dur *= 0.6
    s_div = S.lin(rdt, 0.5 * ref['rdt'] / 100, 1.5 * ref['rdt'] / 100) * dur
    s_valo = S.lin(-per, -1.6 * ref['per'], -0.6 * ref['per']) if per else 0.0
    return (POIDS_DIV * s_div + POIDS_VALO * s_valo) / (POIDS_DIV + POIDS_VALO)

def regularite(s, i):
    """Dividende verse aussi l'annee d'avant (bulletin precedent) et pas divise par plus de 2."""
    if i == 0: return None
    p = S.D[S.DATES[i - 1]].get(s); c = S.D[S.DATES[i]].get(s)
    if not p or not c or not c['date']: return False
    d_prev = dt.date.fromisoformat(S.DATES[i - 1])
    if not (p['date'] and (d_prev - p['date']).days <= 430 and p['div']): return False
    if p['cours'] and c['cours'] and 0.55 <= c['cours'] / p['cours'] <= 4 and c['div'] < 0.5 * p['div']: return False
    return True

def meteo(t0):
    per = S.SNAP[t0]['per']
    return ('☀️', 1.0) if per <= 12.5 else ('🌧️', 0.5) if per >= 18 else ('🌥️', 0.8)

def choisir(pool, regul, divers, n=10):
    i = S.DATES.index(pool[0]['t0']); d0 = dt.date.fromisoformat(pool[0]['t0'])
    sc = {x['s']: note(S.D[x['t0']][x['s']], x['t0'], d0, regularite(x['s'], i) if regul else None) for x in pool}
    top, g, sct = [], {}, {}
    for x in sorted(pool, key=lambda x: sc[x['s']], reverse=True):
        if divers:
            gg = GROUPE.get(x['s']); ss = secteur(x['s'])
            if gg and g.get(gg, 0) >= 3: continue
            if sct.get(ss, 0) >= 5: continue
            if gg: g[gg] = g.get(gg, 0) + 1
            sct[ss] = sct.get(ss, 0) + 1
        top.append(x)
        if len(top) == n: break
    return top

rows, _ = S.periodes()
T = S.DATES[:-1]
ew = [S.moy([x['ret'] for x in rows if x['t0'] == t]) for t in T]

def run(regul=False, divers=False, met=False):
    out, picks = [], []
    for t0 in T:
        pool = [x for x in rows if x['t0'] == t0]
        top = choisir(pool, regul, divers)
        r = S.moy([x['ret'] for x in top])
        if met:
            m, part = meteo(t0)
            i = S.DATES.index(t0)
            jours = (dt.date.fromisoformat(S.DATES[i + 1]) - dt.date.fromisoformat(t0)).days
            r = part * r + (1 - part) * ((1 + TAUX_RESERVE) ** (jours / 365) - 1)
        out.append(r); picks.append([x['s'] for x in top])
    return out, picks

def resume(nom, v):
    x = 100; path = [100]
    for r in v: x *= 1 + r; path.append(x)
    pic, pire = 100, 0
    for p in path: pic = max(pic, p); pire = min(pire, p / pic - 1)
    bat = sum(1 for a, b in zip(v, ew) if a >= b - 1e-9)
    print(f"{nom:<44}{path[5]:>7.0f}{path[-1]:>8.0f}{pire*100:>9.0f} %{bat:>6}/{len(v)}   " + ' '.join(f"{r*100:+5.0f}" for r in v))
    return path

if __name__ == '__main__':
    print('Années :', ' '.join(S.lab(t) for t in T))
    print('Météo  :', ' '.join(f"{S.lab(t)}:{meteo(t)[0]}(PER {S.SNAP[t]['per']})" for t in T))
    print(f"\n{'Version':<44}{'2020':>7}{'2026':>8}{'Pire chute':>11}{'≥ marché':>9}   rendements annuels %")
    res = {}
    res['A'] = resume('A. Méthode actuelle (poids 20/25)', run()[0])
    res['B'] = resume('B. A + régularité du dividende', run(regul=True)[0])
    res['C'] = resume('C. B + diversification (3/groupe, 5 banques)', run(True, True)[0])
    res['D'] = resume('D. C + météo de la bourse', run(True, True, True)[0])
    res['M'] = resume('Moyenne du marché', ew)
    v_old = []
    for t0 in T:
        pool = [x for x in rows if x['t0'] == t0]
        v_old.append(S.moy([x['ret'] for x in sorted(pool, key=lambda x: x['note'], reverse=True)[:10]]))
    resume('Ancienne méthode (poids 25/20)', v_old)
    # concentration
    for nom, (rg, dv) in {'A': (False, False), 'C': (True, True)}.items():
        _, pk = run(rg, dv)
        mx = max(sum(1 for s in p if GROUPE.get(s) == 'BOA') for p in pk)
        bq = max(sum(1 for s in p if s in FINANCE) for p in pk)
        print(f"Version {nom} : jusqu'à {mx} BOA et {bq} banques dans un même portefeuille")
    # robustesse de la meteo : seuils decales
    print('\nMétéo, sensibilité aux seuils (soleil ≤ / pluie ≥) :')
    base = run(True, True)[0]
    for lo, hi in [(11, 16), (12.5, 18), (14, 20)]:
        v = []
        for t0, r in zip(T, base):
            per = S.SNAP[t0]['per']; part = 1.0 if per <= lo else 0.5 if per >= hi else 0.8
            i = S.DATES.index(t0); j = (dt.date.fromisoformat(S.DATES[i + 1]) - dt.date.fromisoformat(t0)).days
            v.append(part * r + (1 - part) * ((1 + TAUX_RESERVE) ** (j / 365) - 1))
        resume(f'   seuils {lo}/{hi}', v)
    print('\nPortefeuilles version D :')
    for t0, p in zip(T, run(True, True, True)[1]): print(f"   {S.lab(t0)} {meteo(t0)[0]} : {', '.join(p)}")
