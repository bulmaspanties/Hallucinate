import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

Item {
    id: page
    objectName: "visualizer"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 32
        spacing: 18

        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: "Spectrum visualizer"
                color: Theme.text
                font.family: Theme.displayFamily
                font.pixelSize: Theme.fontSize(25)
                font.weight: Font.Bold
            }
            StyledCheck {
                enabled: player.visualizerAvailable
                text: player.visualizerAvailable ? "Enable live spectrum" : "NumPy is required"
                checked: player.visualizerEnabled
                onToggled: player.setVisualizerEnabled(checked)
            }
        }

        Item { Layout.fillHeight: true }
        Text {
            Layout.alignment: Qt.AlignHCenter
            text: player.visualizerEnabled
                ? player.playing ? "Now playing" : "Start playback to see the spectrum"
                : "Enable the visualizer to analyze audio in the background"
            color: Theme.textDim
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(15)
        }
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 300
            Layout.maximumWidth: 920
            Layout.alignment: Qt.AlignHCenter
            radius: Theme.radius + 4
            color: Theme.surface
            clip: true

            Row {
                id: bars
                anchors { fill: parent; margins: 24 }
                spacing: 5
                Repeater {
                    model: player.visualizerLevels
                    Rectangle {
                        required property real modelData
                        width: Math.max(2, (bars.width - 5 * 23) / 24)
                        height: Math.max(4, modelData * (bars.height - 8))
                        anchors.bottom: parent.bottom
                        radius: Theme.radiusSmall
                        color: Theme.accent
                        opacity: 0.45 + modelData * 0.55
                        Behavior on height {
                            NumberAnimation { duration: 90; easing.type: Easing.OutCubic }
                        }
                        Behavior on opacity { NumberAnimation { duration: 90 } }
                    }
                }
            }
        }
        Text {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignHCenter
            text: player.hasTrack ? player.current.title + " · " + player.current.artist : "Nothing playing"
            color: Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(17)
            elide: Text.ElideRight
            horizontalAlignment: Text.AlignHCenter
        }
        Item { Layout.fillHeight: true }
    }
}
