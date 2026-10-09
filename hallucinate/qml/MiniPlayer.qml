import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

Window {
    id: mini
    width: 380
    height: 112
    minimumWidth: 320
    maximumWidth: 640
    minimumHeight: 112
    maximumHeight: 112
    visible: shell.miniOpen
    title: "Hallucinate — Mini"
    flags: Qt.Window | Qt.WindowStaysOnTopHint
    color: Theme.panel
    onClosing: shell.showMain()

    Rectangle { anchors.fill: parent; color: Theme.panel }

    Cover {
        id: art
        x: 12; y: 12; width: 88; height: 88
        radius: Theme.radiusSmall
        source: player.hasTrack ? player.current.artUrl : ""
    }
    ColumnLayout {
        anchors { left: art.right; leftMargin: 12; right: parent.right; rightMargin: 12; top: parent.top; topMargin: 12; bottom: parent.bottom; bottomMargin: 10 }
        spacing: 2
        Text {
            Layout.fillWidth: true
            text: player.hasTrack ? player.current.title : "Nothing playing"
            color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14); font.weight: Font.DemiBold
            elide: Text.ElideRight
        }
        Text {
            Layout.fillWidth: true
            text: player.hasTrack ? player.current.artist : ""
            color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12)
            elide: Text.ElideRight
        }
        Item { Layout.fillHeight: true }
        RowLayout {
            Layout.fillWidth: true
            spacing: 4
            IconButton { icon: "prev"; tip: "Previous"; onClicked: player.previous() }
            IconButton { icon: player.playing ? "pause" : "play"; tip: player.playing ? "Pause" : "Play"; size: 24; onClicked: player.toggle() }
            IconButton { icon: "next"; tip: "Next"; onClicked: player.next() }
            Item { Layout.fillWidth: true }
            IconButton { icon: "expand"; tip: "Back to full window"; onClicked: shell.showMain() }
        }
        StyledSlider {
            Layout.fillWidth: true
            from: 0
            to: Math.max(1, player.duration)
            value: player.position
            enabled: player.hasTrack
            onMoved: player.seek(value)
        }
    }
    Shortcut { sequence: "Space"; onActivated: player.toggle() }
    Shortcut { sequence: "Escape"; onActivated: shell.showMain() }
}
