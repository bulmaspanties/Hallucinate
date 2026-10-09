import QtQuick
import QtQuick.Controls
import "."

Item {
    id: page
    objectName: "songs"
    property bool duplicatesVisible: false

    function applyFilters() {
        duplicatesVisible = false
        library.filterTracks(
            genreFilter.currentIndex > 0 ? genreFilter.currentText : "",
            yearFilter.currentIndex > 0 ? Number(yearFilter.currentText) : 0,
            formatFilter.currentIndex > 0 ? formatFilter.currentText : "")
    }

    Text {
        id: title
        x: 28; y: 20
        text: "Songs"
        color: Theme.text
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize(30)
        font.weight: Font.Bold
    }
    Text {
        anchors { left: title.right; leftMargin: 14; baseline: title.baseline }
        text: duplicatesVisible ? library.duplicates.count + " probable duplicates"
            : library.filtersActive ? library.filteredTracks.count + " filtered tracks"
            : library.trackCount + " tracks"
        color: Theme.textDim
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize(14)
    }
    Row {
        id: filters
        x: 28
        y: title.y + title.height + 12
        width: parent.width - 56
        height: 40
        spacing: 10
        ComboBox {
            id: genreFilter
            width: 180
            height: 38
            model: ["All genres"].concat(library.genres)
            onActivated: page.applyFilters()
        }
        ComboBox {
            id: yearFilter
            width: 110
            height: 38
            model: ["All years"].concat(library.years.map(function(value) { return String(value) }))
            onActivated: page.applyFilters()
        }
        ComboBox {
            id: formatFilter
            width: 130
            height: 38
            model: ["All formats"].concat(library.formats)
            onActivated: page.applyFilters()
        }
        PillButton {
            height: 38
            text: "Clear"
            visible: library.filtersActive
            onClicked: {
                genreFilter.currentIndex = 0
                yearFilter.currentIndex = 0
                formatFilter.currentIndex = 0
                library.filterTracks("", 0, "")
            }
        }
        PillButton {
            height: 38
            text: duplicatesVisible ? "Show songs" : library.duplicatesLoading ? "Finding…" : "Find duplicates"
            enabled: !library.duplicatesLoading
            onClicked: {
                duplicatesVisible = !duplicatesVisible
                if (duplicatesVisible) library.findDuplicates()
            }
        }
    }
    ListView {
        id: list
        anchors { top: filters.bottom; topMargin: 10; left: parent.left; right: parent.right; bottom: parent.bottom }
        anchors.leftMargin: 20; anchors.rightMargin: 8
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: page.duplicatesVisible ? library.duplicates
            : library.filtersActive ? library.filteredTracks : library.songs
        cacheBuffer: 400
        ScrollBar.vertical: ScrollBar {}
        delegate: TrackRow {
            path: model.path
            rowIndex: index
            width: ListView.view.width - 12
            title: model.title
            artist: model.artist + (page.duplicatesVisible ? " · " + model.duplicateCount + " copies" : "")
            album: model.album
            durText: model.durText
            artUrl: model.artUrl
            current: player.hasTrack && player.current.id === model.id
            onActivated: {
                if (page.duplicatesVisible) library.playDuplicate(index)
                else if (library.filtersActive) library.playFilteredSongs(index)
                else library.playSongs(index)
            }
            onEnqueue: player.enqueue(list.model.get(index))
        }
    }
    Text {
        anchors.centerIn: list
        visible: list.count === 0
        text: page.duplicatesVisible
            ? library.duplicatesLoading ? "Checking for duplicates…" : "No probable duplicates found."
            : library.filtersActive ? "No tracks match these filters." : ""
        color: Theme.textDim
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize(14)
    }
}
