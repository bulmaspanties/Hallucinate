import QtQuick
import "."

// A pill for choosing between options (selected is filled) or showing an active filter (closable).
Rectangle {
    id: chip
    property string text
    property bool selected: false
    property bool closable: false
    signal clicked()
    implicitWidth: chipLabel.implicitWidth + (closable ? 46 : 30)
    implicitHeight: 34
    radius: height / 2
    color: selected ? Theme.accent : (chipMouse.containsMouse ? Theme.glassHover : Theme.glass)
    border.width: selected ? 0 : 1
    border.color: Theme.stroke
    Behavior on color { ColorAnimation { duration: 140 } }
    Accessible.role: Accessible.Button
    Accessible.name: text
    Text {
        id: chipLabel
        x: 15
        anchors.verticalCenter: parent.verticalCenter
        text: chip.text
        color: chip.selected ? Theme.onAccent : Theme.text
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize(13)
        font.weight: chip.selected ? Font.DemiBold : Font.Normal
    }
    Icon {
        visible: chip.closable
        anchors { right: parent.right; rightMargin: 13; verticalCenter: parent.verticalCenter }
        width: 11; height: 11
        name: "close"
        color: chip.selected ? Theme.onAccent : Theme.textDim
    }
    MouseArea { id: chipMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: chip.clicked() }
}
