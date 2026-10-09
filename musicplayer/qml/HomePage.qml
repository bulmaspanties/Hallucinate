import QtQuick
import QtQuick.Controls
import "."

Item {
    id: page
    objectName: "home"

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
            x: 28; y: 20
            width: fl.width - 56
            spacing: 22

            Text {
                text: "Home"
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(30)
                font.weight: Font.Bold
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
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(20)
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

            Row {
                visible: library.trackCount > 0
                spacing: 12
                Repeater {
                    model: [
                        { n: library.trackCount, l: "songs" },
                        { n: library.albumCount, l: "albums" },
                        { n: library.artistCount, l: "artists" }
                    ]
                    Rectangle {
                        required property var modelData
                        width: 130; height: 64; radius: Theme.radius
                        color: Theme.surface
                        Column {
                            anchors.centerIn: parent
                            Text { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.n; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(22); font.weight: Font.Bold }
                            Text { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.l; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12) }
                        }
                    }
                }
            }

            Text {
                visible: library.recentAlbums.count > 0
                text: "Recently added"
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(20)
                font.weight: Font.DemiBold
            }
            ListView {
                visible: library.recentAlbums.count > 0
                width: parent.width
                height: 240
                orientation: ListView.Horizontal
                spacing: 18
                clip: true
                model: library.recentAlbums
                boundsBehavior: Flickable.StopAtBounds
                delegate: AlbumCard {
                    albumKey: model.album_key
                    title: model.album
                    subtitle: model.album_artist
                    artUrl: model.artUrl
                }
            }

            Text {
                visible: userLib.recentPlayed.count > 0
                text: "Recently played"
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(20)
                font.weight: Font.DemiBold
            }
            ListView {
                visible: userLib.recentPlayed.count > 0
                width: parent.width
                height: 240
                orientation: ListView.Horizontal
                spacing: 18
                clip: true
                model: userLib.recentPlayed
                boundsBehavior: Flickable.StopAtBounds
                delegate: AlbumCard {
                    albumKey: model.album_key
                    title: model.album
                    subtitle: model.album_artist
                    artUrl: model.artUrl
                }
            }

            Text {
                visible: userLib.mostPlayed.count > 0
                text: "Most played"
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(20)
                font.weight: Font.DemiBold
            }
            Column {
                visible: userLib.mostPlayed.count > 0
                width: parent.width
                Repeater {
                    model: userLib.mostPlayed
                    TrackRow {
                        width: parent.width
                        path: model.path
                        rowIndex: index
                        number: index + 1
                        title: model.title
                        artist: model.artist
                        album: model.album
                        durText: model.durText
                        artUrl: model.artUrl
                        current: player.hasTrack && player.current.id === model.id
                        onActivated: userLib.playMostPlayed(index)
                        onEnqueue: player.enqueue(userLib.mostPlayed.get(index))
                    }
                }
            }
        }
    }
}
