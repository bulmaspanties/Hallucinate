import QtQuick
import QtQuick.Controls
import "."

// Home is about your library: something to play from your own shelves, when you listen, what your collection
// holds, and albums you haven't heard in a while.
Item {
    id: page
    objectName: "home"
    property var pick: ({})
    readonly property var facts: userLib.home.facts || ({})

    function reroll() { pick = library.randomAlbum(pick.album_key || "") }
    Component.onCompleted: reroll()
    Connections {
        target: library
        function onReloaded() { if (!page.pick.album_key) page.reroll() }
    }

    Flickable {
        id: fl
        anchors.fill: parent
        contentWidth: width
        contentHeight: col.height + 40
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {}

        Column {
            id: col
            x: 28; y: 12
            width: fl.width - 56
            spacing: 26

            Column {
                spacing: 6
                Text {
                    text: "Home"
                    color: Theme.text
                    font.family: Theme.displayFamily
                    font.pixelSize: Theme.fontSize(25)
                    font.weight: Font.Bold
                }
                Text {
                    objectName: "librarySummary"
                    visible: library.trackCount > 0
                    text: [library.albumCount + " albums", library.trackCount + " songs", library.artistCount + " artists",
                           page.facts.seconds ? Theme.fmtHours(page.facts.seconds) + " of music" : ""].filter(s => s).join("  ·  ")
                    color: Theme.textDim
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(14)
                }
            }

            Rectangle {
                visible: library.trackCount === 0
                width: parent.width
                height: 220
                radius: Theme.radius + 4
                color: Theme.surface
                Column {
                    anchors.centerIn: parent
                    spacing: 12
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: !library.ready ? "Loading your library…"
                            : library.scanning ? "Scanning your music…"
                            : library.hasFolders ? "No music found" : "Welcome! Let's find your music"
                        color: Theme.text
                        font.family: Theme.displayFamily
                        font.pixelSize: Theme.fontSize(16)
                        font.weight: Font.DemiBold
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: library.scanning ? "Songs appear here as they are found."
                            : library.missingFolders.length > 0 ? "Folder not found or unreadable: " + library.missingFolders.join(", ")
                            : library.hasFolders ? "Your folders contain no supported audio files. Add another folder or check Settings."
                            : "Choose the folder that holds your music to get started."
                        color: Theme.textDim
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(14)
                    }
                    ScanBar { width: 320; anchors.horizontalCenter: parent.horizontalCenter }
                    PillButton {
                        anchors.horizontalCenter: parent.horizontalCenter
                        visible: !library.scanning && library.ready
                        primary: true
                        text: "Choose music folder"
                        onClicked: picker.open()
                    }
                    FolderPicker { id: picker }
                }
            }

            // Something to play, and when you listen
            Flow {
                visible: library.trackCount > 0
                width: parent.width
                spacing: 18
                RandomAlbumCard {
                    width: col.width >= 860 ? (col.width - 18) * 0.5 : col.width
                    album: page.pick
                    onReroll: page.reroll()
                }
                ListeningCard {
                    width: col.width >= 860 ? (col.width - 18) * 0.5 : col.width
                }
            }

            // What your collection holds
            Row {
                id: factRow
                visible: library.trackCount > 0
                width: parent.width
                spacing: 14
                readonly property real tileWidth: (width - 3 * spacing) / 4
                component Fact: GlassPanel {
                    property string value
                    property string label
                    width: factRow.tileWidth; height: 96
                    Column {
                        anchors { left: parent.left; leftMargin: 20; verticalCenter: parent.verticalCenter }
                        spacing: 4
                        Text { text: value; color: Theme.text; font.family: Theme.displayFamily; font.pixelSize: Theme.fontSize(21); font.weight: Font.Bold }
                        Text { text: label; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13) }
                    }
                }
                Fact { value: page.facts.seconds ? Theme.fmtHours(page.facts.seconds).replace(" ", "\u2009") : "–"; label: "of music" }
                Fact { value: page.facts.bytes ? Theme.fmtBytes(page.facts.bytes) : "–"; label: "on disk" }
                Fact { value: page.facts.tracks ? Math.round(page.facts.lossless * 100) + "%" : "–"; label: "lossless" }
                GlassPanel {
                    id: formatsTile
                    objectName: "formatsTile"
                    width: factRow.tileWidth; height: 96
                    readonly property var formats: page.facts.formats || []
                    readonly property var swatches: [Theme.accent, Theme.art1, Theme.art2, Theme.accentHi, Theme.textDim]
                    Column {
                        anchors { left: parent.left; right: parent.right; margins: 18; verticalCenter: parent.verticalCenter }
                        spacing: 10
                        Row {
                            width: parent.width
                            height: 10
                            Repeater {
                                model: formatsTile.formats
                                Rectangle {
                                    required property var modelData
                                    required property int index
                                    width: Math.max(3, parent.width * modelData.share - 2)
                                    height: 10
                                    radius: 5
                                    color: formatsTile.swatches[index % 5]
                                }
                            }
                        }
                        Flow {
                            width: parent.width
                            spacing: 10
                            Repeater {
                                model: formatsTile.formats
                                Row {
                                    required property var modelData
                                    required property int index
                                    spacing: 5
                                    Rectangle { anchors.verticalCenter: parent.verticalCenter; width: 8; height: 8; radius: 4; color: formatsTile.swatches[index % 5] }
                                    Text { text: modelData.name + " " + Math.round(modelData.share * 100) + "%"; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11) }
                                }
                            }
                        }
                    }
                }
            }

            component AlbumShelf: Column {
                property alias model: shelf.model
                property string title
                property string subtitle
                spacing: 14
                width: col.width
                SectionHeader { title: parent.title; subtitle: parent.subtitle }
                ListView {
                    id: shelf
                    width: parent.width
                    height: 262
                    orientation: ListView.Horizontal
                    spacing: 20
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    delegate: AlbumCard {
                        albumKey: model.album_key
                        title: model.album
                        subtitle: model.album_artist
                        artUrl: model.artUrl
                        note: model.reason || ""
                    }
                }
            }

            AlbumShelf {
                objectName: "rediscoverShelf"
                visible: userLib.rediscover.count > 0
                title: "Rediscover"
                subtitle: "Albums you haven't played in a while, or ever"
                model: userLib.rediscover
            }
            AlbumShelf {
                visible: userLib.onThisDay.count > 0
                title: "On this day"
                subtitle: "What you were listening to around this date in past years"
                model: userLib.onThisDay
            }
            AlbumShelf {
                visible: library.recentAlbums.count > 0
                title: "Recently added"
                subtitle: "New on your shelves"
                model: library.recentAlbums
            }
        }
    }
}
