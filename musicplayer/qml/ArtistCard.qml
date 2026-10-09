import QtQuick
import "."

Item {
    id: card
    property string name
    property string subtitle
    property url artUrl
    property real cardWidth: 150
    width: cardWidth
    height: cardWidth + 56

    Cover {
        id: art
        width: card.cardWidth; height: card.cardWidth
        radius: width / 2
        source: card.artUrl
        fallback: "♫"
        scale: ma.containsMouse ? 1.03 : 1
        Behavior on scale { NumberAnimation { duration: 140 } }
    }
    Column {
        anchors { top: art.bottom; topMargin: 10; left: parent.left; right: parent.right }
        spacing: 2
        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: card.name
            color: Theme.text
            font.pixelSize: 14
            font.weight: Font.DemiBold
            elide: Text.ElideRight
        }
        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: card.subtitle
            color: Theme.textDim
            font.pixelSize: 12
            elide: Text.ElideRight
        }
    }
    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: Nav.openArtist(card.name)
    }
}
