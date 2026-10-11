import QtQuick
import QtQuick.Controls
import "."

Item {
    id: page
    objectName: "artist"
    property string artistName
    readonly property var info: library.artistInfo(artistName)
    readonly property var albumsModel: library.artistAlbumsModel(artistName)
    readonly property var tracksModel: library.artistTracksModel(artistName)

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
            x: 28; y: 24
            width: fl.width - 56
            spacing: 16

            Row {
                spacing: 24
                Cover {
                    width: 150; height: 150; radius: 75
                    source: page.info.artUrl || ""
                    fallback: "♫"
                }
                Column {
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 8
                    Text { text: "ARTIST"; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); font.weight: Font.DemiBold }
                    Text { text: page.artistName; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(40); font.weight: Font.Bold }
                    Text {
                        text: page.info.albums + " albums • " + page.info.tracks + " songs"
                        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14)
                    }
                    Row {
                        spacing: 10
                        PillButton { primary: true; text: "Play all"; onClicked: library.playArtist(page.artistName, false) }
                        PillButton {
                            text: "Shuffle"
                            onClicked: {
                                player.setShuffle(true)
                                library.playArtist(page.artistName, true)
                            }
                        }
                    }
                }
            }

            Text { text: "Albums"; color: Theme.text; font.family: Theme.displayFamily; font.pixelSize: Theme.fontSize(16); font.weight: Font.DemiBold }
            ListView {
                width: parent.width; height: 240
                orientation: ListView.Horizontal
                spacing: 18; clip: true
                boundsBehavior: Flickable.StopAtBounds
                model: page.albumsModel
                delegate: AlbumCard {
                    albumKey: model.album_key
                    title: model.album
                    subtitle: model.year > 0 ? String(model.year) : "Album"
                    artUrl: model.artUrl
                }
            }

            Text { text: "Songs"; color: Theme.text; font.family: Theme.displayFamily; font.pixelSize: Theme.fontSize(16); font.weight: Font.DemiBold }
            Repeater {
                model: page.tracksModel
                TrackRow {
            path: model.path
            audioFormat: model.codec
            audioBitrate: model.bitrate
            rowIndex: index
                    width: col.width
                    title: model.title
                    artist: model.artist
                    album: model.album
                    durText: model.durText
                    artUrl: model.artUrl
                    current: player.hasTrack && player.current.id === model.id
                    onActivated: player.playList(page.tracksModel.toList(), index)
                    onEnqueue: player.enqueue(page.tracksModel.get(index))
                }
            }
        }
    }
}
