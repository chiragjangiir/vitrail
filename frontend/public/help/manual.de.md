# Vitrail Benutzerhandbuch

## Willkommen bei Vitrail

Vitrail ist eine Digital-Signage-Plattform: Sie spielen Inhalte (Videos, Bilder, Webseiten, News-Feeds, Audio) auf Bildschirmen aus, die von Playern gesteuert werden — alles über eine zentrale Weboberfläche.

### Die wichtigsten Konzepte

- **Organisation**: Ihr Arbeitsbereich. Inhalte, Player und Benutzer sind von anderen Organisationen isoliert.
- **Player**: die Software auf dem Gerät am Bildschirm (Linux-NUC, Raspberry Pi, Windows-PC, Android-Box, Chromebox, BrightSign oder eine einfache Chrome-Erweiterung). Er holt seine Anweisungen vom Server — nie umgekehrt — und funktioniert auch offline weiter.
- **Medium**: ein importierter Inhalt (Video, Bild, Dokument) oder ein dynamischer (Webseite, Feed, HDMI-Eingang).
- **Playlist**: eine Abfolge von Medien in Dauerschleife.
- **Zeitplan (Schedule)**: wann und auf welchen Playern eine Playlist läuft.
- **Ereignis (Event)**: eine einmalige oder ausgelöste Ausstrahlung mit Vorrang vor dem normalen Zeitplan.
- **Kampagne**: Werbeinhalte von Werbetreibenden in Ihren Schleifen, verkauft als Share of Voice (Retail Media).

### Der typische Ablauf

1. **Player registrieren**: Provisioning-Token erzeugen, Player installieren, er erscheint unter Players.
2. **Inhalte importieren** in die Mediathek.
3. **Playlist erstellen** mit diesen Inhalten.
4. **Einplanen** der Playlist auf einem oder mehreren Playern.

Der Bildschirm zeigt den Inhalt wenige Sekunden nach dem Speichern des Zeitplans.

> Fehlt ein Menü oder eine Aktion? Vermutlich eine Rollenfrage: Fragen Sie Ihren Organisations-Administrator (siehe „Benutzer, Rollen und Sicherheit").

## Player

### Einen Player registrieren

Ein Player tritt Ihrer Organisation über ein **Provisioning-Token** bei:

1. **Players → Provisioning** → **Neues Token** (obere Leiste).
2. Maximale Player-Anzahl und Ablaufdatum wählen (oder „Ohne Ablauf").
3. Token (`sfp_…`) kopieren und bei der Player-Installation zusammen mit der Server-URL angeben.

Beim ersten Start tauscht der Player das Token gegen seine dauerhafte Identität und erscheint unter **Players**. Ein aktives Token kann **widerrufen** (registriert nicht mehr; bestehende Player laufen weiter) und danach gelöscht werden.

### Batch-Provisioning und USB-Stick

Der Dialog **Payload erzeugen** bereitet die Konfiguration mehrerer Geräte auf einmal vor: pro Gerät oder geteilte Einstellungen, CSV-Import, Auflösung (Auto/HD/FHD/4K/8K/benutzerdefiniert), WLAN, Wiederanbindung eines bestehenden Players (durchsuchbare Liste). Der Payload wird per USB-Stick auf vorbereitete Linux-Player angewendet, bei BrightSign per SD-Karte.

### Überwachen und aus der Ferne konfigurieren

Die Player-Liste zeigt den Zustand (online / offline / geplanter Standby) mit dem letzten Kontakt. Der Detailbereich eines Players zeigt: Gerät, Bildschirm, Netzwerk, Zeitzone, Medieninventar, aktuellen Screenshot, Decoding-Fähigkeiten.

Ohne SSH können Sie setzen: Auflösung, Drehung, Lautstärke, Ton, Render-Engine, Zeitzone, Bandbreitenlimit. Der Knopf **„Info auf dem Bildschirm"** blendet ein Diagnose-Panel direkt auf dem Player-Bildschirm ein (Name, Netzwerk, laufender Zeitplan, gespieltes Medium). Einmal-Aktionen: App neu starten, Gerät neu starten, Resync erzwingen, Screenshot. Die Schaltfläche **„Sammelbefehle“** in der oberen Leiste sendet denselben Befehl an ein ganzes Ziel (Organisation, Standort, Standortgruppe, Player-Gruppe); eine Vorschau listet die betroffenen Bildschirme **vor** dem Senden auf, und destruktive Befehle (Neustart, App beenden, Wartung) erfordern ein Bestätigungshäkchen **und Ihre PIN**.

Zwei „Kampagnen"-Einstellungen liegen ebenfalls hier: **Von Werbekampagnen ausgeschlossen** (Opt-out) und die **Werbe-Belegungsobergrenze** (siehe Kampagnen).

### Gruppen und LAN-Synchronisation

**Player-Gruppen** dienen als Ausspielziel und tragen die **LAN-Synchronisation**: mehrere Player im selben lokalen Netz spielen dasselbe Video bildgenau (Videowand, stimmige Atmosphäre). Die Synchronisation ist zuverlässig, wenn die Gruppe **homogen** ist (gleiche Hardware) und die Player dieselbe Uhr teilen (siehe NTP). Ein Gruppenmitglied kann als **NTP-Relais** bestimmt werden.

### Chrome-Erweiterung (ohne Hardware)

Die Chrome-Erweiterung macht aus einem Browser einen Player: ideal zum Testen oder für einen vorhandenen Arbeitsplatz. Erweiterung laden (Entwicklermodus), Server-URL und ein `sfp_…`-Token eingeben. Grenzen: keine LAN-Synchronisation, eingeschränkter Offline-Modus. Für einen echten ChromeOS-Kiosk nutzen Sie den ChromeOS-PWA-Player.

## Standorte (Sites)

Ein **Standort** steht für einen physischen Ort (Filiale, Geschäft). Jeder Player ist einem Standort zugeordnet.

- **Zeitzone**: die gesamte Planung läuft in der Ortszeit des Standorts. Ein zugeordneter Player wird automatisch auf die Zeitzone des Standorts ausgerichtet (Warnhinweis bei Abweichung, Fernkorrektur aus dem Detailbereich).
- **Öffnungszeiten**: Tage und Uhrzeiten, mit **datierten Ausnahmen** (Feiertag, Inventur, Abendveranstaltung) und automatischer Schließung an **Feiertagen** (optionaler Regionalkalender). Ein Tag ohne Zeiten gilt als geschlossen. Diese Zeiten steuern die Bildschirmversorgung (siehe „Bildschirme und Strom") und sind dem Assistenten bekannt („hat Standort X sonntags geöffnet?").
- **NTP-Server**: damit alle Player des Standorts exakt dieselbe Uhr teilen (unerlässlich für die LAN-Synchronisation).
- **Koordinaten**: Standort auf der Karte platzieren (für Geo-Berichte und das Werbeportal).
- **Ausgeschlossene Kategorien**: Branchenkategorien, die an diesem Standort keine Werbung schalten dürfen (siehe Kampagnen).
- Der Reiter **Standortgruppen** erstellt Mengen (Region, Marke) als Ziel in Zeitplänen, Ereignissen, Kampagnen und Updates.

Beim Überfahren eines Standorts (Liste) fasst ein Tooltip seine Player und die 7-Tage-Werbebelegung zusammen.

## Mediathek

### Importieren

**Mediathek → Importieren**: Videos, Bilder, Dokumente (PDF). Der Reiter **Freie Fotos** schöpft aus Unsplash/Pexels mit automatischer Attribution. Ein Video wird automatisch in ein universelles Format transkodiert: der bisherige Inhalt läuft während der Verarbeitung weiter, kein Bildschirm wird schwarz. Ist die **Renditions**-Richtlinie der Organisation aktiv, erzeugt ein 4K-Video zusätzlich eine Full-HD-Version — jeder Player erhält die zu seinem Bildschirm passende Auflösung.

### Organisieren

- **Ordner** und Unterordner (linke Spalte), Massenverschiebung.
- **Tags**: Taxonomie nach Namensräumen (Mediathek → Tags), Mehrfachzuweisung und **Tag-Filterung auf Player-Ebene** (ein Player spielt nur Inhalte, die zu seinen Tags passen).
- Suche, Typfilter (Bilder/Videos/Audio/Dokumente/Webseiten), Paginierung.

### Lebenszyklus verwalten

- **Datei ersetzen** ohne die Identität des Mediums zu ändern: Playlists bleiben unberührt, der Wechsel erfolgt atomar am Ende der Transkodierung.
- **Sicher löschen**: der Auswirkungsdialog listet Playlists, Zeitpläne, Ereignisse und Audio-Körbe, die das Medium nutzen, samt Ausspielstatus, vor der kaskadierenden Löschung.
- **Quarantäne**: ein Medium sofort flottenweit sperren (auch offline), danach entsperren oder den Cache leeren.
- **Konformität**: jedes Video trägt ein Urteil (bereit / abspielbar / nicht konform) zu seiner Kodierung, mit Neuanalyse und Passthrough-Modus (Originaldatei ohne Neukodierung behalten).

## Vorlagen (Templates)

**Vorlagen** definieren Mehrzonen-Layouts (Hauptvideo + Laufband + Logo…). Der Editor arbeitet in der deklarierten **Canvas-Auflösung** (FHD, 4K, Hochformat, LED nach Maß) — wählen Sie die Auflösung des Zielbildschirms. Eine mit einer Vorlage verknüpfte Playlist speist deren Zonen; eine Warnung erscheint, wenn die Vorlagenauflösung nicht zum Zielbildschirm passt.

## Playlists

1. **Playlists → Neue Playlist**, dann Medien hinzufügen (Mehrfachauswahl, Suche, Ordner).
2. Reihenfolge, Anzeigedauer von Bildern/Dokumenten und Zone festlegen (bei Mehrzonen-Vorlagen). Die **Videos zeigen ihre native Dauer** — sie lässt sich ablesen, nicht einstellen.
3. Änderungen sammeln sich als **Entwurf**: der Knopf **Veröffentlichen** schiebt sie in einem Zug zu den Playern (sauberer Wechsel, nie ein leerer Zustand).

Die Kopfzeile des Editors und jede Playlist-Kachel zeigen **die Anzahl der Inhalte und die Gesamtdauer** der Schleife; die Summe folgt Ihren Änderungen live, Entwurf eingeschlossen.

### Eine Playlist ansehen

Die **Wiedergabe**-Schaltfläche — auf der Karte einer Playlist oder im Editor — spielt die Schleife so ab, wie es ein Bildschirm täte. Bei einer Playlist mit einer **Mehrzonen-Vorlage** setzt die Vorschau alle Zonen gleichzeitig zusammen, im Seitenverhältnis der Vorlage, wobei jede Zone mit ihrem eigenen Timer weiterschaltet.

Es ist eine Vorschau, kein Spiegel eines Bildschirms: Jede Zone beginnt am Anfang ihrer Schleife, und Rotation, Kampagnen-Spots und Tag-Filterung werden hier nicht nachgespielt. Feeds, Webseiten und HDMI-Eingänge erscheinen mit ihrem Namen an ihrem tatsächlichen Platz und in ihrer tatsächlichen Größe — sie werden auf dem Bildschirm erzeugt, im Moment der Ausstrahlung.

### Ausspielregeln pro Element

Jedes Element kann eine eigene Regel tragen: Wochentage, Zeitfenster, Gültigkeitszeitraum — in der Ortszeit des Players. **Ausnahmen pro Ziel** verfeinern: ein bestimmter Player oder eine Gruppe spielt das Element nach einer anderen Regel. Ein Element ohne Regel läuft unbegrenzt.

### Rotations-Playlist (N Elemente pro Durchlauf)

Eine Playlist kann als Element **in einer anderen verschachtelt** werden (Knopf **Playlist hinzufügen** im Editor). Ihre **Rotations-Einstellung** bestimmt das Verhalten:

- **Alle Elemente**: die Sub-Playlist läuft bei jedem Durchlauf vollständig.
- **N pro Durchlauf — der Reihe nach**: N Element(e) pro Durchlauf, die nächsten im nächsten Durchlauf (bei 5 Videos und 2 pro Durchlauf: 1-2, dann 3-4, dann 5-1…).
- **N pro Durchlauf — zufällig**: gemischte Reihenfolge, aber kein Element wiederholt sich, bis alle gespielt wurden; danach wird neu gemischt.

Nur eine Verschachtelungsebene ist erlaubt; eine als Sub-Playlist referenzierte Playlist kann nicht gelöscht werden (zuerst aus den Eltern-Playlists entfernen). Regeln und Tags pro Element liegen auf den Elementen **der Sub-Playlist**. Die Rotation bleibt zwischen Bildschirmen einer LAN-Gruppe **synchron**, und die **Timeline-Simulation** zeigt den tatsächlichen Ablauf Durchlauf für Durchlauf. Erscheint dieselbe Sub-Playlist **mehrfach** in einem Durchlauf, spielen alle Vorkommen das **gleiche Element im gleichen Durchlauf** (geteilte Ziehung — garantiert den Determinismus); für Abwechslung innerhalb eines Durchlaufs erhöhen Sie stattdessen „Elemente pro Durchlauf“.

Diese Einstellungen **folgen dem Entwurf** wie die Inhalte: Werden sie geändert, erscheint der Hinweis „Nicht veröffentlichte Änderungen“, und die Bildschirme spielen weiterhin die veröffentlichte Schleife, bis Sie auf **Veröffentlichen** klicken (bzw. bis zur **Freigabe** bei einer moderierten, gesteuerten Playlist).

## Audio-Körbe

**Audio-Körbe** liefern Hintergrundbeschallung im Geschäft, unabhängig vom Bildinhalt: Hintergrundmusik, Jingles in Intervallen oder zu festen Zeiten, mit automatischem **Ducking** (die Musik senkt sich während eines Jingles). Jeder Player hat eine **Audio-Rolle**: Standardinhalte (Videoton), nur Audio, oder gemischt (Hintergrund + stummgeschaltete Videos). Das **Filial-Bedienpanel** (LAN) lässt das Personal vor Ort ohne CMS-Konto agieren. Jede Korb-Kachel zeigt **die Anzahl der Titel und die Gesamtdauer**. Musikrechte-Berichte stützen sich auf nachgewiesene Wiedergaben.

## Zeitplanung

Ein **Zeitplan** sagt, was ausgespielt wird (eine Playlist), wo (Player, Gruppen, Standorte, Standortgruppen, Tags) und wann (Tage, Zeitfenster, Gültigkeitszeitraum, Priorität).

1. **Zeitplanung** → Regel anlegen, Playlist, Ziele und Zeitfenster wählen.
2. Die betroffenen Player aktualisieren sich in Sekunden.
3. Der **einheitliche Kalender** überlagert visuelle und Audio-Programme, Events und Kampagnen (Legende mit Symbolen). Filtern Sie nach Typ (Alle/Visuell/Audio/Events/Kampagnen) oder nach **Ziel** (Standortgruppe, Standort, Player); der **CSV-Export** folgt den aktiven Filtern. Bei Überlappung gewinnt die höchste **Priorität**.

Netze mit mehreren Ebenen (Zentrale, Regionen, Märkte) stellen ihre Programmierung mit der **hierarchischen Governance** zusammen — siehe den eigenen Abschnitt weiter unten.

## Hierarchische Governance (Multi-Standort-Netze)

Die **Governance** ist für Netze gedacht, in denen mehrere Ebenen über den Inhalt entscheiden: eine Zentrale, Regionen, Märkte. Jede Ebene stellt **ihren** Teil der Programmierung zusammen, und die Bildschirme spielen die **Summe** der Ebenen, von denen sie abhängen. Eine Einzelstandort-Installation braucht das nicht: ohne Knoten ändert sich nichts (das Feld „Eigentümer-Knoten“ wird gar nicht angezeigt).

### Die fünf Begriffe

- **Der Knoten** ist eine Ebene der Organisation. Seine **Ebene** im Baum (Wurzel = 0) legt die Reihenfolge national → lokal fest, nicht sein „Typ“, der nur ein Etikett ist.
- **Der Bereich** ist die Menge der Bildschirme, die ein Knoten steuert: Sie hängen ihm Bildschirme, Bildschirmgruppen, Standorte oder Standortgruppen an. Der Bereich eines Knotens **schließt den seiner Nachfahren ein** — es genügt, die Standorte an die Marktknoten zu hängen.
- **Die Ebene (Layer)**: jedes einem Knoten zugeordnete Programm erzeugt eine Ebene. Ein Bildschirm kompiliert alle Ebenen der Knoten, von denen er abhängt. Genau das zeigt die Spalte „Kompiliertes Programm“, **für diesen Bildschirm und zu diesem Zeitpunkt**.
- **Die Regel** legt fest, wie viel jede Ebene nehmen darf. Am häufigsten ist „**Inhalte pro Runde**“: mit 1 platziert jede Ebene einen Inhalt pro Runde und **rotiert** ihre Inhalte.
- **Der Knoten-Administrator** entscheidet für diesen Knoten. ⚠️ Eine Berechtigung genügt **nie**: erst diese Zuweisung erlaubt das Schreiben.

### Wer darf was

Ein Knoten-Administrator handelt auf **seinem Knoten und dessen gesamtem Teilbaum**. Die Ebenen darüber sieht er **nur lesend**, benachbarte Zweige sieht er **gar nicht**. Drei Handlungen steigen immer eine Stufe auf: einen Inhalt aus der Governance **lösen**, die **Moderation entfernen** oder eine **Einschränkung aufheben**, und eine Einreichung **freigeben** — der Prüfer muss einen **übergeordneten** Knoten verwalten, und niemand gibt seine eigene Einreichung frei. Einen **Wurzelknoten** anzulegen ist dem Organisations-Administrator vorbehalten.

- **Governance — Direktor**: Baut die Struktur: Knoten, Bereiche, Administratoren, Regeln. Liest Inhalte, erzeugt sie nicht.
- **Governance — Programmierer**: Erstellt die **Programme** und **Playlists** seiner Knoten, reicht zur Freigabe ein.
- **Governance — Redakteur**: Erzeugt Inhalte (Playlists, Medien) und reicht sie ein. Löscht keine Medien, programmiert nicht.
- **Governance — Prüfer**: Gibt frei, lehnt ab oder fordert Änderungen in seinem Teilbaum.

Diese vier Rollen tragen eine **Bereichssemantik**: ihr Inhaber handelt nur in seinem Teilbaum, und **nicht verwalteter Inhalt ist für ihn unsichtbar**.

### Verwalteter Inhalt

Eine Playlist, ein Medium, eine Vorlage, ein Ereignis und eine VOD-Konfiguration können einem Knoten gehören (Feld „Eigentümer-Knoten“). Ohne Knoten gehört das Objekt der Organisation und verhält sich wie bisher. Ein zugeordnetes Objekt kann nur von den Administratoren seines Knotens oder eines übergeordneten Knotens bearbeitet werden; ist der Knoten als **„Inhalt freigabepflichtig“** markiert, wird **eingereicht** statt veröffentlicht, und die Freigabe veröffentlicht. Diese Moderation wird **nach unten vererbt**.

⚠️ **Zwei teure Missverständnisse.** Eine Playlist einem Knoten zuzuordnen entscheidet, **wer sie bearbeitet**; es **sendet sie nicht** — das Senden kommt von einem **Programm** am selben Knoten. Und die **Rolle** sagt, was man tun darf, die **Administrator-Zuweisung** sagt **wo**.

### Nur einen Teil der Bildschirme eines Knotens ansprechen

Standardmäßig läuft ein einem Knoten zugeordnetes Programm auf **allen** seinen Bildschirmen. Um nur einen Teil anzusprechen, fügen Sie **Ziele** hinzu: sie **schränken** den Bereich ein, erweitern ihn nie, und eine untere Ebene kann eine **geerbte** Ebene nie einschränken. Ein Ziel, das keinen Bildschirm behält, wird namentlich abgelehnt, und die Anzahl der behaltenen Bildschirme wird angezeigt. **Ein Programm ohne Ziel zu lassen ist oft richtig**: es deckt dann seinen ganzen Knoten ab, auch später hinzugefügte Standorte.

### Vollständiges Beispiel: Eingang und Ausgang eines Marktes

Ziel: in jedem Markt spielen der **Eingangs-** und der **Ausgangsbildschirm** einen Inhalt **mehr** als die übrigen, und der Marktleiter ändert seine Inhalte und Programme selbst.

**Der Baum** — `National` → `Dpt-01` → `Site-01`, `Site-02`.

**Der Bereich** — man hängt **den Standort** an den Marktknoten. Abteilung und National haben **keine Zuweisung**: sie erben aus dem Teilbaum.

**Zwei Bildschirmgruppen** — „Eingänge“ enthält den Eingangsbildschirm **jedes** Marktes, „Ausgänge“ die Ausgänge. Die Gruppe markiert die **Rolle** des Bildschirms, der Knoten den **Markt**: die Kreuzung beider bezeichnet den richtigen Bildschirm, ohne eine Gruppe pro Markt anzulegen.

**Die Inhalte** — jeder Markt besitzt **seine eigenen** Playlists: lokal, Eingang, Ausgang. 🔑 Eine zwischen zwei Märkten geteilte Playlist kann nur ihr Eigentümer bearbeiten — der andere Leiter kann sie nicht einmal lesen.

**Die Programme** — eines pro Knoten, plus zwei pro Markt:

- **National** — Programm „SC National“, **ohne Ziel**: alle Bildschirme des Netzes.
- **Dpt-01** — Programm „SC Dpt“, **ohne Ziel**: alle Bildschirme der Abteilung.
- **Site-01** — Programm „SC Site-01“, gezielt auf die Bildschirme des Marktes: lokaler Inhalt.
- **Site-01** — Programm „SC Eingang Site-01“, gezielt auf die Gruppe „Eingänge“: nur der Eingang.
- **Site-01** — Programm „SC Ausgang Site-01“, gezielt auf die Gruppe „Ausgänge“: nur der Ausgang.

Mit „Inhalte pro Runde = 1“ auf jedem Knoten spielen gewöhnliche Bildschirme **3 Inhalte pro Runde** (national + Abteilung + lokal), Eingang und Ausgang je **4**.

**Einen Markt hinzufügen** sind dann fünf Schritte: den Knoten unter der Abteilung anlegen, den Standort daran hängen, seine drei Playlists anlegen, seine drei Programme anlegen, seinen Eingangsbildschirm der Gruppe „Eingänge“ und den Ausgangsbildschirm der Gruppe „Ausgänge“ hinzufügen. Die Programme von National und Abteilung bleiben unberührt.

### Einen Bereich im großen Maßstab zusammenstellen

Die Schaltfläche **„Bildschirme hinzufügen“** öffnet eine **serverseitige** Suche: filtern Sie nach Art (Bildschirm, Bildschirmgruppe, Standort, Standortgruppe), wählen Sie **mehrere Ziele auf einmal**, und jede Zeile nennt **wie viele Bildschirme sie darstellt**. Ein Bildschirm, der noch **keinem** Knoten zugeordnet ist, wird angeboten und **etikettiert**: so wird eine vergessene Installation sichtbar und reparierbar.

### Umstellen und diagnostizieren

Ein Knoten kann unter einen anderen Elternknoten **verschoben** werden: Pfade, Ebenen und Ausspielung des gesamten Teilbaums folgen. Er kann nicht unter einen eigenen Nachfahren verschoben werden, auch nicht in einen Zweig, den man nicht verwaltet.

Ist die Vorschau eines Bildschirms leer, **nennt die Meldung die Ursache**: kein Knoten, kein Programm am Knoten, inaktives Programm, keine Playlist, **keine Zeitregel** (es wird nie aktiv), oder außerhalb seines Fensters zu diesem Zeitpunkt.

## Ereignisse

Ein **Ereignis** hat vorübergehend Vorrang vor dem Zeitplan: Aktion, Durchsage, ausgelöster Inhalt.

- Inhalt: eine Playlist oder ein einzelnes Medium. Ziel: Organisation, Standort, Gruppe oder Player — und die Typen lassen sich in einem Ereignis **mischen** („dieser Standort“ + „diese 3 Bildschirme“, wie bei Kampagnen): die Auswahlen summieren sich, die Zusammenfassung nennt alles Enthaltene. „Gesamte Organisation“ ersetzt die anderen Auswahlen.
- Typen: **manuell** (auf Abruf ausgelöst), **geplant** (Datums-/Zeitfenster, optional wiederkehrend).
- **Stunden-Spot**: bei einem geplanten Ereignis auf „Einmal abspielen" die Wiederholung in festem Intervall aktivieren (z. B. ein Spot alle 30 Minuten). Das Feld erscheint nur in dieser Kombination.
- **Referenz-Zeitzone** (geplantes Ereignis): sie legt fest, was „18:00" bedeutet. Standard ist die Server-Zeitzone. In einem Netz über mehrere Länder sollte sie ausdrücklich gewählt werden — ein Ereignis startet zu **einem einzigen Zeitpunkt**, nicht um 18:00 in jedem Land. Die Zeitzone steht in der Liste neben der Uhrzeit.
- ⚠️ Nicht zu verwechseln mit dem **Embargo**, einem **absoluten** Zeitpunkt (UTC): es hängt von keiner Zeitzone ab und wird von dieser Einstellung nicht berührt.
- Option **„Bildschirme anlassen"**: hält die Anzeige während des Ereignisses auch außerhalb der Öffnungszeiten aktiv.
- Am Ende kehrt der Player exakt zu seinem Zeitplan zurück (aktuelle Uhrzeit).
- Ein **mitten im Zeitfenster (re)aktiviertes** Ereignis mit einem nie zuvor verteilten Medium kann einige Minuten brauchen, bis es erscheint (der Player lädt die Datei zuerst herunter — nie ein schwarzer Bildschirm). Vorab aktivieren/planen für einen sofortigen Wechsel.

## On-Demand-Ausspielung (VOD)

Die Seite **On-Demand** spielt einen Inhalt sofort aus, über dem Zeitplan, ohne Playlists anzufassen. Eine **VOD-Konfiguration** bündelt Medien und ein Ziel: entweder **ausgewählte Player** (desselben Standorts) oder einen **gesamten Standort** – dann wird jeder später hinzugefügte Player automatisch berücksichtigt; die Medien sind vorab heruntergeladen, das Auslösen ist sofort: **Einmal** oder **Schleife** (bis Stop). Die Berechtigung `vod : trigger` allein genügt für ein „Filial"-Konto. Danach setzt der Zeitplan zur aktuellen Uhrzeit fort.

> **BrightSign**-Besonderheiten: Start und Stopp können **bis zu 2 Sekunden** dauern (integriertes lokales Relais) — das ist normal. Während der Ausspielung ist die Playlist ausgesetzt (nur ein Hardware-Videostream auf diesen Playern) und setzt danach zur aktuellen Uhrzeit fort. Der erste Vorab-Download kann bei 4K-Dateien dauern: solange ein Medium nicht im Cache ist, wird gestreamt (verzögerter Start).

## HDMI-Eingang

Das Medium **„HDMI-Eingang"** zeigt jede am HDMI-Eingang des Players angeschlossene Quelle (TV-Receiver, Box, Konsole) — rein lokale Wiedergabe. Kompatibel: BrightSign mit physischem HDMI-Eingang (Reihen XT, 4K114x, XD1230).

- **In einer Playlist**: ein Zeitfenster schaltet auf die Quelle um und setzt dann die Playlist fort; Player ohne Eingang überspringen das Element. Ohne Signal zeigt der Bildschirm „No Signal Detected" (nie ein schwarzes Bild).
- **Auf Abruf**: über eine VOD-Konfiguration, Knöpfe **Auf HDMI umschalten / Zurück zur Playlist** (Fortsetzung zur aktuellen Uhrzeit).
- **Lokale Seite**: jeder kompatible BrightSign bietet `http://<ip>:8888/control` — umschalten/zurück von jedem Telefon im Geschäft, ohne Konto und Server (Aktivierung + PIN pro Player).
- Schutzmechanismen: eine aktive Umschaltung wird beim Abschalten des Bildschirms beendet; jede Sitzung wird protokolliert (Audit + signierter Wiedergabenachweis mit der realen Dauer).

## Feeds und Webseiten

### Feeds (Nachrichtenströme)

Ein **Feed** ist eine vom Server abgefragte Quelle: RSS/Atom, Google News, YouTube, Wetter, Krypto, Finanzen, soziale Netzwerke (über den Feed-Proxy). Anzeigemodi: Laufband, Karussell, Raster, Vollbild-Artikel, geteiltes Layout, Liste, Social Wall, Diagramm. Optionen: **KI-Zusammenfassung** der Artikel (ein Satz, aus der Ferne lesbar), **Moderation** (jeden Artikel vor der Ausstrahlung freigeben), Vorschaubilder im Player-Cache (funktioniert offline).

### Webseiten (URL Display)

Zeigen Sie eine Webseite auf dem Bildschirm: **WebView**-Modus (Live-Rendering auf dem Player) oder **Server-Aufnahme** (der Server fotografiert die Seite periodisch — für Seiten, die das Einbetten verweigern oder serverseitige Anmeldung brauchen). Eine Webseite ist ein Medium wie jedes andere: Tags, Playlists, Zeitplanung.

## KI-Generierung

Vitrail generiert Bilder, Videos, Musik und Sprecherstimmen aus einer Beschreibung. Das erzeugte Medium landet ganz normal in der Mediathek.

- **Voraussetzung**: die KI-Schlüssel Ihrer Organisation (**Einstellungen → KI-Schlüssel**) — fal.ai (Bilder/Videos/Musik/Stimme), ElevenLabs (Pro-Audio), Anthropic (Prompt-Assistent und Studio). Sie zahlen Ihren eigenen Anbieter; ohne Schlüssel bleibt die Funktion inaktiv.
- **Wo**: Mediathek → **Generieren (KI)** für ein einzelnes Asset; **Studio** für eine komplette Kampagne aus einem Briefing (Konzepte je Format, Gesamtkosten vor dem Start angezeigt).
- **Prompts**: die Modelle arbeiten auf Englisch — der **Prompt-Assistent** verwandelt Ihre Idee (jede Sprache) in einen optimierten englischen Prompt + Negativ-Prompt. Einfach bleiben: Motiv + Aktion + Stil; für Video Kamera und Licht ergänzen; nie Meta-Anweisungen („Werbeinhalt…" wird sonst ins Bild gemalt).
- **Bearbeitung**: Freistellen (Hintergrund entfernen), Retusche per Anweisung, mehrere Varianten, Bild → Video (nur die Bewegung beschreiben).
- Eine **Kostenschätzung** erscheint vor jeder Generierung.

## Promo-Generator

Der **Promo-Generator** erstellt ein Werbeplakat (Bild oder kurzes Video) aus einem Produkt, einem Preis und einem Layout. Das Ergebnis landet in der Mediathek und wird wie jedes andere Medium ausgespielt.

- **Wo**: Mediathek → **Promo-Generator**.
- **Ein Ablauf in sechs Schritten**: **Für wen?** · **Das Produkt** · **Text und Preis** · **Layout** · **Hintergrund** · **Freie Bearbeitung**. Es ist immer nur ein Schritt geöffnet, damit alle seine Felder auf den Bildschirm passen; zugeklappt **zeigt ein Schritt seinen Wert**. Die Reihenfolge ist frei.
- **Zuerst „Für wen?"**: die eigene Marke oder ein Werbekunde — die **Markenrichtlinie ergibt sich daraus** (Farben, Schrift, Logo, Hinweise), statt gewählt zu werden.
- **Von einer Produkt-URL ausgehen**: Adresse einer Produktseite einfügen, Name, Preis und Foto werden übernommen. Alles bleibt änderbar — eine Eingabehilfe, keine Quelle der Wahrheit.
- **Der Preis ist Pflicht.** **Erzeugen** bleibt aus, solange er fehlt, und der Hinweis unter der Vorschau nennt das Fehlende **und führt zum richtigen Schritt**. Derselbe Hinweis meldet Lesbarkeitsprobleme, die der Server vor der Erzeugung erneut prüft.
- **Die KI macht nur den Hintergrund** (und stellt das Produkt frei). Preis, Rabatt, Name und Rechtshinweise setzt das Compositing aus Ihrer Eingabe — also exakt.
- **Verketten**: „Mit anderem Produkt wiederholen" behält Marke, Layout, Hintergrund und Hinweise; **Voreinstellungen** rufen eine komplette Konfiguration ab.

### Serienmodus — ein Layout, N Produkte

Der Umschalter **Ein Visual / Serie** oben ersetzt die Vorschau durch eine **Tabelle**: eine Zeile je Visual. Der Ablauf links definiert weiterhin das **Gemeinsame** (Marke, Layout, Hintergrund, Hinweise, Währung); die Tabelle trägt nur das **Wechselnde** — Produkt, Slogan, Preis, Streichpreis, Rabatt.

- **Drei Wege, sie zu füllen, kombinierbar**: eine Zeile von Hand ergänzen, eine **CSV importieren** oder **aus einer Tabelle einfügen** (Excel, Google Sheets). Kopfzeilen werden auf Deutsch, Französisch und Englisch erkannt, in beliebiger Reihenfolge. ⚠️ Ohne erkannte Kopfzeile werden die Spalten **der Reihe nach** gelesen, und der Bildschirm sagt es — prüfen Sie die Tabelle.
- **Der Import ergänzt**, er ersetzt nicht: zwei Dateien nacheinander oder Nacharbeit von Hand sind möglich.
- **Eine Zeile ohne Preis stoppt die Serie nicht**: sie wird hervorgehoben, im Hinweis benannt und übersprungen. Die Schaltfläche nennt die Zahl der tatsächlich erzeugten Visuals.
- Jedes Visual wird **nach seinem Produkt benannt**, sonst landeten alle unter demselben Namen in der Mediathek.

## Markenrichtlinien

Eine **Markenrichtlinie** legt Farben, Schrift, Logo, Rechtshinweise und Ton einer Marke ein für alle Mal fest. Der **Promo-Generator** füllt damit anschließend jedes Motiv vor.

- **Zwei Geltungsbereiche**: eine Richtlinie für Ihre **Organisation** und eine je **Werbekunde**. Wird ein Motiv für einen Werbekunden erstellt, gilt dessen Richtlinie, sonst die der Organisation.
- **Wo**: Promo-Generator → Schaltfläche **Markenrichtlinien und Schriften** in der oberen Leiste. Nur für Organisationsadministratoren.
- **Eine Richtlinie ersetzt nur, was sie festlegt**: eine nicht angehakte Farbe bedeutet „die Richtlinie sagt nichts", und die Vorlage behält ihre eigene. So lässt sich eine einzelne Akzentfarbe vorgeben, ohne die übrigen zu überschreiben.
- **Sie füllt vor, sie sperrt nicht**: bei einem konkreten Motiv gewinnt Ihre Eingabe gegen die Richtlinie. Rechtshinweise werden nur einmal übernommen — löschen Sie sie bewusst, kehren sie nicht zurück.
- **Logo und Markenname werden nie von der KI gezeichnet**: ein erzeugter Hintergrund erhält nur Palette und Ton als anzustrebende Atmosphäre. Logo, Markenname und Hinweise setzt anschließend das Compositing, also exakt. Die Schaltfläche „Markenlogo platzieren" fügt es als verschiebbare Ebene ein.
- Solange keine Richtlinie besteht, ändert sich nichts: die Motive behalten die Farben ihrer Vorlage.

## Kampagnen (Retail Media)

Die Seite **Kampagnen** verkauft Ihre Bildschirme als Werbeinventar: ein Werbetreibender kauft einen **Share of Voice (SOV)** — einen Prozentsatz der Sendezeit — über einen Zeitraum und eine Menge von Bildschirmen.

### Werbetreibende und Konkurrenzausschluss

Legen Sie Ihre **Werbetreibenden** an (Seite Werbetreibende): jeder erhält einen Mediathek-Ordner „Werbetreibende/<Name>" und eine oder mehrere **Branchenkategorien**. An jedem **Standort** listen Sie die **ausgeschlossenen** Kategorien: betroffene Werbetreibende können diesen Standort weder anvisieren noch dort ausspielen (durchgesetzt in Targeting, Belegung, Angebot, Bericht, Portal und Ausspielung).

### Kampagne anlegen und veröffentlichen

Eine Kampagne = Zeitraum (+ optionales tägliches Zeitfenster), **verkaufter SOV in %**, Preis (SOV-basiert oder pauschal, manuell erfasst — ein **Richtangebot** wird aus den Bildschirmtarifen berechnet), Ziele (kumulierbar: Org, Standorte, Standortgruppen, Gruppen, Player) und Werbemittel (Videos/Bilder, gewichtete Rotation). Status: Entwurf → veröffentlicht (geplant / live / beendet), Pause (sofortige Entfernung von den Bildschirmen), Fortsetzung, Stornierung.

- **Inventar**: die Belegungsprognose warnt bei 80 % und blockiert bei 100 % der **Obergrenze** jedes Bildschirms (Obergrenze je Player oder Standort einstellbar — z. B. Kassenbildschirm auf 20 % begrenzt); ein Org-Admin kann erzwingen (bewusste Überbuchung).
- **Tarife**: € je 1 % SOV pro Tag, vererbt Org → Standort → Player.
- **Erreichbarer SOV**: ein gelber Hinweis warnt, wenn der gewünschte SOV über das hinausgeht, was die tatsächlich geplante Schleife erlaubt, mit einem Knopf „X % verwenden".
- **Maximale Werbemitteldauer**: je Org einstellbar (Standard 30 s) — Ablehnung beim Hinzufügen, erneute Prüfung beim Veröffentlichen.
- **Werbemittel-Freigabe** (optional, je Org): jedes neue Werbemittel startet „Ausstehend" und muss vor der Ausstrahlung freigegeben werden.
- **Kalender**: monatliches Gantt der Kampagnen mit Tageslast (gelb/rot).
- **Import**: komplette Kampagne aus einer JSON-Datei (Dry-Run-Vorschau, Anlage als Entwurf, manuelle Veröffentlichung), auch **per API** mit einem `sfi_`-Schlüssel.

### Ausspielung, Nachweis und Bericht

Die Werbemittel werden **in die bestehende Schleife eingefügt**, in der Frequenz des verkauften SOV — nie zwei Spots hintereinander (höchstens eine Werbung pro Schleifendurchlauf; der Überschuss wird zu gemessener, alarmierter Unterlieferung). Jeder Durchlauf erzeugt einen vom Bildschirm **signierten Wiedergabenachweis**. Der **Werbekundenbericht** liefert Durchläufe, Sendezeit, gelieferten vs. verkauften SOV, hierarchische Aufschlüsselung Gruppen → Standorte → Bildschirme, Betrag — **White-Label-PDF**-Export und **geschützter öffentlicher Link** (Passwort, IP-Allowlist). Benachrichtigungen: Kampagne gestartet / beendet / **untergeliefert**.

## Werbeportal (Advertiser Portal)

Das **Portal** (`/portal`) ist der White-Label-Bereich Ihrer Werbetreibenden: jeder sieht nur **seine eigenen** Kampagnen.

- **Zugang öffnen**: Detailbereich des Werbetreibenden → Abschnitt Portalzugang → per E-Mail einladen (Startpasswort wird nur einmal angezeigt). Ein Werbekonto landet immer im Portal, nie im CMS.
- **Der Werbetreibende kann**: seine Kampagnen und Berichte verfolgen (PDF), **eine Kampagne anlegen** (Standorte auf der Karte — mit seiner Kategorie unvereinbare Standorte sind ausgegraut —, Zeitraum, SOV oder **Exklusiv** = 100 %, aggregierte Verfügbarkeit ok/knapp/voll und **Live-Angebot**), Werbemittel hochladen (einstellbare Kontingente, Standard 20 Dateien / 1024 MB — stets vor der Ausstrahlung geprüft), **zur Freigabe einreichen**, bei Änderungswünschen korrigieren und erneut einreichen, **Standortlisten** speichern, seine **Sprache** wählen (5 verfügbar).
- Aktiviert die Organisation die **„Auswahl je Bildschirm (Portal)"**, kann der Werbetreibende einzelne Bildschirme je Standort ankreuzen.
- Eine **Glocke** informiert über Entscheidungen (plus E-Mail, wenn Sie es bei der Entscheidung ankreuzen).

## Freigaben (Approvals)

Die Seite **Freigaben** bündelt die Freigabeanfragen — aktuell Kampagnen (aus dem CMS oder dem Portal eingereicht).

1. **Einreichen**: „Zur Freigabe einreichen" (nur eine aktive Anfrage pro Ressource). Eine Kampagne in Prüfung kann nicht veröffentlicht werden.
2. **Prüfung**: der Prüfer sieht alles — abspielbare Werbemittel, Werbetreibender, Zeitraum, gewünschter und erreichbarer SOV, Angebot, benannte Ziele, prognostizierte Belegung mit den bereits laufenden Kampagnen.
3. **Entscheidung**: freigeben / ablehnen / Änderungen anfordern (Begründung Pflicht), mit Option **E-Mail an den Werbetreibenden** (standardmäßig angekreuzt). Die Freigabe gibt auch die ausstehenden Werbemittel der Anfrage frei.
4. **Erneute Einreichung** nach Korrekturen; Verlauf bleibt erhalten.

Prüfer (`approvals`-Berechtigungen) sehen die Warteschlange der gesamten Organisation und eine **Glocke** in der oberen Leiste; **CSV/PDF-Exporte** der Warteschlange; Anfragen in einem Endstatus können aus der Liste entfernt werden (Audit-Spur bleibt).

## Berichte und Analysen

- **Executive Dashboard**: Netzwerk-KPIs, **Network Health Score**, Trends — Standort-/Gruppenfilter, **White-Label-PDF**-Export (Ihr Logo), **geplanter E-Mail-Versand**.
- Spezialisierte Dashboards: NOC (Flottenzustand), Inhalte, Geo (Standortkarte), Publikum.
- **Proof of Play**: jede Wiedergabe wird erfasst, verkettet (Merkle) und **vom Player signiert** — Integritätsprüfung und exportierbares **Zertifikat**. Musikrechte-Berichte stützen sich darauf.
- **Freigabelinks**: veröffentlichen Sie einen schreibgeschützten Bericht mit Passwort und IP-Allowlist für einen Kunden oder die Geschäftsleitung.
- **BI-Konnektoren**: drei CSV-Streams (`sfr_`-API-Schlüssel) für Power BI, Tableau, Excel, Metabase.

## Benachrichtigungen

**Einstellungen → Benachrichtigungen**: **Kanäle** (JSON-Webhook oder **E-Mail**, bis 20 Empfänger) und **Regeln**, die Ereignisse damit verknüpfen: Player offline (geplanter Standby löst nicht aus; eine nach Öffnung nicht erwachte Flotte schon), Feed-Fehler, fehlgeschlagenes OTA-Deployment, Kampagnen (gestartet/beendet/untergeliefert), Freigaben (eingereicht/freigegeben/abgelehnt/Änderungen). Test-Senden-Knopf an jedem Kanal.

## KI-Assistent und Jeanine

Der **Assistent** (Knopf unten rechts oder **Strg+Umschalt+A**) kennt Ihr Konto und diese Dokumentation und antwortet in Ihrer Sprache.

- **Lesen**: Player (Status, warum ein Bildschirm aus ist), Playlists („wer spielt sie"), Standorte und **Öffnungszeiten**, Zeitpläne, Medien (nachgewiesene Sendezeit, nie gespielt), Kampagnen (Status, Bericht), HDMI-Sitzungen, Alarme.
- **Aktionen**: er **bereitet vor** (führt nie allein aus) — Medien zu Playlists hinzufügen/entfernen, Playlist/Feed/Ereignis/Zeitplan anlegen, Player neu starten, Screenshot, Bildschirm an/aus, HDMI-Umschaltung, VOD, Zeitzone, Medien in Ordner einsortieren, **OTA-Updates der Player** (neueste stabile Version). Sie bestätigen per Knopf; sensible Aktionen sind Org-Admins vorbehalten.
- **Jeanine (Telegram)**: derselbe Assistent per Messenger. Verknüpfen Sie Ihr Konto unter **Profil → Karte Messaging** (`/link CODE` an den Bot); der Org-Admin verwaltet verknüpfte Konten unter Einstellungen → Messaging. Sensible Aktionen (Neustart, Bildschirm aus, Zeitplan löschen, OTA…) verlangen Ihren **6-stelligen PIN-Code** (im Profil festgelegt; eine Aktion, 2 Minuten, Sperre nach 3 Fehlern, Nachricht wird aus dem Verlauf gelöscht — nie per Sprache).
- **Sprachnachrichten**: senden Sie eine Sprachnachricht (≤ 2 Min.) — Transkription in Ihrer Profilsprache, Antwort als Text + Sprachnotiz (fal.ai- und ElevenLabs-Schlüssel erforderlich).
- Kosten: der Assistent nutzt **die KI-Schlüssel Ihrer Organisation** und respektiert deren Kontingent.

## Player-Updates (OTA)

**Einstellungen → Updates** steuert Fernaktualisierungen aller Player-Typen. **Kein automatisches Update ohne Ihre Freigabe.**

- **Inventar**: aktuelle vs. neueste Version **je Plattform**, kombinierte Filter (OS, Version, Zustand, Standort, Gruppe).
- **Katalog**: Ihre veröffentlichten Versionen (SemVer, Kanal, Plattform).
- **Version importieren** (Linux/RPi/Windows/Android): per **URL** oder per **Datei** (.tar.gz/.apk) — Plattform und Version werden **automatisch erkannt**, mit Vorschau vor der Bestätigung; das Archiv wird auf Ihrem Server gespeichert, die Player laden es von dort.
- **Bereitgestellte Versionen** (BrightSign/ChromeOS): diese Player erhalten ihren Code **mit dem Server-Update**; **deklarieren** Sie die bereitgestellte Version, um sie bereitstellbar zu machen. **Anheften**: ein Server-Update bewegt einen Player **nicht**, bis Sie die Version bereitstellen — ideal zum Testen in einer Sandbox vor dem gesamten Bestand.
- **Empfohlener Ablauf**: als **Beta** veröffentlichen (für die Flotte unsichtbar) → auf eine Testgruppe ausrollen → **Auf stabil heben** → breit ausrollen.
- **Deployment**: Version + Ziele (Player, Gruppe, Standort, Tags, Org) + Strategie (sofort, schrittweise, geplant) + **Zeitfenster** (Download / Installation in Ortszeit — kein Neustart mitten am Tag). Verfolgung je Player (Download → bereit → Installation → Erfolg/Fehler), Fortschrittsring, Pause/Fortsetzung/Abbruch. Ein Offline-Player wendet bei Rückkehr an.
- **Über den Assistenten**: „aktualisiere die Player" bietet veralteten Playern die neueste stabile Version ihrer Plattform an (Org-Admin; PIN über Telegram).

## Bildschirme und Strom

Vitrail schaltet Ihre Bildschirme nach den **Öffnungszeiten des Standorts** ein und aus — der Player bleibt an, nur der Bildschirm wird gesteuert.

1. Öffnungszeiten des Standorts pflegen (mit Ausnahmen und Feiertagen) und **Auto-Power** aktivieren (optionale Vor-/Nachlaufzeiten).
2. Je Player: **Den Standortzeiten folgen** (empfohlen), eigenes Fenster, immer an, oder manuell.
3. Steuerung je nach Ausstattung: **RS232/IP**-Controller (Profi-Displays), **HDMI-CEC**, oder als Rückfall die **Abschaltung des Videosignals** (der Bildschirm geht in Standby).

Jeder Player kennt seine Einschaltfenster **14 Tage im Voraus**: ist der Server unerreichbar, steuert er seinen Bildschirm selbst. Ein vom Programm abgeschalteter Player wird als **„Geplanter Standby"** markiert — kein Alarm; kommt er nach der Öffnung nicht zurück, wird alarmiert. Die An/Aus-Knöpfe im Detailbereich sind einmalig; ein Ereignis kann „Bildschirme anlassen".

## Server und Dauer der Kodierungen

Jedes hochgeladene Video wird **neu kodiert**, damit alle Bildschirme es abspielen können — die mit Abstand schwerste Aufgabe des Servers. Die Seite **Einstellungen → Server** sagt Ihnen, warum es so lange dauert.

**Kodierkapazität** — die Zeile, die fast alles erklärt: **Hardwarebeschleunigung aktiv** oder nicht. Ohne nutzbare Grafikkarte läuft die Kodierung über den Prozessor und ist deutlich langsamer. **Gemessene Durchsätze** = die tatsächlich an Ihren eigenen Dateien beobachteten Geschwindigkeiten. **Arbeitsdatenträger** = freier Platz, auf dem der Worker seine temporären Dateien schreibt.

> **„Kein Medien-Worker antwortet“** ist kein Anzeigedetail: keine Kodierung kann abgeschlossen werden. Diese Angaben kommen vom **Worker**, nicht vom Webserver — schweigt er, sagt die Seite es, statt veraltete Werte zu zeigen.

**Vor dem Start misst der Server**: er kodiert etwa zehn Sekunden **Ihrer** Datei mit genau dem Befehl, der verwendet wird, und rechnet hoch. Drei Fälle: **unter 20 Min.** startet von selbst · **20 Min. bis 4 Std.** entscheiden Sie, das Medium wartet als **Entscheidung erforderlich** · **über 4 Std.** wird standardmäßig abgelehnt, ein Administrator kann es überstimmen. Eine Ablehnung ist keine Sackgasse: der Bildschirm bietet an, in **niedrigerer Auflösung** zu kodieren, jeweils mit eigener Schätzung.

Diese Seite ist dem **Lizenzinhaber** vorbehalten. Wird Ihr Server von einem Dienstleister betrieben, sagt der Bildschirm es Ihnen: Kapazität und Warteschlange gehören zu seinem Betrieb.

## Benutzer, Rollen und Sicherheit

**Mitgelieferte Rollen** — diese Liste nennt nur Rechte, die der Server tatsächlich durchsetzt:

- **Organisations-Administrator**: alles innerhalb seiner Organisation.
- **Designer**: Medien und Templates (anlegen/ändern/löschen), Playlists (anlegen/ändern).
- **Planer**: Zeitpläne, Ereignisse und VOD (anlegen/ändern/auslösen); Lesen von Playern, Playlists, Medien.
- **Kampagnenverantwortlicher**: Kampagnen von A bis Z (anlegen, veröffentlichen, Berichte); Lesen von Medien, Templates, Berichten.
- **Genehmiger**: Anträge prüfen, genehmigen oder ablehnen; Lesen von Medien, Playlists, Templates.
- **Berichtsleser**: nur Berichte einsehen.
- **Filialbediener**: die Audio-Körbe seiner Filiale steuern.
- **Governance-Manager**: die Governance-Hierarchie konfigurieren (Knoten, Delegationen); Inhalte lesen.
- **Governance-Redakteur**: die Inhalte seines Knotens zusammenstellen (Playlists, Medien, Feeds) und zur Freigabe einreichen; **löscht keine Medien**.
- **Governance-Prüfer**: über die Freigabeanträge seines Bereichs entscheiden; **nie die eigene Einreichung**, und nur von einem übergeordneten Knoten aus.
- **Standort-Programmierer**: die Ausspielung der **Knoten, die er verwaltet**, planen (sein Umfang ergibt sich aus seiner Knotenzuweisung, nicht aus der Berechtigung allein).
- **Betrachter**: durchgehend nur lesen.
- **Werbetreibender (Portal)**: eigene Kampagnen und Berichte über das Portal.

> **Menüs richten sich nach der Rolle**: Was ein Benutzer nicht nutzen kann, wird ausgeblendet. Ein fehlendes Menü bedeutet ein fehlendes Leserecht, keine Störung.

> Die Rollen **API-Benutzer** und **Player** gewähren nichts und werden nicht mehr angeboten: Integrationen nutzen **API-Schlüssel**, Player ein **Maschinen-Token**.

> **Eigene Rolle**: anlegen, dann **auf ihre Zeile klicken**, um Berechtigungen zu setzen. Systemrollen sind schreibgeschützt; grau hinterlegte Berechtigungen (in Kürze) gehören zu noch nicht entwickelten Funktionen.

- **Einstellungen → Benutzer & Rollen**: Benutzer, **Gruppen** (Gruppenrollen ergänzen die des Kontos; Geltungsbereich Org/Standort/Player-Gruppe) und **eigene Rollen** aus atomaren Berechtigungen `Modul : Operation` (siehe Liste oben).
- Das Löschen eines Benutzers ist eine **Deaktivierung** (die E-Mail bleibt reserviert); das Löschen eines Werbekontos trennt es vom Portal.
- **2FA (TOTP)**: je Benutzer aktivierbar, für Administratoren verpflichtend.
- **API-Schlüssel**: BI-Exporte (`sfr_`), Kampagnen-Import (`sfi_`) — Wert wird nur einmal angezeigt, widerrufbar.
- **Einstellungen → Sicherheit**: Sitzungsrichtlinie, Anmeldeversuche.
- Jede sensible Aktion wird im **Audit-Log** protokolliert.

## Profil und Einstellungen

**Einstellungen → Profil**: Name, E-Mail, Passwort, **Oberflächensprache** (Französisch, Englisch, Spanisch, Portugiesisch, Deutsch — Assistent und E-Mails folgen ihr), helles/dunkles Design (Knopf in der oberen Leiste), 2FA, **Karte Messaging — Telegram** (Jeanine-Verknüpfung + **PIN-Code** für sensible Aktionen), Reaktivierung der Hilfeblasen.

## Schnelle Fehlerbehebung

- **Player offline**: Strom, Netzwerk, Server-URL prüfen. Außerhalb der Öffnungszeiten ist „Geplanter Standby" normal (Auto-Power hat den Bildschirm abgeschaltet; manche Boxen kappen auch ihr Netzwerk).
- **„No Signal Detected"**: die angeschlossene HDMI-Quelle sendet nicht (aus, abgesteckt) — das Bild kehrt von selbst zurück, sobald das Signal wieder da ist.
- **„Medium nicht verfügbar"**: Player für diesen Inhaltstyp nicht aktuell, oder Server-Transkodierung nicht abgeschlossen.
- **Schwarzer/eingefrorener Bildschirm**: Transkodierung prüfen; bei einer synchronisierten Wand die Gruppe homogen halten; „Info auf dem Bildschirm" zeigt die Diagnose vor Ort.
- **Kein Ton**: Audio-Rolle des Players prüfen (Standard / nur Audio / gemischt), gesetzte Lautstärke und Stummschaltung.
- **Inhalt ändert sich nicht**: Player online? Zielt der Zeitplan wirklich auf diesen Player/diese Gruppe? Jede Änderung stößt normalerweise eine sofortige Synchronisation an.
- **Offline**: native Player spielen ihre Inhalte lokal (Playlists, Videos, gecachte Feeds) auch bei ausgefallenem Server; die Chrome-Erweiterung hängt stärker am Netz.

> Mehr nötig? Fragen Sie den Assistenten (Strg+Umschalt+A) — er kennt dieses Handbuch und den Zustand Ihres Kontos.
