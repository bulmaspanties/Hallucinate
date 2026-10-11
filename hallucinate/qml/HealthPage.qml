import QtQuick
import QtQuick.Controls
import QtQuick.Shapes
import "."

// Library health: a score, then each kind of problem with what it means and a fix next to every item.
Item {
    id: page
    objectName: "health"
    readonly property var report: library.health || ({})
    readonly property var checks: report.checks || []
    readonly property int score: report.score !== undefined ? report.score : 100
    property string expanded: ""
    Component.onCompleted: library.checkHealth()

    function fixLabel(kind, id) {
        if (kind === "folder") return "Remove"
        if (id === "covers") return "Find cover"
        if (kind === "album") return "Edit album"
        return "Edit tags"
    }
    function fix(check, item) {
        if (check.kind === "folder") library.removeFolder(item.path)
        else if (check.id === "covers") metaEditor.fetchCover(item.album_key, item.album_artist || "", item.album || "", false)
        else if (check.kind === "album") Nav.editAlbum(item.album_key)
        else Nav.editTags(item.path)
    }
    Connections {
        target: metaEditor
        function onChanged() { library.checkHealth() }
    }

    Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: content.height + 48
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {}

        Column {
            id: content
            x: 28; y: 22
            width: parent.width - 56
            spacing: 18

            Row {
                spacing: 22
                // score ring
                Item {
                    width: 96; height: 96
                    Shape {
                        anchors.fill: parent
                        preferredRendererType: Shape.CurveRenderer
                        ShapePath {
                            strokeColor: Theme.stroke; strokeWidth: 8; fillColor: "transparent"; capStyle: ShapePath.RoundCap
                            PathAngleArc { centerX: 48; centerY: 48; radiusX: 42; radiusY: 42; startAngle: 0; sweepAngle: 360 }
                        }
                        ShapePath {
                            strokeColor: page.score >= 85 ? Theme.accent : page.score >= 60 ? "#e8b25a" : Theme.error
                            strokeWidth: 8; fillColor: "transparent"; capStyle: ShapePath.RoundCap
                            PathAngleArc { centerX: 48; centerY: 48; radiusX: 42; radiusY: 42; startAngle: -90; sweepAngle: 3.6 * page.score }
                        }
                    }
                    Text {
                        objectName: "healthScore"
                        anchors.centerIn: parent
                        text: page.score
                        color: Theme.text
                        font.family: Theme.displayFamily
                        font.pixelSize: Theme.fontSize(26)
                        font.weight: Font.Bold
                    }
                }
                Column {
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 6
                    Text {
                        text: "Library health"
                        color: Theme.text
                        font.family: Theme.displayFamily
                        font.pixelSize: Theme.fontSize(25)
                        font.weight: Font.Bold
                    }
                    Text {
                        objectName: "healthSummary"
                        text: page.report.loading && !page.checks.length ? "Checking your library…"
                            : (page.report.issues || 0) === 0 ? "Nothing to fix. Your library is in great shape."
                            : page.report.issues + (page.report.issues === 1 ? " thing" : " things") + " worth a look across "
                              + (page.report.albums || 0) + " albums and " + (page.report.tracks || 0) + " songs"
                        color: Theme.textDim
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(14)
                    }
                    PillButton {
                        text: page.report.loading ? "Checking…" : "Check again"
                        enabled: !page.report.loading
                        onClicked: library.checkHealth()
                    }
                }
            }

            Repeater {
                model: page.checks
                GlassPanel {
                    id: card
                    required property var modelData
                    readonly property bool open: page.expanded === modelData.id && modelData.count > 0
                    width: content.width
                    height: cardCol.implicitHeight + 32
                    opacity: modelData.count > 0 ? 1 : 0.6
                    Column {
                        id: cardCol
                        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 16 }
                        spacing: 10
                        Item {
                            width: parent.width
                            height: Math.max(head.implicitHeight, 34)
                            Rectangle {
                                id: dot
                                anchors.verticalCenter: parent.verticalCenter
                                width: 10; height: 10; radius: 5
                                color: card.modelData.count === 0 ? Theme.accent
                                    : card.modelData.id === "folders" ? Theme.error : "#e8b25a"
                            }
                            Column {
                                id: head
                                anchors { left: dot.right; leftMargin: 14; right: countText.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
                                spacing: 2
                                Text {
                                    text: card.modelData.title
                                    color: Theme.text
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(15)
                                    font.weight: Font.DemiBold
                                }
                                Text {
                                    width: parent.width
                                    text: card.modelData.detail
                                    color: Theme.textDim
                                    wrapMode: Text.Wrap
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSize(12)
                                }
                            }
                            Text {
                                id: countText
                                anchors { right: chevron.left; rightMargin: 10; verticalCenter: parent.verticalCenter }
                                text: card.modelData.count === 0 ? "All good" : card.modelData.count
                                color: card.modelData.count === 0 ? Theme.accent : Theme.text
                                font.family: Theme.displayFamily
                                font.pixelSize: Theme.fontSize(card.modelData.count === 0 ? 13 : 18)
                                font.weight: Font.DemiBold
                            }
                            Icon {
                                id: chevron
                                anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                                width: 16; height: 16
                                visible: card.modelData.count > 0
                                name: "down"
                                rotation: card.open ? 180 : 0
                                color: Theme.textDim
                                Behavior on rotation { NumberAnimation { duration: 160 } }
                            }
                            MouseArea {
                                anchors.fill: parent
                                enabled: card.modelData.count > 0
                                cursorShape: Qt.PointingHandCursor
                                onClicked: page.expanded = card.open ? "" : card.modelData.id
                            }
                        }
                        Column {
                            visible: card.open
                            width: parent.width
                            spacing: 2
                            Repeater {
                                model: card.open ? card.modelData.items : []
                                Rectangle {
                                    id: itemRow
                                    required property var modelData
                                    width: cardCol.width
                                    height: 48
                                    radius: 10
                                    color: rowHover.hovered ? Theme.glassHover : "transparent"
                                    HoverHandler { id: rowHover }
                                    Cover {
                                        id: thumb
                                        visible: card.modelData.kind !== "folder"
                                        x: 6; anchors.verticalCenter: parent.verticalCenter
                                        width: 36; height: 36; radius: 8
                                        source: itemRow.modelData.artUrl || ""
                                        fallback: ((itemRow.modelData.album || itemRow.modelData.title || "?") + "").charAt(0)
                                    }
                                    Column {
                                        anchors { left: thumb.visible ? thumb.right : parent.left; leftMargin: 12; right: fixButton.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
                                        Text {
                                            width: parent.width
                                            text: card.modelData.kind === "folder" ? itemRow.modelData.path
                                                : card.modelData.kind === "album" ? itemRow.modelData.album : itemRow.modelData.title
                                            color: Theme.text
                                            elide: Text.ElideMiddle
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSize(13)
                                        }
                                        Text {
                                            width: parent.width
                                            visible: card.modelData.kind !== "folder"
                                            text: card.modelData.kind === "album"
                                                ? itemRow.modelData.album_artist + (itemRow.modelData.parts ? "  ·  " + itemRow.modelData.parts + " parts" : "")
                                                : itemRow.modelData.artist + "  ·  " + itemRow.modelData.album
                                                  + (card.modelData.id === "bitrate" ? "  ·  " + Math.round(itemRow.modelData.bitrate / 1000) + " kbps" : "")
                                                  + (card.modelData.id === "duplicates" ? "  ·  " + itemRow.modelData.path : "")
                                            color: Theme.textDim
                                            elide: Text.ElideMiddle
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSize(11)
                                        }
                                    }
                                    PillButton {
                                        id: fixButton
                                        objectName: "healthFix_" + card.modelData.id
                                        anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter }
                                        height: 32
                                        text: page.fixLabel(card.modelData.kind, card.modelData.id)
                                        enabled: !(card.modelData.id === "covers" && metaEditor.busy)
                                        onClicked: page.fix(card.modelData, itemRow.modelData)
                                    }
                                }
                            }
                            Text {
                                visible: card.modelData.count > card.modelData.items.length
                                text: "Showing the first " + card.modelData.items.length + " of " + card.modelData.count
                                color: Theme.textDim
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSize(12)
                                topPadding: 6
                            }
                        }
                    }
                }
            }
        }
    }
}
