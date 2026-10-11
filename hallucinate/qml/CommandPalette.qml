import QtQuick
import QtQuick.Controls
import "."

// Ctrl+K: type to jump anywhere, run any command, or play something. Commands are matched fuzzily (letters in
// order, word starts count most); albums, artists and songs come from the library search.
Popup {
    id: palette
    objectName: "commandPalette"
    property var win
    property var results: []
    property int current: 0
    parent: Overlay.overlay
    x: Math.round((parent.width - width) / 2)
    y: Math.round(parent.height * 0.12)
    width: Math.min(640, parent.width - 80)
    height: Math.min(field.height + 24 + Math.max(1, results.length) * 50 + 20, parent.height * 0.7)
    modal: true
    focus: true
    padding: 0
    Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, 0.35) }
    enter: Transition {
        ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 140 }
            NumberAnimation { property: "scale"; from: 0.97; to: 1; duration: 160; easing.type: Easing.OutCubic }
        }
    }
    exit: Transition { NumberAnimation { property: "opacity"; to: 0; duration: 100 } }
    background: Rectangle {
        radius: 22
        color: Theme.glassStrong
        border.width: 1
        border.color: Theme.strokeHi
    }

    function show() {
        field.text = ""
        rebuild()
        open()
        field.forceActiveFocus()
    }
    onClosed: if (win) win.contentItem.forceActiveFocus()

    // --- commands ------------------------------------------------------------------------
    function commands() {
        var w = win
        var c = [
            { t: "Home", s: "Go to", i: "home", run: () => w.go("home") },
            { t: "Albums", s: "Go to", i: "album", run: () => w.go("albums") },
            { t: "Artists", s: "Go to", i: "artist", run: () => w.go("artists") },
            { t: "Songs", s: "Go to", i: "songs", run: () => w.go("songs") },
            { t: "Liked Songs", s: "Go to", i: "heart", run: () => w.go("liked") },
            { t: "Stats", s: "Go to", i: "stats", run: () => w.go("stats") },
            { t: "History", s: "Go to", i: "history", run: () => w.go("history") },
            { t: "Visualizer", s: "Go to", i: "wave", run: () => w.go("visualizer") },
            { t: "Settings", s: "Go to", i: "settings", run: () => w.go("settings") },
            { t: "Library health", s: "Go to", i: "sparkle", run: () => w.go("health") },
            { t: "Colour wall", s: "Albums", i: "album", run: () => { shell.setUiValue("albumsView", "colour"); w.go("albums") } },
            { t: "Timeline", s: "Albums", i: "album", run: () => { shell.setUiValue("albumsView", "timeline"); w.go("albums") } },
            { t: player.playing ? "Pause" : "Play", s: "Playback  ·  Space", i: player.playing ? "pause" : "play", run: () => player.toggle() },
            { t: "Next track", s: "Playback  ·  N", i: "next", run: () => player.next() },
            { t: "Previous track", s: "Playback  ·  P", i: "prev", run: () => player.previous() },
            { t: player.shuffle ? "Shuffle off" : "Shuffle on", s: "Playback  ·  S", i: "shuffle", run: () => player.toggleShuffle() },
            { t: "Change repeat", s: "Playback  ·  R", i: "repeat", run: () => player.cycleRepeat() },
            { t: player.radio ? "Radio off" : "Radio on", s: "Keep playing similar songs", i: "radio", run: () => player.setRadio(!player.radio) },
            { t: "Now playing", s: "View  ·  F", i: "fullscreen", run: () => Nav.toggleNowPlaying() },
            { t: "Queue", s: "View  ·  Q", i: "queue", run: () => { w.queueOpen = !w.queueOpen; if (w.queueOpen) w.lyricsOpen = false } },
            { t: "Lyrics", s: "View  ·  L", i: "note", run: () => { w.lyricsOpen = !w.lyricsOpen; if (w.lyricsOpen) w.queueOpen = false } },
            { t: "Mini player", s: "View  ·  Ctrl+M", i: "expand", run: () => shell.toggleMini() },
            { t: shell.sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar", s: "View", i: "sidebar", run: () => shell.setSidebarCollapsed(!shell.sidebarCollapsed) },
            { t: "Play a random album", s: "Library", i: "dice", run: () => { var a = library.randomAlbum(""); if (a.album_key) library.playAlbum(a.album_key, 0) } },
            { t: "Rescan library", s: "Library", i: "search", run: () => library.rescan() },
            { t: "New playlist", s: "Playlists", i: "plus", run: () => w.newPlaylist() },
            { t: "New smart playlist", s: "Playlists", i: "sparkle", run: () => Nav.newSmartPlaylist() },
        ]
        var styles = [["liquid", "Liquid"], ["aurora", "Aurora"], ["nebula", "Nebula"], ["bars", "Bars"]]
        styles.forEach(st => c.push({ t: "Visualizer: " + st[1], s: "Style", i: "wave", run: () => shell.setVisualizerStyle(st[0]) }))
        themeManager.availableThemes.forEach(name => c.push({ t: "Theme: " + name, s: "Appearance", i: "settings", run: () => themeManager.selectTheme(name) }))
        for (var p = 0; p < userLib.playlists.count; p++) {
            var pl = userLib.playlists.get(p)
            c.push({ t: pl.name, s: "Playlist", i: "playlist", run: ((id) => () => Nav.openPlaylist(id))(pl.id) })
        }
        return c
    }

    // Letters of the query in order; word starts and consecutive letters score higher. -1 when no match.
    function score(text, query) {
        var t = text.toLowerCase(), q = query.toLowerCase()
        if (!q.length) return 0
        var at = t.indexOf(q)
        if (at === 0) return 1000 - t.length
        if (at > 0 && /\W/.test(t[at - 1])) return 800 - t.length
        var s = 0, ti = 0, run = 0
        for (var qi = 0; qi < q.length; qi++) {
            var found = false
            for (; ti < t.length; ti++) {
                if (t[ti] === q[qi]) {
                    var wordStart = ti === 0 || /\W/.test(t[ti - 1])
                    run = (run > 0 && ti > 0 && t[ti - 1] === q[qi - 1]) ? run + 1 : 1
                    s += 10 + (wordStart ? 25 : 0) + run * 4
                    ti++
                    found = true
                    break
                }
            }
            if (!found) return -1
        }
        // scattered letters are noise: ask for word starts or runs to back a subsequence match
        return s >= q.length * 24 ? s - t.length : -1
    }

    function rebuild() {
        var q = field.text.trim()
        var out = []
        var cmds = commands()
        if (!q.length) {
            out = cmds.slice(0, 12)
        } else {
            out = cmds.map(c => ({ c: c, s: score(c.t + " " + c.s, q) }))
                      .filter(x => x.s >= 0).sort((a, b) => b.s - a.s).slice(0, 6).map(x => x.c)
            var m = library.searchAlbums
            for (var i = 0; i < Math.min(4, m.count); i++) {
                var a = m.get(i)
                out.push({ t: a.album, s: "Album  ·  " + a.album_artist, art: a.artUrl, run: ((k) => () => Nav.openAlbum(k))(a.album_key) })
            }
            m = library.searchArtists
            for (i = 0; i < Math.min(3, m.count); i++) {
                var r = m.get(i)
                out.push({ t: r.name, s: "Artist", art: r.artUrl, round: true, run: ((n) => () => Nav.openArtist(n))(r.name) })
            }
            m = library.searchTracks
            for (i = 0; i < Math.min(5, m.count); i++) {
                var tr = m.get(i)
                out.push({ t: tr.title, s: "Song  ·  " + tr.artist, art: tr.artUrl, run: ((ix) => () => library.playSearchTracks(ix))(i) })
            }
        }
        results = out
        current = 0
    }
    function runCurrent() {
        if (current < 0 || current >= results.length) return
        var item = results[current]
        close()
        item.run()
    }

    Timer { id: searchDelay; interval: 110; onTriggered: { library.search(field.text); palette.rebuild() } }
    Connections {
        target: library.searchTracks
        enabled: palette.opened
        function onCountChanged() { palette.rebuild() }
    }
    Connections {
        target: library.searchAlbums
        enabled: palette.opened
        function onCountChanged() { palette.rebuild() }
    }

    contentItem: Column {
        TextField {
            id: field
            objectName: "paletteField"
            width: parent.width
            height: 58
            placeholderText: "Type a command, page, album, artist or song…"
            placeholderTextColor: Theme.textDim
            color: Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(16)
            leftPadding: 52
            rightPadding: 18
            background: Item {
                Icon { x: 20; anchors.verticalCenter: parent.verticalCenter; width: 18; height: 18; name: "search"; color: Theme.accent }
                Rectangle { anchors { left: parent.left; right: parent.right; bottom: parent.bottom } height: 1; color: Theme.stroke }
            }
            onTextEdited: { palette.rebuild(); searchDelay.restart() }
            Keys.onDownPressed: { palette.current = Math.min(palette.results.length - 1, palette.current + 1); list.positionViewAtIndex(palette.current, ListView.Contain) }
            Keys.onUpPressed: { palette.current = Math.max(0, palette.current - 1); list.positionViewAtIndex(palette.current, ListView.Contain) }
            Keys.onReturnPressed: palette.runCurrent()
            Keys.onEnterPressed: palette.runCurrent()
            Keys.onEscapePressed: palette.close()
        }
        ListView {
            id: list
            objectName: "paletteResults"
            width: parent.width
            height: palette.height - field.height
            topMargin: 8; bottomMargin: 8
            clip: true
            model: palette.results
            boundsBehavior: Flickable.StopAtBounds
            delegate: Rectangle {
                required property var modelData
                required property int index
                x: 8
                width: list.width - 16
                height: 50
                radius: 12
                color: index === palette.current ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.18) : "transparent"
                Item {
                    id: lead
                    x: 12; width: 32; height: 32
                    anchors.verticalCenter: parent.verticalCenter
                    Icon {
                        anchors.centerIn: parent
                        visible: !modelData.art && modelData.i !== undefined
                        width: 18; height: 18
                        name: modelData.i || ""
                        color: index === palette.current ? Theme.accent : Theme.textDim
                    }
                    Cover {
                        anchors.fill: parent
                        visible: modelData.art !== undefined
                        radius: modelData.round ? 16 : 7
                        source: modelData.art || ""
                        fallback: (modelData.t || "?").charAt(0)
                    }
                }
                Text {
                    anchors { left: lead.right; leftMargin: 14; right: sub.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
                    text: modelData.t
                    color: Theme.text
                    elide: Text.ElideRight
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(14)
                    font.weight: index === palette.current ? Font.DemiBold : Font.Normal
                }
                Text {
                    id: sub
                    anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter }
                    width: Math.min(implicitWidth, parent.width * 0.42)
                    horizontalAlignment: Text.AlignRight
                    text: modelData.s || ""
                    color: Theme.textDim
                    elide: Text.ElideRight
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(12)
                }
                MouseArea {
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onEntered: palette.current = index
                    onClicked: { palette.current = index; palette.runCurrent() }
                }
            }
            Text {
                anchors.centerIn: parent
                visible: palette.results.length === 0
                text: "Nothing matches"
                color: Theme.textDim
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(13)
            }
        }
    }
}
