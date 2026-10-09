import QtQuick
import QtQuick.Controls
import "."

CheckBox {
    id: box
    contentItem: Text {
        text: box.text
        leftPadding: 30
        color: Theme.text
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize(14)
        verticalAlignment: Text.AlignVCenter
    }
    indicator: Rectangle {
        implicitWidth: 20
        implicitHeight: 20
        radius: Theme.radius / 2
        x: box.leftPadding
        y: parent.height / 2 - height / 2
        color: box.checked ? Theme.accent : Theme.surface
        border.color: box.checked ? Theme.accent : Theme.border
        Text {
            anchors.centerIn: parent
            text: box.checked ? "✓" : ""
            color: Theme.onAccent
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(13)
        }
    }
}
