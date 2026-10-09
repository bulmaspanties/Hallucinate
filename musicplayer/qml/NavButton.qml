import QtQuick
import "."

Item {
    id: item
    property string text
    property bool selected: false
    signal clicked()
    height: 40
    Rectangle {
        anchors.fill: parent
        radius: Theme.radiusSmall
        color: item.selected ? Theme.surfaceHi : (ma.containsMouse ? Theme.surface : "transparent")
    }
    Rectangle {
        visible: item.selected
        width: 3; height: 18; radius: 2
        color: Theme.accent
        anchors { left: parent.left; verticalCenter: parent.verticalCenter }
    }
    Text {
        anchors { left: parent.left; leftMargin: 18; verticalCenter: parent.verticalCenter }
        text: item.text
        color: item.selected || ma.containsMouse ? Theme.text : Theme.textDim
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize(14)
        font.weight: item.selected ? Font.DemiBold : Font.Normal
    }
    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: item.clicked()
    }
}
