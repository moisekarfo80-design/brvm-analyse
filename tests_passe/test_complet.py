"""Test sur 10 ans de la methode COMPLETE de l'application (dividende, prix, solidite, croissance, regularite),
sans tricher : a chaque date, seuls les bilans deja publies sont utilises (exercice <= annee - 1).
Portefeuille de 10 actions, 3 par groupe et 5 banques au plus, meteo de la bourse, frais SA2IF."""
import os, sys, json, math, statistics as st, datetime as dt
os.environ['LONG'] = '1'
sys.path.insert(0, '/home/claude/backtest')
sys.path.insert(0, '/home/claude/brvm-depot/serveur')
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    import simulation as S
    import ameliorations as AM
import analyse as A

B = json.load(open('/home/claude/brvm-depot/donnees/bilans.json'))
HIST = B.get('historique', {})
T = S.DATES[:-1]
FRAIS = 0.01 * 1.18 + 0.003      # par ordre (courtage SA2IF 1 % HT + TVA + BRVM)
GARDE = 0.0059                   # conservation par an
POIDS = {'div': 20, 'valo': 25, 'qual': 30, 'croi': 20}


def bilans_connus(sym, annee_decision):
    """Bilans valides deja publies a la date de decision (exercice <= annee - 1)."""
    h = HIST.get(sym, {})
    return {a: b for a, b in h.items() if b.get('statut') == 'valide' and int(a) <= annee_decision - 1}


def notes_bilan(sym, annee):
    h = bilans_connus(sym, annee)
    if not h:
        return None, None, 0
    dernier = h[max(h, key=int)]
    r = dernier.get('ratios', {})
    comp = []
    if dernier.get('banque'):
        if 'roe' in r: comp.append(A.lin(r['roe'], 0.05, 0.22))
        if 'coef_exploitation' in r: comp.append(A.lin(-r['coef_exploitation'], -0.75, -0.40))
        if 'cout_risque_pnb' in r: comp.append(A.lin(-r['cout_risque_pnb'], -0.35, 0.0))
    else:
        if 'roe' in r: comp.append(A.lin(r['roe'], 0.0, 0.25))
        if 'marge' in r: comp.append(A.lin(r['marge'], 0.0, 0.15))
        if 'dette_cp' in r: comp.append(A.lin(-r['dette_cp'], -1.5, 0.0))
    rns = A.serie_resultats(h)
    cagr = None
    if len(rns) >= 3:
        comp.append(A.lin(sum(1 for v in rns.values() if v > 0) / len(rns), 0.5, 1.0))
        ans = sorted(rns)
        v0, v1 = rns[ans[0]], rns[ans[-1]]
        if v0 > 0 and v1 > 0:
            cagr = (v1 / v0) ** (1 / (ans[-1] - ans[0])) - 1
    s_qual = st.mean(comp) if len(comp) >= 2 else None
    comp = []
    if 'croissance_resultat' in r: comp.append(A.lin(r['croissance_resultat'], -0.25, 0.25))
    if 'croissance_activite' in r: comp.append(A.lin(r['croissance_activite'], -0.10, 0.15))
    if cagr is not None:
        comp += [A.lin(cagr, -0.10, 0.15)] * 2
    s_croi = st.mean(comp) if comp else None
    return s_qual, s_croi, len(rns)


def note_complete(x):
    t0 = x['t0']; annee = int(t0[:4]) + (1 if t0[5:7] == '12' else 0)   # fin decembre Y -> decision pour Y+1, bilans <= Y
    annee_pub = int(t0[:4]) if t0[5:7] == '12' else int(t0[:4]) - 1     # derniere annee civile ecoulee
    r = S.D[t0][x['s']]; ref = S.SNAP[t0]; d0 = dt.date.fromisoformat(t0)
    frais = r['date'] is not None and (d0 - r['date']).days <= 430
    rdt = (r['div'] / r['cours']) if (frais and r['div'] and r['cours']) else 0.0
    per = r['per'] if (r['per'] and 0 < r['per'] < 60) else None
    payout = rdt * per if per else None
    dur = 1.0 if payout is None or payout <= 0.8 else 0.8 if payout <= 1.0 else 0.5
    if rdt > 2.5 * ref['rdt'] / 100: dur = min(dur, 0.5)
    s_div = A.lin(rdt, 0.5 * ref['rdt'] / 100, 1.5 * ref['rdt'] / 100) * dur
    s_valo = A.lin(-per, -1.6 * ref['per'], -0.6 * ref['per']) if per else 0.0
    s_qual, s_croi, nb_ans = notes_bilan(x['s'], annee_pub + 1)
    parts = [(POIDS['div'], s_div), (POIDS['valo'], s_valo), (POIDS['qual'], s_qual), (POIDS['croi'], s_croi)]
    parts = [(p, v) for p, v in parts if v is not None]
    return sum(p * v for p, v in parts) / sum(p for p, _ in parts), s_qual is not None or s_croi is not None


def choisir(pool, cle, n=10):
    top, g, nf = [], {}, 0
    for x in sorted(pool, key=cle, reverse=True):
        gg = AM.GROUPE.get(x['s'])
        if gg and g.get(gg, 0) >= 3: continue
        if x['s'] in AM.FINANCE and nf >= 5: continue
        if gg: g[gg] = g.get(gg, 0) + 1
        nf += x['s'] in AM.FINANCE
        top.append(x)
        if len(top) == n: break
    return top


def run(cle, meteo=True, frais=True):
    out, picks, prev = [], [], []
    for t0 in T:
        pool = [x for x in ROWS if x['t0'] == t0]
        top = choisir(pool, cle)
        r = S.moy([x['ret'] for x in top])
        s = [x['s'] for x in top]
        i = S.DATES.index(t0)
        jours = (dt.date.fromisoformat(S.DATES[i + 1]) - dt.date.fromisoformat(t0)).days
        if meteo:
            _, part = AM.meteo(t0)
            r = part * r + (1 - part) * ((1 + AM.TAUX_RESERVE) ** (jours / 365) - 1)
        if frais:
            rot = 1.0 if not prev else len(set(s) - set(prev)) / len(s)
            r -= (FRAIS if not prev else 2 * FRAIS * rot) + GARDE * jours / 365
        prev = s
        out.append(r); picks.append(s)
    return out, picks


def chemin(v):
    x, p = 100, [100]
    for r in v: x *= 1 + r; p.append(x)
    pic, pire = 100, 0
    for q in p: pic = max(pic, q); pire = min(pire, q / pic - 1)
    return p, pire


if __name__ == '__main__':
    ROWS, _ = S.periodes()
    notes = {}
    for x in ROWS:
        n, avec = note_complete(x)
        x['nc'], x['avec_bilan'] = n, avec
    print('Couverture des bilans deja publies a chaque date :')
    for t0 in T:
        pool = [x for x in ROWS if x['t0'] == t0]
        print(f"   {S.lab(t0):>6} : {sum(x['avec_bilan'] for x in pool):>2} actions sur {len(pool)} avec un bilan connu")
    ew = [S.moy([x['ret'] for x in ROWS if x['t0'] == t]) for t in T]
    comp = [S.SNAP[S.DATES[i + 1]]['composite'] / S.SNAP[S.DATES[i]]['composite'] - 1 for i in range(len(T))]
    res = {
        'Methode complete (avec bilans), frais': run(lambda x: x['nc'])[0],
        'Methode complete, sans meteo, frais': run(lambda x: x['nc'], meteo=False)[0],
        'Methode simplifiee (dividende+prix), frais': run(lambda x: x['note'])[0],
        'Moyenne du marche (sans frais)': ew,
        'Indice Composite (cours seuls)': comp,
    }
    print(f"\n{'Version':<46}{'2020':>6}{'Fin':>7}{'Pire chute':>11}{'>= marche':>10}   par annee (%)")
    print(' ' * 46 + ' ' * 24 + '   ' + ' '.join(f"{S.lab(t):>5}" for t in T))
    for nom, v in res.items():
        p, pire = chemin(v)
        bat = sum(1 for a, b in zip(v, ew) if a >= b - 1e-9)
        print(f"{nom:<46}{p[5]:>6.0f}{p[-1]:>7.0f}{pire*100:>10.0f}%{bat:>7}/{len(v)}   " + ' '.join(f"{r*100:>5.0f}" for r in v))
    # periode ou les bilans sont vraiment disponibles
    debut = next((i for i, t in enumerate(T) if sum(x['avec_bilan'] for x in ROWS if x['t0'] == t) >= 20), None)
    if debut is not None:
        print(f"\nSur la periode ou au moins 20 actions ont un bilan connu ({S.lab(T[debut])} et apres) :")
        for nom, v in res.items():
            vv = v[debut:]; p, pire = chemin(vv)
            print(f"   {nom:<46} 100 -> {p[-1]:.0f}   pire chute {pire*100:.0f} %")
    print('\nEtoiles (methode complete) et resultat l\'annee suivante :')
    for e in (5, 4, 3, 2, 1):
        xs = [x['ret'] for x in ROWS if S.etoiles(x['nc']) == e]
        if xs: print(f"   {'★'*e:<6}{len(xs):>4} cas  mediane {st.median(xs)*100:+6.1f} %  moyenne {S.moy(xs)*100:+6.1f} %  en perte {sum(v < 0 for v in xs)/len(xs)*100:4.0f} %")
    print('\nPortefeuilles choisis (methode complete) :')
    for t0, p in zip(T, run(lambda x: x['nc'])[1]):
        print(f"   {S.lab(t0):>6} : {', '.join(p)}")
