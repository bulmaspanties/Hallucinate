import QtQuick
import QtQuick.Controls
import "."

Rectangle {
    id: panel
    color: Theme.panel

    Row {
        id: head
        x: 18; y: 16
        spacing: 12
        Text { text: "Queue"; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(18); font.weight: Font.Bold; anchors.verticalCenter: parent.verticalCenter }
        Text { text: player.queueModel.count + " tracks"; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); anchors.verticalCenter: parent.verticalCenter }
    }
    PillButton {
        anchors { right: parent.right; rightMargin: 14; verticalCenter: head.verticalCenter }
        height: 30
        text: "Clear"
        onClicked: player.clearQueue()
    }
    Text {
        visible: player.queueModel.count === 0
        anchors.centerIn: parent
        text: "Queue is empty"
        color: Theme.textDim
    }
    ListView {
        id: list
        anchors { top: head.bottom; topMargin: 14; left: parent.left; right: parent.right; bottom: parent.bottom }
        anchors.leftMargin: 8; anchors.rightMargin: 4
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: player.queueModel
        currentIndex: player.currentIndex
        ScrollBar.vertical: ScrollBar {}
        onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)
        delegate: Rectangle {
            width: ListView.view.width - 10
            height: 54
            radius: Theme.radiusSmall
            color: hh.hovered ? Theme.surface : "transparent"
            HoverHandler { id: hh }
            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: player.playIndex(index) }
            Cover { id: art; x: 6; anchors.verticalCenter: parent.verticalCenter; width: 38; height: 38; radius: Theme.radiusSmall; source: model.artUrl }
            Column {
                anchors { left: art.right; leftMargin: 10; right: rm.left; rightMargin: 4; verticalCenter: parent.verticalCenter }
                spacing: 2
                Text {
                    width: parent.width; text: model.title; elide: Text.ElideRight; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
                    color: index === player.currentIndex ? Theme.accent : Theme.text
                }
                Text { width: parent.width; text: model.artist; elide: Text.ElideRight; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11); color: Theme.textDim }
            }
            IconButton {
                id: rm
                anchors { right: parent.right; rightMargin: 2; verticalCenter: parent.verticalCenter }
                icon: "close"; size: 12
                opacity: hh.hovered ? 1 : 0
                onClicked: player.removeAt(index)
            }
        }
    }
}
