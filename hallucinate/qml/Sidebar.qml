import QtQuick
import QtQuick.Controls
import "."

// Floating glass navigation rail. Collapsed it shows icons only; expanded it adds labels and the playlists.
Item {
    id: side
    property bool collapsed: shell.sidebarCollapsed
    property string section: ""
    property bool atRoot: true
    signal navigate(string id)
    signal openPlaylist(int id, string name)
    signal openSmartPlaylist(int id, string name)
    signal newPlaylist()
    signal newSmartPlaylist()

    readonly property int railWidth: 76
    readonly property int fullWidth: 236
    width: collapsed ? railWidth : fullWidth
    Behavior on width { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }

    readonly property var pages: [
        { id: "home", t: "Home", i: "home" }, { id: "albums", t: "Albums", i: "album" },
        { id: "artists", t: "Artists", i: "artist" }, { id: "songs", t: "Songs", i: "songs" },
        { id: "liked", t: "Liked Songs", i: "heart" }, { id: "stats", t: "Stats", i: "stats" },
        { id: "visualizer", t: "Visualizer", i: "wave" }
    ]

    Rectangle {
        id: panel
        anchors { fill: parent; leftMargin: 10; topMargin: 10; bottomMargin: 10 }
        radius: 24
        color: Theme.glass
        border.width: 1
        border.color: Theme.stroke

        // Brand
        Item {
            id: brand
            anchors { left: parent.left; right: parent.right; top: parent.top; topMargin: 12 }
            height: 48
            Image {
                id: logo
                x: side.collapsed ? (parent.width - width) / 2 : 14
                anchors.verticalCenter: parent.verticalCenter
                width: 32; height: 32
                source: "../assets/hallucinate.png"; sourceSize: Qt.size(64, 64); smooth: true
                Behavior on x { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
            }
            Text {
                anchors { left: logo.right; leftMargin: 10; verticalCenter: parent.verticalCenter }
                text: "Hallucinate"
                opacity: side.collapsed ? 0 : 1
                visible: opacity > 0
                Behavior on opacity { NumberAnimation { duration: 140 } }
                color: Theme.text
                font.family: Theme.displayFamily
                font.pixelSize: Theme.fontSize(15)
                font.weight: Font.DemiBold
                font.letterSpacing: 0.3
            }
        }

        Column {
            id: navCol
            anchors { left: parent.left; right: parent.right; top: brand.bottom; topMargin: 14; leftMargin: 10; rightMargin: 10 }
            spacing: 4
            Repeater {
                model: side.pages
                RailButton {
                    required property var modelData
                    width: navCol.width
                    text: modelData.t
                    icon: modelData.i
                    collapsed: side.collapsed
                    selected: side.section === modelData.id && side.atRoot
                    onClicked: side.navigate(modelData.id)
                }
            }
        }

        Rectangle {
            id: divider
            anchors { left: parent.left; right: parent.right; top: navCol.bottom; topMargin: 12; leftMargin: 22; rightMargin: 22 }
            height: 1
            color: Theme.stroke
        }

        // Playlists: a list when expanded, a menu behind one button when collapsed
        Item {
            id: plHeader
            anchors { left: parent.left; right: parent.right; top: divider.bottom; topMargin: 10; leftMargin: 10; rightMargin: 10 }
            height: side.collapsed ? 42 : 30
            RailButton {
                anchors.fill: parent
                visible: side.collapsed
                text: "Playlists"
                icon: "playlist"
                collapsed: true
                selected: (side.section.indexOf("pl") === 0 || side.section.indexOf("smart") === 0) && side.atRoot
                onClicked: playlistMenu.popup(side.railWidth - 10, 0)
            }
            Text {
                visible: !side.collapsed
                anchors { left: parent.left; leftMargin: 14; verticalCenter: parent.verticalCenter }
                text: "PLAYLISTS"
                color: Theme.textDim
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(11)
                font.weight: Font.DemiBold
                font.letterSpacing: 1.2
            }
            IconButton {
                id: newPlButton
                visible: !side.collapsed
                anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                icon: "plus"; size: 14; tip: "New playlist"
                onClicked: newPlMenu.popup(newPlButton, 0, newPlButton.height)
            }
            Menu {
                id: newPlMenu
                MenuItem { text: "New playlist"; onTriggered: side.newPlaylist() }
                MenuItem { text: "New smart playlist"; onTriggered: side.newSmartPlaylist() }
            }
            Menu {
                id: playlistMenu
                MenuItem { text: "New playlist…"; onTriggered: side.newPlaylist() }
                MenuItem { text: "New smart playlist…"; onTriggered: side.newSmartPlaylist() }
                MenuSeparator {}
                Instantiator {
                    model: userLib.playlists
                    delegate: MenuItem {
                        text: model.name
                        onTriggered: side.openPlaylist(model.id, model.name)
                    }
                    onObjectAdded: (index, object) => playlistMenu.insertItem(index + 3, object)
                    onObjectRemoved: (index, object) => playlistMenu.removeItem(object)
                }
                Instantiator {
                    model: userLib.smartPlaylists
                    delegate: MenuItem {
                        text: "✦ " + model.name
                        onTriggered: side.openSmartPlaylist(model.id, model.name)
                    }
                    onObjectAdded: (index, object) => playlistMenu.addItem(object)
                    onObjectRemoved: (index, object) => playlistMenu.removeItem(object)
                }
            }
        }

        ListView {
            id: plList
            visible: !side.collapsed
            anchors { left: parent.left; right: parent.right; top: plHeader.bottom; topMargin: 4; bottom: footer.top; bottomMargin: 6; leftMargin: 10; rightMargin: 10 }
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: userLib.playlists
            delegate: RailButton {
                width: ListView.view.width
                height: 36
                text: model.name
                icon: "playlist"
                selected: side.section === "pl" + model.id && side.atRoot
                onClicked: side.openPlaylist(model.id, model.name)
            }
            footer: Column {
                width: ListView.view ? ListView.view.width : 0
                Repeater {
                    model: userLib.smartPlaylists
                    RailButton {
                        width: parent.width
                        height: 36
                        text: model.name
                        icon: "sparkle"
                        selected: side.section === "smart" + model.id && side.atRoot
                        onClicked: side.openSmartPlaylist(model.id, model.name)
                    }
                }
            }
        }

        // Settings, the collapse toggle and scan progress stay at the bottom
        Column {
            id: footer
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom; bottomMargin: 12; leftMargin: 10; rightMargin: 10 }
            spacing: 4
            ScanBar {
                width: parent.width - 16
                x: 8
                compact: true
                visible: active && !side.collapsed
            }
            RailButton {
                width: parent.width
                text: "Settings"
                icon: "settings"
                collapsed: side.collapsed
                selected: side.section === "settings" && side.atRoot
                onClicked: side.navigate("settings")
            }
            RailButton {
                objectName: "sidebarToggle"
                width: parent.width
                text: side.collapsed ? "Expand sidebar" : "Collapse sidebar"
                icon: "sidebar"
                collapsed: side.collapsed
                onClicked: shell.setSidebarCollapsed(!side.collapsed)
            }
        }
    }
}
