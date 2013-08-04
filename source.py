# -*- coding: utf-8 -*-

"""
    A rhythmbox plugin for playing music from baidu music.

    Copyright (C) 2013 pandasunny <pandasunny@gmail.com>

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

from __future__ import division

import os
import cPickle as pickle
import threading

from gi.repository import GObject
from gi.repository import GLib
from gi.repository import Gdk
from gi.repository import Gtk
from gi.repository import RB

DELTA = 200


class BaseSource(RB.StaticPlaylistSource):

    albumart = {}
    client = None

    def __init__(self):
        super(BaseSource, self).__init__()

        self.songs = []
        self.activated = False
        self.popup = None

        # get_status function
        self.updating = False
        self.status = ""
        self.progress = 0

        # set up the coverart
        self.__art_store = RB.ExtDB(name="album-art")
        self.__req_id = self.__art_store.connect(
                "request", self.__album_art_requested
                )

    def do_selected(self):
        if not self.activated:

            self.set_entry_view()
            # setup the source's status
            self.activated = True

    def do_show_popup(self):
        if self.activate and self.popup:
            self.popup.popup(None, None, None, None,
                    3, Gtk.get_current_event_time())

    def do_get_status(self, status, progress_text, progress):
        progress_text = None
        if self.updating:
            return (self.status, progress_text, self.progress)
        else:
            qm = self.get_query_model()
            return (qm.compute_status_normal("%d song", "%d songs"), None, 2.0)

    def do_add_uri(self):
        return False

    def do_impl_can_add_to_queue(self):
        return False

    def do_impl_can_cut(self):
        return False

    def do_impl_can_copy(self):
        return False

    def do_impl_can_delete(self):
        return True

    def do_impl_can_move_to_trash(self):
        return False

    def do_impl_can_paste(self):
        return False

    def do_impl_can_rename(self):
        return False

    def do_delete_thyself(self):

        self.__art_store.disconnect(self.__req_id)
        self.__req_id = None
        self.__art_store = None

        self.songs = None

        RB.StaticPlaylistSource.delete_thyself(self)

    def __album_art_requested(self, store, key, last_time):
        album = key.get_field("album").decode("utf-8")
        artist = key.get_field("artist").decode("utf-8")
        uri = self.albumart[artist+album] \
                if artist+album in self.albumart else None
        if uri:
            print('album art uri: %s' % uri)
            storekey = RB.ExtDBKey.create_storage("album", album)
            storekey.add_field("artist", artist)
            store.store_uri(storekey, RB.ExtDBSourceType.SEARCH, uri)

    def __add_songs(self, songs, index=-1):
        """ Create entries and commit.

        Args:
            songs: A list includes all songs.
        """
        if not songs:
            return False

        db = self.get_db()

        for song in songs:
            try:
                entry = RB.RhythmDBEntry.new(
                        db, self.props.entry_type, song["songId"]
                        )
                db.entry_set(
                        entry, RB.RhythmDBPropType.TITLE,
                        song["songName"].encode("utf-8")
                        )
                db.entry_set(
                        entry, RB.RhythmDBPropType.ARTIST,
                        song["artistName"].encode("utf-8")
                        )
                db.entry_set(
                        entry, RB.RhythmDBPropType.ALBUM,
                        song["albumName"].encode("utf-8")
                        )
                self.add_entry(entry, index)
                if song["songPicBig"]:
                    albumart = song["songPicBig"]
                elif song["songPicRadio"]:
                    albumart = song["songPicRadio"]
                else:
                    albumart = song["songPicSmall"]
                self.albumart[song["artistName"]+song["albumName"]] = albumart
            except TypeError, e:
                self.add_location(song["songId"], index)
            except KeyError, e:
                pass

        db.commit()

    def add_songs(self, *args):

        Gdk.threads_add_idle(
                GLib.PRIORITY_DEFAULT_IDLE,
                lambda args: self.__add_songs(*args),
                args
                )

    def set_entry_view(self):
        ev = self.get_entry_view()
        ev.get_column(RB.EntryViewColumn.TRACK_NUMBER).set_visible(False)
        ev.get_column(RB.EntryViewColumn.GENRE).set_visible(False)

    def get_songs(self, song_ids):
        """ Get all informations of songs.

        Args:
            song_ids: A list includes all songs' IDs.

        Returns:
            A list includes all informations.
        """
        self.status = _("Loading song list...")
        start, total, songs = 0, len(song_ids), []
        while start < total:
            songs.extend(self.client.get_song_info(song_ids[start:start+DELTA]))
            self.progress = start/total
            self.notify_status_changed()
            start += DELTA
        self.progress = start/total
        self.notify_status_changed()
        return songs

    def test(self):
        qm = self.get_query_model()
        for row in qm:
            entry = row[0]
            print entry.get_ulong(RB.RhythmDBPropType.ENTRY_ID)
            print entry.get_string(RB.RhythmDBPropType.LOCATION)
            print entry.get_string(RB.RhythmDBPropType.TITLE)

class CollectSource(BaseSource):

    def __init__(self):
        super(CollectSource, self).__init__()

    def do_selected(self):
        if not self.activated:

            shell = self.props.shell
            self.popup = shell.props.ui_manager.get_widget("/CollectSourcePopup")

            self.set_entry_view()

            # load the song list
            if self.client.islogin:
                self.load()

            self.activated = True

    def do_impl_delete(self):
        entries = self.get_entry_view().get_selected_entries()
        song_ids = [int(entry.dup_string(RB.RhythmDBPropType.LOCATION)) \
                for entry in entries]
        if self.client.remove_favorite_songs(song_ids):
            for entry in entries:
                self.remove_entry(entry)
                self.songs = filter(lambda x: x not in song_ids, self.songs)

    def do_delete_thyself(self):
        self.songs = None
        BaseSource.delete_thyself(self)

    def __get_song_ids(self):
        """ Get all ids of songs from baidu music.

        Returns:
            A list includes all ids.
        """
        self.status = _("Loading song IDs...")
        start, song_ids = 0, []
        while True:
            song_ids.extend(self.client.get_collect_ids(start))
            self.progress = start/self.client.total
            self.notify_status_changed()
            start += DELTA
            if start >= self.client.total:
                song_ids.reverse()
                break
        self.progress = start/self.client.total
        self.notify_status_changed()
        return song_ids

    def __load_cb(self):
        """ The callback function of load all songs. """
        self.updating = True
        self.songs = self.__get_song_ids()
        songs = self.get_songs(self.songs)
        self.add_songs(songs, 0)
        self.updating = False
        self.notify_status_changed()

    def load(self):
        """ The thread function of load all songs. """
        #Gdk.threads_add_idle(GLib.PRIORITY_DEFAULT_IDLE, self.__load_cb, [])
        thread = threading.Thread(target=self.__load_cb)
        thread.start()

    def __sync_cb(self):
        """ The callback function of sync all songs. """
        self.updating = True
        song_ids = self.__get_song_ids()

        # checkout the added items and the deleted items
        add_ids = song_ids[:]   # the added items
        delete_ids = []         # the delete items
        for key, item in enumerate(self.songs):
            index = key - len(delete_ids)
            if index >= len(song_ids) or song_ids[index] != item:
                delete_ids.append(item)
            elif song_ids[index] == item:
                add_ids.remove(item)
        add_ids.reverse()

        # traversal rows in the query model
        if delete_ids:
            for row in self.__query_model:
                entry = row[0]
                song_id = int(entry.get_string(RB.RhythmDBPropType.LOCATION))
                if song_id in delete_ids:
                    self.remove_entry(entry)

        if add_ids:
            songs = self.get_songs(add_ids)
            self.add_songs(songs, 0)

        self.songs = song_ids
        self.updating = False
        self.notify_status_changed()

    def sync(self):
        """ The thread function of sync all songs. """
        thread = threading.Thread(target=self.__sync_cb)
        thread.start()

    def add(self, songs):
        """ Create entries with songs.

        Args:
            songs: A list includes songs.
        """
        if songs:
            songs.reverse()
            self.songs.extend([int(song["songId"]) for song in songs])
            self.add_songs(songs, 0)

    def clear(self):
        """ Clear all entries in the source. """
        qm = self.get_query_model()
        for row in qm:
            entry = row[0]
            self.remove_entry(entry)


class TempSource(BaseSource):

    def __init__(self):
        super(TempSource, self).__init__()

    def do_selected(self):
        if not self.activated:

            self.set_entry_view()

            self.__playlist =  RB.find_user_cache_file("baidu-music/temp.pls")
            if not os.path.isfile(self.__playlist):
                os.mknod(self.__playlist)
            else:
                try:
                    song_ids = pickle.load(open(self.__playlist, "rb"))
                    songs = self.get_songs(song_ids)
                    self.add(songs)
                except Exception, e:
                    pass

            self.activated = True

    def do_impl_delete(self):
        entries = self.get_entry_view().get_selected_entries()
        for entry in entries:
            self.remove_entry(entry)
            song_id = int(entry.get_string(RB.RhythmDBPropType.LOCATION))
            self.songs.remove(song_id)
        self.__save()

    def add(self, songs):
        """ Create entries with songs.

        Args:
            songs: A list includes songs.
        """
        if songs:
            self.songs.extend([int(song["songId"]) for song in songs])
            self.add_songs(songs, -1)
            self.__save()

    def __save(self):
        pickle.dump(self.songs, open(self.__playlist, "wb"))


GObject.type_register(CollectSource)
GObject.type_register(TempSource)
