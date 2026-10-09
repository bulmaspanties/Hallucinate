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
    activeFocusOnTab: true
    Keys.onSpacePressed: btn.clicked()
    Keys.onReturnPressed: btn.clicked()
    Keys.onEnterPressed: btn.clicked()
    Accessible.role: Accessible.Button
    Accessible.name: text
    Accessible.onPressAction: btn.clicked()
    Rectangle { anchors.fill: parent; anchors.margins: -2; radius: height / 2; color: "transparent"; border.width: 2; border.color: Theme.accent; visible: btn.activeFocus }

    Text {
        id: label
        anchors.centerIn: parent
        text: btn.text
        color: btn.primary ? Theme.onAccent : Theme.text
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize(14)
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
