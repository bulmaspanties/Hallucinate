pragma Singleton
import QtQuick

QtObject {
    signal openAlbum(string key)
    signal openArtist(string name)
    signal openSettings()
    signal back()
}
