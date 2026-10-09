import QtQuick
import QtQuick.Controls
import "."

Item {
    id: page
    objectName: "artists"
    readonly property int cols: Math.max(2, Math.floor((width - 40) / 170))

    Text {
        id: title
        x: 28; y: 20
        text: "Artists"
        color: Theme.text
        font.pixelSize: 30
        font.weight: Font.Bold
    }
    GridView {
        id: grid
        anchors { top: title.bottom; topMargin: 14; left: parent.left; right: parent.right; bottom: parent.bottom }
        anchors.leftMargin: 20; anchors.rightMargin: 8
        cellWidth: Math.floor((width - 12) / page.cols)
        cellHeight: cellWidth + 60
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: library.artists
        cacheBuffer: 600
        ScrollBar.vertical: ScrollBar {}
        delegate: Item {
            width: grid.cellWidth; height: grid.cellHeight
            ArtistCard {
                x: 10; y: 8
                cardWidth: grid.cellWidth - 28
                name: model.name
                subtitle: model.albums + (model.albums === 1 ? " album" : " albums")
                artUrl: model.artUrl
            }
        }
    }
}
