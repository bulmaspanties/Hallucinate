pragma Singleton
import QtQuick

QtObject {
    signal openAlbum(string key)
    signal openArtist(string name)
    signal openSettings()
    signal openLiked()
    signal goHome()
    signal openPlaylist(int id)
    signal trackMenu(string path, string title, string context, int index)
    signal back()
}
