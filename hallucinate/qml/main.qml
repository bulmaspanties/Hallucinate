import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

ApplicationWindow {
    id: window
    width: 1280
    height: 800
    minimumWidth: 900
    minimumHeight: 600
    visible: true
    title: player.hasTrack ? player.current.title + " — " + player.current.artist : "Hallucinate"
    color: Theme.bg

    palette.window: Theme.bg
    palette.windowText: Theme.text
    palette.base: Theme.surface
    palette.text: Theme.text
    palette.button: Theme.surface
    palette.buttonText: Theme.text
    palette.highlight: Theme.accent
    palette.highlightedText: Theme.onAccent
    palette.placeholderText: Theme.textDim

    property string section: "home"
    property bool queueOpen: false
    property bool lyricsOpen: false

    function pageFor(name) {
        switch (name) {
        case "albums": return albumsPage
        case "artists": return artistsPage
        case "songs": return songsPage
        case "stats": return statsPage
        case "history": return historyPage
        case "visualizer": return visualizerPage
        case "settings": return settingsPage
        case "liked": return likedPage
        default: return homePage
        }
    }
    function go(name) {
        section = name
        stack.clear()
        stack.push(pageFor(name))
        if (searchField.text.length > 0) searchField.text = ""
    }
    function openPlaylist(id, name) {
        section = "pl" + id
        stack.clear()
        stack.push(playlistPage, { playlistId: id, playlistName: name })
        if (searchField.text.length > 0) searchField.text = ""
    }
    function openSmartPlaylist(id, name) {
        section = "smart" + id
        stack.clear()
        stack.push(smartPlaylistPage, { smartId: id, playlistName: name })
        if (searchField.text.length > 0) searchField.text = ""
    }
    function newPlaylist() { createDlg.open() }
    function openAlbum(key) { stack.push(albumDetail, { albumKey: key }) }
    function openArtist(name) { stack.push(artistDetail, { artistName: name }) }
    function showSearch() {
        if (stack.currentItem && stack.currentItem.objectName === "search") return
        stack.push(searchPage, { query: searchField.text })
    }

    Component { id: homePage; HomePage {} }
    Component { id: albumsPage; AlbumsPage {} }
    Component { id: artistsPage; ArtistsPage {} }
    Component { id: songsPage; SongsPage {} }
    Component { id: statsPage; StatsPage {} }
    Component { id: historyPage; HistoryPage {} }
    Component { id: visualizerPage; VisualizerPage {} }
    Component { id: settingsPage; SettingsPage {} }
    Component { id: likedPage; PlaylistPage { liked: true } }
    Component { id: playlistPage; PlaylistPage {} }
    Component { id: smartPlaylistPage; SmartPlaylistPage {} }
    Component { id: searchPage; SearchPage {} }
    Component { id: albumDetail; AlbumDetailPage {} }
    Component { id: artistDetail; ArtistDetailPage {} }

    Connections {
        target: Nav
        function onOpenAlbum(key) { window.openAlbum(key) }
        function onOpenArtist(name) { window.openArtist(name) }
        function onOpenSettings() { window.go("settings") }
        function onOpenLiked() { window.go("liked") }
        function onGoHome() { window.go("home") }
        function onOpenHistory(day) {
            window.go("history")
            if (day.length && stack.currentItem) stack.currentItem.period = "day:" + day
        }
        function onOpenPlaylist(id) {
            var name = ""
            for (var i = 0; i < userLib.playlists.count; i++) if (userLib.playlists.get(i).id === id) name = userLib.playlists.get(i).name
            window.openPlaylist(id, name)
        }
        function onOpenSmartPlaylist(id, name) { window.openSmartPlaylist(id, name) }
        function onEditSmartPlaylist(id, name) { smartEditor.openEdit(id, name) }
        function onEditTags(path) { tagEditor.editTrack(path) }
        function onEditAlbum(key) { tagEditor.editAlbum(key) }
        function onTrackMenu(path, title, context, index) { trackMenu.show(path, title, context, index) }
        function onBack() { if (stack.depth > 1) stack.pop() }
    }

    Timer {
        id: searchTimer
        interval: 120
        onTriggered: {
            library.search(searchField.text)
            if (searchField.text.length > 0) {
                window.showSearch()
                if (stack.currentItem) stack.currentItem.query = searchField.text
            } else if (stack.currentItem && stack.currentItem.objectName === "search") {
                window.go(window.section)
            }
        }
    }

    TrackMenu { id: trackMenu }
    SmartPlaylistEditor {
        id: smartEditor
        onSaved: function (id, name) { window.openSmartPlaylist(id, name) }
    }
    TagEditor { id: tagEditor }
    MiniPlayer {}
    onClosing: function (close) { close.accepted = !shell.handleClose() }
    Dialog {
        id: createDlg
        parent: Overlay.overlay
        anchors.centerIn: parent
        modal: true
        title: "New playlist"
        standardButtons: Dialog.Ok | Dialog.Cancel
        onOpened: { createField.text = ""; createField.forceActiveFocus() }
        onAccepted: if (createField.text.trim().length) window.openPlaylist(userLib.createPlaylist(createField.text.trim()), createField.text.trim())
        TextField { id: createField; width: 280; placeholderText: "Playlist name"; selectByMouse: true; onAccepted: createDlg.accept() }
    }

    // Drop audio files or folders anywhere to play them (the queue panel, above it, appends instead)
    DropArea {
        id: dropArea
        anchors.fill: parent
        keys: ["text/uri-list"]
        onDropped: function (drop) {
            if (!drop.hasUrls) return
            library.playDropped(drop.urls, false)
            drop.acceptProposedAction()
        }
    }

    Ambience {
        anchors.fill: parent
        z: -1
        animated: shell.ambientMotion && window.active
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            Sidebar {
                id: sidebar
                Layout.preferredWidth: width
                Layout.fillHeight: true
                section: window.section
                atRoot: stack.depth <= 1
                onNavigate: id => window.go(id)
                onOpenPlaylist: (id, name) => window.openPlaylist(id, name)
                onOpenSmartPlaylist: (id, name) => window.openSmartPlaylist(id, name)
                onNewPlaylist: window.newPlaylist()
                onNewSmartPlaylist: smartEditor.openNew()
            }

            // Content
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 0

                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 68
                    IconButton {
                        id: backBtn
                        anchors { left: parent.left; leftMargin: 18; verticalCenter: parent.verticalCenter }
                        icon: "back"
                        visible: stack.depth > 1
                        onClicked: Nav.back()
                    }
                    TextField {
                        id: searchField
                        anchors { left: backBtn.visible ? backBtn.right : parent.left; leftMargin: backBtn.visible ? 8 : 24; verticalCenter: parent.verticalCenter }
                        width: Math.min(520, parent.width - 120)
                        height: 42
                        placeholderText: "Search artists, albums, songs   ( / )"
                        placeholderTextColor: Theme.textDim
                        color: Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(14)
                        leftPadding: 44
                        rightPadding: 14
                        selectByMouse: true
                        background: Rectangle {
                            radius: height / 2
                            color: searchField.activeFocus ? Theme.glassStrong : Theme.glass
                            border.width: 1
                            border.color: searchField.activeFocus ? Theme.strokeHi : Theme.stroke
                            Behavior on border.color { ColorAnimation { duration: 160 } }
                            Icon { x: 16; anchors.verticalCenter: parent.verticalCenter; width: 16; height: 16; name: "search"; color: searchField.activeFocus ? Theme.accentHi : Theme.textDim }
                        }
                        onTextChanged: searchTimer.restart()
                        Keys.onEscapePressed: { text = ""; focus = false; window.contentItem.forceActiveFocus() }
                        Keys.onReturnPressed: if (stack.currentItem && stack.currentItem.objectName === "search") window.contentItem.forceActiveFocus()
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 0
                    StackView {
                        id: stack
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        // Pages dissolve in with a slight rise: soft, not a hard cut
                        pushEnter: Transition {
                            ParallelAnimation {
                                NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 220; easing.type: Easing.OutCubic }
                                NumberAnimation { property: "y"; from: 14; to: 0; duration: 260; easing.type: Easing.OutCubic }
                            }
                        }
                        pushExit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 120 } }
                        popEnter: pushEnter
                        popExit: pushExit
                        replaceEnter: pushEnter
                        replaceExit: pushExit
                    }
                    QueuePanel {
                        Layout.preferredWidth: window.queueOpen ? 330 : 0
                        Layout.fillHeight: true
                        Layout.rightMargin: 10
                        Layout.bottomMargin: 4
                        visible: window.queueOpen
                    }
                    LyricsPanel {
                        Layout.preferredWidth: window.lyricsOpen ? 350 : 0
                        Layout.fillHeight: true
                        Layout.rightMargin: 10
                        Layout.bottomMargin: 4
                        visible: window.lyricsOpen
                    }
                }
            }
        }

        NowPlayingBar {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.playerHeight
            Layout.margins: 10
            Layout.topMargin: 6
            queueOpen: window.queueOpen
            lyricsOpen: window.lyricsOpen
            onToggleQueue: { window.queueOpen = !window.queueOpen; if (window.queueOpen) window.lyricsOpen = false }
            onToggleLyrics: { window.lyricsOpen = !window.lyricsOpen; if (window.lyricsOpen) window.queueOpen = false }
        }
    }

    // Keyboard shortcuts (disabled while typing in the search box)
    readonly property bool typing: searchField.activeFocus
    Shortcut { sequence: "Space"; enabled: !window.typing; onActivated: player.toggle() }
    Shortcut { sequence: "Left"; enabled: !window.typing; onActivated: player.seekBy(-5000) }
    Shortcut { sequence: "Right"; enabled: !window.typing; onActivated: player.seekBy(5000) }
    Shortcut { sequence: "Up"; enabled: !window.typing; onActivated: player.changeVolume(0.05) }
    Shortcut { sequence: "Down"; enabled: !window.typing; onActivated: player.changeVolume(-0.05) }
    Shortcut { sequence: "N"; enabled: !window.typing; onActivated: player.next() }
    Shortcut { sequence: "P"; enabled: !window.typing; onActivated: player.previous() }
    Shortcut { sequence: "S"; enabled: !window.typing; onActivated: player.toggleShuffle() }
    Shortcut { sequence: "R"; enabled: !window.typing; onActivated: player.cycleRepeat() }
    Shortcut { sequence: "Q"; enabled: !window.typing; onActivated: { window.queueOpen = !window.queueOpen; if (window.queueOpen) window.lyricsOpen = false } }
    Shortcut { sequence: "Ctrl+M"; onActivated: shell.toggleMini() }
    Shortcut { sequence: "L"; enabled: !window.typing; onActivated: { window.lyricsOpen = !window.lyricsOpen; if (window.lyricsOpen) window.queueOpen = false } }
    Shortcut { sequence: "Alt+Left"; onActivated: Nav.back() }
    Shortcut { sequences: ["/", "Ctrl+F", "Ctrl+K"]; enabled: !window.typing; onActivated: { searchField.forceActiveFocus(); searchField.selectAll() } }
    Shortcut { sequence: "Ctrl+Q"; onActivated: Qt.quit() }

    Rectangle {
        anchors.fill: parent
        visible: dropArea.containsDrag
        color: Qt.rgba(Theme.bg.r, Theme.bg.g, Theme.bg.b, 0.8)
        border.color: Theme.accent
        border.width: 3
        Text {
            anchors.centerIn: parent
            text: "Drop to play"
            color: Theme.text; font.family: Theme.displayFamily; font.pixelSize: Theme.fontSize(21); font.weight: Font.DemiBold
        }
    }

    Component.onCompleted: go("home")
}
