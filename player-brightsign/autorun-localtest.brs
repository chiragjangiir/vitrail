' ============================================================================
' SignFlow — autorun-localtest.brs  (PoC Phase 0 — cache local natif BrightSign)
' ----------------------------------------------------------------------------
' BUT : prouver l'inconnue U1 (make-or-break) du plan NATIVE_CACHE_PLAN.md :
'   « le <video> d'une page HTTPS lit-il une source HTTP locale 127.0.0.1 ? »
'
' Ce que fait ce PoC :
'   1. (BOS 8.2+) pose les flags registre web security + web inspector.
'   2. Démarre un roHttpServer sur le port 8888 qui sert SD:/test.mp4 à /test.mp4.
'   3. Charge la page de test localtest.html (servie par le frontend) qui pointe
'      un <video> sur http://127.0.0.1:8888/test.mp4 et affiche le verdict à l'écran.
'
' À FAIRE PAR ED :
'   • Copier N'IMPORTE QUEL petit .mp4 (H.264) sur la racine de la carte SD,
'     nommé  test.mp4   (chemin device : /storage/sd/test.mp4).
'   • Renommer/copier ce fichier en  autorun.brs  sur la SD (sauvegarder l'ancien),
'     garder config.json (backend_url utilisé pour charger la page de test).
'   • Reboot. Lire le verdict à l'écran (panneau de droite) + DevTools distant via
'     chrome://inspect  ou  http://<ip-player>:2999  (même LAN).
'
' Les points « VERIFY » dépendent de la version BrightSignOS — on itère via l'inspector.
' ============================================================================

Sub Main()
    msgport = CreateObject("roMessagePort")

    ' ── Config (backend_url depuis config.json, comme l'autorun normal) ─────
    cfg = {}
    raw = ReadAsciiFile("config.json")
    if raw <> invalid and raw <> "" then
        parsed = ParseJson(raw)
        if type(parsed) = "roAssociativeArray" then cfg = parsed
    end if
    backend = ""
    if cfg.backend_url <> invalid then backend = cfg.backend_url

    w = 1920 : h = 1080
    if cfg.width <> invalid then w = cfg.width
    if cfg.height <> invalid then h = cfg.height

    ' ── (BOS 8.2+) Flags registre — websecurity:false ne suffit plus seul ───
    ' VERIFY noms de clés/section. Effet possible seulement au PROCHAIN boot
    ' (registre lu à l'init Chromium) → prévoir 2 reboots si pas d'effet au 1er.
    ' ⚠️ NOMS DE CLÉS AVEC ESPACES (doc BrightSign : « registry write html disable web security 1 »).
    ' L'ancien "disable_web_security" (underscores) était FAUX → flag jamais appliqué.
    ' Avec la page chargée en LOCAL (origine http, ci-dessous) on n'en a PAS besoin pour la vidéo,
    ' mais on les pose quand même (utile si on revient à une page https distante + inspector).
    reg = CreateObject("roRegistrySection", "html")
    if reg <> invalid then
        reg.Write("disable web security", "1")   ' autorise http loopback depuis page https (mixed-content)
        reg.Write("enable web inspector", "1")   ' DevTools distant (port inspector_server)
        reg.Flush()
    end if

    ' ── Serveur HTTP local : sert la PAGE + la vidéo sur 127.0.0.1:8888 ─────
    ' CHEMINS RELATIFS (l'autorun s'exécute depuis la racine SD — comme
    ' ReadAsciiFile("config.json") plus haut). L'ancien "/storage/sd/test.mp4"
    ' renvoyait 404 (fichier introuvable) -> cadre vidéo vide.
    ' On sert AUSSI localtest.html en LOCAL → la page sera chargée en
    ' http://127.0.0.1:8888 (même origine que la vidéo) → ZÉRO mixed-content.
    server = CreateObject("roHttpServer", { port: 8888 })
    if server <> invalid then
        server.SetPort(msgport)
        ok1 = server.AddGetFromFile({ url_path: "/test.mp4",      content_type: "video/mp4",                filename: "test.mp4" })
        ok2 = server.AddGetFromFile({ url_path: "/localtest.html", content_type: "text/html; charset=utf-8", filename: "localtest.html" })
        ok3 = server.AddGetFromFile({ url_path: "/",               content_type: "text/html; charset=utf-8", filename: "localtest.html" })
        print "roHttpServer add test.mp4="; ok1; " html="; ok2; " root="; ok3
    else
        print "roHttpServer indisponible !"
    end if

    ' ── roHtmlWidget : charge la page DEPUIS LE SERVEUR LOCAL (origine http) ──
    url = "http://127.0.0.1:8888/localtest.html"
    r = CreateObject("roRectangle", 0, 0, w, h)
    config = {
        url: url
        javascript_enabled: true
        brightsign_js_objects_enabled: true
        storage_path: "SD:/sf_html_storage"
        security_params: { websecurity: false }      ' + registry ci-dessus pour BOS 8.2+
        inspector_server: { ip_addr: "0.0.0.0", port: 2999 }   ' DevTools distant LAN
    }
    html = CreateObject("roHtmlWidget", r, config)
    html.SetPort(msgport)
    html.AllowJavaScriptUrls({ all: "*" })

    sleep(4000)       ' laisse réseau + serveur s'établir
    html.Show()

    ' ── Boucle de messages (retient server + html en scope = serveur actif) ──
    while true
        msg = wait(0, msgport)
        ' (PoC : on ne traite rien ; on garde juste le process vivant.)
    end while
End Sub
