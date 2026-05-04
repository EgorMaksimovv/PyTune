#version = 1.6.2-alpha
import sys
import os
import json
import math
import random
from dataclasses import dataclass, field
from typing import Optional

from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QSlider, QLabel,
    QFileDialog, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QMessageBox, QLineEdit, QTabWidget, QTextEdit, QAbstractItemView,
    QDialog, QFormLayout, QDialogButtonBox, QScrollArea, QSizePolicy
)
from PyQt6.QtCore import Qt, QUrl, QTimer, QThread, pyqtSignal, QMimeData
from PyQt6.QtGui import QPixmap, QKeySequence, QShortcut, QDragEnterEvent, QDropEvent, QIcon, QColor, QPainter, QFont
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, TIT2, TPE1, USLT, TXXX
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4, MP4Cover
from mutagen.asf import ASF
from mutagen.oggvorbis import OggVorbis
from mutagen.oggopus import OggOpus
from mutagen.wave import WAVE
from version import __version__  # type: ignore


SUPPORTED_EXTENSIONS = {'.mp3', '.wav', '.flac', '.ogg', '.opus', '.aac', '.m4a', '.wma', '.asf'}
PLAYLISTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "playlists.json")

@dataclass
class TrackMeta:
    path: str
    title: str = ""
    artist: str = ""
    cover: Optional[bytes] = field(default=None, repr=False)
    lyrics: Optional[str] = None

    @property
    def display_name(self) -> str:
        if self.artist:
            return f"{self.artist} — {self.title}"
        return self.title or os.path.basename(self.path)


class MetaWorker(QThread):
    finished = pyqtSignal(TrackMeta)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path

    def run(self):
        if self.isInterruptionRequested():
            return
        meta = MetaReader.read(self.path)
        if not self.isInterruptionRequested():
            self.finished.emit(meta)


class MetaReader:
    @staticmethod
    def read(path: str) -> TrackMeta:
        """Читает все метаданные за один проход по файлу."""
        title = artist = ""
        cover = None
        lyrics = None
        try:
            audio, ext = MetaReader._open(path)
            if audio is None:
                return TrackMeta(path=path, title=os.path.basename(path))

            if ext == '.mp3':
                tags = audio.tags or {}
                for tag in tags.values():
                    if isinstance(tag, TIT2):
                        title = str(tag.text[0])
                    elif isinstance(tag, TPE1):
                        artist = str(tag.text[0])
                    elif isinstance(tag, APIC) and not cover:
                        cover = tag.data
                    elif isinstance(tag, USLT) and not lyrics:
                        lyrics = tag.text
                if not lyrics:
                    for tag in tags.values():
                        if isinstance(tag, TXXX) and tag.desc.upper() == 'LYRICS':
                            lyrics = tag.text[0]
                            break

            elif ext == '.flac':
                title = (audio.get('title') or [''])[0]
                artist = (audio.get('artist') or [''])[0]
                if audio.pictures:
                    cover = audio.pictures[0].data
                lyrics = (audio.get('lyrics') or [None])[0]

            elif ext in ('.m4a', '.mp4', '.aac'):
                title = str((audio.get('\xa9nam') or [''])[0])
                artist = str((audio.get('\xa9ART') or [''])[0])
                covr = audio.get('covr') or []
                if covr:
                    cover = bytes(covr[0])
                lyr = audio.get('\xa9lyr')
                if lyr:
                    lyrics = lyr[0]
                else:
                    for k, v in audio.items():
                        if k.startswith('----:') and 'LYRICS' in k.upper():
                            lyrics = v[0].decode('utf-8', errors='ignore')
                            break

            elif ext in ('.wma', '.asf'):
                title = str((audio.get('Title') or [''])[0])
                artist = str((audio.get('Author') or [''])[0])
                pic = (audio.get('WM/Picture') or [None])[0]
                if pic:
                    cover = pic.data
                raw = (audio.get('WM/Lyrics') or [None])[0]
                lyrics = str(raw) if raw is not None else None

            elif ext in ('.ogg', '.opus'):
                title = (audio.get('title') or [''])[0]
                artist = (audio.get('artist') or [''])[0]
                lyrics = (audio.get('lyrics') or [None])[0]

            elif ext == '.wav':
                tags = audio.tags or {}
                for tag in tags.values():
                    if isinstance(tag, TIT2):
                        title = str(tag.text[0])
                    elif isinstance(tag, TPE1):
                        artist = str(tag.text[0])
                    elif isinstance(tag, APIC) and not cover:
                        cover = tag.data
                    elif isinstance(tag, USLT) and not lyrics:
                        lyrics = tag.text

        except Exception as e:
            print(f"[MetaReader] Ошибка чтения {path}: {e}")

        if isinstance(lyrics, list):
            lyrics = '\n'.join(lyrics)

        return TrackMeta(
            path=path,
            title=title or os.path.basename(path),
            artist=artist,
            cover=cover,
            lyrics=lyrics or None,
        )

    @staticmethod
    def _open(path: str):
        ext = os.path.splitext(path)[1].lower()
        if ext == '.mp3':
            return MP3(path, ID3=ID3), ext
        if ext == '.flac':
            return FLAC(path), ext
        if ext in ('.m4a', '.mp4', '.aac'):
            return MP4(path), ext
        if ext in ('.wma', '.asf'):
            return ASF(path), ext
        if ext == '.ogg':
            return OggVorbis(path), ext
        if ext == '.opus':
            return OggOpus(path), ext
        if ext == '.wav':
            return WAVE(path), ext
        return None, ext

    @staticmethod
    def write(path: str, title: str, artist: str, cover: Optional[bytes], lyrics: Optional[str]):
        """Записывает метаданные обратно в файл."""
        try:
            audio, ext = MetaReader._open(path)
            if audio is None:
                return

            if ext == '.mp3':
                if audio.tags is None:
                    audio.add_tags()
                tags = audio.tags
                tags.delall('TIT2'); tags.delall('TPE1')
                tags.delall('APIC'); tags.delall('USLT')
                tags['TIT2'] = TIT2(encoding=3, text=title)
                tags['TPE1'] = TPE1(encoding=3, text=artist)
                if cover:
                    tags['APIC'] = APIC(encoding=3, mime='image/jpeg',
                                        type=3, desc='Cover', data=cover)
                if lyrics:
                    tags['USLT'] = USLT(encoding=3, lang='rus', desc='', text=lyrics)
                audio.save()

            elif ext == '.flac':
                audio['title'] = [title]
                audio['artist'] = [artist]
                if lyrics:
                    audio['lyrics'] = [lyrics]
                elif 'lyrics' in audio:
                    del audio['lyrics']
                if cover:
                    pic = Picture()
                    pic.type = 3
                    pic.mime = 'image/jpeg'
                    pic.data = cover
                    audio.clear_pictures()
                    audio.add_picture(pic)
                audio.save()

            elif ext in ('.m4a', '.mp4', '.aac'):
                audio['\xa9nam'] = [title]
                audio['\xa9ART'] = [artist]
                if lyrics:
                    audio['\xa9lyr'] = [lyrics]
                elif '\xa9lyr' in audio:
                    del audio['\xa9lyr']
                if cover:
                    audio['covr'] = [MP4Cover(cover, imageformat=MP4Cover.FORMAT_JPEG)]
                audio.save()

            elif ext in ('.ogg', '.opus'):
                audio['title'] = [title]
                audio['artist'] = [artist]
                if lyrics:
                    audio['lyrics'] = [lyrics]
                elif 'lyrics' in audio:
                    del audio['lyrics']
                audio.save()

            elif ext in ('.wma', '.asf'):
                audio['Title'] = [title]
                audio['Author'] = [artist]
                if lyrics:
                    audio['WM/Lyrics'] = [lyrics]
                elif 'WM/Lyrics' in audio:
                    del audio['WM/Lyrics']
                if cover:
                    from mutagen.asf import ASFByteArrayAttribute
                    audio['WM/Picture'] = [ASFByteArrayAttribute(cover)]
                elif 'WM/Picture' in audio:
                    del audio['WM/Picture']
                audio.save()

            elif ext == '.wav':
                if audio.tags is None:
                    audio.add_tags()
                tags = audio.tags
                tags.delall('TIT2'); tags.delall('TPE1')
                tags.delall('APIC'); tags.delall('USLT')
                tags['TIT2'] = TIT2(encoding=3, text=title)
                tags['TPE1'] = TPE1(encoding=3, text=artist)
                if cover:
                    tags['APIC'] = APIC(encoding=3, mime='image/jpeg',
                                        type=3, desc='Cover', data=cover)
                if lyrics:
                    tags['USLT'] = USLT(encoding=3, lang='rus', desc='', text=lyrics)
                audio.save()

        except Exception as e:
            print(f"[MetaReader] Ошибка записи {path}: {e}")
            raise 


@dataclass
class AppSettings:
    crossfade_duration: int = 5
    hotkey_play:        str = "Space"
    hotkey_next:        str = "Ctrl+Right"
    hotkey_prev:        str = "Ctrl+Left"
    hotkey_seek_fwd:    str = "Right"
    hotkey_seek_back:   str = "Left"
    hotkey_vol_up:      str = "Up"
    hotkey_vol_down:    str = "Down"

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "AppSettings":
        fields = {f.name for f in AppSettings.__dataclass_fields__.values()}
        return AppSettings(**{k: v for k, v in d.items() if k in fields})


SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")


class AppSettingsManager:
    @staticmethod
    def load() -> AppSettings:
        if not os.path.exists(SETTINGS_FILE):
            return AppSettings()
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return AppSettings.from_dict(json.load(f))
        except Exception as e:
            print(f"[AppSettingsManager] Не удалось загрузить настройки: {e}")
            return AppSettings()

    @staticmethod
    def save(s: AppSettings):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(s.to_dict(), f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"[AppSettingsManager] Не удалось сохранить настройки: {e}")


class HotkeyEdit(QLineEdit):
    """Поле, которое перехватывает нажатие клавиши и записывает её как строку."""

    def __init__(self, value: str, parent=None):
        super().__init__(value, parent)
        self.setReadOnly(True)
        self.setPlaceholderText("Нажмите клавишу…")

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_unknown, Qt.Key.Key_Control,
                   Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
            return
        seq = QKeySequence(int(event.modifiers()) | key).toString()
        self.setText(seq)


class SettingsDialog(QDialog):
    """Диалог настроек: crossfade и горячие клавиши."""

    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.setMinimumWidth(420)

        self._s = settings

        tabs = QTabWidget()

        playback_widget = QWidget()
        pb_form = QFormLayout(playback_widget)
        pb_form.setSpacing(10)
        pb_form.setContentsMargins(12, 12, 12, 12)

        cf_row = QHBoxLayout()
        self._cf_slider = QSlider(Qt.Orientation.Horizontal)
        self._cf_slider.setRange(0, 15)
        self._cf_slider.setValue(settings.crossfade_duration)
        self._cf_label = QLabel(f"{settings.crossfade_duration} сек")
        self._cf_label.setFixedWidth(46)
        self._cf_slider.valueChanged.connect(
            lambda v: self._cf_label.setText(f"{v} сек")
        )
        cf_row.addWidget(self._cf_slider)
        cf_row.addWidget(self._cf_label)
        pb_form.addRow("Crossfade:", cf_row)

        cf_hint = QLabel("0 — crossfade отключён")
        cf_hint.setStyleSheet("color: gray; font-size: 11px;")
        pb_form.addRow("", cf_hint)

        tabs.addTab(playback_widget, "Воспроизведение")

        hk_widget = QWidget()
        hk_form = QFormLayout(hk_widget)
        hk_form.setSpacing(8)
        hk_form.setContentsMargins(12, 12, 12, 12)

        self._hk = {}
        hotkeys = [
            ("hotkey_play",      "Play / Pause"),
            ("hotkey_next",      "Следующий трек"),
            ("hotkey_prev",      "Предыдущий трек"),
            ("hotkey_seek_fwd",  "Перемотка вперёд (+5 с)"),
            ("hotkey_seek_back", "Перемотка назад (−5 с)"),
            ("hotkey_vol_up",    "Громкость +"),
            ("hotkey_vol_down",  "Громкость −"),
        ]
        for attr, label in hotkeys:
            edit = HotkeyEdit(getattr(settings, attr))
            self._hk[attr] = edit
            hk_form.addRow(label + ":", edit)

        reset_btn = QPushButton("Сбросить по умолчанию")
        reset_btn.clicked.connect(self._reset_hotkeys)
        hk_form.addRow("", reset_btn)

        scroll = QScrollArea()
        scroll.setWidget(hk_widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        tabs.addTab(scroll, "Горячие клавиши")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    def _reset_hotkeys(self):
        defaults = AppSettings()
        for attr, edit in self._hk.items():
            edit.setText(getattr(defaults, attr))

    @property
    def result_settings(self) -> AppSettings:
        s = AppSettings(
            crossfade_duration=self._cf_slider.value(),
        )
        for attr, edit in self._hk.items():
            setattr(s, attr, edit.text())
        return s


class ShuffleQueue:
    """
    Перемешанная очередь треков.
    При включении shuffle генерирует случайный порядок всех треков,
    текущий трек ставится первым. Хранит позицию в очереди.
    """

    def __init__(self):
        self._queue: list[int] = []
        self._pos: int = -1

    def build(self, track_count: int, current_index: int):
        """Строит новую перемешанную очередь из всех треков."""
        if track_count == 0:
            self._queue = []
            self._pos = -1
            return
        others = [i for i in range(track_count) if i != current_index]
        random.shuffle(others)
        if current_index >= 0:
            self._queue = [current_index] + others
        else:
            self._queue = others
        self._pos = 0

    def clear(self):
        self._queue = []
        self._pos = -1

    @property
    def current(self) -> int:
        """Индекс текущего трека в плейлисте или -1."""
        if 0 <= self._pos < len(self._queue):
            return self._queue[self._pos]
        return -1

    def next(self) -> int:
        """Переходит к следующему треку в очереди, возвращает индекс или -1."""
        if not self._queue:
            return -1
        self._pos = (self._pos + 1) % len(self._queue)
        return self._queue[self._pos]

    def prev(self) -> int:
        """Переходит к предыдущему треку в очереди, возвращает индекс или -1."""
        if not self._queue:
            return -1
        self._pos = (self._pos - 1) % len(self._queue)
        return self._queue[self._pos]

    def sync_to(self, track_index: int):
        """Синхронизирует позицию очереди с заданным индексом трека."""
        if track_index in self._queue:
            self._pos = self._queue.index(track_index)

    def upcoming(self, count: int = 50) -> list[int]:
        """Возвращает список индексов треков, которые будут играть следующими."""
        if not self._queue:
            return []
        start = self._pos + 1
        n = min(count, len(self._queue) - 1)
        return [self._queue[(start + i) % len(self._queue)] for i in range(n)]

    def remove_track(self, track_index: int):
        """Удаляет трек из очереди и сдвигает индексы."""
        new_queue = []
        removed_before_pos = 0
        removed_at_pos = False
        for i, qi in enumerate(self._queue):
            if qi == track_index:
                if i < self._pos:
                    removed_before_pos += 1
                elif i == self._pos:
                    removed_at_pos = True
                continue
            new_queue.append(qi - 1 if qi > track_index else qi)
        self._queue = new_queue
        if not self._queue:
            self._pos = -1
            return
        new_pos = self._pos - removed_before_pos
        if removed_at_pos:
            new_pos = min(new_pos, len(self._queue) - 1)
        self._pos = max(0, new_pos)

    def __len__(self):
        return len(self._queue)


class PlaylistModel:
    """
    Хранит список треков, кэш метаданных и текущий индекс воспроизведения.
    Не знает ничего об UI и плеере — только данные.
    """

    def __init__(self):
        self.tracks: list[str] = []
        self.meta_cache: dict[str, TrackMeta] = {}
        self.current_index: int = -1
        self.shuffle_queue = ShuffleQueue()

    def add(self, path: str) -> bool:
        """Добавляет трек. Возвращает True, если трек был добавлен."""
        if path in self.tracks or not os.path.isfile(path):
            return False
        self.tracks.append(path)
        return True

    def remove(self, index: int) -> Optional[str]:
        """Удаляет трек по индексу, обновляет current_index. Возвращает путь."""
        if not (0 <= index < len(self.tracks)):
            return None
        path = self.tracks.pop(index)
        self.meta_cache.pop(path, None)
        self.shuffle_queue.remove_track(index)
        if not self.tracks:
            self.current_index = -1
        elif index == self.current_index:
            self.current_index = min(index, len(self.tracks) - 1)
        elif index < self.current_index:
            self.current_index -= 1
        return path

    def reorder(self, new_order: list[str]):
        """Пересобирает список треков после drag-and-drop."""
        current_path = self.current_track
        self.tracks = new_order
        if current_path and current_path in self.tracks:
            self.current_index = self.tracks.index(current_path)

    def clear(self):
        self.tracks.clear()
        self.meta_cache.clear()
        self.current_index = -1

    @property
    def current_track(self) -> Optional[str]:
        if 0 <= self.current_index < len(self.tracks):
            return self.tracks[self.current_index]
        return None

    def random_index(self) -> int:
        """Устаревший метод — используется только если очередь пуста."""
        if not self.tracks:
            return -1
        if len(self.tracks) == 1:
            return 0
        idx = random.randrange(len(self.tracks))
        while idx == self.current_index:
            idx = random.randrange(len(self.tracks))
        return idx


    def set_meta(self, meta: TrackMeta):
        self.meta_cache[meta.path] = meta

    def get_meta(self, path: str) -> Optional[TrackMeta]:
        return self.meta_cache.get(path)

    def to_dict(self) -> dict:
        return {
            "tracks": list(self.tracks),
            "current_index": self.current_index,
        }

    def from_dict(self, data: dict):
        self.tracks = [p for p in data.get("tracks", []) if os.path.isfile(p)]
        idx = data.get("current_index", -1)
        self.current_index = idx if 0 <= idx < len(self.tracks) else (0 if self.tracks else -1)


class SettingsManager:
    """
    Отвечает исключительно за персистентность: читает / пишет playlists.json.
    Не знает об UI, плеере или PlaylistModel.
    """

    DEFAULT_NAME = "Плейлист 1"

    @staticmethod
    def load() -> tuple[dict, str]:
        """
        Возвращает (playlists_dict, current_playlist_name).
        playlists_dict: {name: {"tracks": [...], "current_index": int}}
        """
        default_name = SettingsManager.DEFAULT_NAME
        playlists: dict = {}

        if not os.path.exists(PLAYLISTS_FILE):
            old_file = "playlist.json"
            if os.path.exists(old_file):
                try:
                    with open(old_file, "r", encoding="utf-8") as f:
                        old_data = json.load(f)
                    playlists[default_name] = {
                        "tracks": old_data.get("playlist", []),
                        "current_index": old_data.get("current_index", -1),
                    }
                except Exception:
                    pass
            if not playlists:
                playlists[default_name] = {"tracks": [], "current_index": -1}
            return playlists, default_name

        try:
            with open(PLAYLISTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            playlists = data.get("playlists", {})
            current = data.get("current_playlist", default_name)
        except Exception as e:
            print(f"[SettingsManager] Не удалось загрузить плейлисты: {e}")
            playlists = {default_name: {"tracks": [], "current_index": -1}}
            current = default_name

        if not playlists:
            playlists[default_name] = {"tracks": [], "current_index": -1}
            current = default_name
        if current not in playlists:
            current = next(iter(playlists))
        return playlists, current

    @staticmethod
    def save(playlists: dict, current_playlist_name: str):
        data = {
            "current_playlist": current_playlist_name,
            "playlists": playlists,
        }
        try:
            with open(PLAYLISTS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"[SettingsManager] Не удалось сохранить плейлисты: {e}")


class PlaybackController:
    """
    Инкапсулирует логику воспроизведения: play/pause/stop/next/prev/seek.
    Знает о QMediaPlayer и PlaylistModel, не знает об UI-виджетах.
    """

    REPEAT_OFF   = 0
    REPEAT_ONE   = 1
    REPEAT_ALL   = 2

    CROSSFADE_INTERVAL_MS = 50

    def __init__(self, model: PlaylistModel):
        self.model        = model
        self._master_volume: float = 0.8

        self.player       = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)

        self._fade_player       = QMediaPlayer()
        self._fade_audio_output = QAudioOutput()
        self._fade_player.setAudioOutput(self._fade_audio_output)
        self._fade_audio_output.setVolume(0.0)

        self.shuffle_mode: bool = False
        self.repeat_mode:  int  = self.REPEAT_OFF

        self.on_track_changed = None
        self.on_queue_changed = None


        self.crossfade_duration: int = 0
        self._crossfade_active: bool = False
        self._crossfade_triggered: bool = False
        self._crossfade_just_finished: bool = False
        self._crossfade_next_index: int = -1
        self._crossfade_elapsed_ms: int = 0
        self._crossfade_timer = QTimer()
        self._crossfade_timer.setInterval(self.CROSSFADE_INTERVAL_MS)
        self._crossfade_timer.timeout.connect(self._crossfade_tick)

        self.player.positionChanged.connect(self._check_crossfade_trigger)


    def play_index(self, index: int):
        if not (0 <= index < len(self.model.tracks)):
            return
        path = self.model.tracks[index]
        if not os.path.isfile(path):
            return

        if (self.crossfade_duration > 0
                and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
                and not self._crossfade_active):
            self._start_crossfade(index)
            return

        self._cancel_crossfade()

        self.model.current_index = index
        if self.shuffle_mode:
            self.model.shuffle_queue.sync_to(index)
        self.player.setSource(QUrl.fromLocalFile(path))
        self.audio_output.setVolume(self._master_volume)
        self.player.play()
        if self.on_track_changed:
            self.on_track_changed(index)
        if self.shuffle_mode and self.on_queue_changed:
            self.on_queue_changed()

    def _check_crossfade_trigger(self, position_ms: int):
        """Вызывается при каждом изменении позиции основного плеера."""
        if self.crossfade_duration <= 0 or self._crossfade_active or self._crossfade_triggered:
            return
        if self.repeat_mode == self.REPEAT_ONE:
            return
        duration = self.player.duration()
        if duration <= 0:
            return
        threshold_ms = self.crossfade_duration * 1000
        if duration <= threshold_ms:
            return
        if position_ms >= duration - threshold_ms:
            next_idx = self._next_index()
            if next_idx >= 0:
                self._crossfade_triggered = True
                self._start_crossfade(next_idx)

    def _next_index(self) -> int:
        """Возвращает индекс следующего трека (с учётом режимов) или -1."""
        if not self.model.tracks:
            return -1
        if self.shuffle_mode:
            q = self.model.shuffle_queue
            upcoming = q.upcoming(1)
            return upcoming[0] if upcoming else -1
        if self.repeat_mode == self.REPEAT_ONE:
            return self.model.current_index
        nxt = self.model.current_index + 1
        if nxt >= len(self.model.tracks):
            if self.repeat_mode == self.REPEAT_ALL:
                return 0
            return -1
        return nxt

    def _start_crossfade(self, next_index: int):
        if not (0 <= next_index < len(self.model.tracks)):
            return
        path = self.model.tracks[next_index]
        if not os.path.isfile(path):
            return

        self._crossfade_active = True
        self._crossfade_next_index = next_index
        self._crossfade_elapsed_ms = 0

        self._fade_player.setSource(QUrl.fromLocalFile(path))
        self._fade_audio_output.setVolume(0.0)
        self._fade_player.play()
        self._crossfade_timer.start()

    def _crossfade_tick(self):
        self._crossfade_elapsed_ms += self.CROSSFADE_INTERVAL_MS
        total_ms = self.crossfade_duration * 1000
        if total_ms <= 0:
            self._finish_crossfade()
            return
        t = min(1.0, self._crossfade_elapsed_ms / total_ms)

        self.audio_output.setVolume(self._master_volume * (1.0 - t))
        self._fade_audio_output.setVolume(self._master_volume * t)

        if t >= 1.0:
            self._finish_crossfade()

    def _finish_crossfade(self):
        self._crossfade_timer.stop()

        pos = self._fade_player.position()
        path = self.model.tracks[self._crossfade_next_index]

        self._fade_player.stop()
        self._fade_player.setSource(QUrl())
        self._fade_audio_output.setVolume(0.0)

        self.model.current_index = self._crossfade_next_index
        if self.shuffle_mode:
            self.model.shuffle_queue.sync_to(self._crossfade_next_index)
        self._crossfade_active = False
        self._crossfade_triggered = False
        self._crossfade_just_finished = True
        self._crossfade_next_index = -1

        self.player.stop()
        self.audio_output.setVolume(self._master_volume)
        self.player.setSource(QUrl.fromLocalFile(path))

        _FINAL_STATUSES = {
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.InvalidMedia,
            QMediaPlayer.MediaStatus.NoMedia,
        }

        def _on_loaded(status, _pos=pos, _called=[False]):
            if _called[0] or status not in _FINAL_STATUSES:
                return
            _called[0] = True
            try:
                self.player.mediaStatusChanged.disconnect(_on_loaded)
            except RuntimeError:
                pass
            if status == QMediaPlayer.MediaStatus.LoadedMedia:
                self.player.setPosition(_pos)
                self.player.play()

        self.player.mediaStatusChanged.connect(_on_loaded)

        current_status = self.player.mediaStatus()
        if current_status in _FINAL_STATUSES:
            _on_loaded(current_status)

        if self.on_track_changed:
            self.on_track_changed(self.model.current_index)
        if self.shuffle_mode and self.on_queue_changed:
            self.on_queue_changed()

    def _cancel_crossfade(self):
        if self._crossfade_active:
            self._crossfade_timer.stop()
            self._fade_player.stop()
            self._fade_player.setSource(QUrl())
            self._fade_audio_output.setVolume(0.0)
            self._crossfade_active = False
            self._crossfade_triggered = False
            self._crossfade_just_finished = False
            self._crossfade_next_index = -1
            self._crossfade_elapsed_ms = 0
            self.audio_output.setVolume(self._master_volume)

    def play_pause(self) -> bool:
        """Переключает play/pause. Возвращает True, если треки вообще есть."""
        if not self.model.tracks:
            return False
        state = self.player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._cancel_crossfade()
            self.player.pause()
        elif self.player.source().isEmpty():
            self.play_index(max(self.model.current_index, 0))
        else:
            self.player.play()
        return True

    def stop(self):
        self._cancel_crossfade()
        self.player.stop()

    def next_track(self):
        if not self.model.tracks:
            return
        if self.shuffle_mode:
            nxt = self.model.shuffle_queue.next()
            if nxt >= 0:
                self.play_index(nxt)
            return
        if self.repeat_mode == self.REPEAT_ONE:
            self.play_index(self.model.current_index)
            return
        nxt = self.model.current_index + 1
        if nxt >= len(self.model.tracks):
            if self.repeat_mode == self.REPEAT_ALL:
                self.play_index(0)
            else:
                self.stop()
        else:
            self.play_index(nxt)

    def prev_track(self):
        if not self.model.tracks:
            return
        if self.player.position() > 2000:
            self.player.setPosition(0)
            return
        if self.shuffle_mode:
            prv = self.model.shuffle_queue.prev()
            if prv >= 0:
                self.play_index(prv)
        else:
            self.play_index((self.model.current_index - 1) % len(self.model.tracks))

    def seek_relative(self, ms: int):
        pos = max(0, min(self.player.position() + ms, self.player.duration()))
        self.player.setPosition(pos)

    def set_volume(self, percent: int):
        self._master_volume = max(0, min(100, percent)) / 100
        if not self._crossfade_active:
            self.audio_output.setVolume(self._master_volume)

    def toggle_shuffle(self) -> bool:
        self.shuffle_mode = not self.shuffle_mode
        if self.shuffle_mode:
            self.model.shuffle_queue.build(
                len(self.model.tracks), self.model.current_index
            )
        else:
            self.model.shuffle_queue.clear()
        if self.on_queue_changed:
            self.on_queue_changed()
        return self.shuffle_mode

    def toggle_repeat(self) -> int:
        self.repeat_mode = (self.repeat_mode + 1) % 3
        return self.repeat_mode

    @property
    def is_crossfading(self) -> bool:
        """Публичный доступ к флагу активного кроссфейда."""
        return self._crossfade_active


class MetaThreadPool:
    """
    Хранит ссылки на все активные MetaWorker-потоки.
    Удаляет поток из пула автоматически по сигналу finished,
    предотвращая преждевременную сборку мусора.
    """

    def __init__(self):
        self._active: list[MetaWorker] = []

    def submit(self, path: str, on_ready) -> MetaWorker:
        worker = MetaWorker(path)
        worker.finished.connect(on_ready)
        worker.finished.connect(lambda _meta, w=worker: self._release(w))
        self._active.append(worker)
        worker.start()
        return worker

    def _release(self, worker: MetaWorker):
        try:
            self._active.remove(worker)
        except ValueError:
            pass

    def cancel_all(self):
        """Запрашивает остановку всех активных потоков и дожидается их завершения."""
        for w in list(self._active):
            w.requestInterruption()
            w.quit()
        for w in list(self._active):
            w.wait(500)
        self._active.clear()


class EditMetaDialog(QDialog):
    """Диалог для редактирования названия, исполнителя, обложки и текста трека."""

    def __init__(self, meta: TrackMeta, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Редактировать тег")
        self.setMinimumWidth(520)
        self.setMinimumHeight(560)

        self._cover_bytes: Optional[bytes] = meta.cover

        self.title_edit  = QLineEdit(meta.title)
        self.artist_edit = QLineEdit(meta.artist)

        self.cover_label = QLabel()
        self.cover_label.setFixedSize(180, 180)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setStyleSheet("border: 1px solid #aaa; border-radius: 4px; background: #f0f0f0;")
        self._refresh_cover_preview()

        self.cover_btn        = QPushButton("Выбрать обложку…")
        self.cover_remove_btn = QPushButton("Удалить обложку")
        self.cover_remove_btn.setEnabled(self._cover_bytes is not None)
        cover_btns = QHBoxLayout()
        cover_btns.addWidget(self.cover_btn)
        cover_btns.addWidget(self.cover_remove_btn)

        cover_box = QVBoxLayout()
        cover_box.addWidget(self.cover_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        cover_box.addLayout(cover_btns)

        self.lyrics_edit = QTextEdit()
        self.lyrics_edit.setPlaceholderText("Текст песни…")
        self.lyrics_edit.setText(meta.lyrics or "")
        self.lyrics_edit.setMinimumHeight(160)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )

        form = QFormLayout()
        form.setSpacing(10)
        form.addRow("Название:", self.title_edit)
        form.addRow("Исполнитель:", self.artist_edit)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)
        main_layout.addLayout(form)
        main_layout.addLayout(cover_box)
        main_layout.addWidget(QLabel("Текст песни:"))
        main_layout.addWidget(self.lyrics_edit)
        main_layout.addWidget(buttons)

        self.cover_btn.clicked.connect(self._choose_cover)
        self.cover_remove_btn.clicked.connect(self._remove_cover)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

    def _refresh_cover_preview(self):
        if self._cover_bytes:
            pix = QPixmap()
            if pix.loadFromData(self._cover_bytes):
                self.cover_label.setPixmap(
                    pix.scaled(180, 180,
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
                )
                return
        pix = QPixmap(180, 180)
        pix.fill(Qt.GlobalColor.lightGray)
        self.cover_label.setPixmap(pix)

    def _choose_cover(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выбрать обложку", "",
            "Images (*.jpg *.jpeg *.png *.bmp *.webp);;All Files (*)"
        )
        if path:
            with open(path, 'rb') as f:
                self._cover_bytes = f.read()
            self._refresh_cover_preview()
            self.cover_remove_btn.setEnabled(True)

    def _remove_cover(self):
        self._cover_bytes = None
        self._refresh_cover_preview()
        self.cover_remove_btn.setEnabled(False)

    @property
    def result_title(self) -> str:
        return self.title_edit.text().strip()

    @property
    def result_artist(self) -> str:
        return self.artist_edit.text().strip()

    @property
    def result_cover(self) -> Optional[bytes]:
        return self._cover_bytes

    @property
    def result_lyrics(self) -> Optional[str]:
        text = self.lyrics_edit.toPlainText().strip()
        return text or None


class DnDListWidget(QListWidget):
    files_dropped = pyqtSignal(list)
    order_changed = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e: QDropEvent):
        if e.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in e.mimeData().urls()]
            self.files_dropped.emit(paths)
            e.acceptProposedAction()
        else:
            super().dropEvent(e)
            order = [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]
            self.order_changed.emit(order)


class PlaylistManagerPanel(QWidget):
    """Боковая панель для управления несколькими плейлистами."""
    playlist_selected = pyqtSignal(str)
    playlist_renamed  = pyqtSignal(str, str)
    playlist_deleted  = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(190)

        title = QLabel("Плейлисты")
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        self.new_btn    = QPushButton("＋ Новый")
        self.rename_btn = QPushButton("✏ Переименовать")
        self.delete_btn = QPushButton("✕ Удалить")

        for btn in (self.new_btn, self.rename_btn, self.delete_btn):
            btn.setFixedHeight(26)

        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(4)
        btn_layout.addWidget(self.new_btn)
        btn_layout.addWidget(self.rename_btn)
        btn_layout.addWidget(self.delete_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 8, 6, 8)
        layout.setSpacing(6)
        layout.addWidget(title)
        layout.addWidget(self.list_widget)
        layout.addLayout(btn_layout)

        self.new_btn.clicked.connect(self._on_new)
        self.rename_btn.clicked.connect(self._on_rename)
        self.delete_btn.clicked.connect(self._on_delete)
        self.list_widget.currentRowChanged.connect(self._on_row_changed)

    def populate(self, names: list, current: str):
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for n in names:
            self.list_widget.addItem(n)
        items = self.list_widget.findItems(current, Qt.MatchFlag.MatchExactly)
        if items:
            self.list_widget.setCurrentItem(items[0])
        self.list_widget.blockSignals(False)

    def current_name(self) -> Optional[str]:
        item = self.list_widget.currentItem()
        return item.text() if item else None

    def _ask_name(self, title: str, default: str = "") -> Optional[str]:
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setFixedWidth(300)
        edit = QLineEdit(default)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        lay = QVBoxLayout(dlg)
        lay.addWidget(edit)
        lay.addWidget(btns)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return edit.text().strip() or None
        return None

    def _on_row_changed(self, row: int):
        item = self.list_widget.item(row)
        if item:
            self.playlist_selected.emit(item.text())

    def _on_new(self):
        name = self._ask_name("Новый плейлист", "Плейлист")
        if not name:
            return
        existing = [self.list_widget.item(i).text()
                    for i in range(self.list_widget.count())]
        if name in existing:
            QMessageBox.warning(self, "Ошибка", f'Плейлист "{name}" уже существует.')
            return
        self.list_widget.addItem(name)
        self.list_widget.setCurrentRow(self.list_widget.count() - 1)

    def _on_rename(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        old = item.text()
        new = self._ask_name("Переименовать плейлист", old)
        if not new or new == old:
            return
        existing = [self.list_widget.item(i).text()
                    for i in range(self.list_widget.count())]
        if new in existing:
            QMessageBox.warning(self, "Ошибка", f'Плейлист "{new}" уже существует.')
            return
        item.setText(new)
        self.playlist_renamed.emit(old, new)

    def _on_delete(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        if self.list_widget.count() == 1:
            QMessageBox.information(self, "Удаление", "Нельзя удалить последний плейлист.")
            return
        name = item.text()
        answer = QMessageBox.question(
            self, "Удаление плейлиста",
            f'Удалить плейлист "{name}"?\nТреки с диска удалены не будут.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if answer == QMessageBox.StandardButton.Yes:
            row = self.list_widget.row(item)
            self.list_widget.takeItem(row)
            self.playlist_deleted.emit(name)
            new_row = min(row, self.list_widget.count() - 1)
            self.list_widget.setCurrentRow(new_row)


class WaveformSlider(QWidget):
    """Прогресс-полоса с градиентом и анимированным псевдо-waveform."""
    sliderMoved = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(36)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._minimum = 0
        self._maximum = 0
        self._value   = 0

        self._bars = [0.3 + 0.7 * random.random() for _ in range(80)]

        self._anim_phase = 0.0
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._tick_anim)

    def _tick_anim(self):
        self._anim_phase = (self._anim_phase + 0.12) % (2 * math.pi)
        self.update()

    def setRange(self, minimum: int, maximum: int):
        self._minimum = minimum
        self._maximum = maximum
        if maximum <= minimum:
            self._anim_timer.stop()
        elif not self._anim_timer.isActive():
            self._anim_timer.start(40)
        self.update()

    def setValue(self, value: int):
        self._value = value
        if self._maximum > self._minimum:
            if not self._anim_timer.isActive():
                self._anim_timer.start(40)
        self.update()

    def value(self) -> int:
        return self._value

    def _fraction(self) -> float:
        if self._maximum <= self._minimum:
            return 0.0
        return (self._value - self._minimum) / (self._maximum - self._minimum)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        frac = self._fraction()
        played_x = int(w * frac)

        bar_count = len(self._bars)
        bar_w = w / bar_count
        center_y = h / 2

        for i, bar_h_frac in enumerate(self._bars):
            bx = i * bar_w
            dist = abs(i / bar_count - frac)
            pulse = 1.0 + 0.18 * math.exp(-dist * 30) * math.sin(self._anim_phase + i * 0.3)
            bar_h = bar_h_frac * (h * 0.75) * pulse
            by = center_y - bar_h / 2

            played = (bx + bar_w / 2) < played_x

            if played:
                t = i / bar_count
                r = int(92  + (86  - 92)  * t)
                g = int(107 + (179 - 107) * t)
                b = int(192 + (233 - 192) * t)
                color = QColor(r, g, b)
            else:
                color = QColor(180, 180, 190, 120)

            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            rect_w = max(1.0, bar_w - 1.5)
            painter.drawRoundedRect(
                int(bx), int(by), int(rect_w), int(bar_h), 2, 2
            )

        cx = played_x
        cy = int(center_y)
        pulse_r = 6 + 1.5 * math.sin(self._anim_phase)
        painter.setBrush(QColor(255, 255, 255))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(int(cx - pulse_r), int(cy - pulse_r),
                            int(pulse_r * 2), int(pulse_r * 2))

        painter.end()

    def mousePressEvent(self, event):
        self._seek(event.position().x())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._seek(event.position().x())

    def _seek(self, x: float):
        if self._maximum <= self._minimum:
            return
        frac = max(0.0, min(1.0, x / self.width()))
        val = int(self._minimum + frac * (self._maximum - self._minimum))
        self._value = val
        self.update()
        self.sliderMoved.emit(val)


class PyTune(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f'PyTune {__version__}')
        self.setMinimumSize(900, 550)
        self.setAcceptDrops(True)

        self._model      = PlaylistModel()
        self._ctrl       = PlaybackController(self._model)
        self._thread_pool = MetaThreadPool()
        self._tray_quit: bool = False
        self._settings   = AppSettingsManager.load()

        self._ctrl.on_track_changed = self._on_track_changed_by_ctrl
        self._ctrl.on_queue_changed = self._refresh_queue_panel

        self.playlists: dict           = {}
        self.current_playlist_name: str = SettingsManager.DEFAULT_NAME

        self._build_ui()
        self._connect_signals()
        self._setup_shortcuts()
        self._setup_tray()
        self.load_playlists()

    def _build_ui(self):
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Поиск (по названию / исполнителю)…")

        self.list_widget = DnDListWidget()

        self.open_btn    = QPushButton('Открыть')
        self.delete_btn  = QPushButton('Удалить')
        self.edit_btn    = QPushButton('✏ Редактировать')
        self.settings_btn = QPushButton('⚙')
        self.settings_btn.setFixedWidth(32)
        self.settings_btn.setToolTip("Настройки")
        self.prev_btn    = QPushButton('⏮')
        self.play_btn    = QPushButton('▶')
        self.stop_btn    = QPushButton('■')
        self.next_btn    = QPushButton('⏭')
        self.shuffle_btn = QPushButton('🔀')
        self.repeat_btn  = QPushButton('🔁')

        self.position_slider = WaveformSlider()
        self.position_slider.setRange(0, 0)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self._ctrl.set_volume(80)
        self._ctrl.crossfade_duration = self._settings.crossfade_duration

        self.time_label = QLabel('00:00 / 00:00')

        top_controls = QHBoxLayout()
        for w in (self.open_btn, self.delete_btn, self.edit_btn, self.settings_btn):
            top_controls.addWidget(w)
        top_controls.addStretch()
        top_controls.addWidget(QLabel('Громкость'))
        top_controls.addWidget(self.volume_slider)

        bottom_controls = QHBoxLayout()
        bottom_controls.addStretch()
        for w in (self.prev_btn, self.play_btn, self.stop_btn,
                  self.next_btn, self.shuffle_btn, self.repeat_btn):
            bottom_controls.addWidget(w)
        bottom_controls.addStretch()

        self.playlist_name_label = QLabel("")
        self.playlist_name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.playlist_name_label.setStyleSheet(
            "font-weight: bold; font-size: 12px; color: #555; padding: 2px;"
        )

        left = QVBoxLayout()
        left.addWidget(self.playlist_name_label)
        left.addWidget(self.search_bar)
        left.addWidget(self.list_widget)
        left.addLayout(top_controls)
        left.addLayout(bottom_controls)
        left.addWidget(self.position_slider)
        left.addWidget(self.time_label)

        self.playlist_panel = PlaylistManagerPanel()

        self.tab_widget = QTabWidget()

        cover_container = QWidget()
        cover_inner = QHBoxLayout(cover_container)
        cover_inner.setContentsMargins(0, 0, 0, 0)
        self.cover_label = QLabel()
        self.cover_label.setFixedSize(200, 200)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setStyleSheet("border: 1px solid gray;")
        cover_inner.addStretch()
        cover_inner.addWidget(self.cover_label, alignment=Qt.AlignmentFlag.AlignTop)
        cover_inner.addStretch()
        self.tab_widget.addTab(cover_container, "Обложка")

        self.lyrics_text = QTextEdit()
        self.lyrics_text.setReadOnly(True)
        self.lyrics_text.setPlaceholderText("Текст песни отсутствует")
        self.tab_widget.addTab(self.lyrics_text, "Текст")

        self.queue_list = QListWidget()
        self.queue_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.queue_list.itemDoubleClicked.connect(self._on_queue_item_double_clicked)
        self.tab_widget.addTab(self.queue_list, "Очередь")

        self.title_label = QLabel("—")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet("font-weight: bold; font-size: 14px; margin-top: 5px;")
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.title_label.setMinimumWidth(0)

        self.artist_label = QLabel("")
        self.artist_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.artist_label.setStyleSheet("font-size: 13px; color: gray;")
        self.artist_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.artist_label.setMinimumWidth(0)

        right = QVBoxLayout()
        right.addWidget(self.tab_widget)
        right.addWidget(self.title_label)
        right.addWidget(self.artist_label)

        self._set_default_cover()

        main = QHBoxLayout()
        main.addWidget(self.playlist_panel)
        main.addLayout(left, 3)
        main.addLayout(right, 1)
        self.setLayout(main)

    def _connect_signals(self):
        self.open_btn.clicked.connect(self.open_files)
        self.delete_btn.clicked.connect(self.delete_selected)
        self.edit_btn.clicked.connect(self.edit_selected_meta)
        self.settings_btn.clicked.connect(self._open_settings)
        self.play_btn.clicked.connect(self._on_play_pause_clicked)
        self.stop_btn.clicked.connect(self._ctrl.stop)
        self.prev_btn.clicked.connect(self._ctrl.prev_track)
        self.next_btn.clicked.connect(self._ctrl.next_track)
        self.shuffle_btn.clicked.connect(self._on_toggle_shuffle)
        self.repeat_btn.clicked.connect(self._on_toggle_repeat)

        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list_widget.files_dropped.connect(self._add_paths)
        self.list_widget.order_changed.connect(self._on_order_changed)

        self.cover_label.mouseDoubleClickEvent = lambda _: self.edit_selected_meta()

        self.playlist_panel.playlist_selected.connect(self._switch_playlist)
        self.playlist_panel.playlist_renamed.connect(self._rename_playlist)
        self.playlist_panel.playlist_deleted.connect(self._delete_playlist)

        self.search_bar.textChanged.connect(self._filter_list)

        self.position_slider.sliderMoved.connect(self._ctrl.player.setPosition)
        self.volume_slider.valueChanged.connect(self._ctrl.set_volume)

        self._ctrl.player.positionChanged.connect(self.position_slider.setValue)
        self._ctrl.player.durationChanged.connect(lambda d: self.position_slider.setRange(0, d))
        self._ctrl.player.playbackStateChanged.connect(self._update_play_button)
        self._ctrl.player.mediaStatusChanged.connect(self._on_media_status)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_time_label)
        self._timer.start(500)

    def _setup_shortcuts(self):
        for sc in self.findChildren(QShortcut):
            sc.setEnabled(False)
            sc.deleteLater()

        s = self._settings

        fixed = {
            Qt.Key.Key_MediaPlay:     self._on_play_pause_clicked,
            Qt.Key.Key_MediaStop:     self._ctrl.stop,
            Qt.Key.Key_MediaNext:     self._ctrl.next_track,
            Qt.Key.Key_MediaPrevious: self._ctrl.prev_track,
        }
        for key, slot in fixed.items():
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(slot)

        configurable = [
            (s.hotkey_play,      self._on_play_pause_clicked),
            (s.hotkey_next,      self._ctrl.next_track),
            (s.hotkey_prev,      self._ctrl.prev_track),
            (s.hotkey_seek_fwd,  lambda: self._ctrl.seek_relative(+5_000)),
            (s.hotkey_seek_back, lambda: self._ctrl.seek_relative(-5_000)),
            (s.hotkey_vol_up,    lambda: self.volume_slider.setValue(
                                     min(100, self.volume_slider.value() + 5))),
            (s.hotkey_vol_down,  lambda: self.volume_slider.setValue(
                                     max(0, self.volume_slider.value() - 5))),
        ]
        for seq_str, slot in configurable:
            if seq_str:
                sc = QShortcut(QKeySequence(seq_str), self)
                sc.activated.connect(slot)
        extra = {
            QKeySequence("Shift+Right"): lambda: self._ctrl.seek_relative(+30_000),
            QKeySequence("Shift+Left"):  lambda: self._ctrl.seek_relative(-30_000),
            QKeySequence("Ctrl+O"):      self.open_files,
            QKeySequence("Delete"):      self.delete_selected,
            QKeySequence("Ctrl+E"):      self.edit_selected_meta,
            QKeySequence("Ctrl+S"):      self._on_toggle_shuffle,
            QKeySequence("Ctrl+R"):      self._on_toggle_repeat,
        }
        for seq, slot in extra.items():
            sc = QShortcut(seq, self)
            sc.activated.connect(slot)

    def _open_settings(self):
        dlg = SettingsDialog(self._settings, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._settings = dlg.result_settings
            self._ctrl.crossfade_duration = self._settings.crossfade_duration
            self._setup_shortcuts()
            AppSettingsManager.save(self._settings)

    def _on_play_pause_clicked(self):
        if not self._ctrl.play_pause():
            QMessageBox.information(self, 'Пусто', 'Добавьте аудио-файлы.')

    def _refresh_queue_panel(self):
        """Обновляет список очереди во вкладке."""
        self.queue_list.clear()

        if not self._ctrl.shuffle_mode:
            item = QListWidgetItem("Shuffle выключен")
            item.setForeground(QColor("gray"))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.queue_list.addItem(item)
            return

        q = self._model.shuffle_queue
        upcoming = q.upcoming(len(self._model.tracks))

        fm = self.queue_list.fontMetrics()
        available = self.queue_list.viewport().width() - 8

        def _add_queue_item(ti, prefix=""):
            p = self._model.tracks[ti]
            m = self._model.get_meta(p)
            full = m.display_name if m else os.path.basename(p)
            disp = prefix + full
            elided = fm.elidedText(disp, Qt.TextElideMode.ElideRight, max(available, 60))
            li = QListWidgetItem(elided)
            li.setData(Qt.ItemDataRole.UserRole, ti)
            li.setToolTip(full)
            self.queue_list.addItem(li)

        current_idx = q.current
        if current_idx >= 0:
            _add_queue_item(current_idx, "▶  ")

        for track_idx in upcoming:
            _add_queue_item(track_idx)

    def _on_queue_item_double_clicked(self, item: QListWidgetItem):
        """Переходит к треку по двойному клику в панели очереди."""
        track_idx = item.data(Qt.ItemDataRole.UserRole)
        if track_idx is None:
            return
        self._model.shuffle_queue.sync_to(track_idx)
        self._ctrl.play_index(track_idx)

    def _on_meta_ready_queue_update(self, meta: TrackMeta):
        """При загрузке метаданных обновить очередь, если она видна."""
        self._on_meta_ready(meta)
        if self._ctrl.shuffle_mode:
            self._refresh_queue_panel()

    def _on_toggle_shuffle(self):
        active = self._ctrl.toggle_shuffle()
        self.shuffle_btn.setStyleSheet("background: lightgreen;" if active else "")
        self._refresh_queue_panel()

    def _on_toggle_repeat(self):
        mode = self._ctrl.toggle_repeat()
        icons = ['🔁', '🔂', '🔁∞']
        self.repeat_btn.setText(icons[mode])

    def _on_item_double_clicked(self, item: QListWidgetItem):
        row = self.list_widget.row(item)
        if 0 <= row < len(self._model.tracks):
            self._ctrl.play_index(row)

    def _on_media_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self._ctrl._crossfade_just_finished:
                self._ctrl._crossfade_just_finished = False
                return
            if not self._ctrl.is_crossfading:
                self._ctrl.next_track()

    def _on_track_changed_by_ctrl(self, index: int):
        """Вызывается PlaybackController после смены трека."""
        self._highlight_current()
        if not (0 <= index < len(self._model.tracks)):
            return
        path = self._model.tracks[index]
        meta = self._model.get_meta(path)
        if meta:
            self._show_meta(meta)
            if not self.isVisible():
                self._notify_track(meta)
        else:
            self._set_default_cover()
        if self._ctrl.shuffle_mode:
            self._refresh_queue_panel()

    def _on_order_changed(self, new_order: list[str]):
        self._model.reorder(new_order)

    def open_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, 'Открыть аудио-файлы', '',
            'Audio Files (*.mp3 *.wav *.flac *.ogg *.opus *.aac *.m4a *.wma *.asf);;All Files (*)'
        )
        self._add_paths(files)

    def _add_paths(self, paths: list[str]):
        added = False
        for p in paths:
            if os.path.isdir(p):
                for root, _, files in os.walk(p):
                    for f in sorted(files):
                        if os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS:
                            if self._add_single(os.path.join(root, f)):
                                added = True
            elif os.path.splitext(p)[1].lower() in SUPPORTED_EXTENSIONS:
                if self._add_single(p):
                    added = True

        if added and self._model.current_index == -1:
            self._ctrl.play_index(0)

    def _add_single(self, path: str) -> bool:
        if not self._model.add(path):
            return False
        item = QListWidgetItem(os.path.basename(path))
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setToolTip(path)
        self.list_widget.addItem(item)
        self._thread_pool.submit(path, self._on_meta_ready)
        if self._ctrl.shuffle_mode:
            self._model.shuffle_queue.build(
                len(self._model.tracks), self._model.current_index
            )
            self._refresh_queue_panel()
        return True

    def _on_meta_ready(self, meta: TrackMeta):
        self._model.set_meta(meta)
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == meta.path:
                item.setText(meta.display_name)
                break
        if self._model.current_track == meta.path:
            self._show_meta(meta)
            if not self.isVisible():
                self._notify_track(meta)
        if self._ctrl.shuffle_mode:
            self._refresh_queue_panel()

    def edit_selected_meta(self):
        row = self.list_widget.currentRow()
        if row < 0:
            QMessageBox.information(self, 'Редактирование', 'Выберите трек для редактирования.')
            return

        path = self._model.tracks[row]
        meta = self._model.get_meta(path) or TrackMeta(path=path)

        dlg = EditMetaDialog(meta, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        new_title  = dlg.result_title  or os.path.basename(path)
        new_artist = dlg.result_artist
        new_cover  = dlg.result_cover
        new_lyrics = dlg.result_lyrics

        try:
            MetaReader.write(path, new_title, new_artist, new_cover, new_lyrics)
        except Exception as e:
            QMessageBox.critical(self, 'Ошибка записи', f'Не удалось сохранить теги:\n{e}')
            return

        updated_meta = TrackMeta(path=path, title=new_title, artist=new_artist,
                                 cover=new_cover, lyrics=new_lyrics)
        self._model.set_meta(updated_meta)

        self.list_widget.item(row).setText(updated_meta.display_name)
        if row == self._model.current_index:
            self._show_meta(updated_meta)

    def delete_selected(self):
        row = self.list_widget.currentRow()
        current_item = self.list_widget.item(row) if row >= 0 else None
        if current_item is None or current_item.isHidden():
            QMessageBox.information(self, 'Удаление', 'Выберите трек для удаления.')
            return

        path = current_item.data(Qt.ItemDataRole.UserRole)
        row = self._model.tracks.index(path) if path in self._model.tracks else -1
        if row < 0:
            return

        was_current = (row == self._model.current_index)
        self._model.remove(row)
        list_row = self.list_widget.row(current_item)
        self.list_widget.takeItem(list_row)

        if not self._model.tracks:
            self._ctrl.stop()
            self._set_default_cover()
            return

        if was_current:
            self._ctrl.play_index(self._model.current_index)

    def _save_current_playlist_state(self):
        self.playlists[self.current_playlist_name] = self._model.to_dict()

    def _load_playlist_into_ui(self, name: str):
        self._ctrl.stop()
        self._thread_pool.cancel_all()
        self.list_widget.clear()
        self._model.clear()
        self._set_default_cover()

        data = self.playlists.get(name, {})
        self._model.from_dict(data)

        for path in self._model.tracks:
            item = QListWidgetItem(os.path.basename(path))
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            self.list_widget.addItem(item)
            self._thread_pool.submit(path, self._on_meta_ready)

        if self._model.tracks:
            self._highlight_current()

        self.playlist_name_label.setText(f"▶  {name}")

    def _switch_playlist(self, name: str):
        if name == self.current_playlist_name:
            return
        self._save_current_playlist_state()
        if name not in self.playlists:
            self.playlists[name] = {"tracks": [], "current_index": -1}
        self.current_playlist_name = name
        self._load_playlist_into_ui(name)

    def _rename_playlist(self, old: str, new: str):
        if old in self.playlists:
            self.playlists[new] = self.playlists.pop(old)
        if self.current_playlist_name == old:
            self.current_playlist_name = new
            self.playlist_name_label.setText(f"▶  {new}")

    def _delete_playlist(self, name: str):
        self.playlists.pop(name, None)
        if self.current_playlist_name == name:
            new_name = self.playlist_panel.current_name()
            if new_name:
                if new_name not in self.playlists:
                    self.playlists[new_name] = {"tracks": [], "current_index": -1}
                self.current_playlist_name = new_name
                self._load_playlist_into_ui(new_name)

    def save_playlists(self):
        self._save_current_playlist_state()
        SettingsManager.save(self.playlists, self.current_playlist_name)

    def load_playlists(self):
        self.playlists, self.current_playlist_name = SettingsManager.load()
        self.playlist_panel.populate(list(self.playlists.keys()), self.current_playlist_name)
        self._load_playlist_into_ui(self.current_playlist_name)

    def _filter_list(self, text: str):
        text = text.lower().strip()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            path = item.data(Qt.ItemDataRole.UserRole)
            meta = self._model.get_meta(path)
            haystack = (
                (meta.title + ' ' + meta.artist).lower() if meta
                else os.path.basename(path).lower()
            )
            item.setHidden(text not in haystack)

    def _elide(self, label: QLabel, text: str) -> None:
        fm = label.fontMetrics()
        available = max(label.width(), 100)
        elided = fm.elidedText(text, Qt.TextElideMode.ElideRight, available)
        label.setText(elided)
        label.setToolTip(text)

    def _show_meta(self, meta: TrackMeta):
        title = meta.title or os.path.basename(meta.path)
        self._elide(self.title_label, title)
        self._elide(self.artist_label, meta.artist)

        if meta.artist:
            self.setWindowTitle(f"PyTune  ›  {meta.artist}  ›  {title}")
        else:
            self.setWindowTitle(f"PyTune  ›  {title}")
        cover_loaded = False
        if meta.cover:
            pix = QPixmap()
            if pix.loadFromData(meta.cover):
                self.cover_label.setPixmap(
                    pix.scaled(200, 200,
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
                )
                cover_loaded = True
        if not cover_loaded:
            self._set_default_cover_image()
        self.lyrics_text.setText(meta.lyrics or '')

    def _set_default_cover(self):
        self._set_default_cover_image()
        self.title_label.setText("—")
        self.artist_label.setText("")
        self.lyrics_text.clear()
        self.setWindowTitle(f"PyTune {__version__}")

    def _set_default_cover_image(self):
        pix = QPixmap(200, 200)
        pix.fill(Qt.GlobalColor.lightGray)
        self.cover_label.setPixmap(pix)

    def _highlight_current(self):
        idx = self._model.current_index
        if 0 <= idx < self.list_widget.count():
            self.list_widget.setCurrentRow(idx)

    def _update_time_label(self):
        def fmt(ms): s = ms // 1000; return f"{s//60:02d}:{s%60:02d}"
        self.time_label.setText(
            f"{fmt(self._ctrl.player.position())} / {fmt(self._ctrl.player.duration())}"
        )

    def _update_play_button(self, state):
        self.play_btn.setText(
            '⏸' if state == QMediaPlayer.PlaybackState.PlayingState else '▶'
        )

    def _make_tray_icon(self) -> QIcon:
        pix = QPixmap(64, 64)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#5c6bc0"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, 64, 64)
        painter.setPen(QColor("white"))
        font = QFont("Arial", 32, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "♪")
        painter.end()
        return QIcon(pix)

    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = None
            return

        self._tray = QSystemTrayIcon(self._make_tray_icon(), self)
        self._tray.setToolTip("PyTune")

        menu = QMenu()
        self._tray_play_action = menu.addAction("▶  Воспроизвести / Пауза")
        self._tray_play_action.triggered.connect(self._on_play_pause_clicked)

        tray_next = menu.addAction("⏭  Следующий")
        tray_next.triggered.connect(self._ctrl.next_track)

        tray_prev = menu.addAction("⏮  Предыдущий")
        tray_prev.triggered.connect(self._ctrl.prev_track)

        menu.addSeparator()

        tray_show = menu.addAction("🪟  Показать окно")
        tray_show.triggered.connect(self._show_from_tray)

        menu.addSeparator()

        tray_quit = menu.addAction("✕  Выход")
        tray_quit.triggered.connect(self._quit_app)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

        self._ctrl.player.playbackStateChanged.connect(self._update_tray_play_action)

    def _update_tray_play_action(self, state):
        if self._tray is None:
            return
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._tray_play_action.setText("⏸  Пауза")
        else:
            self._tray_play_action.setText("▶  Воспроизвести")

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_from_tray()

    def _show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_app(self):
        self._tray_quit = True
        self._thread_pool.cancel_all()
        self.save_playlists()
        if self._tray:
            self._tray.hide()
        QApplication.quit()

    def _notify_track(self, meta: TrackMeta):
        if self._tray is None or not self._tray.isVisible():
            return
        title = meta.title or os.path.basename(meta.path)
        body  = meta.artist if meta.artist else "Неизвестный исполнитель"
        self._tray.showMessage(title, body, self._make_tray_icon(), 3000)

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        paths = [u.toLocalFile() for u in e.mimeData().urls()]
        self._add_paths(paths)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        path = self._model.current_track
        if path:
            meta = self._model.get_meta(path)
            if meta:
                self._elide(self.title_label, meta.title or os.path.basename(meta.path))
                self._elide(self.artist_label, meta.artist)
        if self._ctrl.shuffle_mode:
            self._refresh_queue_panel()

    def closeEvent(self, event):
        if self._tray_quit or self._tray is None:
            self._thread_pool.cancel_all()
            self.save_playlists()
            if self._tray:
                self._tray.hide()
            event.accept()
            if self._tray is None:
                QApplication.quit()
        else:
            event.ignore()
            self.hide()
            self._tray.showMessage(
                "PyTune",
                "Приложение свёрнуто в трей. Двойной клик для открытия.",
                self._make_tray_icon(),
                2000
            )


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = PyTune()
    window.show()
    sys.exit(app.exec())
