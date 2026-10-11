import QtQuick
import QtQuick.Controls
import "."

// The visualizer filling the page, with its style choice on top and the current track below.
Item {
    id: page
    objectName: "visualizer"
    readonly property var styles: [
        { id: "liquid", t: "Liquid" }, { id: "aurora", t: "Aurora" }, { id: "nebula", t: "Nebula" }, { id: "bars", t: "Bars" }
    ]

    Rectangle {
        id: frame
        anchors { fill: parent; margins: 14; topMargin: 6 }
        radius: 26
        color: "#05030a"
        clip: true
        border.width: 1
        border.color: Theme.stroke

        Visualizer {
            id: vis
            objectName: "pageVisualizer"
            anchors.fill: parent
            style: shell.visualizerStyle
            active: page.visible && Window.window && Window.window.active !== false
        }

        // Legibility for the overlays
        Rectangle {
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: 120
            gradient: Gradient {
                GradientStop { position: 0; color: Qt.rgba(0, 0, 0, 0.45) }
                GradientStop { position: 1; color: "transparent" }
            }
        }
        Rectangle {
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
            height: 150
            gradient: Gradient {
                GradientStop { position: 0; color: "transparent" }
                GradientStop { position: 1; color: Qt.rgba(0, 0, 0, 0.55) }
            }
        }

        Flow {
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 22 }
            spacing: 8
            Repeater {
                model: page.styles
                Chip {
                    required property var modelData
                    objectName: "visualizerStyle_" + modelData.id
                    text: modelData.t
                    selected: shell.visualizerStyle === modelData.id
                    onClicked: shell.setVisualizerStyle(modelData.id)
                }
            }
            Item { width: 8; height: 1 }
            StyledCheck {
                enabled: player.visualizerAvailable
                text: player.visualizerAvailable ? "React to the music" : "NumPy is required to react to the music"
                checked: player.visualizerEnabled
                onToggled: player.setVisualizerEnabled(checked)
            }
        }

        Row {
            anchors { left: parent.left; bottom: parent.bottom; margins: 24 }
            spacing: 14
            Cover {
                width: 56; height: 56; radius: 14
                visible: player.hasTrack
                source: player.hasTrack ? player.current.artUrl || "" : ""
            }
            Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 3
                Text {
                    text: player.hasTrack ? player.current.title : "Nothing playing"
                    color: "white"
                    font.family: Theme.displayFamily
                    font.pixelSize: Theme.fontSize(18)
                    font.weight: Font.DemiBold
                }
                Text {
                    text: player.hasTrack ? player.current.artist
                        : (player.visualizerEnabled ? "Play something to see it" : "Turn on “React to the music” to see the sound")
                    color: Qt.rgba(1, 1, 1, 0.7)
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(13)
                }
            }
        }
        Text {
            anchors { right: parent.right; bottom: parent.bottom; margins: 24 }
            visible: !vis.gpu && shell.visualizerStyle !== "bars"
            text: "Liquid, Aurora and Nebula need hardware graphics"
            color: Qt.rgba(1, 1, 1, 0.6)
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(12)
        }
    }
}
