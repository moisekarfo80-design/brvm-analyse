"use strict";
// BRVM Analyse : application mobile (aide a la decision, pas un conseil d'investissement).
// Tout ce qui est personnel (profil, portefeuille, suivi, lecons) reste sur ce telephone (localStorage).

const FRAIS_DEFAUT = { courtage: 1.0, tva: 18, brvm: 0.3, conservation: 0.5, tenue: 8000, sgi: "SA2IF" };
const TAUX_RESERVE = 0.055;   // reserve placee sans risque (obligations d'Etat UEMOA, environ 5,5 %/an)
const TAUX_OBLIG = 0.065;     // comparaison « tout en obligations d'Etat »
const ONGLETS = [["accueil", "🏠", "Accueil"], ["classement", "🏆", "Classement"], ["investir", "💸", "Investir"], ["portefeuille", "💼", "Portefeuille"], ["apprendre", "🎓", "Apprendre"]];
const METEO = {
  soleil: ["☀️", "Bourse bon marché", "Bon moment pour investir : tu peux placer toute la somme prévue."],
  nuageux: ["🌥️", "Bourse dans la normale", "Investis 80 % de ta somme et garde 20 % en réserve."],
  pluie: ["🌧️", "Bourse chère", "Investis doucement : moitié en actions, moitié en réserve."]
};
const H = { lt: "Long terme", mt: "Moyen terme", ct: "Court terme" };
const MOT = { 5: "Excellente", 4: "Bonne", 3: "Correcte", 2: "Faible", 1: "Très faible" };
const COULEURS = ["#1747C9", "#5B83E8", "#9DB5F2", "#0E1B3D", "#3A5BA8", "#7FA0EE", "#244FB8", "#B8C9F0", "#4C6FD0", "#2A3B66"];
const RESERVE_COUL = "#C9D4EC";

let D = null, ecran = "accueil", horizon = "lt", recherche = "", vuePf = "suivi", filtreMsg = "tous";
let inv = { montant: 50000, duree: 3 }, ficheEtat = { s: null, h: "lt", montant: 50000, duree: 3 }, quiz = null;

// ---------- stockage local
const lire = (k, d) => { try { const v = localStorage.getItem("brvm." + k); return v ? JSON.parse(v) : d; } catch (e) { return d; } };
const ecrire = (k, v) => { try { localStorage.setItem("brvm." + k, JSON.stringify(v)); } catch (e) {} };

// ---------- outils
const fcfa = (x) => x == null || isNaN(x) ? "—" : Math.round(x).toLocaleString("fr-FR").replace(/ | /g, " ") + " FCFA";
const nb = (x, d = 1) => x == null || isNaN(x) ? "—" : x.toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d });
const pc = (x, d = 1) => x == null ? "—" : (x > 0 ? "+" : x < 0 ? "−" : "") + nb(Math.abs(x) * 100, d) + " %";
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const dateFr = (iso) => iso ? new Date(iso.slice(0, 10) + "T12:00:00").toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" }) : "—";
const auj = () => new Date().toISOString().slice(0, 10);
const ajoutMois = (iso, m) => { const d = new Date(iso + "T12:00:00"); d.setMonth(d.getMonth() + m); return d.toISOString().slice(0, 10); };
const ans = (iso) => (Date.now() - new Date(iso + "T12:00:00").getTime()) / (365.25 * 864e5);
const action = (s) => D.actions.find((a) => a.s === s);
const etoiles = (n) => n ? `<span class="etoiles" aria-label="${n} étoiles sur 5">${"★".repeat(n)}<span class="vide">${"★".repeat(5 - n)}</span></span>` : `<span class="gris">non noté</span>`;
const fleche = (v) => v == null ? "" : `<span class="fleche ${v > 0.4 ? "haut" : v < -0.4 ? "bas" : "gris"}">${v > 0.4 ? "▲" : v < -0.4 ? "▼" : "="} ${v > 0 ? "+" : ""}${nb(v, 0)} en 1 mois</span>`;
const barres = (f) => { const n = f >= 80 ? 4 : f >= 60 ? 3 : f >= 35 ? 2 : 1; return `<span class="barres" aria-label="fiabilité ${n} sur 4">${[1, 2, 3, 4].map((i) => `<i class="${i <= n ? "on" : ""}"></i>`).join("")}</span>`; };
const tauxOrdre = () => { const f = lire("frais", FRAIS_DEFAUT); return (f.courtage * (1 + f.tva / 100) + f.brvm) / 100; };
const fraisOrdre = (m) => m * tauxOrdre();
const puces = (liste, actif, attr) => `<div class="puces">${liste.map(([v, l]) => `<button class="puce-choix ${v === actif ? "on" : ""}" data-${attr}="${v}">${l}</button>`).join("")}</div>`;
const FEUX = { vert: "#1F9D55", orange: "#E08A00", rouge: "#C0362C", gris: "#A9B3C7" };
const feu = (a, long) => !a.feu ? "" : long
  ? `<span class="feu f-${a.feu.couleur}"><i></i>${esc(a.feu.mot)}</span>`
  : `<span class="feu f-${a.feu.couleur}" title="Solidité : ${esc(a.feu.mot)}" aria-label="Solidité : ${esc(a.feu.mot)}"><i></i>${esc(a.feu.mot)}</span>`;
const autresDrapeaux = (a) => (a.drapeaux || []).filter((d) => !/^En perte au dernier bilan|^Solvabilité/.test(d));
const fermerBtn = `<button class="fermer" data-fermer aria-label="Fermer">✕</button>`;

// ---------- fourchettes de gains (modele tire du test 2016-2025)
// mal / bien : 1 chance sur 5 de faire moins bien / mieux. Frais d'achat SGI compris.
function fourchette(modele, n, montant, partReserve = 0) {
  if (!modele) return null;
  const z = (D.projections && D.projections.z) || 0.84;
  const mu = Math.log(1 + modele.median), s = modele.sigma;
  const enAct = montant * (1 - partReserve) * (1 - tauxOrdre());
  const res = montant * partReserve * Math.pow(1 + TAUX_RESERVE, n);
  const f = (k) => enAct * Math.exp(n * mu + k * z * s * Math.sqrt(Math.max(n, 0))) + res;
  return { mal: f(-1), probable: f(0), bien: f(1) };
}
const arrondi = (x) => Math.round(x / 500) * 500;

// ---------- profil (quiz)
const QUESTIONS = [
  ["Tu places 50 000 FCFA. Un mois après, ils valent 45 000. Tu fais quoi ?", [["Je vends tout, je ne supporte pas de perdre", 0], ["J'attends que ça remonte", 2], ["J'en rachète, c'est moins cher", 3]]],
  ["Quand pourrais-tu avoir besoin de cet argent ?", [["Dans moins d'un an", 0], ["Dans 1 à 3 ans", 2], ["Pas avant 3 ans ou plus", 3]]],
  ["Tu préfères…", [["Gagner peu, mais presque sûr", 0], ["Un peu plus, avec quelques hauts et bas", 2], ["Viser plus haut, même si ça secoue", 3]]],
  ["As-tu une épargne de côté en cas d'urgence ?", [["Non, pas encore", 0], ["Un peu", 2], ["Oui, plusieurs mois de dépenses", 3]]],
  ["La bourse, pour toi, c'est…", [["Tout nouveau", 1], ["J'ai quelques bases", 2], ["Je suis déjà à l'aise", 3]]]
];
const PROFILS = {
  Prudent: ["🛡️", "Tu préfères la tranquillité. On garde une bonne part de ton argent à l'abri (obligations, épargne) et on investit le reste petit à petit."],
  "Équilibré": ["⚖️", "Tu acceptes quelques hauts et bas pour espérer gagner plus. On suit la météo de la bourse : plus d'actions quand elle est bon marché, plus de réserve quand elle est chère."],
  Dynamique: ["🚀", "Tu vises loin et tu restes calme quand ça secoue. On met un peu plus d'argent en actions, toujours en répartissant le risque."]
};
const profilDe = (score) => score <= 6 ? "Prudent" : score <= 11 ? "Équilibré" : "Dynamique";
function partActions(profil) {
  const m = D.meteo.part_actions;
  return profil === "Prudent" ? m * 0.6 : profil === "Dynamique" ? Math.min(1, m + 0.1) : m;
}

// ---------- plan d'investissement : actions reellement achetables avec la somme
function construirePlan(montant, profil) {
  const part = partActions(profil);
  const enActions = montant * part;
  const taux = tauxOrdre();
  const k = Math.max(2, Math.min(10, Math.floor(enActions / 10000)));
  const parLigne = Math.min(enActions / k, montant * 0.4);   // pas plus de 40 % sur une seule societe
  const lignes = [];
  for (const s of D.portefeuilles.lt) {
    if (lignes.length >= k) break;
    const a = action(s);
    if (!a || !a.cours) continue;
    const qte = Math.floor(parLigne / (a.cours * (1 + taux)));
    if (qte < 1) continue;
    lignes.push({ s, qte, prix: a.cours, cout: qte * a.cours, frais: fraisOrdre(qte * a.cours) });
  }
  const investi = lignes.reduce((t, l) => t + l.cout + l.frais, 0);
  const reserve = montant - investi;
  return { montant, profil, part, lignes, investi, reserve, partReserve: reserve / montant, frais: lignes.reduce((t, l) => t + l.frais, 0) };
}

function anneau(segments) {
  const C = 2 * Math.PI * 60; let acc = 0;
  return `<svg viewBox="0 0 160 160" width="150" height="150" aria-hidden="true" class="anneau"><circle cx="80" cy="80" r="60" fill="none" stroke="#EEF2FA" stroke-width="22"/>${segments.map(([p, c]) => {
    const l = C * p; const el = `<circle cx="80" cy="80" r="60" fill="none" stroke="${c}" stroke-width="22" stroke-dasharray="${l.toFixed(1)} ${(C - l + 0.01).toFixed(1)}" stroke-dashoffset="${(-acc).toFixed(1)}" transform="rotate(-90 80 80)"/>`; acc += l; return el;
  }).join("")}</svg>`;
}

// ---------- suivi « promis ou reel »
function etatSuivi() {
  const plan = lire("plan", null);
  if (!plan || !D) return null;
  const t = Math.max(0, ans(plan.date));
  const divs = lire("dividendes", []).filter((d) => d.date >= plan.date).reduce((s, d) => s + d.montant, 0);
  let valActions = 0, coutActions = 0;
  for (const l of plan.lignes) { const a = action(l.s); valActions += (a && a.cours ? a.cours : l.prix) * l.qte; coutActions += l.prix * l.qte; }
  const reserve = plan.reserve * Math.pow(1 + TAUX_RESERVE, t);
  const valeur = valActions + reserve + divs;
  const z = fourchette(plan.modele, t, plan.montant, plan.partReserve);
  const ratios = Object.entries(plan.coursDepart || {}).map(([s, c]) => { const a = action(s); return a && a.cours && c ? a.cours / c : null; }).filter((x) => x).sort((a, b) => a - b);
  const marche = ratios.length ? ratios[Math.floor(ratios.length / 2)] - 1 : 0;
  const statut = t < 1 / 24 ? "depart" : valeur < z.mal ? "moins" : valeur > z.bien ? "mieux" : "prevu";
  const causes = [
    ["Tout le marché", coutActions * marche / plan.montant],
    ["Tes sociétés", (valActions - coutActions * (1 + marche)) / plan.montant],
    ["Dividendes reçus", divs / plan.montant],
    ["Réserve placée", (reserve - plan.reserve) / plan.montant],
    ["Frais", -plan.frais / plan.montant]
  ];
  const etapes = [[1, "1 mois"], [3, "3 mois"], [6, "6 mois"], [12, "1 an"], [24, "2 ans"], [36, "3 ans"], [60, "5 ans"]]
    .filter(([m]) => m <= Math.max(12, plan.duree * 12)).map(([m, l]) => ({ m, l, date: ajoutMois(plan.date, m), fait: ajoutMois(plan.date, m) <= auj() }));
  // memoire : une valeur par jour pour la courbe
  const h = lire("histoSuivi", []);
  if (!h.length || h[h.length - 1].d !== auj()) { h.push({ d: auj(), v: Math.round(valeur), m: marche }); ecrire("histoSuivi", h.slice(-400)); }
  return { plan, t, valeur, z, marche, statut, causes, etapes, histo: h, gain: valeur / plan.montant - 1 };
}

function courbeSuivi(st) {
  const { plan } = st, W = 320, Hh = 150, n = plan.duree;
  const xmax = Math.max(0.25, Math.min(n, st.t * 2 || 0.25));
  const pts = []; for (let i = 0; i <= 24; i++) pts.push((xmax * i) / 24);
  const zs = pts.map((x) => fourchette(plan.modele, x, plan.montant, plan.partReserve));
  const vals = zs.flatMap((z) => [z.mal, z.bien]).concat(st.histo.map((p) => p.v)).concat([plan.montant]);
  const ymin = Math.min(...vals) * 0.98, ymax = Math.max(...vals) * 1.02;
  const X = (x) => 10 + (x / xmax) * (W - 20), Y = (y) => Hh - 18 - ((y - ymin) / (ymax - ymin)) * (Hh - 30);
  const zone = pts.map((x, i) => `${X(x)},${Y(zs[i].bien)}`).join(" ") + " " + pts.slice().reverse().map((x, i) => `${X(x)},${Y(zs[24 - i].mal)}`).join(" ");
  const mien = st.histo.map((p) => `${X(Math.min(xmax, ans(plan.date) - ans(p.d)))},${Y(p.v)}`).join(" ");
  const marche = st.histo.map((p) => `${X(Math.min(xmax, ans(plan.date) - ans(p.d)))},${Y(plan.montant * (1 + p.m))}`).join(" ");
  const ici = st.histo[st.histo.length - 1];
  const lab = (x) => x < 1 ? Math.round(x * 12) + " mois" : nb(x, x % 1 ? 1 : 0) + " an" + (x >= 2 ? "s" : "");
  return `<svg viewBox="0 0 ${W} ${Hh}" width="100%" role="img" aria-label="Valeur de ton portefeuille comparée à la zone promise">
    <polygon points="${zone}" fill="#E6EDFC"/>
    <line x1="${X(0)}" x2="${X(xmax)}" y1="${Y(plan.montant)}" y2="${Y(plan.montant)}" stroke="#A9B8DA" stroke-dasharray="3 4"/>
    ${st.histo.length > 1 ? `<polyline points="${marche}" fill="none" stroke="#9AA6BF" stroke-width="2" stroke-dasharray="5 4"/>` : ""}
    ${st.histo.length > 1 ? `<polyline points="${mien}" fill="none" stroke="#1747C9" stroke-width="3" stroke-linejoin="round"/>` : ""}
    <circle cx="${X(Math.min(xmax, st.t))}" cy="${Y(ici.v)}" r="6" fill="#1747C9" stroke="#fff" stroke-width="2"/>
    <text x="${X(0)}" y="${Hh - 2}" font-size="10" fill="#55607A">Départ</text>
    <text x="${X(xmax)}" y="${Hh - 2}" font-size="10" fill="#55607A" text-anchor="end">${lab(xmax)}</text>
  </svg>
  <div class="legende"><span><i style="background:#E6EDFC"></i>Zone promise</span><span><i style="background:#1747C9"></i>Ton argent</span><span><i style="background:#9AA6BF"></i>Tout le marché</span></div>`;
}

// ---------- messages (ceux du serveur + ceux calcules sur le telephone)
function tousMessages() {
  const m = D.messages.map((x) => ({ ...x, quand: dateFr(D.maj) }));
  const st = etatSuivi();
  if (st) {
    const faits = st.etapes.filter((e) => e.fait);
    if (faits.length) {
      const e = faits[faits.length - 1];
      m.unshift({ type: "info", titre: `Ton bilan des ${e.l}`, quand: dateFr(e.date), texte: `${pc(st.gain)} depuis le départ : ${({ prevu: "comme prévu", mieux: "mieux que prévu", moins: "moins bien que prévu, garde ton calme : c'est déjà arrivé dans le passé", depart: "c'est le début" })[st.statut]}.`, aller: "portefeuille" });
    }
  }
  for (const p of lire("portefeuille", [])) {
    const a = action(p.s);
    if (a && a.etoiles && a.etoiles.lt <= 2) m.unshift({ type: "alerte", titre: `${a.nom} : note faible`, quand: dateFr(D.maj), texte: `Ton action est à ${a.etoiles.lt}★ en long terme. Pas de panique : regarde la fiche et décide au bilan annuel.`, fiche: a.s });
  }
  const mois = auj().slice(0, 7);
  if (+auj().slice(8) >= 5 && !lire("mois", []).includes(mois)) m.unshift({ type: "faire", titre: "Investissement du mois", quand: "Ce mois-ci", texte: "Tu n'as pas encore investi ce mois-ci. Va dans Investir pour voir quoi acheter.", aller: "investir" });
  if (!lire("profil", null)) m.unshift({ type: "faire", titre: "Fais le quiz de profil", quand: "1 minute", texte: "5 questions pour adapter la part d'actions et de réserve à ta situation.", quiz: true });
  return m;
}
const cleMsg = (m) => m.titre + "|" + m.texte;

// ---------- chargement
async function charger() {
  try {
    const r = await fetch("data/resultats.json?t=" + Date.now(), { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    D = await r.json(); ecrire("cache", D);
    document.getElementById("hors").hidden = true;
  } catch (e) {
    D = lire("cache", null);
    document.getElementById("hors").hidden = !D;
  }
  if (!D) { document.getElementById("ecran").innerHTML = `<div class="carte vide-etat">Impossible de charger les données. Vérifie ta connexion puis rouvre l'application.</div>`; return; }
  document.getElementById("sousTitre").textContent = "Cours du " + dateFr(D.date_cours);
  majPastille();
  rendre();
}
function majPastille() {
  const vus = lire("vus", []);
  const n = tousMessages().filter((m) => !vus.includes(cleMsg(m))).length;
  const p = document.getElementById("pastille"); p.hidden = !n; p.textContent = n;
}

// ---------- ecrans
function rendre() {
  document.getElementById("nav").innerHTML = ONGLETS.map(([id, ic, nom]) => `<button class="${ecran === id ? "on" : ""}" data-onglet="${id}" aria-label="${nom}"><span>${ic}</span>${nom}</button>`).join("");
  document.getElementById("ecran").innerHTML = ({ accueil, classement, investir, portefeuille, apprendre })[ecran]();
  animerCompteurs();
}
function animerCompteurs() {
  document.querySelectorAll(".compteur[data-cible]").forEach((el) => {
    const cible = +el.dataset.cible, plan = lire("plan", null), depart = plan ? plan.montant : cible, t0 = performance.now();
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const pas = (t) => { const k = Math.min(1, (t - t0) / 1200), e = 1 - Math.pow(1 - k, 3); el.textContent = fcfa(depart + (cible - depart) * e); if (k < 1) requestAnimationFrame(pas); };
    requestAnimationFrame(pas);
  });
}

function ligneAction(a, i, h) {
  const n = a.notes ? a.notes[h] : null;
  return `<button class="action" data-fiche="${a.s}">
    ${i ? `<span class="rang">${i}</span>` : ""}
    <span class="info"><span class="nom">${esc(a.nom)}</span><div class="gris">${fcfa(a.cours)} · ${esc(a.secteur)}</div>${feu(a)}${autresDrapeaux(a)[0] ? ` <span class="puce">⚠ ${esc(autresDrapeaux(a)[0])}</span>` : ""}</span>
    <span style="text-align:right">${etoiles(a.etoiles && a.etoiles[h])}<div class="note">${n == null ? "—" : nb(n, 0)}<span class="gris">/100</span></div>${fleche(a.fleches && a.fleches[h])}</span>
  </button>`;
}

function accueil() {
  const m = METEO[D.meteo.code];
  const top = D.portefeuilles.lt.slice(0, 3).map(action);
  const alerte = D.messages.find((x) => x.type !== "info");
  const profil = lire("profil", null);
  const st = etatSuivi();
  const carte = CARTES[jourIndex() % CARTES.length];
  return `
  <div class="carte meteo">
    <div class="ligne"><span class="gros">${m[0]}</span><div><h2 style="margin:0">${m[1]}</h2><div class="gris">PER moyen ${nb(D.marche.per)} · rendement ${nb(D.marche.rendement)} %</div></div></div>
    <p style="margin:12px 0 0">${m[2]}</p>
  </div>
  ${!profil ? `<button class="carte appel" data-quiz><span style="font-size:30px">🧭</span><span><b>Quel investisseur es-tu ?</b><div class="gris">5 questions, 1 minute. L'application s'adapte à ta réponse.</div></span><span class="chev">›</span></button>` : ""}
  ${st ? `<button class="carte appel" data-onglet="portefeuille"><span style="font-size:30px">${({ prevu: "✅", mieux: "🌟", moins: "🧘", depart: "🌱" })[st.statut]}</span><span><b>Mon suivi : ${fcfa(st.valeur)}</b><div class="gris">${pc(st.gain)} depuis le ${dateFr(st.plan.date)} · ${({ prevu: "comme prévu", mieux: "mieux que prévu", moins: "moins bien que prévu", depart: "c'est le début" })[st.statut]}</div></span><span class="chev">›</span></button>` : ""}
  <div class="carte">
    <div class="ligne entre"><h3 style="margin:0">Fiabilité de l'analyse</h3>${barres(D.fiabilite)}</div>
    <div class="gris" style="margin-top:6px">${D.fiabilite} % · mise à jour le ${dateFr(D.maj)}.</div>
    ${alerte ? `<div class="puce" style="margin-top:10px">⚠ ${esc(alerte.titre)}</div>` : ""}
  </div>
  <div class="carte">
    <div class="ligne entre"><h2 style="margin:0">Top long terme</h2><button class="bouton second petit" data-onglet="classement">Tout voir</button></div>
    ${top.map((a, i) => ligneAction(a, i + 1, "lt")).join("")}
  </div>
  <button class="carte appel" data-onglet="apprendre"><span style="font-size:30px">💡</span><span><b>Carte du jour</b><div class="gris">${esc(carte[0])}</div></span><span class="chev">›</span></button>`;
}

function classement() {
  const hz = D.horizons[horizon];
  const q = recherche.trim().toLowerCase();
  const liste = D.classements[horizon].map(action).filter((a) => !q || a.nom.toLowerCase().includes(q) || a.s.toLowerCase().includes(q));
  const exclues = D.actions.filter((a) => !D.classements[horizon].includes(a.s));
  return `
  <div class="seg" role="tablist">${Object.keys(H).map((h) => `<button role="tab" class="${h === horizon ? "on" : ""}" data-horizon="${h}">${H[h]}</button>`).join("")}</div>
  <div class="carte">
    <div class="gris">${esc(hz.duree)} · la note compte le dividende et le prix${horizon === "ct" ? ", plus la tendance du cours" : ""}, comparés à toute la bourse. Les bilans sont expliqués dans chaque fiche, mais ne changent pas la note (test sur 10 ans).</div>
    <div class="gris" style="margin-top:8px">Feu de solidité (d'après les bilans) : <span class="feu f-vert"><i></i>Solide</span> <span class="feu f-orange"><i></i>Moyenne</span> <span class="feu f-rouge"><i></i>Fragile</span></div>
    ${horizon === "ct" ? `<div class="puce" style="margin-top:8px">⚠ Le court terme suit la hausse récente : c'est le plus risqué.</div>` : ""}
  </div>
  <div class="champ"><input id="cherche" type="search" placeholder="Chercher une action (ex. Sonatel)" value="${esc(recherche)}" aria-label="Chercher une action"></div>
  <div class="carte" style="padding:4px 12px">${liste.map((a) => ligneAction(a, D.classements[horizon].indexOf(a.s) + 1, horizon)).join("") || `<div class="vide-etat">Aucune action trouvée.</div>`}</div>
  ${exclues.length && !q ? `<div class="gris" style="padding:0 4px 8px">Non classées : ${exclues.map((a) => esc(a.nom) + " (" + esc((a.drapeaux || ["données manquantes"])[0]) + ")").join(", ")}.</div>` : ""}`;
}

// ---------- fiche d'une action
const CRITERES = [["qual", "Solidité"], ["div", "Dividende"], ["valo", "Prix"], ["croi", "Croissance"], ["tend", "Tendance du cours"], ["actu", "Actualité"]];
function poidsCritere(c, h) {
  if (c === "div") return 20;
  if (c === "valo") return h === "lt" ? 25 : h === "mt" ? 30 : 15;
  if (c === "tend") return h === "ct" ? 20 : 0;
  return 0;
}
function resume(a, h) {
  const e = a.etoiles && a.etoiles[h];
  const plus = (a.raisons || []).filter((r) => r[0] === "plus").map((r) => r[1]);
  const moins = (a.raisons || []).filter((r) => r[0] === "moins" || r[0] === "attention").map((r) => r[1]);
  return `${a.nom}. Note ${H[h].toLowerCase()} : ${e ? MOT[e].toLowerCase() + ", " + e + " étoiles sur 5" : "non notée"}. `
    + (plus.length ? "Points forts : " + plus.slice(0, 3).join(". ") + ". " : "")
    + (moins.length ? "Points faibles : " + moins.slice(0, 3).join(". ") + ". " : "")
    + "C'est une aide à la décision, pas un conseil.";
}
function fiche(s) {
  if (s && ficheEtat.s !== s) ficheEtat = { ...ficheEtat, s, h: horizon };
  const a = action(ficheEtat.s), h = ficheEtat.h;
  const mes = lire("portefeuille", []).find((p) => p.s === a.s);
  const e = a.etoiles && a.etoiles[h];
  const crit = a.criteres || {};
  const bars = CRITERES.map(([c, nom], i) => {
    const v = crit[c], p = poidsCritere(c, h);
    const coul = v == null ? "#E8EDF7" : v >= 65 ? "#1747C9" : v >= 45 ? "#7E95D6" : "#B9C4DE";
    const etiquette = v == null ? (c === "actu" ? "pas encore suivie" : "pas de donnée") : p ? `compte ${p} pts` : c === "tend" ? "compte au court terme" : "pour info";
    return `<div class="critere"><div class="ligne entre"><span>${nom}</span><span class="gris">${v == null ? "—" : v + "/100"} · ${etiquette}</span></div><div class="jauge"><span style="width:${v || 0}%;background:${coul};animation-delay:${(0.1 + i * 0.07).toFixed(2)}s"></span></div></div>`;
  }).join("");
  const mod = D.projections && e ? D.projections.etoiles[String(e)] : null;
  const f = mod ? fourchette(mod, ficheEtat.duree, ficheEtat.montant) : null;
  const parleOk = "speechSynthesis" in window;
  ouvrir(`
    <div class="ligne entre" style="margin-bottom:12px"><div><h2 style="margin:0">${esc(a.nom)}</h2><div class="gris">${esc(a.s)} · ${esc(a.secteur)} · ${esc(a.pays)}</div></div>${fermerBtn}</div>
    <div class="seg">${Object.keys(H).map((x) => `<button class="${x === h ? "on" : ""}" data-fhorizon="${x}">${H[x]}</button>`).join("")}</div>
    <div class="carte" style="text-align:center">
      ${a.notes && a.notes[h] != null ? `<div class="grandes-etoiles" aria-label="${e} étoiles sur 5">${[0, 1, 2, 3, 4].map((i) => `<span style="animation-delay:${(0.1 + i * 0.08).toFixed(2)}s">${i < e ? "★" : "☆"}</span>`).join("")}</div>
      <div style="font-size:20px;font-weight:800;margin-top:4px">${MOT[e]}</div><div class="gris">${nb(a.notes[h], 0)}/100 · fiabilité ${a.fiabilite[h]} % ${barres(a.fiabilite[h])}</div>` : `<div class="gris">Pas de note pour l'instant.</div>`}
      ${parleOk ? `<button class="bouton second" style="margin-top:12px" data-ecouter>🔊 Écouter l'explication</button>` : ""}
    </div>
    <div class="carte"><div class="ligne entre"><span style="font-size:26px;font-weight:700">${fcfa(a.cours)}</span>${a.var_jour != null ? `<span class="fleche ${a.var_jour >= 0 ? "haut" : "bas"}">${a.var_jour >= 0 ? "▲ +" : "▼ "}${nb(a.var_jour, 2)} % aujourd'hui</span>` : ""}</div>
      <div class="grille3" style="margin-top:12px"><button class="case" data-mot="dividende"><div class="gris">Rendement ⓘ</div><div class="val">${a.rendement != null ? nb(a.rendement) + " %" : "—"}</div></button><button class="case" data-mot="per"><div class="gris">PER ⓘ</div><div class="val">${a.per != null ? nb(a.per) : "—"}</div></button><div class="case"><div class="gris">Sur 1 an</div><div class="val">${a.tendance != null ? (a.tendance > 0 ? "+" : "") + nb(a.tendance, 0) + " %" : "—"}</div></div></div>
    </div>
    ${a.feu ? `<div class="carte"><div class="ligne entre"><h3 style="margin:0">Solidité de l'entreprise</h3>${feu(a, true)}</div>
      <div class="gris" style="margin-top:6px">${a.feu.couleur === "gris" ? "Pas assez de chiffres dans ses bilans pour juger." : "D'après ses bilans : " + esc(a.feu.pourquoi) + "."}</div>
      ${a.solvabilite ? jaugeSolva(a.solvabilite) : a.secteur === "Banques et finance" ? `<div class="gris" style="margin-top:8px">Solvabilité : pas encore trouvée dans ses rapports.</div>` : ""}
      <div class="gris" style="margin-top:8px">Le feu ne change pas la note : il t'aide à éviter une société fragile.</div></div>` : ""}
    <div class="carte"><h3>Pourquoi cette note ?</h3>${bars}
      <div class="gris" style="margin-top:8px">« Compte » : le critère entre dans la note. « Pour info » : tiré des bilans, montré pour t'aider à juger, mais sans effet sur la note.</div></div>
    ${f ? `<div class="carte"><h3>Si je mets…</h3>
      ${puces([[25000, "25 000"], [50000, "50 000"], [100000, "100 000"]], ficheEtat.montant, "fmontant")}
      ${puces([[1, "1 an"], [3, "3 ans"], [5, "5 ans"]], ficheEtat.duree, "fduree")}
      <div class="trois">${[["Si ça va mal", f.mal, "mal"], ["Le plus probable", f.probable, "prob"], ["Si ça va bien", f.bien, "bien"]].map(([l, v, c]) => `<div class="t-${c}"><div class="gris">${l}</div><b>${fcfa(arrondi(v))}</b></div>`).join("")}</div>
      <div class="gris" style="margin-top:8px">D'après ${mod.cas} cas réels de 2016 à 2025 d'actions notées comme celle-ci : ${Math.round(mod.perte * 100)} % ont perdu de l'argent sur un an. Une seule action, c'est risqué : mieux vaut en avoir plusieurs.</div></div>` : ""}
    <div class="carte"><h3>Les raisons, en détail</h3>${(a.raisons || []).map(([t, txt]) => `<div class="raison r-${t}"><b>${{ plus: "+", moins: "−", attention: "!", neutre: "•" }[t]}</b><span>${esc(txt)}</span></div>`).join("")}${(a.drapeaux || []).map((d) => `<div class="raison r-attention"><b>!</b><span>${esc(d)}</span></div>`).join("")}
      <div class="gris" style="margin-top:6px">${a.bilan ? "Bilan " + esc(a.bilan.exercice) + (a.bilan.manuel ? " (chiffres saisis à la main, PDF scanné)" : " lu automatiquement et contrôlé") + "." : "Bilan pas encore lu."}</div></div>
    ${a.resultats && a.resultats.length >= 3 ? graphResultats(a.resultats) : ""}
    ${a.dividende ? `<div class="carte"><h3>Dernier dividende</h3><div>${fcfa(a.dividende)} par action, versé le ${dateFr(a.date_dividende)}</div></div>` : ""}
    <button class="bouton" data-ajouter="${a.s}">${mes ? "Modifier dans mon portefeuille" : "Ajouter à mon portefeuille"}</button>
    <p class="gris" style="text-align:center">Aide à la décision, pas un conseil d'investissement.</p>`);
}

function jaugeSolva(sv) {
  const max = 25, pos = (v) => Math.min(100, v / max * 100);
  const c = sv.ratio < sv.norme ? FEUX.rouge : sv.ratio < 13 ? FEUX.orange : FEUX.vert;
  return `<div style="margin-top:12px"><div class="ligne entre"><b>Solvabilité</b> <span class="gris">(${esc(sv.periode || sv.exercice)})</span><b style="color:${c}">${sv.approx ? "plus de " : ""}${nb(sv.ratio, 1)} %</b></div>
    <div class="solva"><span style="width:${pos(sv.ratio)}%;background:${c}"></span><i style="left:${pos(sv.norme)}%" title="minimum"></i><i class="moy" style="left:${pos(14.7)}%"></i></div>
    <div class="ligne entre gris" style="font-size:12px"><span>| minimum exigé 11,5 %</span><span>| moyenne des banques 14,7 %</span></div>
    <div class="gris" style="margin-top:6px">Les fonds propres de la banque, comparés aux risques qu'elle prend. Plus c'est haut, mieux elle peut encaisser des crédits non remboursés.${sv.ratio_n1 ? ` L'année d'avant : ${nb(sv.ratio_n1, 1)} %.` : ""}</div>
    ${sv.source ? `<a class="lien" href="${esc(sv.source)}" target="_blank" rel="noopener">Source : ${esc((sv.document || "rapport").slice(0, 60))}</a>` : ""}</div>`;
}

function graphResultats(r) {
  const max = Math.max(...r.map((x) => Math.abs(x[1]))) || 1;
  const unite = max >= 1e9 ? [1e9, "milliards"] : max >= 1e6 ? [1e6, "millions"] : [1e3, "milliers"];
  return `<div class="carte"><h3>Résultat net par année</h3><div class="gris" style="margin-bottom:10px">En ${unite[1]} de FCFA, d'après les bilans officiels</div>
    <div style="display:flex;align-items:flex-end;gap:8px;height:120px">${r.map(([an, v]) => `<div style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%;gap:4px">
      <span style="font-size:11px;font-weight:600;color:${v < 0 ? "var(--rouge)" : "var(--encre)"}">${nb(v / unite[0], 1)}</span>
      <div class="colonne" style="height:${Math.max(4, Math.abs(v) / max * 80)}px;background:${v < 0 ? "var(--rouge)" : "var(--bleu)"}"></div>
      <span class="gris" style="font-size:11px">${an}</span></div>`).join("")}</div></div>`;
}

const MOTS = {
  dividende: ["Dividende et rendement", "La part du bénéfice que l'entreprise te reverse, en général une fois par an. Le rendement, c'est ce dividende divisé par le prix de l'action.", "Tu as une part d'une boutique : à la fin de l'année, elle te donne ta part du bénéfice. 7 % de rendement : 7 000 FCFA par an pour 100 000 FCFA placés."],
  per: ["PER", "Combien d'années de bénéfice tu paies en achetant l'action. Plus il est bas, moins l'action est chère.", "PER de 7 : le prix de l'action correspond à 7 années de bénéfice de l'entreprise."]
};

// ---------- investir
function investir() {
  const profil = lire("profil", null) || "Équilibré";
  const plan = construirePlan(inv.montant, profil);
  const modele = D.projections && D.projections.portefeuille;
  const f = fourchette(modele, inv.duree, inv.montant, plan.partReserve);
  const segs = plan.lignes.map((l, i) => [(l.cout + l.frais) / inv.montant, COULEURS[i % COULEURS.length]]).concat([[plan.reserve / inv.montant, RESERVE_COUL]]);
  const montantMensuel = lire("mensuel", 20000);
  const m = METEO[D.meteo.code];
  const autre = ![25000, 50000, 100000].includes(inv.montant);
  return `
  <div class="carte">
    <h2>Combien veux-tu placer ?</h2>
    ${puces([[25000, "25 000"], [50000, "50 000"], [100000, "100 000"]], inv.montant, "imontant")}
    <div class="champ" style="margin:8px 0 0"><input id="montantLibre" type="number" inputmode="numeric" min="0" step="5000" placeholder="Autre somme (FCFA)" value="${autre ? inv.montant : ""}" aria-label="Autre somme"></div>
    <h3 style="margin-top:14px">Pendant combien de temps ?</h3>
    ${puces([[1, "1 an"], [3, "3 ans"], [5, "5 ans"]], inv.duree, "iduree")}
  </div>
  <button class="carte appel" data-quiz><span style="font-size:28px">${PROFILS[profil][0]}</span><span><b>Ton profil : ${profil}</b><div class="gris">${lire("profil", null) ? "D'après ton quiz · le refaire" : "Profil par défaut · fais le quiz (1 min)"}</div></span><span class="chev">›</span></button>
  <div class="carte">
    <h3>Ce que tu achètes</h3>
    <div class="ligne" style="align-items:center;gap:14px">${anneau(segs)}<div style="flex:1;min-width:0">${plan.lignes.map((l, i) => `<div class="leg-ligne"><i style="background:${COULEURS[i % COULEURS.length]}"></i><span><b>${esc(action(l.s).nom)}</b><div class="gris">${l.qte} action${l.qte > 1 ? "s" : ""} · ${nb((l.cout + l.frais) / inv.montant * 100, 0)} %</div></span></div>`).join("")}
      <div class="leg-ligne"><i style="background:${RESERVE_COUL}"></i><span><b>Mis de côté</b><div class="gris">${fcfa(plan.reserve)} à l'abri · ${nb(plan.reserve / inv.montant * 100, 0)} %</div></span></div></div></div>
    <div class="gris" style="margin-top:10px">${m[0]} Météo : ${m[1].toLowerCase()} · ${Math.round(plan.part * 100)} % prévu en actions pour un profil ${profil.toLowerCase()}. Avec une petite somme, on choisit moins de sociétés pour limiter les frais, et pas plus de 40 % sur une seule. Frais d'achat : ${fcfa(plan.frais)}.</div>
    ${!plan.lignes.length ? `<div class="puce" style="margin-top:8px">Somme trop petite pour acheter une action conseillée : garde-la et ajoute celle du mois prochain.</div>` : ""}
  </div>
  ${f ? `<div class="carte">
    <h3>Dans ${inv.duree} an${inv.duree > 1 ? "s" : ""}, tu pourrais avoir</h3>
    <div class="trois">${[["Si ça va mal", f.mal, "mal"], ["Le plus probable", f.probable, "prob"], ["Si ça va bien", f.bien, "bien"]].map(([l, v, c]) => `<div class="t-${c}"><div class="gris">${l}</div><b>${fcfa(arrondi(v))}</b></div>`).join("")}</div>
    <div class="gris" style="margin-top:8px">Calculé à partir du test de la méthode sur 2016-2025, frais SGI compris, impôt sur les dividendes non déduit. Sans risque (obligations d'État), tu aurais environ ${fcfa(arrondi(inv.montant * Math.pow(1 + TAUX_OBLIG, inv.duree)))}. Le passé ne garantit pas l'avenir.</div>
  </div>` : ""}
  ${plan.lignes.length ? `<button class="bouton" data-valider>Je valide et je suis ce portefeuille</button>` : ""}
  <div class="carte" style="margin-top:14px">
    <h3>Chaque mois</h3>
    <div class="champ"><label for="mensuel">Somme mise de côté chaque mois</label><input id="mensuel" type="number" inputmode="numeric" min="0" step="1000" value="${montantMensuel}"></div>
    ${propositionMois(montantMensuel, profil)}
    <button class="bouton second" data-mois style="margin-top:10px">J'ai investi ce mois-ci ✓</button>
    <div class="gris" style="margin-top:6px;text-align:center">${lire("mois", []).length ? `Déjà ${lire("mois", []).length} mois enregistré${lire("mois", []).length > 1 ? "s" : ""}.` : "Touche le bouton après ton achat pour suivre ta régularité."}</div>
  </div>
  <div class="carte">
    <h3>Portefeuille type long terme</h3>
    <div class="gris" style="margin-bottom:6px">10 actions, 3 au plus par groupe, 5 banques au plus. Construis-le petit à petit.</div>
    ${D.portefeuilles.lt.map((s, i) => ligneAction(action(s), i + 1, "lt")).join("")}
  </div>
  <p class="gris" style="text-align:center">Aide à la décision, pas un conseil d'investissement.</p>`;
}

function propositionMois(montant, profil) {
  const enActions = montant * partActions(profil);
  const taux = tauxOrdre();
  const dejaPf = lire("portefeuille", []).map((p) => p.s);
  const choix = D.portefeuilles.lt.map(action).filter((a) => a.cours && a.cours * (1 + taux) <= enActions);
  const p = choix.find((a) => !dejaPf.includes(a.s)) || choix[0];
  if (!p) return `<div class="gris">Aucune action conseillée ne coûte moins de ${fcfa(enActions)}. Garde cet argent et achète le mois prochain avec deux mois d'argent.</div>`;
  const qte = Math.floor(enActions / (p.cours * (1 + taux)));
  const cout = qte * p.cours, fr = fraisOrdre(cout), pct = fr / cout * 100;
  return `<div class="ligne entre"><span>En actions (${Math.round(partActions(profil) * 100)} %)</span><b>${fcfa(enActions)}</b></div>
    <div class="ligne entre" style="margin-top:4px"><span>En réserve</span><b>${fcfa(montant - enActions)}</b></div>
    <div style="margin-top:10px"><b>Ce mois-ci : ${qte} × ${esc(p.nom)}</b> <span class="gris">(${fcfa(p.cours)} l'action, ${etoiles(p.etoiles.lt)})</span></div>
    <div class="gris">Coût ${fcfa(cout)} + frais d'environ ${fcfa(fr)} (${nb(pct)} %).${dejaPf.includes(p.s) ? "" : " Une société que tu n'as pas encore : ton risque est mieux réparti."}</div>
    ${pct > 2 ? `<div class="puce" style="margin-top:8px">⚠ Frais supérieurs à 2 % : mieux vaut attendre et acheter avec deux mois d'argent.</div>` : ""}`;
}

// ---------- portefeuille : suivi + mes actions
function portefeuille() {
  return `<div class="seg">${[["suivi", "Mon suivi"], ["actions", "Mes actions"]].map(([v, l]) => `<button class="${v === vuePf ? "on" : ""}" data-vuepf="${v}">${l}</button>`).join("")}</div>` + (vuePf === "suivi" ? suivi() : mesActions());
}

function suivi() {
  const st = etatSuivi();
  if (!st) return `<div class="carte vide-etat"><div style="font-size:40px">🌱</div><b>Pas encore de suivi</b><p>Dans « Investir », choisis une somme et une durée, puis touche « Je valide et je suis ce portefeuille ». Je comparerai ici ce qui était promis avec ce qui se passe vraiment.</p><button class="bouton" data-onglet="investir">Aller dans Investir</button></div>`;
  const { plan } = st;
  const S = { prevu: ["✅", "Comme prévu", "Ton argent est dans la zone promise."], mieux: ["🌟", "Mieux que prévu", "Ton argent est au-dessus de la zone promise. Ne t'emballe pas : ça peut redescendre."], moins: ["🧘", "Moins bien que prévu", "Ton argent est sous la zone promise. C'est déjà arrivé dans le passé (2017-2020) avant de bien remonter. Garde ton cap si tu n'as pas besoin de cet argent."], depart: ["🌱", "C'est le début", "Reviens dans quelques semaines : le suivi a besoin d'un peu de temps."] }[st.statut];
  const maxC = Math.max(0.02, ...st.causes.map((c) => Math.abs(c[1])));
  const prochaine = st.etapes.find((e) => !e.fait);
  const badge = [...st.etapes].reverse().find((e) => e.fait && e.m >= 3);
  return `
  <div class="carte">
    <div class="gris">Portefeuille du ${dateFr(plan.date)} · ${fcfa(plan.montant)} · ${plan.duree} an${plan.duree > 1 ? "s" : ""} · ${esc(plan.profil)}</div>
    <div class="gris" style="margin-top:10px">Ce que vaut ton portefeuille aujourd'hui</div>
    <div class="ligne" style="align-items:baseline;gap:8px"><span class="compteur" data-cible="${Math.round(st.valeur)}">${fcfa(st.valeur)}</span></div>
    <div class="${st.gain >= 0 ? "haut" : "bas"}" style="font-weight:700">${pc(st.gain)} depuis le départ</div>
    <div class="gris">dividendes et frais compris</div>
  </div>
  <div class="carte">
    <div class="ligne entre"><h3 style="margin:0">Promis ou réel ?</h3><span class="etiquette e-${st.statut}">${S[0]} ${S[1]}</span></div>
    <div style="margin:10px 0">${courbeSuivi(st)}</div>
    <div class="gris">${S[2]} Zone promise aujourd'hui : de ${fcfa(arrondi(st.z.mal))} à ${fcfa(arrondi(st.z.bien))}.</div>
  </div>
  <div class="carte">
    <h3>D'où vient ton gain</h3>
    ${st.causes.map(([l, v], i) => `<div class="cause"><span>${l}</span><div class="jauge"><span style="width:${Math.abs(v) / maxC * 100}%;background:${v >= 0 ? "var(--bleu)" : "var(--rouge)"};animation-delay:${(0.2 + 0.1 * i).toFixed(2)}s"></span></div><b class="${v >= 0 ? "" : "bas"}" style="text-align:right">${pc(v)}</b></div>`).join("")}
    <div class="gris" style="margin-top:6px">« Tout le marché » : ce que tu aurais gagné en suivant la bourse. « Tes sociétés » : ce que le choix des actions a ajouté ou enlevé.</div>
  </div>
  <div class="carte">
    <h3>Bilans d'étape</h3>
    <div class="etapes">${st.etapes.map((e) => `<div class="${e.fait ? "fait" : ""}"><span>${e.fait ? "✓" : "·"}</span><small>${e.l}</small></div>`).join("")}</div>
    ${prochaine ? `<div class="gris" style="margin-top:8px">Prochain bilan : ${dateFr(prochaine.date)} (${prochaine.l}).</div>` : `<div class="gris" style="margin-top:8px">Durée prévue atteinte : bravo pour ta patience !</div>`}
  </div>
  ${badge ? `<div class="carte badge-carte"><span>🏅</span><div><b>Badge « ${badge.l} de patience »</b><div class="gris">Tu as gardé ton cap. C'est comme ça qu'on investit.</div></div></div>` : ""}
  <button class="bouton second" data-dividende style="margin-bottom:10px">💰 J'ai reçu un dividende</button>
  <button class="bouton second" data-arreter>Arrêter ce suivi</button>
  <p class="gris" style="text-align:center">Le suivi utilise les actions et la réserve validées le ${dateFr(plan.date)}. Pour ton portefeuille réel, regarde « Mes actions ».</p>`;
}

function mesActions() {
  const pf = lire("portefeuille", []);
  const frais = lire("frais", FRAIS_DEFAUT);
  let valeur = 0, achat = 0;
  const lignes = pf.map((p) => {
    const a = action(p.s) || { nom: p.s, cours: null };
    const v = (a.cours || p.prix) * p.qte; valeur += v; achat += p.prix * p.qte;
    const g = v - p.prix * p.qte;
    const e = a.etoiles ? a.etoiles.lt : null;
    return `<button class="action" data-fiche="${p.s}"><span class="info"><span class="nom">${esc(a.nom)}</span><div class="gris">${p.qte} × ${fcfa(a.cours)} · acheté ${fcfa(p.prix)}</div>${e && e <= 2 ? `<span class="puce">⚠ Note long terme faible (${e}★) : à revoir au bilan annuel</span>` : ""}${a.feu && a.feu.couleur === "rouge" ? `<span class="puce">⚠ Entreprise fragile : ${esc(a.feu.pourquoi)}</span>` : ""}</span><span style="text-align:right"><b>${fcfa(v)}</b><div class="fleche ${g >= 0 ? "haut" : "bas"}">${g >= 0 ? "+" : ""}${fcfa(g)}</div></span></button>`;
  }).join("");
  const fixes = frais.tenue * (1 + frais.tva / 100) + valeur * frais.conservation * (1 + frais.tva / 100) / 100;
  const divs = lire("dividendes", []).reduce((s, d) => s + d.montant, 0);
  return `
  <div class="carte">
    <h2>Mes actions</h2>
    <div class="ligne entre"><span class="gris">Valeur actuelle</span><b style="font-size:22px">${fcfa(valeur)}</b></div>
    <div class="ligne entre"><span class="gris">Gain ou perte sur les cours</span><b class="${valeur - achat >= 0 ? "haut" : "bas"}">${valeur - achat >= 0 ? "+" : ""}${fcfa(valeur - achat)}</b></div>
    ${divs ? `<div class="ligne entre"><span class="gris">Dividendes reçus</span><b class="haut">+${fcfa(divs)}</b></div>` : ""}
    ${pf.length ? `<div class="gris" style="margin-top:8px">Frais fixes ${esc(frais.sgi)} estimés : ${fcfa(fixes)} par an (${valeur ? nb(fixes / valeur * 100) : "—"} % du portefeuille)${valeur && fixes / valeur > 0.03 ? ". C'est beaucoup au début : cette part baisse vite quand le portefeuille grandit" : ""}.</div>` : ""}
  </div>
  <div class="carte" style="padding:4px 12px">${lignes || `<div class="vide-etat">Aucune action pour l'instant. Ouvre une action dans le classement et touche « Ajouter à mon portefeuille ».</div>`}</div>
  <button class="bouton second" data-dividende style="margin-bottom:12px">💰 J'ai reçu un dividende</button>
  <div class="carte">
    <h3>Frais de ma SGI</h3>
    <div class="gris" style="margin-bottom:10px">Par défaut : grille officielle SA2IF (maximums). Remplace par tes vrais chiffres si besoin.</div>
    <div class="grille3">
      <div class="champ"><label for="f-courtage">Courtage %</label><input id="f-courtage" data-frais="courtage" type="number" step="0.05" value="${frais.courtage}"></div>
      <div class="champ"><label for="f-tva">TVA %</label><input id="f-tva" data-frais="tva" type="number" step="1" value="${frais.tva}"></div>
      <div class="champ"><label for="f-tenue">Tenue /an</label><input id="f-tenue" data-frais="tenue" type="number" step="500" value="${frais.tenue}"></div>
    </div>
    <div class="gris">Tout est enregistré uniquement sur ce téléphone.</div>
  </div>`;
}

// ---------- apprendre
const CARTES = [
  ["Une action, c'est quoi exactement ?", "Une petite part d'une entreprise. Si tu as 1 action d'une boutique qui a 1 000 parts, tu possèdes 1/1 000 de la boutique et tu touches ta part de ses bénéfices."],
  ["Qu'est-ce qu'un dividende ?", "La part du bénéfice que l'entreprise reverse à ses actionnaires, en général une fois par an. Comme un loyer que te paie ta part de boutique."],
  ["Que veut dire un PER de 8 ?", "Le prix de l'action correspond à 8 années de bénéfice. Plus le PER est bas, moins l'action est chère par rapport à ce qu'elle gagne."],
  ["Pourquoi ne pas tout mettre sur une seule action ?", "Si cette société a un problème, tu perds beaucoup. Avec plusieurs sociétés de secteurs différents, une mauvaise surprise pèse peu."],
  ["Que fait une SGI ?", "La Société de Gestion et d'Intermédiation passe tes ordres d'achat et de vente à la BRVM et garde tes actions. Elle prend des frais à chaque ordre."],
  ["Pourquoi garder une réserve ?", "Quand la bourse est chère, une partie de l'argent attend à l'abri. Elle servira à acheter quand les prix seront plus bas."],
  ["La BRVM, c'est quoi ?", "La Bourse Régionale des Valeurs Mobilières, à Abidjan. Elle regroupe les sociétés cotées des 8 pays de l'UEMOA, dont le Burkina Faso."],
  ["Faut-il vendre quand ça baisse ?", "Pas forcément. Les baisses font partie de la bourse. Si la société reste solide et que tu n'as pas besoin de l'argent, attendre est souvent mieux."],
  ["Qu'est-ce que le rendement ?", "Le dividende divisé par le prix de l'action. 6 % de rendement : 6 000 FCFA de dividende par an pour 100 000 FCFA placés."],
  ["Pourquoi investir chaque mois ?", "En achetant un peu chaque mois, tu achètes parfois cher, parfois pas cher, et tu n'as pas besoin de deviner le bon moment."]
];
const LECONS = [
  ["🏪", "Une action = une part de boutique", "Quand tu achètes une action, tu deviens copropriétaire d'une entreprise. Si l'entreprise gagne de l'argent, elle peut te verser un dividende, et la valeur de ta part peut monter. Si elle va mal, ta part peut baisser. Tu ne peux pas perdre plus que ce que tu as mis."],
  ["🪙", "Le dividende, ton loyer annuel", "Chaque année, beaucoup de sociétés de la BRVM reversent une partie de leurs bénéfices. C'est le dividende. Il arrive sur ton compte chez ta SGI, sans rien vendre. Attention : un dividende très élevé une seule année est souvent exceptionnel et ne se répétera pas."],
  ["🏷️", "Cher ou pas cher : le PER", "Le PER compare le prix de l'action aux bénéfices de la société. Un PER de 6, c'est 6 ans de bénéfice : plutôt bon marché. Un PER de 25, c'est cher. L'application compare chaque PER à la moyenne de la bourse."],
  ["🌦️", "Lire la météo de la bourse", "Quand toute la bourse est bon marché (soleil), on investit toute la somme. Quand elle est chère (pluie), on en garde la moitié en réserve. Sur 10 ans de test, cette règle a réduit les grosses chutes."],
  ["🧺", "Ne pas mettre tous ses œufs dans le même panier", "L'application limite à 3 actions d'un même groupe et 5 banques au plus. Une mauvaise nouvelle sur une société ne doit pas ruiner tout ton portefeuille."],
  ["💸", "Les frais, l'ennemi silencieux", "Chaque achat coûte environ 1,5 % chez SA2IF. Acheter et revendre souvent mange tes gains. C'est pour ça que l'application conseille d'acheter pour longtemps et d'éviter les petits ordres de moins de 10 000 FCFA."],
  ["📒", "Lire un bilan sans être comptable", "Trois questions : la société gagne-t-elle de l'argent chaque année ? Ses bénéfices grandissent-ils ? Est-elle trop endettée ? Les fiches te montrent ces réponses à partir des bilans officiels."],
  ["🧘", "Garder son calme quand ça baisse", "En 2017-2020, la BRVM a baissé plusieurs années de suite, puis a fortement remonté de 2021 à 2026. Ceux qui ont vendu en panique ont raté la remontée. Investis seulement l'argent dont tu n'as pas besoin avant plusieurs années."]
];
const jourIndex = () => Math.floor(Date.now() / 864e5);

function badges() {
  const faites = lire("lecons", []), plan = lire("plan", null);
  const patience = plan ? ans(plan.date) : 0;
  return [
    ["Curieux", "★", faites.length >= 1],
    ["Quiz fait", "✓", !!lire("profil", null)],
    ["Toutes les leçons", "🎓", faites.length >= LECONS.length],
    ["Régulier (3 mois)", "🔥", lire("mois", []).length >= 3],
    ["Premier dividende", "💰", lire("dividendes", []).length >= 1],
    ["3 mois de patience", "◷", patience >= 0.25],
    ["1 an de patience", "◷", patience >= 1],
    ["3 ans de patience", "🏆", patience >= 3]
  ];
}

function apprendre() {
  const faites = lire("lecons", []);
  const carte = CARTES[jourIndex() % CARTES.length];
  return `
  <div class="carte">
    <div class="ligne entre"><h2 style="margin:0">Apprendre</h2><b>${Math.round(faites.length / LECONS.length * 100)} %</b></div>
    <div class="gris">${faites.length} leçon${faites.length > 1 ? "s" : ""} sur ${LECONS.length} terminée${faites.length > 1 ? "s" : ""}</div>
    <div class="jauge" style="margin-top:8px"><span style="width:${faites.length / LECONS.length * 100}%;background:var(--bleu)"></span></div>
  </div>
  <h3 style="margin:4px 4px 8px">Carte du jour</h3>
  <button class="flip" data-flip aria-label="Retourner la carte"><span class="flip-in"><span class="face"><small>QUESTION</small><b>${esc(carte[0])}</b><span class="gris">Touche la carte pour voir la réponse</span></span><span class="face dos"><small>RÉPONSE</small><span>${esc(carte[1])}</span></span></span></button>
  <h3 style="margin:16px 4px 8px">Leçons d'une minute <span class="gris" style="font-weight:400">· fais glisser</span></h3>
  <div class="defile">${LECONS.map(([ic, t], i) => `<button class="lecon ${faites.includes(i) ? "faite" : ""}" data-lecon="${i}"><span class="ic">${ic}</span><b>${esc(t)}</b><span class="gris">1 min · ${faites.includes(i) ? "Terminée ✓" : "À faire"}</span></button>`).join("")}</div>
  <div class="ligne entre" style="margin:16px 4px 8px"><h3 style="margin:0">Tes badges</h3><button class="bouton second petit" data-quiz>Quiz de profil</button></div>
  <div class="badges">${badges().map(([n, ic, ok]) => `<div class="${ok ? "ok" : ""}"><span>${ic}</span><small>${esc(n)}</small></div>`).join("")}</div>
  <p class="gris" style="text-align:center">Les badges récompensent ce que tu apprends et ta patience, jamais le nombre d'achats.</p>`;
}

// ---------- fenetres
function ouvrir(html) {
  const c = document.getElementById("couche");
  const dejaOuvert = c.querySelector(".feuille>div");
  const pos = dejaOuvert ? dejaOuvert.scrollTop : 0;
  c.innerHTML = `<div class="feuille ${dejaOuvert ? "sans-anim" : ""}" data-fond><div role="dialog" aria-modal="true">${html}</div></div>`;
  if (dejaOuvert) c.querySelector(".feuille>div").scrollTop = pos;
}
function fermer() { if ("speechSynthesis" in window) speechSynthesis.cancel(); document.getElementById("couche").innerHTML = ""; ficheEtat.s = null; majPastille(); }

function ecranQuiz() {
  const { i, choix, score } = quiz;
  if (i >= QUESTIONS.length) {
    const p = profilDe(score);
    return ouvrir(`<div class="ligne entre" style="margin-bottom:8px"><h2 style="margin:0">Ton profil</h2>${fermerBtn}</div>
      <div class="carte" style="text-align:center"><div style="font-size:52px" class="pop">${PROFILS[p][0]}</div><div style="font-size:24px;font-weight:800">${p}</div><p>${PROFILS[p][1]}</p>
      <div class="gris">Part en actions aujourd'hui (météo ${METEO[D.meteo.code][0]}) : ${Math.round(partActions(p) * 100)} %.</div></div>
      <button class="bouton" data-quizfin>Voir le portefeuille proposé</button>
      <button class="bouton second" style="margin-top:10px" data-quiz>Refaire le quiz</button>`);
  }
  const [q, opts] = QUESTIONS[i];
  ouvrir(`<div class="ligne entre" style="margin-bottom:8px"><h2 style="margin:0">Quiz de profil</h2><span class="gris">${i + 1}/5</span>${fermerBtn}</div>
    <div class="jauge" style="margin-bottom:14px"><span style="width:${(i / 5) * 100 + 6}%;background:var(--bleu)"></span></div>
    <div class="gris" style="margin-bottom:8px">Pas de bonne ou de mauvaise réponse : je veux juste savoir comment tu vis les hauts et les bas.</div>
    <div class="question">${esc(q)}</div>
    ${opts.map(([l], k) => `<button class="option ${choix === k ? "on" : ""}" data-qopt="${k}" style="animation-delay:${(0.06 * k).toFixed(2)}s"><i></i>${esc(l)}</button>`).join("")}
    <button class="bouton" style="margin-top:12px" data-qsuite ${choix == null ? "disabled" : ""}>${i === 4 ? "Voir mon profil" : "Suivant"}</button>`);
}

function formulaireAjout(s) {
  const p = lire("portefeuille", []).find((x) => x.s === s), a = action(s);
  ouvrir(`<div class="ligne entre" style="margin-bottom:12px"><h2 style="margin:0">${esc(a.nom)}</h2>${fermerBtn}</div>
    <div class="champ"><label for="qte">Nombre d'actions</label><input id="qte" type="number" inputmode="numeric" min="0" value="${p ? p.qte : 1}"></div>
    <div class="champ"><label for="prix">Prix d'achat moyen (FCFA)</label><input id="prix" type="number" inputmode="numeric" min="0" value="${p ? p.prix : a.cours}"></div>
    <button class="bouton" data-enregistrer="${s}">Enregistrer</button>
    ${p ? `<button class="bouton second" style="margin-top:10px" data-retirer="${s}">Retirer du portefeuille</button>` : ""}`);
}

function ecranMessages() {
  const liste = tousMessages(), vus = lire("vus", []);
  const vis = filtreMsg === "tous" ? liste : liste.filter((m) => m.type === filtreMsg);
  const html = `<div class="ligne entre" style="margin-bottom:12px"><h2 style="margin:0">Messages</h2>${fermerBtn}</div>
    ${puces([["tous", "Tous"], ["faire", "À faire"], ["alerte", "Alertes"], ["info", "Infos"]], filtreMsg, "filtre")}
    ${vis.map((m, i) => `<div class="carte msg m-${m.type}" style="animation-delay:${(0.05 * i).toFixed(2)}s"><span class="ic">${{ alerte: "⚠️", info: "ℹ️", faire: "✋" }[m.type]}</span><div style="flex:1;min-width:0"><div class="ligne entre"><b>${esc(m.titre)}</b>${vus.includes(cleMsg(m)) ? "" : `<i class="non-lu" aria-label="non lu"></i>`}</div><div class="gris">${esc(m.quand || "")}</div><div>${esc(m.texte)}</div>${m.aller ? `<button class="lien" data-msgaller="${m.aller}">Voir</button>` : m.fiche ? `<button class="lien" data-fiche="${m.fiche}">Voir la fiche</button>` : m.quiz ? `<button class="lien" data-quiz>Faire le quiz</button>` : ""}</div></div>`).join("") || `<div class="vide-etat">Aucun message.</div>`}
    <div class="gris">Sources : ${D.sources.map(esc).join(" · ")}</div>`;
  ouvrir(html);
  ecrire("vus", liste.map(cleMsg));
  document.getElementById("pastille").hidden = true;
}

function celebration(type, montant) {
  const div = type === "dividende", serie = lire("mois", []);
  document.getElementById("couche").innerHTML = `<div class="celeb" data-celeb>
    <video src="celebration.mp4" autoplay muted playsinline></video><img src="celebration_fin.jpg" alt="">
    <div class="c-carte">
      <div class="ligne"><span style="font-size:30px">${div ? "💰" : type === "plan" ? "🚀" : "🔥"}</span><div><h2 style="margin:0">${div ? "Tu as reçu un dividende !" : type === "plan" ? "Portefeuille validé !" : "Investissement du mois fait !"}</h2><div class="gris">${div ? "De l'argent gagné sans rien vendre" : type === "plan" ? "Je le suis pour toi dans « Mon suivi »" : serie.length + " mois enregistré" + (serie.length > 1 ? "s" : "")}</div></div></div>
      <div style="font-size:34px;font-weight:800;color:var(--vert);margin:10px 0">${type === "plan" ? fcfa(montant) : "+" + fcfa(montant)}</div>
      <div class="gris" style="margin-bottom:12px">${div ? "Ajoute-le à ton investissement du mois prochain." : type === "plan" ? "Les actions ont été ajoutées à « Mes actions ». Corrige-les si ton achat réel est différent." : "La régularité compte plus que le bon moment pour acheter."}</div>
      <button class="bouton" data-fermer>Continuer</button>
    </div></div>`;
}

// ---------- interactions
document.addEventListener("click", (ev) => {
  const t = ev.target.closest("button,[data-fond]");
  if (!t || !D) return;
  const d = t.dataset;
  if (d.fond !== undefined && ev.target === t) return fermer();
  if (d.onglet) { fermer(); ecran = d.onglet; recherche = ""; rendre(); return window.scrollTo(0, 0); }
  if (d.msgaller) { fermer(); ecran = d.msgaller; rendre(); return window.scrollTo(0, 0); }
  if (d.horizon) { horizon = d.horizon; return rendre(); }
  if (d.fiche) return fiche(d.fiche);
  if (d.fhorizon) { ficheEtat.h = d.fhorizon; return fiche(); }
  if (d.fmontant) { ficheEtat.montant = +d.fmontant; return fiche(); }
  if (d.fduree) { ficheEtat.duree = +d.fduree; return fiche(); }
  if (d.mot) { const [ti, tx, ex] = MOTS[d.mot]; const retour = ficheEtat.s; return ouvrir(`<div class="ligne entre" style="margin-bottom:12px"><h2 style="margin:0">${ti}</h2>${fermerBtn}</div><div class="carte"><p style="margin-top:0">${tx}</p><div class="gris">Exemple : ${ex}</div></div><button class="bouton second" data-fiche="${retour}">Retour à la fiche</button>`); }
  if (d.ecouter !== undefined) {
    const a = action(ficheEtat.s);
    if (speechSynthesis.speaking) { speechSynthesis.cancel(); t.textContent = "🔊 Écouter l'explication"; return; }
    const u = new SpeechSynthesisUtterance(resume(a, ficheEtat.h)); u.lang = "fr-FR"; u.rate = 0.95;
    const voix = speechSynthesis.getVoices().find((v) => v.lang && v.lang.startsWith("fr")); if (voix) u.voice = voix;
    u.onend = () => { const b = document.querySelector("[data-ecouter]"); if (b) b.textContent = "🔊 Écouter l'explication"; };
    speechSynthesis.speak(u); t.textContent = "⏸ Arrêter la lecture"; return;
  }
  if (d.fermer !== undefined) return fermer();
  if (d.ajouter) return formulaireAjout(d.ajouter);
  if (d.enregistrer) {
    const s = d.enregistrer, qte = +document.getElementById("qte").value, prix = +document.getElementById("prix").value;
    const pf = lire("portefeuille", []).filter((p) => p.s !== s);
    if (qte > 0 && prix > 0) pf.push({ s, qte, prix });
    ecrire("portefeuille", pf); fermer(); ecran = "portefeuille"; vuePf = "actions"; return rendre();
  }
  if (d.retirer) { ecrire("portefeuille", lire("portefeuille", []).filter((p) => p.s !== d.retirer)); fermer(); return rendre(); }
  if (d.imontant) { inv.montant = +d.imontant; return rendre(); }
  if (d.iduree) { inv.duree = +d.iduree; return rendre(); }
  if (d.vuepf) { vuePf = d.vuepf; return rendre(); }
  if (d.valider !== undefined) {
    const plan = construirePlan(inv.montant, lire("profil", null) || "Équilibré");
    const coursDepart = {}; D.actions.forEach((a) => { if (a.cours) coursDepart[a.s] = a.cours; });
    ecrire("plan", { date: auj(), montant: inv.montant, duree: inv.duree, profil: plan.profil, lignes: plan.lignes.map(({ s, qte, prix }) => ({ s, qte, prix })), reserve: plan.reserve, partReserve: plan.partReserve, frais: plan.frais, modele: D.projections.portefeuille, coursDepart });
    ecrire("histoSuivi", []);
    const pf = lire("portefeuille", []);
    for (const l of plan.lignes) {
      const p = pf.find((x) => x.s === l.s);
      if (p) { p.prix = Math.round((p.prix * p.qte + l.prix * l.qte) / (p.qte + l.qte)); p.qte += l.qte; } else pf.push({ s: l.s, qte: l.qte, prix: l.prix });
    }
    ecrire("portefeuille", pf);
    ecran = "portefeuille"; vuePf = "suivi"; rendre();
    return celebration("plan", inv.montant);
  }
  if (d.arreter !== undefined) { if (confirmerArret(t)) { ecrire("plan", null); ecrire("histoSuivi", []); rendre(); } return; }
  if (d.mois !== undefined) {
    const mois = auj().slice(0, 7), serie = lire("mois", []);
    if (!serie.includes(mois)) serie.push(mois);
    ecrire("mois", serie); rendre();
    return celebration("mois", lire("mensuel", 20000));
  }
  if (d.dividende !== undefined) {
    return ouvrir(`<div class="ligne entre" style="margin-bottom:12px"><h2 style="margin:0">Dividende reçu</h2>${fermerBtn}</div>
      <div class="champ"><label for="mdiv">Montant reçu (FCFA)</label><input id="mdiv" type="number" inputmode="numeric" min="0" value=""></div>
      <button class="bouton" data-diviok>Valider</button>`);
  }
  if (d.diviok !== undefined) {
    const m = +document.getElementById("mdiv").value;
    if (m > 0) { const l = lire("dividendes", []); l.push({ date: auj(), montant: m }); ecrire("dividendes", l); rendre(); celebration("dividende", m); }
    return;
  }
  if (d.quiz !== undefined) { quiz = { i: 0, choix: null, score: 0 }; return ecranQuiz(); }
  if (d.qopt) { quiz.choix = +d.qopt; return ecranQuiz(); }
  if (d.qsuite !== undefined && quiz && quiz.choix != null) { quiz.score += QUESTIONS[quiz.i][1][quiz.choix][1]; quiz.i++; quiz.choix = null; if (quiz.i >= QUESTIONS.length) ecrire("profil", profilDe(quiz.score)); return ecranQuiz(); }
  if (d.quizfin !== undefined) { fermer(); ecran = "investir"; rendre(); return window.scrollTo(0, 0); }
  if (d.filtre) { filtreMsg = d.filtre; return ecranMessages(); }
  if (d.flip !== undefined) return t.classList.toggle("retourne");
  if (d.lecon) {
    const i = +d.lecon, [ic, ti, tx] = LECONS[i];
    const l = lire("lecons", []); if (!l.includes(i)) { l.push(i); ecrire("lecons", l); }
    ouvrir(`<div class="ligne entre" style="margin-bottom:12px"><h2 style="margin:0">${ic} ${esc(ti)}</h2>${fermerBtn}</div><div class="carte"><p style="margin:0;font-size:16px;line-height:1.6">${esc(tx)}</p></div>
      ${i + 1 < LECONS.length ? `<button class="bouton" data-lecon="${i + 1}">Leçon suivante</button>` : `<button class="bouton" data-fermer>Terminé 🎓</button>`}`);
    return rendre();
  }
  if (t.id === "cloche") return ecranMessages();
});
function confirmerArret(b) {
  if (b.dataset.sur) return true;
  b.dataset.sur = "1"; b.textContent = "Touche encore pour confirmer"; b.style.color = "var(--rouge)";
  setTimeout(() => { if (b.isConnected) { delete b.dataset.sur; b.textContent = "Arrêter ce suivi"; b.style.color = ""; } }, 4000);
  return false;
}
document.addEventListener("input", (ev) => {
  const t = ev.target;
  if (t.id === "cherche") { recherche = t.value; const pos = t.selectionStart; rendre(); const n = document.getElementById("cherche"); n.focus(); n.setSelectionRange(pos, pos); }
  if (t.id === "mensuel") ecrire("mensuel", Math.max(0, +t.value || 0));
  if (t.dataset.frais) { const f = lire("frais", FRAIS_DEFAUT); f[t.dataset.frais] = +t.value || 0; ecrire("frais", f); }
});
document.addEventListener("change", (ev) => {
  const t = ev.target;
  if (t.id === "montantLibre" && +t.value > 0) { inv.montant = Math.round(+t.value); return rendre(); }
  if (t.id === "mensuel" || t.dataset.frais) rendre();
});
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") fermer(); });

if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
charger();
