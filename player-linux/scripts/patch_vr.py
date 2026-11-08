#!/usr/bin/env python3
# PoC Phase 2 (jetable) : injecte video_renderer dans le display_config.json cache du player
# pour forcer le mode mpv DES le boot (sinon il n'arrive qu'au prochain changement d'item).
import json, os, sys
mode = sys.argv[1] if len(sys.argv) > 1 else 'mpv'
p = os.path.expanduser('~/.config/signflow-player/display_config.json')
d = json.load(open(p))
d['video_renderer'] = mode
json.dump(d, open(p, 'w'), indent=2)
print('patched video_renderer =', d.get('video_renderer'))
