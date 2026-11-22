import variantes_bilans as V, statistics as st
TC=V.TC
ref=lambda x:x['n20']; fil=lambda x:V.filet(x,x['n20'],1)
for n in (6,8,10,12,15):
    def run(cle):
        TC_choisir=TC.choisir
        TC.choisir=lambda pool,c,n0=10: TC_choisir(pool,c,n)
        v,_=TC.run(cle); TC.choisir=TC_choisir; return TC.chemin(v)
    a,pa=run(ref); b,pb=run(fil)
    print(f"{n:>2} actions : reference {a[-1]:5.0f} ({pa*100:.0f} %)   filet perte {b[-1]:5.0f} ({pb*100:.0f} %)")
p=[x for x in V.ROWS if x['ib'] and x['ib']['perte']]
print(f"Societes en perte au dernier bilan : {len(p)} cas, mediane {st.median([x['ret'] for x in p])*100:+.1f} %, en perte {sum(x['ret']<0 for x in p)/len(p)*100:.0f} %")
