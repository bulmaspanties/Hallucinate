import QtQuick
import QtQuick.Controls
import "."

Item {
    id: page
    objectName: "albums"
    readonly property real minCell: 190
    readonly property int cols: Math.max(2, Math.floor((width - 40) / minCell))

    Text {
        id: title
        x: 28; y: 20
        text: "Albums"
        color: Theme.text
        font.family: Theme.displayFamily
        font.pixelSize: Theme.fontSize(25)
        font.weight: Font.Bold
    }
    GridView {
        id: grid
        anchors { top: title.bottom; topMargin: 14; left: parent.left; right: parent.right; bottom: parent.bottom }
        anchors.leftMargin: 20; anchors.rightMargin: 8
        cellWidth: Math.floor((width - 12) / page.cols)
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
