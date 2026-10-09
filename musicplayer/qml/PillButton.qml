import QtQuick
import "."

Rectangle {
    id: btn
    property string text: ""
    property bool primary: false
    signal clicked()
    implicitWidth: label.implicitWidth + 36
    implicitHeight: 38
    radius: height / 2
    color: primary ? (ma.containsMouse ? Theme.accentHi : Theme.accent)
                   : (ma.containsMouse ? Theme.surfaceHi : Theme.surface)
    border.color: Theme.border
    border.width: primary ? 0 : 1
    Behavior on color { ColorAnimation { duration: 120 } }

    Text {
        id: label
        anchors.centerIn: parent
        text: btn.text
        color: btn.primary ? "#0b0b10" : Theme.text
        font.pixelSize: 14
        font.weight: Font.DemiBold
    }
    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: btn.clicked()
    }
}
