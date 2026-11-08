# Test de charge — rafale de reconnexion

Outillage de la mesure « 400 écrans se reconnectent en même temps ». Il vivait dans `/tmp`
et a disparu au premier redémarrage : il est ici pour ne plus être réécrit.

## Ce qu'on mesure

400 connexions WebSocket player lancées **simultanément**, et le délai jusqu'au premier
`player:sync`. C'est le délai que subit un écran quand un site retrouve le courant ou qu'un
serveur redémarre.

## Protocole

1. **Créer le jeu d'essai sur la machine testée** — `mk_players.py N` (dans le conteneur
   backend, `PYTHONPATH=/app`) crée N players `LOADTEST-*` et imprime leurs jetons.
   Les jetons sont forgés **sur place** et **stockés en base** : le WebSocket compare le
   jeton présenté au jeton stocké, un jeton seulement signé serait refusé.
2. **Le générateur tourne sur une AUTRE machine**, dans un conteneur jetable :

   ```
   printf 'FROM python:3.12-slim\nRUN pip install --no-cache-dir websockets\n' \
     | docker build -t sfloadgen -
   SF_URL=ws://<cible>:8080/api/v1/ws/player bash burst.sh <label> <procs> 400
   ```

   `procs` = 1 (un processus × 400) ou 2 (deux processus × 200).
3. `agg.py` agrège les sorties et rend p50 / p95 / max sur l'**union** des latences.

## Pièges — chacun a produit un chiffre faux au moins une fois

- **`ulimit -n` du générateur.** Le conteneur backend de la prod est à **1024** : lancer le
  générateur dedans fait heurter à l'instrument sa propre limite (piège du 02/08). D'où le
  conteneur jetable à `--ulimit nofile=65536`.
- **Le premier run après un redémarrage du backend est à jeter.** Mesuré : +6 % à 1 worker
  mais **+46 % à 4 workers** — chaque processus paie son propre démarrage. Inclure des runs
  à froid biaise donc l'A/B **systématiquement contre** le multi-worker : c'est ce qui a
  fait conclure à tort, le 07/08, que `--workers` ne gagnait que ×1,8.
  Corollaire : un `docker compose up -d` **ne recrée rien** si la configuration n'a pas
  changé — vérifier `StartedAt`, sinon on croit mesurer à froid et on mesure à chaud.
- **`loadavg` ne mesure PAS une rafale.** C'est une moyenne glissante d'une minute ; sur une
  rafale de 10 s elle sous-estime massivement (0,37 relevé le 07/08 là où l'occupation réelle
  était de 100 %). Mesurer les deltas de `/proc/stat`, et `docker stats` pour le conteneur.
- **Une sonde a besoin d'un témoin de fraîcheur.** Un échantillonneur expiré laisse un log
  plein de valeurs anciennes que `tail` sert sans broncher : comparer le dernier horodatage
  à `date +%s` et **refuser** de conclure au-delà de 5 s.
- **Le générateur lui-même.** Vérifié le 08/08 : dédoubler le générateur (2×200) ne change
  rien (≤ 4 % à 1, 4 et 8 workers) — mais c'est à revérifier dès qu'une configuration
  descend nettement sous la seconde.
- Le témoin d'**entrelacement** d'`agg.py` est obligatoire en mode 2 processus : deux
  générateurs qui se relaieraient au lieu de se superposer produiraient la moitié de la
  charge et un verdict faux.

## Après le test

Supprimer les players : `delete from cms_players where player_name like 'LOADTEST-%'`.
Sur une machine non jetable (Lenovo canary), empiler la configuration de test dans un
fichier compose **séparé** (`-f docker-compose.yml -f docker-compose.override.yml -f lt.yml`) :
l'override d'origine porte l'accélération NVIDIA, il ne doit jamais être remplacé.
