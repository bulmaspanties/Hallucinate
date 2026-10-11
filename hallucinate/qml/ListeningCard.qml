import QtQuick
import QtQuick.Controls
import "."

// When you listen: a heatmap of the last 26 weeks (columns are weeks, rows Monday to Sunday), your current
// streak, and this month's most played artists.
GlassPanel {
    id: card
    objectName: "listeningCard"
    readonly property var heat: userLib.home.heatmap || ({})
    readonly property var days: heat.days || []
    readonly property int weeks: Math.max(1, Math.ceil(days.length / 7))
    readonly property real cell: Math.max(6, Math.min(14, (grid.width - (weeks - 1) * 3) / weeks))
    readonly property var artists: userLib.home.topArtists || []
    implicitHeight: 248

    function dateOf(index) {
        if (!heat.first) return ""
        var d = new Date(heat.first + "T12:00:00")
        d.setDate(d.getDate() + index)
        return d.toLocaleDateString(Qt.locale(), "ddd d MMM")
    }

    Column {
        anchors { fill: parent; margins: 22 }
        spacing: 12
        Row {
            width: parent.width
            Text {
                width: parent.width - streak.width
                text: "Listening"
                color: Theme.text
                font.family: Theme.displayFamily
                font.pixelSize: Theme.fontSize(16)
                font.weight: Font.DemiBold
            }
            Text {
                id: streak
                text: (card.heat.streak || 0) > 1 ? card.heat.streak + "-day streak"
                    : (card.heat.activeDays || 0) + ((card.heat.activeDays || 0) === 1 ? " active day" : " active days")
                color: Theme.accent
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(13)
                font.weight: Font.DemiBold
            }
        }
        Item {
            id: grid
            width: parent.width
            height: 7 * card.cell + 6 * 3
            Repeater {
                model: card.days.length
                Rectangle {
                    required property int index
                    readonly property int count: card.days[index]
                    readonly property real level: card.heat.max > 0 ? Math.sqrt(count / card.heat.max) : 0
                    x: Math.floor(index / 7) * (card.cell + 3)
                    y: (index % 7) * (card.cell + 3)
                    width: card.cell; height: card.cell
                    radius: Math.min(4, card.cell / 3)
                    color: count === 0 ? Theme.stroke
                        : Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.25 + 0.75 * level)
                    border.width: index === card.heat.today ? 1 : 0
                    border.color: Theme.text
                    visible: index <= card.heat.today
                    MouseArea { id: cellMouse; anchors.fill: parent; hoverEnabled: true }
                    ToolTip.visible: cellMouse.containsMouse
                    ToolTip.text: card.dateOf(index) + ": " + (count === 1 ? "1 play" : count + " plays")
                    ToolTip.delay: 150
                }
            }
        }
        Text {
            text: card.artists.length ? "Top artists this month" : "Play some music and your listening shows up here."
            color: Theme.textDim
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(12)
        }
        Row {
            spacing: 14
            Repeater {
                model: card.artists.slice(0, 5)
                Row {
                    required property var modelData
                    spacing: 8
                    Cover {
                        width: 28; height: 28; radius: 14
                        source: modelData.artUrl || ""
                        fallback: (modelData.name || "?").charAt(0)
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData.name
                        color: Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(13)
                        width: Math.min(implicitWidth, 110)
                        elide: Text.ElideRight
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Nav.openArtist(modelData.name) }
                    }
                }
            }
        }
    }
}
