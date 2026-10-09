import QtQuick
import "."

Item {
    id: card
    property string albumKey
    property string title
    property string subtitle
    property url artUrl
    property real cardWidth: 170
    width: cardWidth
    height: cardWidth + 62

    Rectangle {
        anchors.fill: parent
        anchors.margins: -6
        radius: Theme.radius + 4
        color: Theme.surface
        opacity: hh.hovered ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 140 } }
    }
    Cover {
        id: art
        width: card.cardWidth; height: card.cardWidth
        radius: Theme.radius
        source: card.artUrl
    }
    Rectangle {
        id: playBtn
        width: 44; height: 44; radius: 22
        color: Theme.accent
        anchors { right: art.right; bottom: art.bottom; margins: 10 }
        opacity: hh.hovered ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 140 } }
        Icon { anchors.centerIn: parent; width: 20; height: 20; name: "play"; color: Theme.onAccent }
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: player.playList(library.albumTracks(card.albumKey), 0)
        }
    }
    Column {
        anchors { top: art.bottom; topMargin: 10; left: parent.left; right: parent.right }
        spacing: 2
        Text {
            width: parent.width
            text: card.title
            color: Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(14)
            font.weight: Font.DemiBold
            elide: Text.ElideRight
        }
        Text {
            width: parent.width
            text: card.subtitle
            color: Theme.textDim
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(12)
            elide: Text.ElideRight
        }
    }
    HoverHandler { id: hh }
    MouseArea {
        anchors.fill: parent
        anchors.margins: -6
        z: -1
        cursorShape: Qt.PointingHandCursor
        onClicked: Nav.openAlbum(card.albumKey)
    }
}
