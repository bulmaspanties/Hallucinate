import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

// Every listen, newest first and grouped by day: search it, narrow it to a period, a day, an artist or where the
// listen came from, play a song again, or remove a listen that shouldn't count.
Item {
    id: page
    objectName: "history"
    property string period: "all"
    property string query: ""
    property string artist: ""
    property string source: ""
    readonly property var info: userLib.historyInfo
    readonly property var summary: info.summary || ({})
    readonly property bool dayPicked: period.indexOf("day:") === 0
    readonly property bool filtered: period !== "all" || query.length > 0 || artist.length > 0 || source.length > 0
    readonly property var periods: [
        { id: "all", t: "All time" }, { id: "today", t: "Today" }, { id: "7d", t: "7 days" },
        { id: "30d", t: "30 days" }, { id: "month", t: "This month" }, { id: "year", t: "This year" }
    ]

    function reload() { userLib.loadHistory(query, period, artist, source) }
    onPeriodChanged: reload()
    onArtistChanged: reload()
    onSourceChanged: reload()
    Component.onCompleted: reload()
    Timer { id: queryTimer; interval: 220; onTriggered: page.reload() }

    function dateOf(iso) { return new Date(iso + "T12:00:00") }
    function dayLabel(iso) {
        var day = dateOf(iso), today = new Date()
        today.setHours(12, 0, 0, 0)
        var age = Math.round((today - day) / 86400000)
        if (age === 0) return "Today"
        if (age === 1) return "Yesterday"
        if (age > 1 && age < 7) return Qt.formatDate(day, "dddd")
        return Qt.formatDate(day, day.getFullYear() === today.getFullYear() ? "dddd d MMMM" : "dddd d MMMM yyyy")
    }
    function fmtListening(seconds) {
        var m = Math.round(seconds / 60)
        if (m < 60) return m + " min"
        return seconds >= 36000 ? Theme.fmtHours(seconds) : Math.floor(m / 60) + " h " + (m % 60) + " min"
    }
    function plural(n, one, many) { return n + " " + (n === 1 ? one : many) }
    function sourceName(s) {
        return s === "lastfm" ? "Last.fm" : s === "listenbrainz" ? "ListenBrainz" : s
    }

    component Chip: Rectangle {
        id: chip
        property string text
        property bool selected: false
        property bool closable: false
        signal clicked()
        implicitWidth: chipLabel.implicitWidth + (closable ? 46 : 30)
        implicitHeight: 34
        radius: height / 2
        color: selected ? Theme.accent : (chipMouse.containsMouse ? Theme.glassHover : Theme.glass)
        border.width: selected ? 0 : 1
        border.color: Theme.stroke
        Behavior on color { ColorAnimation { duration: 140 } }
        Accessible.role: Accessible.Button
        Accessible.name: text
        Text {
            id: chipLabel
            x: 15
            anchors.verticalCenter: parent.verticalCenter
            text: chip.text
            color: chip.selected ? Theme.onAccent : Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(13)
            font.weight: chip.selected ? Font.DemiBold : Font.Normal
        }
        Icon {
            visible: chip.closable
            anchors { right: parent.right; rightMargin: 13; verticalCenter: parent.verticalCenter }
            width: 11; height: 11
            name: "close"
            color: chip.selected ? Theme.onAccent : Theme.textDim
        }
        MouseArea { id: chipMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: chip.clicked() }
    }

    ListView {
        id: list
        objectName: "historyList"
        anchors.fill: parent
        model: userLib.historyModel
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {}
        cacheBuffer: 600
        onAtYEndChanged: if (atYEnd && page.info.hasMore) userLib.loadMoreHistory()

        header: Column {
            x: 28
            width: list.width - 56
            spacing: 18
            topPadding: 22
            bottomPadding: 8

            Column {
                spacing: 6
                width: parent.width
                Text {
                    text: "History"
                    color: Theme.text
                    font.family: Theme.displayFamily
                    font.pixelSize: Theme.fontSize(25)
                    font.weight: Font.Bold
                }
                Text {
                    objectName: "historySummary"
                    width: parent.width
                    wrapMode: Text.Wrap
                    text: (page.summary.plays || 0) === 0 ? (page.filtered ? "No listens match." : "Nothing played yet.")
                        : [page.plural(page.summary.plays, "play", "plays"), page.fmtListening(page.summary.seconds || 0),
                           page.plural(page.summary.songs, "song", "songs"), page.plural(page.summary.artists, "artist", "artists"),
                           page.plural(page.summary.days, "day", "days")].join("  ·  ")
                    color: Theme.textDim
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(14)
                }
            }

            GlassPanel {
                width: parent.width
                height: heatCol.implicitHeight + 40
                Column {
                    id: heatCol
                    anchors { left: parent.left; right: parent.right; top: parent.top; margins: 20 }
                    spacing: 12
                    Row {
                        width: parent.width
                        Text {
                            width: parent.width - streakText.width
                            text: "The last 12 months"
                            color: Theme.text
                            font.family: Theme.displayFamily
                            font.pixelSize: Theme.fontSize(15)
                            font.weight: Font.DemiBold
                        }
                        Text {
                            id: streakText
                            readonly property var heat: page.info.heatmap || ({})
                            text: (heat.streak || 0) > 1 ? heat.streak + "-day streak  ·  " + page.plural(heat.activeDays || 0, "active day", "active days")
                                : page.plural(heat.activeDays || 0, "active day", "active days")
                            color: Theme.accent
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(13)
                            font.weight: Font.DemiBold
                        }
                    }
                    Heatmap {
                        objectName: "historyHeatmap"
                        width: parent.width
                        heat: page.info.heatmap || ({})
                        showMonths: true
                        maxCell: 18
                        selected: page.dayPicked ? page.period.slice(4) : ""
                        onDayClicked: day => page.period = (page.period === "day:" + day ? "all" : "day:" + day)
                    }
                    Text {
                        text: "Click a day to see what you played."
                        color: Theme.textDim
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                    }
                }
            }

            Flow {
                width: parent.width
                spacing: 8
                TextField {
                    id: filterField
                    objectName: "historySearch"
                    width: 260
                    height: 34
                    text: page.query
                    placeholderText: "Search history"
                    placeholderTextColor: Theme.textDim
                    color: Theme.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(13)
                    leftPadding: 36
                    rightPadding: 12
                    selectByMouse: true
                    background: Rectangle {
                        radius: height / 2
                        color: filterField.activeFocus ? Theme.glassStrong : Theme.glass
                        border.width: 1
                        border.color: filterField.activeFocus ? Theme.strokeHi : Theme.stroke
                        Icon { x: 13; anchors.verticalCenter: parent.verticalCenter; width: 14; height: 14; name: "search"; color: Theme.textDim }
                    }
                    onTextEdited: { page.query = text; queryTimer.restart() }
                    Keys.onEscapePressed: { text = ""; page.query = ""; queryTimer.restart() }
                }
                Repeater {
                    model: page.periods
                    Chip {
                        required property var modelData
                        text: modelData.t
                        selected: page.period === modelData.id
                        onClicked: page.period = modelData.id
                    }
                }
                Chip {
                    objectName: "dayChip"
                    visible: page.dayPicked
                    selected: true
                    closable: true
                    text: page.dayPicked ? Qt.formatDate(page.dateOf(page.period.slice(4)), "ddd d MMM yyyy") : ""
                    onClicked: page.period = "all"
                }
                Chip {
                    objectName: "artistChip"
                    visible: page.artist.length > 0
                    selected: true
                    closable: true
                    text: page.artist
                    onClicked: page.artist = ""
                }
                StyledCombo {
                    width: 170
                    height: 34
                    model: ["All sources", "Played here", "Imported"]
                    currentIndex: ["", "local", "imported"].indexOf(page.source)
                    onActivated: page.source = ["", "local", "imported"][currentIndex]
                }
            }
        }

        section.property: "day"
        // Section headers are recycled with a new `section` context property (a required property would go stale)
        section.delegate: Item {
            readonly property string day: section
            width: list.width
            height: 54
            readonly property var totals: (page.info.days || {})[day] || ({})
            Text {
                x: 28
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 8
                text: page.dayLabel(parent.day)
                color: Theme.text
                font.family: Theme.displayFamily
                font.pixelSize: Theme.fontSize(15)
                font.weight: Font.DemiBold
            }
            Text {
                anchors { right: parent.right; rightMargin: 36; bottom: parent.bottom; bottomMargin: 9 }
                visible: (parent.totals.plays || 0) > 0
                text: page.plural(parent.totals.plays || 0, "play", "plays") + "  ·  " + page.fmtListening(parent.totals.seconds || 0)
                color: Theme.textDim
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(12)
            }
        }

        delegate: Item {
            id: row
            required property int index
            required property var model
            readonly property bool available: model.available === 1
            readonly property bool current: available && player.hasTrack && player.current.path === model.path
            width: list.width
            height: 56
            Rectangle {
                anchors { fill: parent; leftMargin: 16; rightMargin: 24 }
                radius: Theme.radiusSmall
                color: rowHover.hovered ? Theme.glassHover : "transparent"
            }
            HoverHandler { id: rowHover }
            Accessible.role: Accessible.ListItem
            Accessible.name: model.title + ", " + model.artist + ", " + model.time

            MouseArea {
                anchors.fill: parent
                enabled: row.available
                cursorShape: row.available ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: userLib.playHistoryEntry(row.index)
            }
            Text {
                id: timeText
                x: 28
                width: 46
                anchors.verticalCenter: parent.verticalCenter
                text: row.model.time
                color: Theme.textDim
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(12)
            }
            Cover {
                id: art
                anchors { left: timeText.right; verticalCenter: parent.verticalCenter }
                width: 40; height: 40; radius: Theme.radiusSmall
                source: row.model.artUrl || ""
                fallback: (row.model.title || "?").charAt(0)
                opacity: row.available ? 1 : 0.55
            }
            Column {
                anchors { left: art.right; leftMargin: 12; right: meta.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
                spacing: 2
                Text {
                    width: parent.width
                    text: row.model.title
                    color: row.current ? Theme.accent : Theme.text
                    elide: Text.ElideRight
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(14)
                    font.weight: Font.Medium
                }
                Row {
                    width: parent.width
                    spacing: 0
                    Text {
                        id: artistText
                        width: Math.min(implicitWidth, parent.width * 0.5)
                        text: row.model.artist
                        color: artistMouse.containsMouse ? Theme.text : Theme.textDim
                        elide: Text.ElideRight
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        font.underline: artistMouse.containsMouse
                        MouseArea {
                            id: artistMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: page.artist = row.model.artist
                        }
                        ToolTip.visible: artistMouse.containsMouse
                        ToolTip.text: "Only show " + row.model.artist
                        ToolTip.delay: 700
                    }
                    Text {
                        width: parent.width - artistText.width
                        visible: (row.model.album || "").length > 0
                        text: "  ·  " + row.model.album
                        color: albumMouse.containsMouse && row.model.album_key.length ? Theme.text : Theme.textDim
                        elide: Text.ElideRight
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(12)
                        MouseArea {
                            id: albumMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            enabled: row.model.album_key.length > 0
                            cursorShape: Qt.PointingHandCursor
                            onClicked: Nav.openAlbum(row.model.album_key)
                        }
                    }
                }
            }
            Row {
                id: meta
                anchors { right: parent.right; rightMargin: 30; verticalCenter: parent.verticalCenter }
                spacing: 10
                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    visible: row.model.source !== "local" || !row.available
                    width: badge.implicitWidth + 16; height: 22; radius: 11
                    color: "transparent"
                    border.width: 1
                    border.color: Theme.stroke
                    Text {
                        id: badge
                        anchors.centerIn: parent
                        text: !row.available ? "Not in library" : page.sourceName(row.model.source)
                        color: Theme.textDim
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(11)
                    }
                    ToolTip.visible: badgeMouse.containsMouse
                    ToolTip.text: row.model.source === "local" ? "This file is no longer in your library"
                                  : "Imported from " + page.sourceName(row.model.source)
                    MouseArea { id: badgeMouse; anchors.fill: parent; hoverEnabled: true }
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    width: 44
                    horizontalAlignment: Text.AlignRight
                    text: row.model.duration > 0 ? row.model.durText : ""
                    color: Theme.textDim
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(12)
                }
                IconButton {
                    objectName: "removeListen"
                    anchors.verticalCenter: parent.verticalCenter
                    icon: "close"
                    size: 14
                    tip: "Remove from history"
                    opacity: rowHover.hovered || activeFocus ? 1 : 0
                    onClicked: userLib.removeHistoryEntry(row.model.id)
                }
            }
        }

        footer: Item {
            width: list.width
            height: list.count === 0 ? 220 : 60
            BusyIndicator {
                anchors.centerIn: parent
                running: page.info.loading && list.count > 0
                visible: running
                width: 28; height: 28
            }
            Column {
                anchors.centerIn: parent
                visible: list.count === 0 && !page.info.loading
                spacing: 8
                Icon {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 34; height: 34
                    name: "history"
                    color: Theme.textDim
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: page.filtered ? "No listens match these filters." : "Songs you play show up here."
                    color: Theme.textDim
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(14)
                }
                PillButton {
                    anchors.horizontalCenter: parent.horizontalCenter
                    visible: page.filtered
                    text: "Clear filters"
                    onClicked: { page.query = ""; page.artist = ""; page.source = ""; page.period = "all"; page.reload() }
                }
            }
        }
    }
}
