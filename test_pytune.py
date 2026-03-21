"""
pytest test_pytune.py -v
"""

import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest.mock as umock
from unittest.mock import MagicMock, patch
import pytest


def _register_stubs():
    heavy = [
        "PyQt6", "PyQt6.QtWidgets", "PyQt6.QtCore", "PyQt6.QtGui",
        "PyQt6.QtMultimedia",
        "mutagen", "mutagen.mp3", "mutagen.id3", "mutagen.flac",
        "mutagen.mp4", "mutagen.asf", "mutagen.oggvorbis",
        "mutagen.oggopus", "mutagen.wave",
        "version",
    ]
    for name in heavy:
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)

    sys.modules["mutagen.mp3"].MP3 = MagicMock()
    sys.modules["mutagen.id3"].ID3 = MagicMock()
    for tag_cls in ("APIC", "TIT2", "TPE1", "USLT", "TXXX"):
        setattr(sys.modules["mutagen.id3"], tag_cls, type(tag_cls, (), {}))
    sys.modules["mutagen.flac"].FLAC = MagicMock()
    sys.modules["mutagen.flac"].Picture = MagicMock()
    sys.modules["mutagen.mp4"].MP4 = MagicMock()
    sys.modules["mutagen.mp4"].MP4Cover = MagicMock()
    sys.modules["mutagen.asf"].ASF = MagicMock()
    sys.modules["mutagen.asf"].ASFByteArrayAttribute = MagicMock()
    sys.modules["mutagen.oggvorbis"].OggVorbis = MagicMock()
    sys.modules["mutagen.oggopus"].OggOpus = MagicMock()
    sys.modules["mutagen.wave"].WAVE = MagicMock()
    sys.modules["version"].__version__ = "0.0.0-test"

    qtcore = sys.modules["PyQt6.QtCore"]
    for sym in ("Qt", "QUrl", "QTimer", "QMimeData", "pyqtSignal"):
        setattr(qtcore, sym, MagicMock())
    qtcore.QThread = object

    qtmm = sys.modules["PyQt6.QtMultimedia"]
    qtmm.QMediaPlayer = MagicMock()
    qtmm.QAudioOutput = MagicMock()

    qtw = sys.modules["PyQt6.QtWidgets"]
    for sym in (
        "QApplication", "QWidget", "QPushButton", "QSlider", "QLabel",
        "QFileDialog", "QHBoxLayout", "QVBoxLayout", "QListWidget",
        "QListWidgetItem", "QMessageBox", "QLineEdit", "QTabWidget",
        "QTextEdit", "QAbstractItemView", "QDialog", "QFormLayout",
        "QDialogButtonBox", "QScrollArea", "QSizePolicy",
        "QSystemTrayIcon", "QMenu",
    ):
        setattr(qtw, sym, MagicMock())

    qtg = sys.modules["PyQt6.QtGui"]
    for sym in (
        "QPixmap", "QKeySequence", "QShortcut", "QDragEnterEvent",
        "QDropEvent", "QIcon", "QColor", "QPainter", "QFont",
    ):
        setattr(qtg, sym, MagicMock())


_register_stubs()


_PYTUNE_CANDIDATES = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "PyTune.py"),
    "/mnt/user-data/uploads/PyTune.py",
]
_PYTUNE_SRC = next((p for p in _PYTUNE_CANDIDATES if os.path.exists(p)), _PYTUNE_CANDIDATES[0])

with umock.patch("os.path.abspath", return_value=tempfile.gettempdir()):
    spec = importlib.util.spec_from_file_location("PyTune", _PYTUNE_SRC)
    pytune = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pytune)

TrackMeta = pytune.TrackMeta
PlaylistModel = pytune.PlaylistModel
SettingsManager = pytune.SettingsManager
MetaReader = pytune.MetaReader
PlaybackController = pytune.PlaybackController


class TestTrackMeta:

    def test_display_name_artist_and_title(self):
        meta = TrackMeta(path="/music/song.mp3", title="Song", artist="Artist")
        assert meta.display_name == "Artist — Song"

    def test_display_name_title_only(self):
        meta = TrackMeta(path="/music/song.mp3", title="Song", artist="")
        assert meta.display_name == "Song"

    def test_display_name_fallback_to_basename(self):
        meta = TrackMeta(path="/music/mysong.mp3", title="", artist="")
        assert meta.display_name == "mysong.mp3"

    def test_display_name_no_args(self):
        meta = TrackMeta(path="/a/b/c.mp3")
        assert meta.display_name == "c.mp3"

    def test_display_name_artist_no_title(self):
        meta = TrackMeta(path="/music/file.mp3", title="", artist="Prince")
        assert meta.display_name == "Prince — "

    def test_cover_default_none(self):
        assert TrackMeta(path="/music/song.mp3").cover is None

    def test_lyrics_default_none(self):
        assert TrackMeta(path="/music/song.mp3").lyrics is None

    def test_cover_stored(self):
        data = b"\xff\xd8\xff"
        assert TrackMeta(path="/x.mp3", cover=data).cover == data

    def test_repr_hides_cover_bytes(self):
        meta = TrackMeta(path="/x.mp3", cover=b"\x00" * 1000)
        assert len(repr(meta)) < 300


class TestPlaylistModel:

    @pytest.fixture
    def model(self):
        return PlaylistModel()

    @pytest.fixture
    def model_with_files(self, tmp_path, model):
        paths = []
        for i in range(3):
            p = tmp_path / f"track{i}.mp3"
            p.write_bytes(b"")
            model.add(str(p))
            paths.append(str(p))
        return model, paths

    def test_add_returns_true_for_new_file(self, tmp_path, model):
        f = tmp_path / "a.mp3"
        f.write_bytes(b"")
        assert model.add(str(f)) is True

    def test_add_appends_track(self, tmp_path, model):
        f = tmp_path / "a.mp3"
        f.write_bytes(b"")
        model.add(str(f))
        assert str(f) in model.tracks

    def test_add_duplicate_returns_false(self, tmp_path, model):
        f = tmp_path / "a.mp3"
        f.write_bytes(b"")
        model.add(str(f))
        assert model.add(str(f)) is False

    def test_add_missing_file_returns_false(self, model):
        assert model.add("/nonexistent/file.mp3") is False

    def test_add_missing_file_not_appended(self, model):
        model.add("/nonexistent/file.mp3")
        assert len(model.tracks) == 0

    def test_remove_valid_index(self, model_with_files):
        model, paths = model_with_files
        removed = model.remove(0)
        assert removed == paths[0]
        assert paths[0] not in model.tracks

    def test_remove_invalid_index_returns_none(self, model):
        assert model.remove(99) is None

    def test_remove_last_track_resets_index(self, tmp_path, model):
        f = tmp_path / "x.mp3"
        f.write_bytes(b"")
        model.add(str(f))
        model.current_index = 0
        model.remove(0)
        assert model.current_index == -1

    def test_remove_before_current_decrements_index(self, model_with_files):
        model, _ = model_with_files
        model.current_index = 2
        model.remove(0)
        assert model.current_index == 1

    def test_remove_after_current_keeps_index(self, model_with_files):
        model, _ = model_with_files
        model.current_index = 0
        model.remove(2)
        assert model.current_index == 0

    def test_remove_current_track_clamps_index(self, model_with_files):
        model, _ = model_with_files
        model.current_index = 2
        model.remove(2)
        assert model.current_index == 1

    def test_remove_clears_meta_cache(self, tmp_path, model):
        f = tmp_path / "x.mp3"
        f.write_bytes(b"")
        model.add(str(f))
        model.set_meta(TrackMeta(path=str(f), title="X"))
        model.remove(0)
        assert model.get_meta(str(f)) is None

    def test_clear_empties_tracks(self, model_with_files):
        model, _ = model_with_files
        model.clear()
        assert model.tracks == []

    def test_clear_resets_index(self, model_with_files):
        model, _ = model_with_files
        model.current_index = 1
        model.clear()
        assert model.current_index == -1

    def test_clear_empties_meta_cache(self, tmp_path, model):
        f = tmp_path / "x.mp3"
        f.write_bytes(b"")
        model.add(str(f))
        model.set_meta(TrackMeta(path=str(f), title="X"))
        model.clear()
        assert model.meta_cache == {}

    def test_current_track_none_when_empty(self, model):
        assert model.current_track is None

    def test_current_track_returns_path(self, model_with_files):
        model, paths = model_with_files
        model.current_index = 1
        assert model.current_track == paths[1]

    def test_current_track_none_for_minus_one(self, model_with_files):
        model, _ = model_with_files
        model.current_index = -1
        assert model.current_track is None

    def test_reorder_updates_current_index(self, model_with_files):
        model, paths = model_with_files
        model.current_index = 0
        new_order = [paths[2], paths[0], paths[1]]
        model.reorder(new_order)
        assert model.current_index == 1

    def test_reorder_replaces_track_list(self, model_with_files):
        model, paths = model_with_files
        new_order = list(reversed(paths))
        model.reorder(new_order)
        assert model.tracks == new_order

    def test_random_index_returns_0_for_single_track(self, tmp_path, model):
        f = tmp_path / "x.mp3"
        f.write_bytes(b"")
        model.add(str(f))
        assert model.random_index() == 0

    def test_random_index_never_returns_current(self, model_with_files):
        model, _ = model_with_files
        model.current_index = 0
        for _ in range(50):
            assert model.random_index() != 0

    def test_random_index_in_range(self, model_with_files):
        model, paths = model_with_files
        for _ in range(20):
            idx = model.random_index()
            assert 0 <= idx < len(paths)

    def test_set_and_get_meta(self, tmp_path, model):
        f = tmp_path / "x.mp3"
        f.write_bytes(b"")
        model.add(str(f))
        meta = TrackMeta(path=str(f), title="Test")
        model.set_meta(meta)
        assert model.get_meta(str(f)) is meta

    def test_get_meta_returns_none_for_unknown(self, model):
        assert model.get_meta("/unknown.mp3") is None

    def test_to_dict_structure(self, model_with_files):
        model, paths = model_with_files
        model.current_index = 1
        d = model.to_dict()
        assert d["tracks"] == paths
        assert d["current_index"] == 1

    def test_from_dict_loads_existing_files(self, tmp_path, model):
        files = [str(tmp_path / f"t{i}.mp3") for i in range(2)]
        for f in files:
            open(f, "wb").close()
        model.from_dict({"tracks": files, "current_index": 1})
        assert model.tracks == files
        assert model.current_index == 1

    def test_from_dict_skips_missing_files(self, tmp_path, model):
        existing = tmp_path / "exists.mp3"
        existing.write_bytes(b"")
        model.from_dict({
            "tracks": [str(existing), "/missing/track.mp3"],
            "current_index": 0,
        })
        assert len(model.tracks) == 1
        assert str(existing) in model.tracks

    def test_from_dict_clamps_invalid_index(self, tmp_path, model):
        f = tmp_path / "t.mp3"
        f.write_bytes(b"")
        model.from_dict({"tracks": [str(f)], "current_index": 999})
        assert model.current_index == 0

    def test_from_dict_empty_tracks_sets_index_minus1(self, model):
        model.from_dict({"tracks": [], "current_index": 0})
        assert model.current_index == -1


class TestSettingsManager:

    @pytest.fixture(autouse=True)
    def isolate_playlists_file(self, tmp_path, monkeypatch):
        fake_path = str(tmp_path / "playlists.json")
        monkeypatch.setattr(pytune, "PLAYLISTS_FILE", fake_path)
        self.playlists_file = fake_path

    def _write(self, data: dict):
        with open(self.playlists_file, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_load_creates_default_when_no_file(self):
        playlists, current = SettingsManager.load()
        assert current == SettingsManager.DEFAULT_NAME
        assert SettingsManager.DEFAULT_NAME in playlists

    def test_load_returns_saved_data(self):
        self._write({
            "current_playlist": "Rock",
            "playlists": {"Rock": {"tracks": [], "current_index": -1}},
        })
        playlists, current = SettingsManager.load()
        assert current == "Rock"
        assert "Rock" in playlists

    def test_load_falls_back_if_current_not_in_playlists(self):
        self._write({
            "current_playlist": "Несуществующий",
            "playlists": {"Реальный": {"tracks": [], "current_index": -1}},
        })
        playlists, current = SettingsManager.load()
        assert current in playlists

    def test_load_empty_playlists_creates_default(self):
        self._write({"current_playlist": "X", "playlists": {}})
        playlists, current = SettingsManager.load()
        assert SettingsManager.DEFAULT_NAME in playlists

    def test_load_corrupt_json_returns_default(self):
        with open(self.playlists_file, "w") as f:
            f.write("{not valid json")
        playlists, current = SettingsManager.load()
        assert current == SettingsManager.DEFAULT_NAME
        assert SettingsManager.DEFAULT_NAME in playlists

    def test_save_creates_file(self):
        SettingsManager.save({"PL": {"tracks": [], "current_index": -1}}, "PL")
        assert os.path.exists(self.playlists_file)

    def test_save_and_load_roundtrip(self):
        playlists = {"Rock": {"tracks": ["/a.mp3", "/b.mp3"], "current_index": 1}}
        SettingsManager.save(playlists, "Rock")
        loaded, current = SettingsManager.load()
        assert current == "Rock"
        assert loaded["Rock"]["tracks"] == ["/a.mp3", "/b.mp3"]

    def test_save_writes_valid_json(self):
        SettingsManager.save({"X": {"tracks": [], "current_index": -1}}, "X")
        with open(self.playlists_file, encoding="utf-8") as f:
            data = json.load(f)
        assert "playlists" in data
        assert "current_playlist" in data

    def test_save_unicode_playlist_name(self):
        name = "Плейлист 🎵"
        SettingsManager.save({name: {"tracks": [], "current_index": -1}}, name)
        loaded, current = SettingsManager.load()
        assert current == name

    def test_save_overwrites_previous_data(self):
        SettingsManager.save({"A": {"tracks": [], "current_index": -1}}, "A")
        SettingsManager.save({"B": {"tracks": [], "current_index": -1}}, "B")
        _, current = SettingsManager.load()
        assert current == "B"


class TestPlaybackController:

    @pytest.fixture
    def ctrl(self, tmp_path):
        with patch.object(pytune, "QMediaPlayer", MagicMock()), \
             patch.object(pytune, "QAudioOutput", MagicMock()), \
             patch.object(pytune, "QTimer", MagicMock()):
            model = PlaylistModel()
            for i in range(3):
                f = tmp_path / f"t{i}.mp3"
                f.write_bytes(b"")
                model.add(str(f))
            ctrl = PlaybackController(model)
            ctrl.model.current_index = 1
            yield ctrl

    def test_next_index_normal(self, ctrl):
        ctrl.shuffle_mode = False
        ctrl.repeat_mode = PlaybackController.REPEAT_OFF
        ctrl.model.current_index = 0
        assert ctrl._next_index() == 1

    def test_next_index_last_no_repeat(self, ctrl):
        ctrl.shuffle_mode = False
        ctrl.repeat_mode = PlaybackController.REPEAT_OFF
        ctrl.model.current_index = 2
        assert ctrl._next_index() == -1

    def test_next_index_last_repeat_all(self, ctrl):
        ctrl.shuffle_mode = False
        ctrl.repeat_mode = PlaybackController.REPEAT_ALL
        ctrl.model.current_index = 2
        assert ctrl._next_index() == 0

    def test_next_index_repeat_one(self, ctrl):
        ctrl.shuffle_mode = False
        ctrl.repeat_mode = PlaybackController.REPEAT_ONE
        ctrl.model.current_index = 1
        assert ctrl._next_index() == 1

    def test_next_index_shuffle_differs_from_current(self, ctrl):
        ctrl.shuffle_mode = True
        ctrl.model.current_index = 0
        for _ in range(50):
            assert ctrl._next_index() != 0

    def test_next_index_empty_model(self, ctrl):
        ctrl.model.clear()
        assert ctrl._next_index() == -1

    def test_toggle_shuffle_on_off(self, ctrl):
        ctrl.shuffle_mode = False
        assert ctrl.toggle_shuffle() is True
        assert ctrl.toggle_shuffle() is False

    def test_toggle_repeat_full_cycle(self, ctrl):
        ctrl.repeat_mode = PlaybackController.REPEAT_OFF
        assert ctrl.toggle_repeat() == PlaybackController.REPEAT_ONE
        assert ctrl.toggle_repeat() == PlaybackController.REPEAT_ALL
        assert ctrl.toggle_repeat() == PlaybackController.REPEAT_OFF

    def test_set_volume_normal(self, ctrl):
        ctrl.set_volume(50)
        assert abs(ctrl._master_volume - 0.5) < 1e-9

    def test_set_volume_clamps_high(self, ctrl):
        ctrl.set_volume(200)
        assert ctrl._master_volume == 1.0

    def test_set_volume_clamps_low(self, ctrl):
        ctrl.set_volume(-50)
        assert ctrl._master_volume == 0.0

    def test_set_volume_zero(self, ctrl):
        ctrl.set_volume(0)
        assert ctrl._master_volume == 0.0

    def test_set_volume_100(self, ctrl):
        ctrl.set_volume(100)
        assert ctrl._master_volume == 1.0

    def test_is_crossfading_initially_false(self, ctrl):
        assert ctrl.is_crossfading is False

    def test_repeat_constants_are_distinct(self, ctrl):
        assert len({
            PlaybackController.REPEAT_OFF,
            PlaybackController.REPEAT_ONE,
            PlaybackController.REPEAT_ALL,
        }) == 3


class TestMetaReaderOpen:

    @pytest.mark.parametrize("ext,mock_name", [
        (".mp3",  "MP3"),
        (".flac", "FLAC"),
        (".m4a",  "MP4"),
        (".mp4",  "MP4"),
        (".aac",  "MP4"),
        (".wma",  "ASF"),
        (".asf",  "ASF"),
        (".ogg",  "OggVorbis"),
        (".opus", "OggOpus"),
        (".wav",  "WAVE"),
    ])
    def test_open_calls_correct_class(self, ext, mock_name, tmp_path):
        path = str(tmp_path / f"file{ext}")
        mocks = {
            name: MagicMock(return_value=MagicMock())
            for name in ("MP3", "FLAC", "MP4", "ASF", "OggVorbis", "OggOpus", "WAVE")
        }
        with patch.multiple(pytune, **mocks):
            audio, returned_ext = MetaReader._open(path)
        assert returned_ext == ext
        mocks[mock_name].assert_called_once()

    def test_open_unknown_extension_returns_none(self, tmp_path):
        path = str(tmp_path / "file.xyz")
        audio, ext = MetaReader._open(path)
        assert audio is None
        assert ext == ".xyz"

    def test_open_returns_extension_lowercase(self, tmp_path):
        path = str(tmp_path / "FILE.MP3")
        with patch.object(pytune, "MP3", MagicMock(return_value=MagicMock())):
            _, ext = MetaReader._open(path)
        assert ext == ".mp3"


class TestMetaReaderRead:

    def test_read_returns_basename_when_open_fails(self, tmp_path):
        p = tmp_path / "song.mp3"
        p.write_bytes(b"")
        with patch.object(MetaReader, "_open", return_value=(None, ".mp3")):
            meta = MetaReader.read(str(p))
        assert meta.title == "song.mp3"
        assert meta.artist == ""

    def test_read_flac_extracts_title_artist_lyrics(self, tmp_path):
        p = tmp_path / "song.flac"
        p.write_bytes(b"")
        mock_audio = MagicMock()
        mock_audio.get.side_effect = lambda k, d=None: {
            "title":  ["My Title"],
            "artist": ["My Artist"],
            "lyrics": ["Some lyrics"],
        }.get(k, d)
        mock_audio.pictures = []
        with patch.object(MetaReader, "_open", return_value=(mock_audio, ".flac")):
            meta = MetaReader.read(str(p))
        assert meta.title == "My Title"
        assert meta.artist == "My Artist"
        assert meta.lyrics == "Some lyrics"

    def test_read_joins_list_lyrics(self, tmp_path):
        p = tmp_path / "song.flac"
        p.write_bytes(b"")
        mock_audio = MagicMock()
        mock_audio.get.side_effect = lambda k, d=None: {
            "title":  ["T"],
            "artist": ["A"],
            "lyrics": [["line1", "line2"]],
        }.get(k, d)
        mock_audio.pictures = []
        with patch.object(MetaReader, "_open", return_value=(mock_audio, ".flac")):
            meta = MetaReader.read(str(p))
        assert meta.lyrics == "line1\nline2"

    def test_read_flac_cover_extracted(self, tmp_path):
        p = tmp_path / "cover.flac"
        p.write_bytes(b"")
        fake_cover = b"\xff\xd8\xff"
        mock_pic = MagicMock()
        mock_pic.data = fake_cover
        mock_audio = MagicMock()
        mock_audio.get.return_value = [""]
        mock_audio.pictures = [mock_pic]
        with patch.object(MetaReader, "_open", return_value=(mock_audio, ".flac")):
            meta = MetaReader.read(str(p))
        assert meta.cover == fake_cover

    def test_read_exception_does_not_raise(self, tmp_path):
        p = tmp_path / "bad.mp3"
        p.write_bytes(b"")
        with patch.object(MetaReader, "_open", side_effect=RuntimeError("boom")):
            meta = MetaReader.read(str(p))
        assert isinstance(meta, TrackMeta)
        assert meta.path == str(p)

    def test_read_empty_title_falls_back_to_basename(self, tmp_path):
        p = tmp_path / "mysong.flac"
        p.write_bytes(b"")
        mock_audio = MagicMock()
        mock_audio.get.side_effect = lambda k, d=None: {
            "title":  [""],
            "artist": [""],
        }.get(k, d)
        mock_audio.pictures = []
        with patch.object(MetaReader, "_open", return_value=(mock_audio, ".flac")):
            meta = MetaReader.read(str(p))
        assert meta.title == "mysong.flac"