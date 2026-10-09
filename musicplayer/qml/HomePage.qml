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
                height: 180
                radius: Theme.radius + 4
                color: Theme.surface
                Column {
                    anchors.centerIn: parent
                    spacing: 12
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: library.scanning ? "Scanning your music…" : "Your library is empty"
                        color: Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(20)
                        font.weight: Font.DemiBold
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: library.scanning ? library.status : "Add a folder with your music to get started."
                        color: Theme.textDim
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(14)
                    }
                    PillButton {
                        anchors.horizontalCenter: parent.horizontalCenter
                        visible: !library.scanning
                        primary: true
                        text: "Add music folder"
                        onClicked: Nav.openSettings()
                    }
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
        }
    }
}
