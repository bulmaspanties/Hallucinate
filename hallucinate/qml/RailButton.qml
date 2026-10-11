import QtQuick
import QtQuick.Controls
import "."

// A navigation entry: icon, and a label when the sidebar is expanded. The selected entry glows.
Item {
    id: item
    property string text
    property string icon
    property bool selected: false
    property bool collapsed: false
    signal clicked()
    height: 42
    activeFocusOnTab: true
    Keys.onSpacePressed: item.clicked()
    Keys.onReturnPressed: item.clicked()
    Keys.onEnterPressed: item.clicked()
    Accessible.role: Accessible.Button
    Accessible.name: text
    Accessible.onPressAction: item.clicked()

    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: "transparent"
        border.width: 2
        border.color: Theme.accent
        visible: item.activeFocus
    }
    Rectangle {
        id: pill
        anchors.fill: parent
        radius: height / 2
        opacity: item.selected ? 1 : (ma.containsMouse ? 0.7 : 0)
        Behavior on opacity { NumberAnimation { duration: 160 } }
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, item.selected ? 0.30 : 0.14) }
            GradientStop { position: 1; color: Qt.rgba(Theme.art1.r, Theme.art1.g, Theme.art1.b, item.selected ? 0.12 : 0.05) }
        }
        border.width: item.selected ? 1 : 0
        border.color: Theme.strokeHi
    }
    Icon {
        id: glyph
        x: item.collapsed ? (item.width - width) / 2 : 14
        anchors.verticalCenter: parent.verticalCenter
        width: 20; height: 20
        name: item.icon
        filled: item.icon === "heart"
        color: item.selected ? Theme.accentHi : (ma.containsMouse ? Theme.text : Theme.textDim)
        Behavior on x { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
    }
    Text {
        anchors { left: glyph.right; leftMargin: 12; right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter }
        text: item.text
        opacity: item.collapsed ? 0 : 1
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 140 } }
        color: item.selected || ma.containsMouse ? Theme.text : Theme.textDim
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize(14)
        font.weight: item.selected ? Font.DemiBold : Font.Normal
        elide: Text.ElideRight
    }
    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: item.clicked()
    }
    ToolTip.visible: item.collapsed && ma.containsMouse
    ToolTip.text: item.text
    ToolTip.delay: 300
}
