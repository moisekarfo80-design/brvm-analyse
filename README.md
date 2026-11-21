# BRVM Analyse

Application personnelle d'aide à la décision pour les actions de la BRVM. Elle tourne **entièrement sur le téléphone**, sans ordinateur.

> Aide à la décision, pas un conseil d'investissement.

## Comment ça marche

- **Chaque soir de semaine** (17 h 47, puis 21 h 13 en secours, heure de Ouagadougou), GitHub Actions lance `serveur/collecte.py` puis `serveur/analyse.py`. Ces scripts :
  1. lisent les cours sur brvm.org et les contrôlent ;
  2. calculent les notes des trois horizons (long, moyen et court terme), la météo de la bourse, la fiabilité et les messages ;
  3. enregistrent `docs/data/resultats.json`.
- **L'application** (`docs/`, publiée par GitHub Pages) télécharge ce petit fichier quand on l'ouvre. Rien ne tourne en arrière-plan sur le téléphone.
- **Le portefeuille personnel** reste enregistré sur le téléphone. Il n'est jamais envoyé sur internet.

## Fichiers

| Fichier | Rôle |
| --- | --- |
| `donnees/reference.json` | Dividendes et bénéfices par action, tirés du dernier bulletin officiel |
| `donnees/historique.csv` | Cours de clôture et volumes, complétés chaque soir |
| `donnees/operations_capital.json` | Fractionnements et actions gratuites, pour corriger les prix |
| `donnees/statut_collecte.json` | Compte rendu de la dernière collecte |
| `donnees/etat.json` | Mémoire des étoiles (anti-clignotement) et historique des notes |
| `docs/` | L'application (PWA) |

## Lancer à la main

Onglet **Actions** → **Mise a jour du soir** → **Run workflow**.

## Tester sans internet

```
pip install -r requirements.txt
python serveur/test_serveur.py
```

## Limites actuelles

- Les notes mesurent le dividende, le prix (PER) et la tendance. La solidité, la croissance et l'actualité seront ajoutées avec la lecture des bilans. D'ici là, la fiabilité reste plafonnée à 59 %.
- Les dividendes et les bénéfices viennent de `reference.json`. Il faut le mettre à jour après chaque saison des dividendes : l'application prévient quand la liste a plus de 120 jours.
