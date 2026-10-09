import QtQuick
import QtQuick.Controls
import "."

Item {
    id: page
    objectName: "songs"

    Text {
        id: title
        x: 28; y: 20
        text: "Songs"
        color: Theme.text
        font.pixelSize: 30
        font.weight: Font.Bold
    }
    Text {
        anchors { left: title.right; leftMargin: 14; baseline: title.baseline }
        text: library.trackCount + " tracks"
        color: Theme.textDim
        font.pixelSize: 14
    }
    ListView {
        id: list
        anchors { top: title.bottom; topMargin: 14; left: parent.left; right: parent.right; bottom: parent.bottom }
        anchors.leftMargin: 20; anchors.rightMargin: 8
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: library.songs
        cacheBuffer: 400
        ScrollBar.vertical: ScrollBar {}
        delegate: TrackRow {
            width: ListView.view.width - 12
            title: model.title
            artist: model.artist
            album: model.album
            durText: model.durText
            artUrl: model.artUrl
            current: player.hasTrack && player.current.id === model.id
            onActivated: player.playList(library.allTracks(), index)
            onEnqueue: player.enqueue(library.songs.get(index))
        }
    }
}
