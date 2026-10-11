import QtQuick
import QtQuick.Controls
import "."

// Plays per day as a grid: columns are weeks, rows Monday to Sunday, newest week on the right.
// `heat` is what core.insights.listening_heatmap returns. Click a day to see what you played.
Item {
    id: map
    property var heat: ({})
    property string selected: ""          // ISO date drawn with a ring
    property bool showMonths: false
    property int gap: 3
    property real maxCell: 14
    signal dayClicked(string day)

    readonly property var days: heat.days || []
    readonly property int weeks: Math.max(1, Math.ceil(days.length / 7))
    readonly property real cell: Math.max(6, Math.min(maxCell, (width - (weeks - 1) * gap) / weeks))
    readonly property real gridTop: showMonths ? Theme.fontSize(11) + 8 : 0
    implicitHeight: gridTop + 7 * cell + 6 * gap

    function dateAt(index) {
        var d = new Date(heat.first + "T12:00:00")
        d.setDate(d.getDate() + index)
        return d
    }
    function isoAt(index) { return heat.first ? Qt.formatDate(dateAt(index), "yyyy-MM-dd") : "" }

    // Month names above the first week that starts in each month
    Repeater {
        model: map.showMonths && map.heat.first ? map.weeks : 0
        Text {
            required property int index
            readonly property var monday: map.dateAt(index * 7)
            visible: monday.getDate() <= 7 && index < map.weeks - 1
            x: index * (map.cell + map.gap)
            text: Qt.formatDate(monday, "MMM")
            color: Theme.textDim
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(11)
        }
    }
    Repeater {
        model: map.days.length
        Rectangle {
            id: cellRect
            required property int index
            readonly property int count: map.days[index]
            readonly property real level: map.heat.max > 0 ? Math.sqrt(count / map.heat.max) : 0
            readonly property string iso: map.isoAt(index)
            x: Math.floor(index / 7) * (map.cell + map.gap)
            y: map.gridTop + (index % 7) * (map.cell + map.gap)
            width: map.cell; height: map.cell
            radius: Math.min(4, map.cell / 3)
            color: count === 0 ? Theme.stroke
                : Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.25 + 0.75 * level)
            border.width: iso === map.selected ? 2 : (index === map.heat.today ? 1 : 0)
            border.color: iso === map.selected ? Theme.accentHi : Theme.text
            visible: index <= map.heat.today
            scale: cellMouse.containsMouse && count > 0 ? 1.25 : 1
            Behavior on scale { NumberAnimation { duration: 90 } }
            MouseArea {
                id: cellMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: cellRect.count > 0 ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: if (cellRect.count > 0) map.dayClicked(cellRect.iso)
            }
            ToolTip.visible: cellMouse.containsMouse
            ToolTip.text: Qt.formatDate(map.dateAt(index), "ddd d MMM yyyy") + ": "
                          + (count === 1 ? "1 play" : count + " plays")
            ToolTip.delay: 150
        }
    }
}
