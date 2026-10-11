import QtQuick
import "."

// A section title in the display face with an optional one-line explanation underneath.
Column {
    property string title
    property string subtitle
    spacing: 4
    Text {
        text: parent.title
        color: Theme.text
        font.family: Theme.displayFamily
        font.pixelSize: Theme.fontSize(17)
        font.weight: Font.DemiBold
    }
    Text {
        visible: text.length > 0
        text: parent.subtitle
        color: Theme.textDim
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize(13)
    }
}
