import QtQuick
import QtQuick.Controls
import "."

ComboBox {
    id: combo
    width: 200
    contentItem: Text {
        leftPadding: 12
        rightPadding: 28
        text: combo.displayText
        color: Theme.text
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize(14)
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    background: Rectangle {
        implicitHeight: 38
        radius: Theme.radius
        color: Theme.surface
        border.color: combo.activeFocus ? Theme.accent : Theme.border
    }
}
