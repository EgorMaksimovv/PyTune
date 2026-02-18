import sys
import os
from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QSlider, QLabel,
    QFileDialog, QHBoxLayout, QVBoxLayout, QListWidget, QMessageBox, QLineEdit,
    QTabWidget, QTextEdit
)
from PyQt6.QtCore import Qt, QUrl, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, TIT2, TPE1, USLT, TXXX
from mutagen.flac import FLAC
from mutagen.mp4 import MP4
from mutagen.asf import ASF
from mutagen.oggvorbis import OggVorbis
from mutagen.oggopus import OggOpus
from mutagen.wave import WAVE
import json
import random


class PyTune(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle('PyTune')
        self.setMinimumSize(1200, 600)

        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)

        self.playlist = []
        self.current_index = -1

        self.shuffle_mode = False
        self.repeat_mode = 0

        self.lyrics_cache = {}

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Поиск трека...")
        self.search_bar.textChanged.connect(self.filter_list)

        self.list_widget = QListWidget()

        self.open_btn = QPushButton('Открыть')
        self.delete_btn = QPushButton('Удалить')
        self.play_btn = QPushButton('▶')
        self.stop_btn = QPushButton('■')
        self.prev_btn = QPushButton('⏮')
        self.next_btn = QPushButton('⏭')
        self.shuffle_btn = QPushButton('🔀')
        self.repeat_btn = QPushButton('🔁')

        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 0)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.audio_output.setVolume(0.8)

        self.time_label = QLabel('00:00 / 00:00')

        self.tab_widget = QTabWidget()

        cover_container = QWidget()
        cover_layout_in_tab = QHBoxLayout(cover_container)
        cover_layout_in_tab.setContentsMargins(0, 0, 0, 0)

        self.cover_label = QLabel()
        self.cover_label.setFixedSize(200, 200)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setStyleSheet("border: 1px solid gray;")

        cover_layout_in_tab.addStretch() 
        cover_layout_in_tab.addWidget(self.cover_label, alignment=Qt.AlignmentFlag.AlignTop)
        cover_layout_in_tab.addStretch()   
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

        self.set_default_cover()

        cover_layout = QVBoxLayout()
        cover_layout.addWidget(self.tab_widget)
        cover_layout.addWidget(self.title_label)
        cover_layout.addWidget(self.artist_label)

        controls_layout = QHBoxLayout()
        controls_layout.addWidget(self.open_btn)
        controls_layout.addWidget(self.delete_btn)
        controls_layout.addWidget(self.prev_btn)
        controls_layout.addWidget(self.play_btn)
        controls_layout.addWidget(self.stop_btn)
        controls_layout.addWidget(self.next_btn)
        controls_layout.addWidget(self.shuffle_btn)
        controls_layout.addWidget(self.repeat_btn)

        controls_layout.addStretch()
        controls_layout.addWidget(QLabel('Громкость'))
        controls_layout.addWidget(self.volume_slider)

        left_layout = QVBoxLayout()
        left_layout.addWidget(self.search_bar)
        left_layout.addWidget(self.list_widget)
        left_layout.addLayout(controls_layout)
        left_layout.addWidget(self.position_slider)
        left_layout.addWidget(self.time_label)

        main_layout = QHBoxLayout()
        main_layout.addLayout(left_layout, 3)
        main_layout.addLayout(cover_layout, 1)
        self.setLayout(main_layout)

        self.open_btn.clicked.connect(self.open_files)
        self.delete_btn.clicked.connect(self.delete_selected)
        self.play_btn.clicked.connect(self.play_pause)
        self.stop_btn.clicked.connect(self.stop)
        self.prev_btn.clicked.connect(self.prev_track)
        self.next_btn.clicked.connect(self.next_track)
        self.list_widget.itemDoubleClicked.connect(self.list_double_clicked)

        self.position_slider.sliderMoved.connect(self.seek)
        self.volume_slider.valueChanged.connect(self.change_volume)

        self.shuffle_btn.clicked.connect(self.toggle_shuffle)
        self.repeat_btn.clicked.connect(self.toggle_repeat)

        self.player.positionChanged.connect(self.position_changed)
        self.player.durationChanged.connect(self.duration_changed)
        self.player.playbackStateChanged.connect(self.update_play_button)
        self.player.mediaStatusChanged.connect(self.media_status_changed)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_time_label)
        self.timer.start(500)

        self.load_playlist()

    def _extract_metadata(self, file_path):
        """
        Извлекает название, исполнителя и обложку из аудиофайла.
        """
        ext = os.path.splitext(file_path)[1].lower()
        title = None
        artist = None
        cover_data = None

        try:
            if ext == '.mp3':
                audio = MP3(file_path, ID3=ID3)
                if audio.tags:
                    for tag in audio.tags.values():
                        if isinstance(tag, TIT2):
                            title = str(tag.text[0])
                        elif isinstance(tag, TPE1):
                            artist = str(tag.text[0])
                        elif isinstance(tag, APIC):
                            cover_data = tag.data
                if not title:
                    title = os.path.basename(file_path)
                return title, artist or "", cover_data

            elif ext == '.flac':
                audio = FLAC(file_path)
                title = audio.get('title', [None])[0]
                artist = audio.get('artist', [None])[0]
                if audio.pictures:
                    cover_data = audio.pictures[0].data
                if not title:
                    title = os.path.basename(file_path)
                return title, artist or "", cover_data

            elif ext in ('.m4a', '.mp4', '.aac'):
                audio = MP4(file_path)
                title_list = audio.get('\xa9nam', [])
                if title_list:
                    title = str(title_list[0])
                artist_list = audio.get('\xa9ART', [])
                if artist_list:
                    artist = str(artist_list[0])
                covr = audio.get('covr', [])
                if covr:
                    cover_data = covr[0]
                if not title:
                    title = os.path.basename(file_path)
                return title, artist or "", cover_data

            elif ext in ('.wma', '.asf'):
                audio = ASF(file_path)
                title = audio.get('Title', [None])[0]
                artist = audio.get('Author', [None])[0]
                pic = audio.get('WM/Picture', [None])[0]
                if pic:
                    cover_data = pic.data
                if not title:
                    title = os.path.basename(file_path)
                return title, artist or "", cover_data

            elif ext in ('.ogg', '.opus'):
                if ext == '.ogg':
                    audio = OggVorbis(file_path)
                else:
                    audio = OggOpus(file_path)
                title = audio.get('title', [None])[0]
                artist = audio.get('artist', [None])[0]
                if not title:
                    title = os.path.basename(file_path)
                return title, artist or "", None

            elif ext == '.wav':
                audio = WAVE(file_path)
                if audio.tags:
                    for tag in audio.tags.values():
                        if isinstance(tag, TIT2):
                            title = str(tag.text[0])
                        elif isinstance(tag, TPE1):
                            artist = str(tag.text[0])
                        elif isinstance(tag, APIC):
                            cover_data = tag.data
                if not title:
                    title = os.path.basename(file_path)
                return title, artist or "", cover_data

            else:
                return os.path.basename(file_path), "", None

        except Exception as e:
            print(f"Ошибка чтения метаданных из {file_path}: {e}")
            return os.path.basename(file_path), "", None

    def _get_lyrics(self, file_path):
        """Извлекает текст песни из аудиофайла"""
        if file_path in self.lyrics_cache:
            return self.lyrics_cache[file_path]

        ext = os.path.splitext(file_path)[1].lower()
        lyrics = None

        try:
            if ext == '.mp3':
                audio = MP3(file_path, ID3=ID3)
                if audio.tags:
                    # Ищем USLT
                    for tag in audio.tags.values():
                        if isinstance(tag, USLT):
                            lyrics = tag.text
                            break
                    if not lyrics:
                        for tag in audio.tags.values():
                            if isinstance(tag, TXXX) and tag.desc.upper() == 'LYRICS':
                                lyrics = tag.text[0]
                                break

            elif ext == '.flac':
                audio = FLAC(file_path)
                lyrics = audio.get('lyrics', [None])[0]

            elif ext in ('.ogg', '.opus'):
                if ext == '.ogg':
                    audio = OggVorbis(file_path)
                else:
                    audio = OggOpus(file_path)
                lyrics = audio.get('lyrics', [None])[0]

            elif ext in ('.m4a', '.mp4'):
                audio = MP4(file_path)
                lyrics_list = audio.get('\xa9lyr', [])
                if lyrics_list:
                    lyrics = lyrics_list[0]
                else:
                    for key, value in audio.items():
                        if key.startswith('----:') and 'LYRICS' in key.upper():
                            lyrics = value[0].decode('utf-8', errors='ignore')
                            break

            elif ext in ('.wma', '.asf'):
                audio = ASF(file_path)
                lyrics = audio.get('WM/Lyrics', [None])[0]

            elif ext == '.wav':
                audio = WAVE(file_path)
                if audio.tags:
                    for tag in audio.tags.values():
                        if isinstance(tag, USLT):
                            lyrics = tag.text
                            break

        except Exception as e:
            print(f"Ошибка извлечения текста из {file_path}: {e}")

        if isinstance(lyrics, list):
            lyrics = '\n'.join(lyrics)

        self.lyrics_cache[file_path] = lyrics
        return lyrics

    def update_cover(self, file_path):
        """Обновляет обложку и информацию о треке."""
        title, artist, cover_data = self._extract_metadata(file_path)
        self.title_label.setText(title)
        self.artist_label.setText(artist)

        if cover_data:
            pixmap = QPixmap()
            if pixmap.loadFromData(cover_data):
                scaled = pixmap.scaled(200, 200,
                                       Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
                self.cover_label.setPixmap(scaled)
                return

        self.set_default_cover()

    def update_lyrics(self, file_path):
        """Обновляет отображаемый текст песни."""
        lyrics = self._get_lyrics(file_path)
        if lyrics:
            self.lyrics_text.setText(lyrics)
        else:
            self.lyrics_text.clear()

    def set_default_cover(self):
        """Устанавливает заглушку для обложки и очищает текст."""
        pix = QPixmap(200, 200)
        pix.fill(Qt.GlobalColor.lightGray)
        self.cover_label.setPixmap(pix)
        self.title_label.setText("—")
        self.artist_label.setText("")
        self.lyrics_text.clear()

    def filter_list(self, text):
        text = text.lower().strip()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            track = item.text().lower()
            filename = os.path.basename(track)
            match = text in filename.lower()
            item.setHidden(not match)

    def toggle_shuffle(self):
        self.shuffle_mode = not self.shuffle_mode
        self.shuffle_btn.setStyleSheet("background: lightgreen;" if self.shuffle_mode else "")

    def toggle_repeat(self):
        self.repeat_mode = (self.repeat_mode + 1) % 3
        if self.repeat_mode == 0:
            self.repeat_btn.setText("🔁")
        elif self.repeat_mode == 1:
            self.repeat_btn.setText("🔂")
        else:
            self.repeat_btn.setText("🔁∞")

    def open_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            'Открыть аудио-файлы',
            '',
            'Audio Files (*.mp3 *.wav *.flac *.ogg *.opus *.aac *.m4a *.wma);;All Files (*)'
        )
        if not files:
            return

        for f in files:
            if f not in self.playlist:
                self.playlist.append(f)
                self.list_widget.addItem(f)

        if self.current_index == -1 and self.playlist:
            self.current_index = 0
            self.play_file(self.playlist[self.current_index])

    def delete_selected(self):
        row = self.list_widget.currentRow()
        if row < 0 or row >= len(self.playlist):
            QMessageBox.information(self, 'Удаление', 'Выберите трек для удаления.')
            return

        file_path = self.playlist[row]
        deleting_current = (row == self.current_index)

        self.playlist.pop(row)
        self.list_widget.takeItem(row)

        if file_path in self.lyrics_cache:
            del self.lyrics_cache[file_path]

        if not self.playlist:
            self.player.stop()
            self.current_index = -1
            self.set_default_cover()
            return

        if deleting_current:
            self.current_index = min(row, len(self.playlist) - 1)
            self.play_file(self.playlist[self.current_index])

    def play_file(self, file_path):
        if not file_path:
            return
        url = QUrl.fromLocalFile(file_path)
        self.player.setSource(url)
        self.player.play()
        self.update_cover(file_path)
        self.update_lyrics(file_path)
        self.highlight_current()

    def play_pause(self):
        if not self.playlist:
            QMessageBox.information(self, 'Пусто', 'Добавьте аудио-файлы.')
            return

        state = self.player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            if self.player.source().isEmpty():
                self.current_index = max(self.current_index, 0)
                self.play_file(self.playlist[self.current_index])
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
            self.current_index = random.randrange(len(self.playlist))
            self.play_file(self.playlist[self.current_index])
            return

        self.current_index = (self.current_index - 1) % len(self.playlist)
        self.play_file(self.playlist[self.current_index])

    def next_track(self):
        if not self.playlist:
            return

        if self.shuffle_mode:
            new_index = random.randrange(len(self.playlist))
            if len(self.playlist) > 1:
                while new_index == self.current_index:
                    new_index = random.randrange(len(self.playlist))
            self.current_index = new_index
            self.play_file(self.playlist[self.current_index])
            return

        if self.repeat_mode == 1:
            self.play_file(self.playlist[self.current_index])
            return

        self.current_index += 1

        if self.repeat_mode == 0 and self.current_index >= len(self.playlist):
            self.stop()
            self.current_index = len(self.playlist) - 1
            return

        self.current_index %= len(self.playlist)
        self.play_file(self.playlist[self.current_index])

    def list_double_clicked(self, item):
        row = self.list_widget.currentRow()
        if 0 <= row < len(self.playlist):
            self.current_index = row
            self.play_file(self.playlist[self.current_index])

    def seek(self, position):
        self.player.setPosition(position)

    def change_volume(self, value):
        self.audio_output.setVolume(value / 100.0)

    def position_changed(self, pos):
        self.position_slider.setValue(pos)

    def duration_changed(self, dur):
        self.position_slider.setRange(0, dur)

    def update_time_label(self):
        pos = int(self.player.position() / 1000)
        dur = int(self.player.duration() / 1000)
        fmt = lambda s: f"{s//60:02d}:{s%60:02d}"
        self.time_label.setText(f"{fmt(pos)} / {fmt(dur)}")

    def update_play_button(self, state):
        self.play_btn.setText('⏸' if state == QMediaPlayer.PlaybackState.PlayingState else '▶')

    def highlight_current(self):
        if 0 <= self.current_index < self.list_widget.count():
            self.list_widget.setCurrentRow(self.current_index)

    def media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.next_track()

    def save_playlist(self):
        data = {"playlist": self.playlist, "current_index": self.current_index}
        try:
            with open("playlist.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except:
            pass

    def load_playlist(self):
        if not os.path.exists("playlist.json"):
            return

        try:
            with open("playlist.json", "r", encoding="utf-8") as f:
                data = json.load(f)

            self.playlist = data.get("playlist", [])
            self.current_index = data.get("current_index", -1)

            self.list_widget.clear()
            for track in self.playlist:
                self.list_widget.addItem(track)

            if self.playlist and 0 <= self.current_index < len(self.playlist):
                self.highlight_current()
                self.update_cover(self.playlist[self.current_index])
        except:
            pass

    def closeEvent(self, event):
        self.save_playlist()
        event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    player = PyTune()
    player.show()
    sys.exit(app.exec())

