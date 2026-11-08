# SignFlow — Clé USB bootable de validation matérielle

Une clé qui **boote Linux (Alpine, sans installer)**, lance **automatiquement** la validation
matérielle d'une machine candidate (CPU / RAM / stockage / GPU / réseau), **écrit un rapport sur
la clé** (dossier `rapports/`) et affiche le verdict à l'écran :

    VALIDÉ · VALIDÉ AVEC RÉSERVES · NON VALIDÉ

Idéal pour tester un boîtier **nu** (sans OS) avant d'installer SignFlow.

## Comment ça marche

- **Alpine « diskless »** boote depuis la clé et charge tous les pilotes (modloop).
- Un **overlay** (`localhost.apkovl.tar.gz`) remplace le login de `tty1` par le validateur
  (`validate.sh`) → il s'exécute seul au démarrage, écrit le rapport, puis éteint la machine.
- Boot **UEFI** par simple présence de `EFI/BOOT/BOOTX64.EFI` (grub autonome) → **aucune écriture
  brute de la clé n'est nécessaire**, on copie juste des fichiers sur une clé FAT32.

## Construire l'image (dans Docker)

```bash
cd installer/bootable
# produit ./out = les fichiers à copier sur la clé
docker run --rm -v "$PWD:/work/src:ro" -v "$PWD/out:/work/out" alpine:3.20 sh /work/src/build.sh
# (optionnel) tester le boot en QEMU + vérifier qu'un rapport est écrit
docker run --rm -v "$PWD:/work/src:ro" -v "$PWD/out:/work/out:ro" alpine:3.20 sh /work/src/test-boot.sh
```

## Déployer sur la clé USB

La clé doit être **FAT32** (partition unique). On **copie** l'arbre `out/` à la racine — rien à
formater ni à flasher (boot UEFI = fichiers) :

```
CLE:\
  EFI\BOOT\BOOTX64.EFI
  boot\vmlinuz-lts, initramfs-lts, modloop-lts, grub\grub.cfg
  localhost.apkovl.tar.gz
  signflow-check.conf
  rapports\        (créé au 1er boot)
```

Windows (PowerShell), la clé étant en E: :
```powershell
Copy-Item -Recurse -Force .\out\* E:\
```

La clé reste une clé FAT32 normale (les fichiers de la clé de test « manuelle » peuvent cohabiter).

## Utiliser sur une machine candidate

1. Brancher la clé, démarrer la machine, entrer dans le menu de boot (F12/F11/Esc selon le BIOS).
2. Choisir la clé USB en mode **UEFI**.
3. Le validateur se lance seul → verdict à l'écran → **rapport écrit dans `rapports\`** de la clé.
4. La machine s'éteint (40 s) ; relire le rapport sur un PC (fichier `.html`/`.txt`).

## Configuration

`signflow-check.conf` à la racine de la clé :
```
BACKEND=https://cms.example.com   # serveur testé (réseau/latence)
PROFILE=fhd                                   # fhd (1080p) ou 4k
```

## Limites

- **Boot UEFI** (machines ~2012+). Le legacy BIOS pur n'est pas couvert (ajout syslinux possible,
  nécessite une écriture du secteur d'amorçage — non fait pour rester « copie de fichiers » sûre).
- **Secure Boot** : `BOOTX64.EFI` (grub autonome) n'est **pas signé** → sur une machine avec Secure
  Boot actif, le démarrer échoue. Désactiver temporairement Secure Boot dans le BIOS (fréquent sur
  les boîtiers de signage). Signature shim/MOK = amélioration future si besoin.
- La détection de **résolution** est indicative en environnement live (pas de serveur graphique).
- Testé en **QEMU/UEFI** ; valider sur le vrai boîtier cible reste recommandé.
