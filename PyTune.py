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
from version import __version__ # type: ignore


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
        meta = MetaReader.read(self.path)
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
        self._anim_timer.start(40)

    def _tick_anim(self):
        self._anim_phase = (self._anim_phase + 0.12) % (2 * 3.14159)
        self.update()

    def setRange(self, minimum: int, maximum: int):
        self._minimum = minimum
        self._maximum = maximum
        self.update()

    def setValue(self, value: int):
        self._value = value
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

        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)

        self.playlists: dict = {}
        self.current_playlist_name: str = "Плейлист 1"

        self.playlist: list = []
        self.meta_cache: dict = {}
        self.current_index: int = -1
        self.shuffle_mode: bool = False
        self.repeat_mode: int = 0
        self._meta_worker: Optional[MetaWorker] = None

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
        self.audio_output.setVolume(0.8)

        self.time_label = QLabel('00:00 / 00:00')

        top_controls = QHBoxLayout()
        for w in (self.open_btn, self.delete_btn, self.edit_btn):
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
        main.addWidget(self.playlist_panel)
        main.addLayout(left, 3)
        main.addLayout(right, 1)
        self.setLayout(main)

    def _connect_signals(self):
        self.open_btn.clicked.connect(self.open_files)
        self.delete_btn.clicked.connect(self.delete_selected)
        self.edit_btn.clicked.connect(self.edit_selected_meta)  
        self.play_btn.clicked.connect(self.play_pause)
        self.stop_btn.clicked.connect(self.stop)
        self.prev_btn.clicked.connect(self.prev_track)
        self.next_btn.clicked.connect(self.next_track)
        self.shuffle_btn.clicked.connect(self.toggle_shuffle)
        self.repeat_btn.clicked.connect(self.toggle_repeat)

        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list_widget.files_dropped.connect(self._add_paths)
        self.list_widget.order_changed.connect(self._on_order_changed)

        self.cover_label.mouseDoubleClickEvent = lambda _: self.edit_selected_meta()

        self.playlist_panel.playlist_selected.connect(self._switch_playlist)
        self.playlist_panel.playlist_renamed.connect(self._rename_playlist)
        self.playlist_panel.playlist_deleted.connect(self._delete_playlist)

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
            Qt.Key.Key_Space:            self.play_pause,
            Qt.Key.Key_MediaPlay:        self.play_pause,
            Qt.Key.Key_MediaStop:        self.stop,
            Qt.Key.Key_MediaNext:        self.next_track,
            Qt.Key.Key_MediaPrevious:    self.prev_track,
            QKeySequence("Ctrl+O"):      self.open_files,
            QKeySequence("Delete"):      self.delete_selected,
            QKeySequence("Ctrl+E"):      self.edit_selected_meta,  
            QKeySequence("Right"):       lambda: self._seek_relative(+5_000),
            QKeySequence("Left"):        lambda: self._seek_relative(-5_000),
            QKeySequence("Shift+Right"): lambda: self._seek_relative(+30_000),
            QKeySequence("Shift+Left"):  lambda: self._seek_relative(-30_000),
            QKeySequence("Up"):          lambda: self._change_volume(+5),
            QKeySequence("Down"):        lambda: self._change_volume(-5),
            QKeySequence("Ctrl+Right"):  self.next_track,
            QKeySequence("Ctrl+Left"):   self.prev_track,
            QKeySequence("Ctrl+S"):      self.toggle_shuffle,
            QKeySequence("Ctrl+R"):      self.toggle_repeat,
        }
        for key, slot in shortcuts.items():
            sc = QShortcut(QKeySequence(key) if isinstance(key, Qt.Key) else key, self)
            sc.activated.connect(slot)


    def edit_selected_meta(self):
        """Открывает диалог редактирования тегов для выбранного трека."""
        row = self.list_widget.currentRow()
        if row < 0:
            QMessageBox.information(self, 'Редактирование', 'Выберите трек для редактирования.')
            return

        path = self.playlist[row]

        meta = self.meta_cache.get(path) or TrackMeta(path=path)

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
            QMessageBox.critical(self, 'Ошибка записи',
                                 f'Не удалось сохранить теги:\n{e}')
            return

        updated_meta = TrackMeta(
            path=path, title=new_title, artist=new_artist,
            cover=new_cover, lyrics=new_lyrics
        )
        self.meta_cache[path] = updated_meta

        item = self.list_widget.item(row)
        item.setText(updated_meta.display_name)

        if row == self.current_index:
            self._show_meta(updated_meta)

    def open_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, 'Открыть аудио-файлы', '',
            'Audio Files (*.mp3 *.wav *.flac *.ogg *.opus *.aac *.m4a *.wma);;All Files (*)'
        )
        self._add_paths(files)

    def _add_paths(self, paths: list[str]):
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
                if not self.isVisible():
                    self._notify_track(meta)

    def _on_order_changed(self, new_order: list[str]):
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
            if not self.isVisible():
                self._notify_track(self.meta_cache[path])
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
        self.volume_slider.setValue(max(0, min(100, self.volume_slider.value() + delta)))

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

    def _save_current_playlist_state(self):
        """Сохраняет состояние активного плейлиста в словарь playlists."""
        self.playlists[self.current_playlist_name] = {
            "tracks": list(self.playlist),
            "current_index": self.current_index,
        }

    def _load_playlist_into_ui(self, name: str):
        """Загружает плейлист name в виджет треков."""
        self.player.stop()
        self.list_widget.clear()
        self.playlist.clear()
        self.current_index = -1
        self._set_default_cover()

        data = self.playlists.get(name, {})
        paths = [p for p in data.get("tracks", []) if os.path.isfile(p)]
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

    def _make_tray_icon(self) -> QIcon:
        """Генерирует простую иконку в виде музыкальной ноты."""
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
        """Создаёт иконку в системном трее с контекстным меню."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = None
            return

        self._tray = QSystemTrayIcon(self._make_tray_icon(), self)
        self._tray.setToolTip("PyTune")

        menu = QMenu()
        self._tray_play_action = menu.addAction("▶  Воспроизвести / Пауза")
        self._tray_play_action.triggered.connect(self.play_pause)

        tray_next = menu.addAction("⏭  Следующий")
        tray_next.triggered.connect(self.next_track)

        tray_prev = menu.addAction("⏮  Предыдущий")
        tray_prev.triggered.connect(self.prev_track)

        menu.addSeparator()

        tray_show = menu.addAction("🪟  Показать окно")
        tray_show.triggered.connect(self._show_from_tray)

        menu.addSeparator()

        tray_quit = menu.addAction("✕  Выход")
        tray_quit.triggered.connect(self._quit_app)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

        self.player.playbackStateChanged.connect(self._update_tray_play_action)

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
        self.save_playlists()
        if self._tray:
            self._tray.hide()
        QApplication.quit()

    def _notify_track(self, meta: TrackMeta):
        """Показывает всплывающее уведомление о смене трека."""
        if self._tray is None or not self._tray.isVisible():
            return
        title = meta.title or os.path.basename(meta.path)
        body = meta.artist if meta.artist else "Неизвестный исполнитель"
        self._tray.showMessage(title, body, self._make_tray_icon(), 3000)

    def save_playlists(self):
        self._save_current_playlist_state()
        data = {
            "current_playlist": self.current_playlist_name,
            "playlists": self.playlists,
        }
        try:
            with open(PLAYLISTS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"[PyTune] Не удалось сохранить плейлисты: {e}")

    def load_playlists(self):
        default_name = "Плейлист 1"
        if not os.path.exists(PLAYLISTS_FILE):
            old_file = "playlist.json"
            if os.path.exists(old_file):
                try:
                    with open(old_file, "r", encoding="utf-8") as f:
                        old_data = json.load(f)
                    self.playlists[default_name] = {
                        "tracks": old_data.get("playlist", []),
                        "current_index": old_data.get("current_index", -1),
                    }
                except Exception:
                    pass
            if not self.playlists:
                self.playlists[default_name] = {"tracks": [], "current_index": -1}
            self.current_playlist_name = default_name
        else:
            try:
                with open(PLAYLISTS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.playlists = data.get("playlists", {})
                self.current_playlist_name = data.get("current_playlist", default_name)
            except Exception as e:
                print(f"[PyTune] Не удалось загрузить плейлисты: {e}")
                self.playlists[default_name] = {"tracks": [], "current_index": -1}
                self.current_playlist_name = default_name

        if not self.playlists:
            self.playlists[default_name] = {"tracks": [], "current_index": -1}
            self.current_playlist_name = default_name
        if self.current_playlist_name not in self.playlists:
            self.current_playlist_name = next(iter(self.playlists))

        self.playlist_panel.populate(list(self.playlists.keys()), self.current_playlist_name)
        self._load_playlist_into_ui(self.current_playlist_name)

    def closeEvent(self, event):
        if getattr(self, '_tray_quit', False) or self._tray is None:
            self.save_playlists()
            if self._tray:
                self._tray.hide()
            event.accept()
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
