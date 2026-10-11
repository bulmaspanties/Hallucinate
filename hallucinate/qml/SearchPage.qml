import QtQuick
import QtQuick.Controls
import "."

Item {
    id: page
    objectName: "search"
    property string query: ""

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
            spacing: 14

            Text {
                visible: page.query.length === 0
                text: "Search your library"
                color: Theme.textDim
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(18)
            }
            Text {
                visible: page.query.length > 0 && library.searchTracks.count === 0
                         && library.searchAlbums.count === 0 && library.searchArtists.count === 0
                text: "No results for “" + page.query + "”"
                color: Theme.textDim
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(18)
            }

            Text {
                visible: library.searchArtists.count > 0
                text: "Artists"
                color: Theme.text; font.family: Theme.displayFamily; font.pixelSize: Theme.fontSize(16); font.weight: Font.DemiBold
            }
            ListView {
                visible: library.searchArtists.count > 0
                width: parent.width; height: 210
                orientation: ListView.Horizontal
                spacing: 18; clip: true
                boundsBehavior: Flickable.StopAtBounds
                model: library.searchArtists
                delegate: ArtistCard {
                    name: model.name
                    subtitle: model.albums + (model.albums === 1 ? " album" : " albums")
                    artUrl: model.artUrl
                }
            }

            Text {
                visible: library.searchAlbums.count > 0
                text: "Albums"
                color: Theme.text; font.family: Theme.displayFamily; font.pixelSize: Theme.fontSize(16); font.weight: Font.DemiBold
            }
            ListView {
                visible: library.searchAlbums.count > 0
                width: parent.width; height: 240
                orientation: ListView.Horizontal
                spacing: 18; clip: true
                boundsBehavior: Flickable.StopAtBounds
                model: library.searchAlbums
                delegate: AlbumCard {
                    albumKey: model.album_key
                    title: model.album
                    subtitle: model.album_artist
                    artUrl: model.artUrl
                }
            }

            Text {
                visible: library.searchTracks.count > 0
                text: "Songs"
                color: Theme.text; font.family: Theme.displayFamily; font.pixelSize: Theme.fontSize(16); font.weight: Font.DemiBold
            }
            Repeater {
                model: library.searchTracks
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
                    onActivated: library.playSearchTracks(index)
                    onEnqueue: player.enqueue(library.searchTracks.get(index))
                }
            }
        }
    }
}
