import QtQuick
import QtQuick.Controls
import "."

// Playback speed and sleep timer.
Menu {
    id: menu
    Menu {
        title: "Playback speed" + (player.speed !== 1 ? " (" + player.speed + "×)" : "")
        Repeater {
            model: [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2]
            MenuItem {
                required property real modelData
                text: modelData + "×"
                checkable: true
                checked: Math.abs(player.speed - modelData) < 0.001
                onTriggered: player.setSpeed(modelData)
            }
        }
    }
    Menu {
        title: "Sleep timer" + (player.sleepRemaining >= 0 ? " (" + Math.ceil(player.sleepRemaining / 60) + " min)" : player.sleepAfterTrack ? " (end of track)" : "")
        MenuItem { text: "Off"; onTriggered: player.setSleepMinutes(0) }
        Repeater {
            model: [5, 10, 15, 30, 45, 60, 90]
            MenuItem {
                required property int modelData
                text: modelData + " minutes"
                onTriggered: player.setSleepMinutes(modelData)
            }
        }
        MenuItem { text: "End of current track"; onTriggered: player.setSleepAfterTrack(true) }
    }
}
