import QtQuick
import QtQuick.Controls
import "."

Slider {
    id: s
    implicitHeight: 18
    padding: 0
    background: Rectangle {
        x: s.leftPadding
        y: s.topPadding + s.availableHeight / 2 - height / 2
        width: s.availableWidth
        height: 4
        radius: 2
        color: Theme.surfaceHi
        Rectangle {
            width: s.visualPosition * parent.width
            height: parent.height
            radius: 2
            color: s.hovered || s.pressed ? Theme.accent : Theme.text
        }
    }
    handle: Rectangle {
        x: s.leftPadding + s.visualPosition * (s.availableWidth - width)
        y: s.topPadding + s.availableHeight / 2 - height / 2
        width: 12; height: 12; radius: width / 2
        color: Theme.text
        visible: s.hovered || s.pressed
    }
}
