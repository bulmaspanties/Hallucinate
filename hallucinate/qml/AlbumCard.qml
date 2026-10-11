import QtQuick
import QtQuick.Shapes
import "."

Item {
    id: card
    property string albumKey
    property string title
    property string subtitle
    property url artUrl
    property real cardWidth: 170
    width: cardWidth
    height: cardWidth + 62
    activeFocusOnTab: true
    Keys.onReturnPressed: Nav.openAlbum(card.albumKey)
    Keys.onSpacePressed: Nav.openAlbum(card.albumKey)
    Accessible.role: Accessible.Button
    Accessible.name: title + (subtitle.length ? ", " + subtitle : "")
    Accessible.onPressAction: Nav.openAlbum(card.albumKey)
    Rectangle { anchors.fill: parent; anchors.margins: -4; radius: Theme.radius + 4; color: "transparent"; border.width: 2; border.color: Theme.accent; visible: card.activeFocus }

    // Hover: the cover lifts and a soft bloom of the accent glows behind it
    Shape {
        id: glow
        readonly property real size: card.cardWidth * 1.5
        x: (card.cardWidth - size) / 2; y: (card.cardWidth - size) / 2 + 8
        width: size; height: size
        opacity: hh.hovered ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 220 } }
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeWidth: 0; strokeColor: "transparent"
            fillGradient: RadialGradient {
                centerX: glow.size / 2; centerY: glow.size / 2; centerRadius: glow.size / 2
                focalX: glow.size / 2; focalY: glow.size / 2
                GradientStop { position: 0.35; color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, Theme.light ? 0.22 : 0.32) }
                GradientStop { position: 1.0; color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0) }
            }
            PathRectangle { x: 0; y: 0; width: glow.size; height: glow.size }
        }
    }
    Cover {
        id: art
        width: card.cardWidth; height: card.cardWidth
        radius: Theme.radius + 4
        source: card.artUrl
        y: hh.hovered ? -4 : 0
        Behavior on y { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
    }
    Rectangle {
        id: playBtn
        width: 44; height: 44; radius: 22
        color: Theme.accent
        anchors { right: art.right; bottom: art.bottom; margins: 10 }
        scale: hh.hovered ? 1 : 0.85
        Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutBack } }
        opacity: hh.hovered ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 140 } }
        Icon { anchors.centerIn: parent; width: 20; height: 20; name: "play"; color: Theme.onAccent }
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: library.playAlbum(card.albumKey, 0)
        }
    }
    Column {
        anchors { top: parent.top; topMargin: card.cardWidth + 12; left: parent.left; right: parent.right }
        spacing: 2
        Text {
            width: parent.width
            text: card.title
            color: Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(14)
            font.weight: Font.DemiBold
            elide: Text.ElideRight
        }
        Text {
            width: parent.width
            text: card.subtitle
            color: Theme.textDim
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(12)
            elide: Text.ElideRight
        }
    }
    HoverHandler { id: hh }
    MouseArea {
        anchors.fill: parent
        anchors.margins: -6
        z: -1
        cursorShape: Qt.PointingHandCursor
        onClicked: Nav.openAlbum(card.albumKey)
    }
}
