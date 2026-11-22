"""Compare plusieurs facons d'utiliser les bilans contre la reference (note dividende 20 + prix 25, 620)."""
import io, contextlib, datetime as dt, statistics as st
import test_complet as TC
S, AM, A = TC.S, TC.AM, TC.A

with contextlib.redirect_stdout(io.StringIO()):
    ROWS, _ = S.periodes()
TC.ROWS = ROWS


def infos_bilan(sym, annee):
    """Ce que les bilans deja publies disent : perte recente, effondrement, regularite."""
    h = TC.bilans_connus(sym, annee)
    rns = A.serie_resultats(h) if h else {}
    if not rns:
        return None
    ans = sorted(rns)
    dernier = rns[ans[-1]]
    perte = dernier <= 0
    chute = len(ans) >= 2 and rns[ans[-2]] > 0 and dernier < 0.5 * rns[ans[-2]]
    regul = sum(v > 0 for v in rns.values()) / len(rns)
    return dict(perte=perte, chute=chute, regul=regul, n=len(rns))


for x in ROWS:
    t0 = x['t0']; d0 = dt.date.fromisoformat(t0)
    i = S.DATES.index(t0)
    x['n20'] = AM.note(S.D[t0][x['s']], t0, d0, None)
    annee_pub = int(t0[:4]) if t0[5:7] == '12' else int(t0[:4]) - 1
    x['nc'], _ = TC.note_complete(x)
    sq, sc, _ = TC.notes_bilan(x['s'], annee_pub + 1)
    x['sq'], x['sc'] = sq, sc
    x['ib'] = infos_bilan(x['s'], annee_pub + 1)


def note_poids(x, pq, pc):
    parts = [(20, x['n20_div']), (25, x['n20_valo'])] if False else None
    base = x['n20']
    extra = [(pq, x['sq']), (pc, x['sc'])]
    extra = [(p, v) for p, v in extra if v is not None and p]
    if not extra:
        return base
    return (45 * base + sum(p * v for p, v in extra)) / (45 + sum(p for p, _ in extra))


def filet(x, base, regle):
    ib = x['ib']
    if ib is None:
        return base
    mauvais = (regle >= 1 and ib['perte']) or (regle >= 2 and ib['chute']) or (regle >= 3 and ib['n'] >= 3 and ib['regul'] < 0.75)
    return base - 100 if mauvais else base


VARIANTES = {
    'Reference : dividende + prix (20/25)': lambda x: x['n20'],
    'Bilans poids fort (actuel, 30/20)': lambda x: x['nc'],
    'Bilans poids moyen (15/10)': lambda x: note_poids(x, 15, 10),
    'Bilans poids faible (8/5)': lambda x: note_poids(x, 8, 5),
    'Solidite seule, faible (10/0)': lambda x: note_poids(x, 10, 0),
    'Filet : ecarter les societes en perte': lambda x: filet(x, x['n20'], 1),
    'Filet : perte ou resultat divise par 2': lambda x: filet(x, x['n20'], 2),
    'Filet : + benefices irreguliers': lambda x: filet(x, x['n20'], 3),
    'Filet perte/chute + poids faible (8/5)': lambda x: filet(x, note_poids(x, 8, 5), 2),
}

if __name__ == '__main__':
    T = TC.T
    debut = next(i for i, t in enumerate(T) if sum(x['ib'] is not None for x in ROWS if x['t0'] == t) >= 20)
    print(f"{'Facon':<44}{'Fin':>6}{'Pire':>7}{'2016-21':>9}{f'{S.lab(T[debut])}+':>9}   par annee (%)")
    for nom, cle in VARIANTES.items():
        v, picks = TC.run(cle)
        p, pire = TC.chemin(v)
        a = TC.chemin(v[:6])[0][-1]
        b = TC.chemin(v[debut:])[0][-1]
        print(f"{nom:<44}{p[-1]:>6.0f}{pire*100:>6.0f}%{a:>9.0f}{b:>9.0f}   " + ' '.join(f"{r*100:>4.0f}" for r in v))
    print('\nPeriodes :', ' '.join(S.lab(t) for t in T), ' | debut couverture bilans :', S.lab(T[debut]))
    # cas ecartes par le filet 2 : etaient-ils vraiment mauvais ?
    ec = [x for x in ROWS if x['ib'] and (x['ib']['perte'] or x['ib']['chute'])]
    gard = [x for x in ROWS if x['ib'] and not (x['ib']['perte'] or x['ib']['chute'])]
    print(f"\nActions avec perte ou resultat divise par 2 : {len(ec)} cas, rendement median l'annee suivante {st.median([x['ret'] for x in ec])*100:+.1f} %, en perte {sum(x['ret']<0 for x in ec)/len(ec)*100:.0f} %")
    print(f"Les autres (avec bilan)                   : {len(gard)} cas, rendement median {st.median([x['ret'] for x in gard])*100:+.1f} %, en perte {sum(x['ret']<0 for x in gard)/len(gard)*100:.0f} %")
