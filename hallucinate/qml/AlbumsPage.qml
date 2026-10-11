import QtQuick
import QtQuick.Controls
import "."

// Albums three ways: A–Z, a wall ordered by cover colour, and a timeline by decade and year.
Item {
    id: page
    objectName: "albums"
    readonly property real minCell: 190
    readonly property int cols: Math.max(2, Math.floor((width - 40) / minCell))
    property string view: shell.uiValue("albumsView", "grid")
    readonly property var views: [{ id: "grid", t: "A–Z" }, { id: "colour", t: "Colour" }, { id: "timeline", t: "Timeline" }]
    onViewChanged: {
        shell.setUiValue("albumsView", view)
        if (view === "colour") library.loadAlbumWall()
    }
    Component.onCompleted: if (view === "colour") library.loadAlbumWall()

    Row {
        id: header
        x: 28; y: 20
        width: parent.width - 56
        spacing: 18
        Text {
            id: title
            anchors.verticalCenter: parent.verticalCenter
            text: "Albums"
            color: Theme.text
            font.family: Theme.displayFamily
            font.pixelSize: Theme.fontSize(25)
            font.weight: Font.Bold
        }
        Row {
            anchors.verticalCenter: parent.verticalCenter
            spacing: 6
            Repeater {
                model: page.views
                Chip {
                    required property var modelData
                    objectName: "albumsView_" + modelData.id
                    text: modelData.t
                    selected: page.view === modelData.id
                    onClicked: page.view = modelData.id
                }
            }
        }
    }

    Loader {
        anchors { top: header.bottom; topMargin: 14; left: parent.left; right: parent.right; bottom: parent.bottom }
        sourceComponent: page.view === "colour" ? wallView : page.view === "timeline" ? timelineView : gridView
    }

    Component {
        id: gridView
        GridView {
            id: grid
            leftMargin: 20; rightMargin: 8
            cellWidth: Math.floor((width - 28) / page.cols)
            cellHeight: cellWidth + 76
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: library.albums
            cacheBuffer: 600
            ScrollBar.vertical: ScrollBar {}
            delegate: Item {
                width: grid.cellWidth; height: grid.cellHeight
                AlbumCard {
                    x: 8; y: 8
                    cardWidth: grid.cellWidth - 24
                    albumKey: model.album_key
                    title: model.album
                    subtitle: (model.year > 0 ? model.year + " • " : "") + model.album_artist
                    artUrl: model.artUrl
                }
            }
        }
    }

    // Covers edge to edge, ordered round the colour wheel; hover for the title
    Component {
        id: wallView
        Item {
            GridView {
                id: wall
                objectName: "colourWall"
                anchors { fill: parent; leftMargin: 24; rightMargin: 12 }
                readonly property int wallCols: Math.max(4, Math.floor(width / 112))
                cellWidth: Math.floor((width - 12) / wallCols)
                cellHeight: cellWidth
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                model: library.albumWall
                cacheBuffer: 800
                ScrollBar.vertical: ScrollBar {}
                delegate: Item {
                    id: tile
                    required property string album_key
                    required property string album
                    required property string album_artist
                    required property string artUrl
                    required property string color
                    width: wall.cellWidth; height: wall.cellHeight
                    z: tileMouse.containsMouse ? 2 : 0
                    Rectangle {
                        anchors { fill: parent; margins: 2 }
                        radius: 6
                        color: tile.color.length ? tile.color : Theme.surface
                    }
                    Cover {
                        anchors { fill: parent; margins: 2 }
                        radius: 6
                        source: tile.artUrl
                        fallback: tile.album.charAt(0)
                        scale: tileMouse.containsMouse ? 1.12 : 1
                        Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                    }
                    MouseArea {
                        id: tileMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: Nav.openAlbum(tile.album_key)
                    }
                    ToolTip.visible: tileMouse.containsMouse
                    ToolTip.text: tile.album + " — " + tile.album_artist
                    ToolTip.delay: 300
                }
            }
            BusyIndicator {
                anchors.centerIn: parent
                running: library.wallLoading && wall.count === 0
                visible: running
            }
            Text {
                anchors.centerIn: parent
                visible: library.wallLoading && wall.count === 0
                anchors.verticalCenterOffset: 44
                text: "Reading the colours of your covers…"
                color: Theme.textDim
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(13)
            }
        }
    }

    // Decades as headings, then each year as a row of covers
    Component {
        id: timelineView
        ListView {
            id: timeline
            objectName: "timeline"
            leftMargin: 28; rightMargin: 12
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: library.timeline
            cacheBuffer: 1200
            ScrollBar.vertical: ScrollBar {}
            readonly property real coverSize: Math.max(96, Math.min(150, (width - 160) / 7))
            delegate: Loader {
                required property var modelData
                width: timeline.width - 40
                sourceComponent: modelData.kind === "decade" ? decadeRow : yearRow
                property var row: modelData
            }
            Component {
                id: decadeRow
                Item {
                    readonly property var row: parent ? parent.row : ({})
                    height: 70
                    Text {
                        id: decadeLabel
                        anchors { left: parent.left; bottom: parent.bottom; bottomMargin: 10 }
                        text: parent.row.label
                        color: Theme.text
                        font.family: Theme.displayFamily
                        font.pixelSize: Theme.fontSize(30)
                        font.weight: Font.Bold
                    }
                    Text {
                        anchors { left: decadeLabel.right; leftMargin: 14; baseline: decadeLabel.baseline }
                        text: parent.row.count + (parent.row.count === 1 ? " album" : " albums")
                        color: Theme.textDim
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(13)
                    }
                    Rectangle {
                        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                        height: 1
                        color: Theme.stroke
                    }
                }
            }
            Component {
                id: yearRow
                Item {
                    id: yearItem
                    readonly property var row: parent ? parent.row : ({})
                    height: Math.max(yearFlow.height, 40) + 24
                    // the year on a thread down the left, a dot for each year
                    Rectangle { x: 34; width: 2; height: parent.height; color: Theme.stroke }
                    Rectangle {
                        x: 29; y: 22; width: 12; height: 12; radius: 6
                        color: Theme.accent
                        border.width: 3; border.color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.3)
                    }
                    Text {
                        x: 52; y: 16
                        width: 64
                        text: yearItem.row.year > 0 ? yearItem.row.year : "—"
                        color: Theme.text
                        font.family: Theme.displayFamily
                        font.pixelSize: Theme.fontSize(16)
                        font.weight: Font.DemiBold
                    }
                    Flow {
                        id: yearFlow
                        x: 124; y: 14
                        width: parent.width - x
                        spacing: 14
                        Repeater {
                            model: yearItem.row.albums
                            Item {
                                id: entry
                                required property var modelData
                                width: timeline.coverSize
                                height: timeline.coverSize + 40
                                Cover {
                                    id: tlCover
                                    width: timeline.coverSize; height: width
                                    radius: 12
                                    source: entry.modelData.artUrl || ""
                                    fallback: (entry.modelData.album || "?").charAt(0)
                                    y: tlMouse.containsMouse ? -3 : 0
                                    Behavior on y { NumberAnimation { duration: 140 } }
                                }
                                Text {
                                    anchors { top: tlCover.bottom; topMargin: 6 }
                                    width: parent.width
                                    text: entry.modelData.album
                                    color: Theme.text
                                    elide: Text.ElideRight
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(12)
                                    font.weight: Font.Medium
                                }
                                Text {
                                    anchors { top: tlCover.bottom; topMargin: 22 }
                                    width: parent.width
                                    text: entry.modelData.album_artist
                                    color: Theme.textDim
                                    elide: Text.ElideRight
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(11)
                                }
                                MouseArea {
                                    id: tlMouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: Nav.openAlbum(entry.modelData.album_key)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
