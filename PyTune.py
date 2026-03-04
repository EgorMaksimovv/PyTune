import sys
import os
import json
import random
from dataclasses import dataclass, field
from typing import Optional

from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QSlider, QLabel,
    QFileDialog, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QMessageBox, QLineEdit, QTabWidget, QTextEdit, QAbstractItemView
)
from PyQt6.QtCore import Qt, QUrl, QTimer, QThread, pyqtSignal, QMimeData
from PyQt6.QtGui import QPixmap, QKeySequence, QShortcut, QDragEnterEvent, QDropEvent
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, TIT2, TPE1, USLT, TXXX
from mutagen.flac import FLAC
from mutagen.mp4 import MP4
from mutagen.asf import ASF
from mutagen.oggvorbis import OggVorbis
from mutagen.oggopus import OggOpus
from mutagen.wave import WAVE


SUPPORTED_EXTENSIONS = {'.mp3', '.wav', '.flac', '.ogg', '.opus', '.aac', '.m4a', '.wma', '.asf'}
PLAYLIST_FILE = "playlist.json"


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
    """Читает метаданные одного трека в фоне и сигнализирует о результате."""
    finished = pyqtSignal(TrackMeta)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path

    def run(self):
        meta = MetaReader.read(self.path)
        self.finished.emit(meta)


class MetaReader:
    """Статический класс для чтения метаданных и текстов из аудиофайлов."""

    @staticmethod
    def read(path: str) -> TrackMeta:
        title, artist, cover = MetaReader._read_tags(path)
        lyrics = MetaReader._read_lyrics(path)
        return TrackMeta(path=path, title=title, artist=artist, cover=cover, lyrics=lyrics)

    @staticmethod
    def _open(path: str):
        """Открывает файл нужным парсером и возвращает объект mutagen."""
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
    def _read_tags(path: str):
        title = artist = ""
        cover = None
        try:
            audio, ext = MetaReader._open(path)
            if audio is None:
                return os.path.basename(path), "", None

            if ext == '.mp3':
                tags = audio.tags or {}
                for tag in tags.values():
                    if isinstance(tag, TIT2):
                        title = str(tag.text[0])
                    elif isinstance(tag, TPE1):
                        artist = str(tag.text[0])
                    elif isinstance(tag, APIC) and not cover:
                        cover = tag.data

            elif ext == '.flac':
                title = (audio.get('title') or [''])[0]
                artist = (audio.get('artist') or [''])[0]
                if audio.pictures:
                    cover = audio.pictures[0].data

            elif ext in ('.m4a', '.mp4', '.aac'):
                title = str((audio.get('\xa9nam') or [''])[0])
                artist = str((audio.get('\xa9ART') or [''])[0])
                covr = audio.get('covr') or []
                if covr:
                    cover = bytes(covr[0])

            elif ext in ('.wma', '.asf'):
                title = str((audio.get('Title') or [''])[0])
                artist = str((audio.get('Author') or [''])[0])
                pic = (audio.get('WM/Picture') or [None])[0]
                if pic:
                    cover = pic.data

            elif ext in ('.ogg', '.opus'):
                title = (audio.get('title') or [''])[0]
                artist = (audio.get('artist') or [''])[0]

            elif ext == '.wav':
                tags = audio.tags or {}
                for tag in tags.values():
                    if isinstance(tag, TIT2):
                        title = str(tag.text[0])
                    elif isinstance(tag, TPE1):
                        artist = str(tag.text[0])
                    elif isinstance(tag, APIC) and not cover:
                        cover = tag.data

        except Exception as e:
            print(f"[MetaReader] Ошибка тегов {path}: {e}")

        return title or os.path.basename(path), artist, cover

    @staticmethod
    def _read_lyrics(path: str) -> Optional[str]:
        lyrics = None
        try:
            audio, ext = MetaReader._open(path)
            if audio is None:
                return None

            if ext == '.mp3':
                tags = audio.tags or {}
                for tag in tags.values():
                    if isinstance(tag, USLT):
                        lyrics = tag.text
                        break
                if not lyrics:
                    for tag in tags.values():
                        if isinstance(tag, TXXX) and tag.desc.upper() == 'LYRICS':
                            lyrics = tag.text[0]
                            break

            elif ext == '.flac':
                lyrics = (audio.get('lyrics') or [None])[0]

            elif ext in ('.ogg', '.opus'):
                lyrics = (audio.get('lyrics') or [None])[0]

            elif ext in ('.m4a', '.mp4'):
                lyr = audio.get('\xa9lyr')
                if lyr:
                    lyrics = lyr[0]
                else:
                    for k, v in audio.items():
                        if k.startswith('----:') and 'LYRICS' in k.upper():
                            lyrics = v[0].decode('utf-8', errors='ignore')
                            break

            elif ext in ('.wma', '.asf'):
                lyrics = str((audio.get('WM/Lyrics') or [None])[0])

            elif ext == '.wav':
                tags = audio.tags or {}
                for tag in tags.values():
                    if isinstance(tag, USLT):
                        lyrics = tag.text
                        break

        except Exception as e:
            print(f"[MetaReader] Ошибка текста {path}: {e}")

        if isinstance(lyrics, list):
            lyrics = '\n'.join(lyrics)
        return lyrics or None


class DnDListWidget(QListWidget):
    """QListWidget с поддержкой drag-and-drop файлов извне и перестановки внутри."""
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


class PyTune(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('PyTune')
        self.setMinimumSize(1200, 600)
        self.setAcceptDrops(True)

        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)

        self.playlist: list[str] = []    
        self.meta_cache: dict[str, TrackMeta] = {}
        self.current_index: int = -1
        self.shuffle_mode: bool = False
        self.repeat_mode: int = 0      
        self._meta_worker: Optional[MetaWorker] = None

        self._build_ui()
        self._connect_signals()
        self._setup_shortcuts()
        self.load_playlist()

    def _build_ui(self):
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Поиск (по названию / исполнителю)…")

        self.list_widget = DnDListWidget()

        self.open_btn    = QPushButton('Открыть')
        self.delete_btn  = QPushButton('Удалить')
        self.prev_btn    = QPushButton('⏮')
        self.play_btn    = QPushButton('▶')
        self.stop_btn    = QPushButton('■')
        self.next_btn    = QPushButton('⏭')
        self.shuffle_btn = QPushButton('🔀')
        self.repeat_btn  = QPushButton('🔁')

        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 0)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.audio_output.setVolume(0.8)

        self.time_label = QLabel('00:00 / 00:00')

        controls = QHBoxLayout()
        for w in (self.open_btn, self.delete_btn, self.prev_btn,
                  self.play_btn, self.stop_btn, self.next_btn,
                  self.shuffle_btn, self.repeat_btn):
            controls.addWidget(w)
        controls.addStretch()
        controls.addWidget(QLabel('Громкость'))
        controls.addWidget(self.volume_slider)

        left = QVBoxLayout()
        left.addWidget(self.search_bar)
        left.addWidget(self.list_widget)
        left.addLayout(controls)
        left.addWidget(self.position_slider)
        left.addWidget(self.time_label)

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

        self.title_label = QLabel("—")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet("font-weight: bold; font-size: 14px; margin-top: 5px;")

        self.artist_label = QLabel("")
        self.artist_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.artist_label.setStyleSheet("font-size: 13px; color: gray;")

        right = QVBoxLayout()
        right.addWidget(self.tab_widget)
        right.addWidget(self.title_label)
        right.addWidget(self.artist_label)

        self._set_default_cover()

        main = QHBoxLayout()
        main.addLayout(left, 3)
        main.addLayout(right, 1)
        self.setLayout(main)

    def _connect_signals(self):
        self.open_btn.clicked.connect(self.open_files)
        self.delete_btn.clicked.connect(self.delete_selected)
        self.play_btn.clicked.connect(self.play_pause)
        self.stop_btn.clicked.connect(self.stop)
        self.prev_btn.clicked.connect(self.prev_track)
        self.next_btn.clicked.connect(self.next_track)
        self.shuffle_btn.clicked.connect(self.toggle_shuffle)
        self.repeat_btn.clicked.connect(self.toggle_repeat)

        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list_widget.files_dropped.connect(self._add_paths)
        self.list_widget.order_changed.connect(self._on_order_changed)

        self.search_bar.textChanged.connect(self._filter_list)

        self.position_slider.sliderMoved.connect(self.player.setPosition)
        self.volume_slider.valueChanged.connect(lambda v: self.audio_output.setVolume(v / 100))

        self.player.positionChanged.connect(self.position_slider.setValue)
        self.player.durationChanged.connect(lambda d: self.position_slider.setRange(0, d))
        self.player.playbackStateChanged.connect(self._update_play_button)
        self.player.mediaStatusChanged.connect(self._on_media_status)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_time_label)
        self._timer.start(500)

    def _setup_shortcuts(self):
        shortcuts = {
            Qt.Key.Key_Space:           self.play_pause,
            Qt.Key.Key_MediaPlay:       self.play_pause,
            Qt.Key.Key_MediaStop:       self.stop,
            Qt.Key.Key_MediaNext:       self.next_track,
            Qt.Key.Key_MediaPrevious:   self.prev_track,
            QKeySequence("Ctrl+O"):     self.open_files,
            QKeySequence("Delete"):     self.delete_selected,
            QKeySequence("Right"):      lambda: self._seek_relative(+5_000),
            QKeySequence("Left"):       lambda: self._seek_relative(-5_000),
            QKeySequence("Shift+Right"):lambda: self._seek_relative(+30_000),
            QKeySequence("Shift+Left"): lambda: self._seek_relative(-30_000),
            QKeySequence("Up"):         lambda: self._change_volume(+5),
            QKeySequence("Down"):       lambda: self._change_volume(-5),
            QKeySequence("Ctrl+Right"): self.next_track,
            QKeySequence("Ctrl+Left"):  self.prev_track,
            QKeySequence("Ctrl+S"):     self.toggle_shuffle,
            QKeySequence("Ctrl+R"):     self.toggle_repeat,
        }
        for key, slot in shortcuts.items():
            sc = QShortcut(QKeySequence(key) if isinstance(key, Qt.Key) else key, self)
            sc.activated.connect(slot)


    def open_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, 'Открыть аудио-файлы', '',
            'Audio Files (*.mp3 *.wav *.flac *.ogg *.opus *.aac *.m4a *.wma);;All Files (*)'
        )
        self._add_paths(files)

    def _add_paths(self, paths: list[str]):
        """Добавляет файлы/папки в плейлист"""
        added = False
        for p in paths:
            if os.path.isdir(p):
                for root, _, files in os.walk(p):
                    for f in sorted(files):
                        if os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS:
                            self._add_single(os.path.join(root, f))
                            added = True
            elif os.path.splitext(p)[1].lower() in SUPPORTED_EXTENSIONS:
                if self._add_single(p):
                    added = True

        if added and self.current_index == -1:
            self.current_index = 0
            self._play_index(0)

    def _add_single(self, path: str) -> bool:
        """Добавляет один файл, если его ещё нет. Возвращает True при успехе."""
        if path in self.playlist:
            return False
        if not os.path.isfile(path):
            return False
        self.playlist.append(path)
        item = QListWidgetItem(os.path.basename(path))
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setToolTip(path)
        self.list_widget.addItem(item)
        worker = MetaWorker(path, self)
        worker.finished.connect(self._on_meta_ready)
        worker.start()
        return True

    def _on_meta_ready(self, meta: TrackMeta):
        self.meta_cache[meta.path] = meta
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == meta.path:
                item.setText(meta.display_name)
                break
        if 0 <= self.current_index < len(self.playlist):
            if self.playlist[self.current_index] == meta.path:
                self._show_meta(meta)

    def _on_order_changed(self, new_order: list[str]):
        """Синхронизирует self.playlist после drag-and-drop внутри списка."""
        current_path = self.playlist[self.current_index] if self.current_index >= 0 else None
        self.playlist = new_order
        if current_path and current_path in self.playlist:
            self.current_index = self.playlist.index(current_path)

    def delete_selected(self):
        row = self.list_widget.currentRow()
        if row < 0:
            QMessageBox.information(self, 'Удаление', 'Выберите трек для удаления.')
            return

        path = self.playlist.pop(row)
        self.list_widget.takeItem(row)
        self.meta_cache.pop(path, None)

        if not self.playlist:
            self.player.stop()
            self.current_index = -1
            self._set_default_cover()
            return

        if row == self.current_index:
            self.current_index = min(row, len(self.playlist) - 1)
            self._play_index(self.current_index)
        elif row < self.current_index:
            self.current_index -= 1

    def _play_index(self, index: int):
        if not (0 <= index < len(self.playlist)):
            return
        self.current_index = index
        path = self.playlist[index]

        if not os.path.isfile(path):
            QMessageBox.warning(self, 'Файл не найден', f'Файл не существует:\n{path}')
            self.delete_selected()
            return

        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()
        self._highlight_current()

        if path in self.meta_cache:
            self._show_meta(self.meta_cache[path])
        else:
            self._set_default_cover()

    def play_pause(self):
        if not self.playlist:
            QMessageBox.information(self, 'Пусто', 'Добавьте аудио-файлы.')
            return
        state = self.player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        elif self.player.source().isEmpty():
            self._play_index(max(self.current_index, 0))
        else:
            self.player.play()

    def stop(self):
        self.player.stop()

    def prev_track(self):
        if not self.playlist:
            return
        if self.player.position() > 2000:
            self.player.setPosition(0)
            return
        if self.shuffle_mode:
            self._play_index(self._random_index())
        else:
            self._play_index((self.current_index - 1) % len(self.playlist))

    def next_track(self):
        if not self.playlist:
            return
        if self.shuffle_mode:
            self._play_index(self._random_index())
            return
        if self.repeat_mode == 1:
            self._play_index(self.current_index)
            return
        nxt = self.current_index + 1
        if nxt >= len(self.playlist):
            if self.repeat_mode == 2:
                self._play_index(0)
            else:
                self.stop()
        else:
            self._play_index(nxt)

    def _random_index(self) -> int:
        if len(self.playlist) <= 1:
            return 0
        idx = random.randrange(len(self.playlist))
        while idx == self.current_index:
            idx = random.randrange(len(self.playlist))
        return idx

    def _seek_relative(self, ms: int):
        pos = max(0, min(self.player.position() + ms, self.player.duration()))
        self.player.setPosition(pos)

    def _change_volume(self, delta: int):
        self.volume_slider.setValue(
            max(0, min(100, self.volume_slider.value() + delta))
        )

    def toggle_shuffle(self):
        self.shuffle_mode = not self.shuffle_mode
        self.shuffle_btn.setStyleSheet("background: lightgreen;" if self.shuffle_mode else "")

    def toggle_repeat(self):
        self.repeat_mode = (self.repeat_mode + 1) % 3
        icons = ['🔁', '🔂', '🔁∞']
        self.repeat_btn.setText(icons[self.repeat_mode])

    def _filter_list(self, text: str):
        text = text.lower().strip()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            path = item.data(Qt.ItemDataRole.UserRole)
            meta = self.meta_cache.get(path)
            haystack = (
                (meta.title + ' ' + meta.artist).lower() if meta
                else os.path.basename(path).lower()
            )
            item.setHidden(text not in haystack)

    def _show_meta(self, meta: TrackMeta):
        self.title_label.setText(meta.title or os.path.basename(meta.path))
        self.artist_label.setText(meta.artist)
        if meta.cover:
            pix = QPixmap()
            if pix.loadFromData(meta.cover):
                self.cover_label.setPixmap(
                    pix.scaled(200, 200,
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
                )
                self.lyrics_text.setText(meta.lyrics or '')
                return
        self._set_default_cover_image()
        self.lyrics_text.setText(meta.lyrics or '')

    def _set_default_cover(self):
        self._set_default_cover_image()
        self.title_label.setText("—")
        self.artist_label.setText("")
        self.lyrics_text.clear()

    def _set_default_cover_image(self):
        pix = QPixmap(200, 200)
        pix.fill(Qt.GlobalColor.lightGray)
        self.cover_label.setPixmap(pix)

    def _highlight_current(self):
        if 0 <= self.current_index < self.list_widget.count():
            self.list_widget.setCurrentRow(self.current_index)

    def _update_time_label(self):
        def fmt(ms): s = ms // 1000; return f"{s//60:02d}:{s%60:02d}"
        self.time_label.setText(
            f"{fmt(self.player.position())} / {fmt(self.player.duration())}"
        )

    def _update_play_button(self, state):
        self.play_btn.setText(
            '⏸' if state == QMediaPlayer.PlaybackState.PlayingState else '▶'
        )

    def _on_item_double_clicked(self, item: QListWidgetItem):
        row = self.list_widget.row(item)
        if 0 <= row < len(self.playlist):
            self._play_index(row)

    def _on_media_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.next_track()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        paths = [u.toLocalFile() for u in e.mimeData().urls()]
        self._add_paths(paths)

    def save_playlist(self):
        data = {"playlist": self.playlist, "current_index": self.current_index}
        try:
            with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"[PyTune] Не удалось сохранить плейлист: {e}")

    def load_playlist(self):
        if not os.path.exists(PLAYLIST_FILE):
            return
        try:
            with open(PLAYLIST_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[PyTune] Не удалось загрузить плейлист: {e}")
            return

        paths = [p for p in data.get("playlist", []) if os.path.isfile(p)]
        saved_index = data.get("current_index", -1)

        for path in paths:
            item = QListWidgetItem(os.path.basename(path))
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            self.list_widget.addItem(item)
            self.playlist.append(path)
            worker = MetaWorker(path, self)
            worker.finished.connect(self._on_meta_ready)
            worker.start()

        if self.playlist:
            self.current_index = saved_index if 0 <= saved_index < len(self.playlist) else 0
            self._highlight_current()

    def closeEvent(self, event):
        self.save_playlist()
        event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = PyTune()
    window.show()
    sys.exit(app.exec())
