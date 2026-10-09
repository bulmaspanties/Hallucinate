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
    Component { id: settingsPage; SettingsPage {} }
    Component { id: likedPage; PlaylistPage { liked: true } }
    Component { id: playlistPage; PlaylistPage {} }
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
        function onOpenPlaylist(id) {
            var name = ""
            for (var i = 0; i < userLib.playlists.count; i++) if (userLib.playlists.get(i).id === id) name = userLib.playlists.get(i).name
            window.openPlaylist(id, name)
        }
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

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // Sidebar
            Rectangle {
                Layout.preferredWidth: Theme.sidebarWidth
                Layout.fillHeight: true
                color: Theme.panel
                Column {
                    anchors { fill: parent; margins: 12 }
                    spacing: 4
                    Row {
                        spacing: 10
                        height: 52
                        Image {
                            width: 32; height: 32; anchors.verticalCenter: parent.verticalCenter
                            source: "../assets/hallucinate.png"; sourceSize: Qt.size(64, 64); smooth: true
                        }
                        Text { anchors.verticalCenter: parent.verticalCenter; text: "Hallucinate"; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(16); font.weight: Font.Bold }
                    }
                    Repeater {
                        model: [
                            { id: "home", t: "Home" }, { id: "albums", t: "Albums" },
                            { id: "artists", t: "Artists" }, { id: "songs", t: "Songs" },
                            { id: "liked", t: "Liked Songs" }, { id: "settings", t: "Settings" }
                        ]
                        NavButton {
                            required property var modelData
                            width: parent.width
                            text: modelData.t
                            selected: window.section === modelData.id && stack.depth <= 1
                            onClicked: window.go(modelData.id)
                        }
                    }
                }
                Item {
                    id: plSection
                    anchors { left: parent.left; right: parent.right; top: parent.top; topMargin: 336; bottom: scanBar.top; bottomMargin: 6; leftMargin: 12; rightMargin: 12 }
                    clip: true
                    Item {
                        id: plHeader
                        width: parent.width; height: 34
                        Text { anchors { left: parent.left; leftMargin: 6; verticalCenter: parent.verticalCenter } text: "PLAYLISTS"; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11); font.weight: Font.DemiBold }
                        IconButton { anchors { right: parent.right; verticalCenter: parent.verticalCenter } icon: "plus"; size: 14; onClicked: window.newPlaylist() }
                    }
                    ListView {
                        anchors { top: plHeader.bottom; left: parent.left; right: parent.right; bottom: parent.bottom }
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        model: userLib.playlists
                        delegate: NavButton {
                            width: ListView.view.width
                            height: 36
                            text: model.name
                            selected: window.section === "pl" + model.id && stack.depth <= 1
                            onClicked: window.openPlaylist(model.id, model.name)
                        }
                    }
                }
                ScanBar {
                    id: scanBar
                    anchors { left: parent.left; right: parent.right; leftMargin: 18; rightMargin: 18; bottom: parent.bottom; bottomMargin: 14 }
                    compact: true
                }
            }

            // Content
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 0

                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 64
                    IconButton {
                        id: backBtn
                        anchors { left: parent.left; leftMargin: 14; verticalCenter: parent.verticalCenter }
                        icon: "back"
                        visible: stack.depth > 1
                        onClicked: Nav.back()
                    }
                    TextField {
                        id: searchField
                        anchors { left: backBtn.visible ? backBtn.right : parent.left; leftMargin: backBtn.visible ? 8 : 28; verticalCenter: parent.verticalCenter }
                        width: Math.min(460, parent.width - 120)
                        height: 40
                        placeholderText: "Search artists, albums, songs   ( / )"
                        placeholderTextColor: Theme.textDim
                        color: Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(14)
                        leftPadding: 42
                        rightPadding: 14
                        selectByMouse: true
                        background: Rectangle {
                            radius: Theme.radiusLarge
                            color: Theme.surface
                            border.width: 1
                            border.color: searchField.activeFocus ? Theme.accent : Theme.border
                            Icon { x: 14; anchors.verticalCenter: parent.verticalCenter; width: 16; height: 16; name: "search"; color: Theme.textDim }
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
                        pushEnter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 140 } }
                        pushExit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 100 } }
                        popEnter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 140 } }
                        popExit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 100 } }
                        replaceEnter: pushEnter
                        replaceExit: pushExit
                    }
                    QueuePanel {
                        Layout.preferredWidth: window.queueOpen ? 320 : 0
                        Layout.fillHeight: true
                        visible: window.queueOpen
                    }
                    LyricsPanel {
                        Layout.preferredWidth: window.lyricsOpen ? 340 : 0
                        Layout.fillHeight: true
                        visible: window.lyricsOpen
                    }
                }
            }
        }

        NowPlayingBar {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.playerHeight
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

    Component.onCompleted: go("home")
}
