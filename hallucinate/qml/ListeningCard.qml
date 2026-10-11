import QtQuick
import QtQuick.Controls
import "."

// When you listen: a heatmap of the last 26 weeks (columns are weeks, rows Monday to Sunday), your current
// streak, and this month's most played artists. Click a day to open it in History.
GlassPanel {
    id: card
    objectName: "listeningCard"
    readonly property var heat: userLib.home.heatmap || ({})
    readonly property var artists: userLib.home.topArtists || []
    implicitHeight: 248

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
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Nav.openHistory("") }
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
        Heatmap {
            id: grid
            objectName: "homeHeatmap"
            width: parent.width
            heat: card.heat
            onDayClicked: day => Nav.openHistory(day)
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
