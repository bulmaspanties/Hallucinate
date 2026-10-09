import QtQuick
import QtQuick.Controls
import "."

Column {
    id: panel
    spacing: 12
    StyledCheck {
        text: "Enable equalizer"
        enabled: player.eqAvailable
        checked: player.eqEnabled
        onToggled: player.setEqEnabled(checked)
    }
    Text {
        visible: !player.eqAvailable
        text: "The equalizer needs the numpy Python package."
        color: Theme.textDim
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize(12)
    }
    Row {
        spacing: 12
        opacity: player.eqEnabled ? 1 : 0.5
        Text { anchors.verticalCenter: parent.verticalCenter; text: "Preset"; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14) }
        StyledCombo {
            id: presetBox
            model: player.eqPresets.concat(["Custom"])
            currentIndex: Math.max(0, model.indexOf(player.eqPreset))
            onActivated: if (currentText !== "Custom") player.setEqPreset(currentText)
        }
    }
    Row {
        spacing: 6
        opacity: player.eqEnabled ? 1 : 0.5
        Repeater {
            model: player.eqBands
            Column {
                required property int index
                required property string modelData
                spacing: 4
                width: 44
                Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: (player.eqGains[index] > 0 ? "+" : "") + Math.round(player.eqGains[index]) ; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11) }
                Slider {
                    id: sl
                    orientation: Qt.Vertical
                    height: 120
                    anchors.horizontalCenter: parent.horizontalCenter
                    from: -12; to: 12; stepSize: 1
                    value: player.eqGains[index]
                    onMoved: player.setEqBand(index, value)
                    background: Rectangle {
                        x: sl.leftPadding + sl.availableWidth / 2 - width / 2
                        y: sl.topPadding
                        width: 4; height: sl.availableHeight; radius: 2
                        color: Theme.surfaceHi
                    }
                    handle: Rectangle {
                        x: sl.leftPadding + sl.availableWidth / 2 - width / 2
                        y: sl.topPadding + sl.visualPosition * (sl.availableHeight - height)
                        width: 14; height: 14; radius: 7
                        color: sl.pressed ? Theme.accentHi : Theme.accent
                    }
                    TapHandler { acceptedButtons: Qt.RightButton; onTapped: player.setEqBand(index, 0) }
                }
                Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: modelData; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11) }
            }
        }
    }
}
