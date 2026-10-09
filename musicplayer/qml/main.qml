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
    title: player.hasTrack ? player.current.title + " — " + player.current.artist : "Music Player"
    color: Theme.bg

    palette.window: Theme.bg
    palette.windowText: Theme.text
    palette.base: Theme.surface
    palette.text: Theme.text
    palette.button: Theme.surface
    palette.buttonText: Theme.text
    palette.highlight: Theme.accent
    palette.highlightedText: "#0b0b10"
    palette.placeholderText: Theme.textDim

    property string section: "home"
    property bool queueOpen: false

    function pageFor(name) {
        switch (name) {
        case "albums": return albumsPage
        case "artists": return artistsPage
        case "songs": return songsPage
        case "settings": return settingsPage
        default: return homePage
        }
    }
    function go(name) {
        section = name
        stack.clear()
        stack.push(pageFor(name))
        if (searchField.text.length > 0) searchField.text = ""
    }
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
    Component { id: searchPage; SearchPage {} }
    Component { id: albumDetail; AlbumDetailPage {} }
    Component { id: artistDetail; ArtistDetailPage {} }

    Connections {
        target: Nav
        function onOpenAlbum(key) { window.openAlbum(key) }
        function onOpenArtist(name) { window.openArtist(name) }
        function onOpenSettings() { window.go("settings") }
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
                        Rectangle {
                            width: 30; height: 30; radius: 8; anchors.verticalCenter: parent.verticalCenter
                            color: Theme.accent
                            Icon { anchors.centerIn: parent; width: 16; height: 16; name: "play"; color: "#0b0b10" }
                        }
                        Text { anchors.verticalCenter: parent.verticalCenter; text: "Music Player"; color: Theme.text; font.pixelSize: 16; font.weight: Font.Bold }
                    }
                    Repeater {
                        model: [
                            { id: "home", t: "Home" }, { id: "albums", t: "Albums" },
                            { id: "artists", t: "Artists" }, { id: "songs", t: "Songs" },
                            { id: "settings", t: "Settings" }
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
                Text {
                    anchors { left: parent.left; leftMargin: 18; bottom: parent.bottom; bottomMargin: 14 }
                    visible: library.scanning
                    text: library.status
                    color: Theme.accent
                    font.pixelSize: 12
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
                        font.pixelSize: 14
                        leftPadding: 42
                        rightPadding: 14
                        selectByMouse: true
                        background: Rectangle {
                            radius: 20
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
                }
            }
        }

        NowPlayingBar {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.playerHeight
            queueOpen: window.queueOpen
            onToggleQueue: window.queueOpen = !window.queueOpen
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
    Shortcut { sequence: "Q"; enabled: !window.typing; onActivated: window.queueOpen = !window.queueOpen }
    Shortcut { sequence: "Alt+Left"; onActivated: Nav.back() }
    Shortcut { sequences: ["/", "Ctrl+F", "Ctrl+K"]; enabled: !window.typing; onActivated: { searchField.forceActiveFocus(); searchField.selectAll() } }
    Shortcut { sequence: "Ctrl+Q"; onActivated: Qt.quit() }

    Component.onCompleted: go("home")
}
