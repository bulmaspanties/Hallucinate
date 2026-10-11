import QtQuick
import QtQuick.Shapes
import "."

// One album from your shelves, picked at random: play it, or roll again.
GlassPanel {
    id: card
    objectName: "randomAlbum"
    property var album: ({})
    readonly property bool hasAlbum: album && album.album_key !== undefined
    signal reroll()
    implicitHeight: 248

    // A bloom of the accent behind the cover
    Shape {
        id: bloom
        readonly property real size: 360
        x: cover.x + cover.width / 2 - size / 2; y: cover.y + cover.height / 2 - size / 2
        width: size; height: size
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeWidth: 0; strokeColor: "transparent"
            fillGradient: RadialGradient {
                centerX: bloom.size / 2; centerY: bloom.size / 2; centerRadius: bloom.size / 2
                focalX: bloom.size / 2; focalY: bloom.size / 2
                GradientStop { position: 0.3; color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, Theme.light ? 0.18 : 0.26) }
                GradientStop { position: 1.0; color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0) }
            }
            PathRectangle { x: 0; y: 0; width: bloom.size; height: bloom.size }
        }
    }
    Cover {
        id: cover
        x: 24; anchors.verticalCenter: parent.verticalCenter
        width: 200; height: 200
        radius: 18
        source: card.hasAlbum ? card.album.artUrl : ""
        MouseArea {
            anchors.fill: parent
            enabled: card.hasAlbum
            cursorShape: Qt.PointingHandCursor
            onClicked: Nav.openAlbum(card.album.album_key)
        }
    }
    Column {
        anchors { left: cover.right; leftMargin: 26; right: parent.right; rightMargin: 24; verticalCenter: parent.verticalCenter }
        spacing: 8
        Text {
            text: "RANDOM ALBUM"
            color: Theme.accent
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(11)
            font.weight: Font.DemiBold
            font.letterSpacing: 1.6
        }
        Text {
            width: parent.width
            text: card.hasAlbum ? card.album.album : "Your albums will appear here"
            color: Theme.text
            font.family: Theme.displayFamily
            font.pixelSize: Theme.fontSize(22)
            font.weight: Font.Bold
            wrapMode: Text.Wrap
            maximumLineCount: 2
            elide: Text.ElideRight
        }
        Text {
            width: parent.width
            visible: card.hasAlbum
            text: card.hasAlbum ? card.album.album_artist : ""
            color: Theme.text
            opacity: 0.85
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(15)
            elide: Text.ElideRight
        }
        Text {
            visible: card.hasAlbum
            text: card.hasAlbum ? [card.album.year > 0 ? card.album.year : "", card.album.n + (card.album.n === 1 ? " song" : " songs"),
                                    card.album.durText].filter(s => s !== "").join("  ·  ") : ""
            color: Theme.textDim
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(13)
        }
        Item { width: 1; height: 6 }
        Row {
            spacing: 10
            PillButton {
                primary: true
                text: "Play album"
                enabled: card.hasAlbum
                onClicked: library.playAlbum(card.album.album_key, 0)
            }
            PillButton {
                objectName: "anotherAlbum"
                text: "Another"
                enabled: library.albumCount > 1
                onClicked: card.reroll()
            }
        }
    }
}
