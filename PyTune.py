import sys
import os
from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QSlider, QLabel,
    QFileDialog, QHBoxLayout, QVBoxLayout, QListWidget, QMessageBox
)
from PyQt6.QtCore import Qt, QUrl, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, TIT2, TPE1


class PyTune(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle('PyTune')
        self.setMinimumSize(700, 600)

        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)

        self.playlist = []
        self.current_index = -1

        self.list_widget = QListWidget()

        self.open_btn = QPushButton('Открыть')
        self.delete_btn = QPushButton('Удалить')
        self.play_btn = QPushButton('▶')
        self.stop_btn = QPushButton('■')
        self.prev_btn = QPushButton('⏮')
        self.next_btn = QPushButton('⏭')

        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 0)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.audio_output.setVolume(0.8)

        self.time_label = QLabel('00:00 / 00:00')

        self.cover_label = QLabel()
        self.cover_label.setFixedSize(200, 200)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setStyleSheet("border: 1px solid gray;")

        self.title_label = QLabel("—")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet("font-weight: bold; font-size: 14px; margin-top: 5px;")

        self.artist_label = QLabel("")
        self.artist_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.artist_label.setStyleSheet("font-size: 13px; color: gray;")

        self.set_default_cover() 

        cover_layout = QVBoxLayout()
        cover_layout.addWidget(self.cover_label)
        cover_layout.addWidget(self.title_label)
        cover_layout.addWidget(self.artist_label)

        controls_layout = QHBoxLayout()
        controls_layout.addWidget(self.open_btn)
        controls_layout.addWidget(self.delete_btn)
        controls_layout.addWidget(self.prev_btn)
        controls_layout.addWidget(self.play_btn)
        controls_layout.addWidget(self.stop_btn)
        controls_layout.addWidget(self.next_btn)
        controls_layout.addStretch()
        controls_layout.addWidget(QLabel('Громкость'))
        controls_layout.addWidget(self.volume_slider)

        left_layout = QVBoxLayout()
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

        self.player.positionChanged.connect(self.position_changed)
        self.player.durationChanged.connect(self.duration_changed)
        self.player.playbackStateChanged.connect(self.update_play_button)
        self.player.mediaStatusChanged.connect(self.media_status_changed)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_time_label)
        self.timer.start(500)

    def set_default_cover(self):
        pix = QPixmap(200, 200)
        pix.fill(Qt.GlobalColor.lightGray)
        self.cover_label.setPixmap(pix)
        self.title_label.setText("—")
        self.artist_label.setText("")

    def update_cover(self, file_path):
        try:
            audio = MP3(file_path, ID3=ID3)
            title = None
            artist = None
            cover_found = False

            if audio.tags:
                for tag in audio.tags.values():
                    if isinstance(tag, TIT2):
                        title = str(tag.text[0])
                    elif isinstance(tag, TPE1):
                        artist = str(tag.text[0])
                    elif isinstance(tag, APIC):
                        pixmap = QPixmap()
                        pixmap.loadFromData(tag.data)
                        scaled = pixmap.scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation)
                        self.cover_label.setPixmap(scaled)
                        cover_found = True

            if not cover_found:
                self.set_default_cover()

            if not title:
                title = os.path.basename(file_path)

            self.title_label.setText(title)
            self.artist_label.setText(artist if artist else "")
        except Exception as e:
            print(f"Ошибка загрузки обложки или тегов: {e}")
            self.set_default_cover()

    def open_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, 'Открыть MP3-файлы', '', 'MP3 Files (*.mp3)')
        if not files:
            return

        added = 0
        for f in files:
            if f not in self.playlist:
                self.playlist.append(f)
                self.list_widget.addItem(f)
                added += 1

        if added == 0:
            QMessageBox.information(self, 'Внимание', 'Все выбранные треки уже добавлены.')

        if self.current_index == -1 and self.playlist:
            self.current_index = 0
            self.play_file(self.playlist[self.current_index])

    def delete_selected(self):
        row = self.list_widget.currentRow()
        if row < 0 or row >= len(self.playlist):
            QMessageBox.information(self, 'Удаление', 'Выберите трек для удаления.')
            return

        deleting_current = (row == self.current_index)
        self.playlist.pop(row)
        self.list_widget.takeItem(row)

        if not self.playlist:
            self.player.stop()
            self.current_index = -1
            self.position_slider.setRange(0, 0)
            self.time_label.setText('00:00 / 00:00')
            self.set_default_cover()
            return

        if deleting_current:
            self.player.stop()
            if row < len(self.playlist):
                self.current_index = row
            else:
                self.current_index = len(self.playlist) - 1
            self.play_file(self.playlist[self.current_index])
        elif row < self.current_index:
            self.current_index -= 1

        self.highlight_current()

    def play_file(self, file_path):
        if not file_path:
            return
        url = QUrl.fromLocalFile(file_path)
        self.player.setSource(url)
        self.player.play()
        self.update_cover(file_path)
        self.highlight_current()

    def play_pause(self):
        if not self.playlist:
            QMessageBox.information(self, 'Пусто', 'Добавьте MP3-файлы.')
            return

        state = self.player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            if self.player.source().isEmpty():
                if self.current_index < 0 or self.current_index >= len(self.playlist):
                    self.current_index = 0
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
        else:
            self.current_index = (self.current_index - 1) % len(self.playlist)
            self.play_file(self.playlist[self.current_index])

    def next_track(self):
        if not self.playlist:
            return
        self.current_index = (self.current_index + 1) % len(self.playlist)
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
        self.update_time_label()

    def duration_changed(self, dur):
        self.position_slider.setRange(0, dur)
        self.update_time_label()

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
            if self.playlist:
                self.current_index = (self.current_index + 1) % len(self.playlist)
                self.play_file(self.playlist[self.current_index])


if __name__ == '__main__':
    app = QApplication(sys.argv)
    player = PyTune()
    player.show()
    sys.exit(app.exec())

