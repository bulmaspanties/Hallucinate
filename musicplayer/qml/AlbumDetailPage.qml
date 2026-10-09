import QtQuick
import QtQuick.Controls
import "."

Item {
    id: page
    objectName: "album"
    property string albumKey
    readonly property var info: library.albumInfo(albumKey)
    readonly property var tracks: library.albumTracksModel(albumKey)

    ListView {
        id: list
        anchors.fill: parent
        anchors.leftMargin: 20; anchors.rightMargin: 8
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: page.tracks
        ScrollBar.vertical: ScrollBar {}

        header: Item {
            width: list.width
            height: 270
            Cover {
                id: cover
                x: 8; y: 24
                width: 220; height: 220
                radius: Theme.radius
                source: page.info.artUrl || ""
            }
            Column {
                anchors { left: cover.right; leftMargin: 26; right: parent.right; bottom: cover.bottom }
                spacing: 8
                Text { text: "ALBUM"; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); font.weight: Font.DemiBold }
                Text {
                    width: parent.width
                    text: page.info.album || ""
                    color: Theme.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(36)
                    font.weight: Font.Bold
                    elide: Text.ElideRight
                }
                Row {
                    spacing: 6
                    Text {
                        text: page.info.album_artist || ""
                        color: Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(15)
                        font.weight: Font.DemiBold
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: Nav.openArtist(page.info.album_artist)
                        }
                    }
                    Text {
                        text: "• " + (page.info.year > 0 ? page.info.year + " • " : "") + page.info.n + " songs • " + page.info.durText
                        color: Theme.textDim
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(14)
                    }
                }
                Row {
                    spacing: 10
                    topPadding: 6
                    PillButton { primary: true; text: "Play"; onClicked: player.playList(page.tracks.toList(), 0) }
                    PillButton {
                        text: "Shuffle"
                        onClicked: {
                            player.setShuffle(true)
                            player.playList(page.tracks.toList(), Math.floor(Math.random() * page.tracks.count))
                        }
                    }
                    PillButton { text: "Add to queue"; onClicked: player.enqueueAll(page.tracks.toList()) }
                }
            }
        }
        delegate: TrackRow {
            path: model.path
            rowIndex: index
            width: ListView.view.width - 12
            number: model.track_no > 0 ? model.track_no : index + 1
            title: model.title
            artist: model.artist
            durText: model.durText
            showArt: false
            showAlbum: false
            current: player.hasTrack && player.current.id === model.id
            onActivated: player.playList(page.tracks.toList(), index)
            onEnqueue: player.enqueue(page.tracks.get(index))
        }
    }
}
