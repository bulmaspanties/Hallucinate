import QtQuick
import "."

Rectangle {
    id: row
    property int number: 0
    property string title
    property string artist
    property string album
    property string durText
    property url artUrl
    property bool current: false
    property bool showArt: true
    property bool showAlbum: true
    signal activated()
    signal enqueue()

    height: 52
    radius: Theme.radiusSmall
    color: hh.hovered ? Theme.surface : "transparent"

    HoverHandler { id: hh }
    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: row.activated()
    }
    Item {
        id: numCol
        width: 36
        height: parent.height
        visible: row.number > 0
        Text {
            anchors.centerIn: parent
            visible: !hh.hovered && !row.current
            text: row.number
            color: Theme.textDim
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(13)
        }
        Icon {
            anchors.centerIn: parent
            width: 14; height: 14
            visible: hh.hovered || row.current
            name: "play"
            color: row.current ? Theme.accent : Theme.text
        }
    }
    Cover {
        id: art
        visible: row.showArt
        x: numCol.visible ? numCol.width : 8
        anchors.verticalCenter: parent.verticalCenter
        width: 38; height: 38; radius: Theme.radiusSmall
        source: row.artUrl
    }
    Column {
        id: titles
        x: (row.showArt ? art.x + art.width : (numCol.visible ? numCol.width : 8)) + 12
        anchors.verticalCenter: parent.verticalCenter
        width: Math.max(80, (row.showAlbum ? (row.width - x - 200) * 0.55 : row.width - x - 130))
        spacing: 2
        Text {
            width: parent.width
            text: row.title
            color: row.current ? Theme.accent : Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(14)
            elide: Text.ElideRight
        }
        Text {
            width: parent.width
            text: row.artist
            color: Theme.textDim
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(12)
            elide: Text.ElideRight
        }
    }
    Text {
        visible: row.showAlbum && row.width > 700
        anchors.verticalCenter: parent.verticalCenter
        x: titles.x + titles.width + 16
        width: row.width - x - 130
        text: row.album
        color: Theme.textDim
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize(13)
        elide: Text.ElideRight
    }
    IconButton {
        id: addBtn
        anchors { right: dur.left; rightMargin: 4; verticalCenter: parent.verticalCenter }
        icon: "plus"; size: 14
        opacity: hh.hovered ? 1 : 0
        onClicked: row.enqueue()
    }
    Text {
        id: dur
        anchors { right: parent.right; rightMargin: 16; verticalCenter: parent.verticalCenter }
        text: row.durText
        color: Theme.textDim
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize(13)
    }
}
