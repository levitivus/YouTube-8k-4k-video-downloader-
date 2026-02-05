"""
youtube_downloader.py
Corrected PyQt5 GUI for listing & downloading YouTube formats.

Requires: Python 3.8+, PyQt5, yt-dlp, ffmpeg on PATH
Place spinner.gif (64x64 transparent) in the same folder for the loader.

LEGALISE PIRACY BABY!!!!!!!
"""

import sys
import os
import urllib.request
from typing import Optional

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem,
    QFileDialog, QProgressBar, QMessageBox, QFrame
)
from PyQt5.QtGui import QPixmap, QMovie, QFont
from PyQt5.QtCore import QThread, pyqtSignal, Qt
import yt_dlp


# ---------- Helpers ----------
def human_readable_size(num):
    if not num:
        return "Unknown"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if num < 1024.0:
            return f"{num:.2f} {unit}"
        num /= 1024.0
    return f"{num:.2f} PB"


def format_entry_display(fmt_meta: dict) -> str:
    """Compact, friendly format string (no format_id prefix)."""
    parts = []
    height = fmt_meta.get('height')
    fps = fmt_meta.get('fps')
    ext = fmt_meta.get('ext') or ''
    filesize = fmt_meta.get('filesize') or fmt_meta.get('filesize_approx')
    tbr = fmt_meta.get('tbr')
    abr = fmt_meta.get('abr')

    if height:
        parts.append(f"{height}p")
        if fps:
            parts.append(f"{fps}fps")
    else:
        if fmt_meta.get('acodec') and (not fmt_meta.get('vcodec') or fmt_meta.get('vcodec') in (None, 'none')):
            parts.append("Audio")
        else:
            parts.append("Unknown")

    if filesize:
        parts.append(f"~{human_readable_size(filesize)}")

    if ext:
        parts.append(ext)

    if tbr:
        try:
            parts.append(f"{int(tbr)}kbps")
        except Exception:
            parts.append(f"{tbr}kbps")
    elif abr:
        try:
            parts.append(f"{int(abr)}kbps")
        except Exception:
            parts.append(f"{abr}kbps")

    vcodec = fmt_meta.get('vcodec')
    acodec = fmt_meta.get('acodec')
    if vcodec and vcodec != 'none' and (not acodec or acodec in (None, 'none')):
        parts.append("(video-only)")
    elif acodec and (not vcodec or vcodec in (None, 'none')):
        parts.append("(audio-only)")
    else:
        parts.append("(video+audio)")

    return " • ".join(parts)


# ---------- ListFormatsWorker ----------
class ListFormatsWorker(QThread):
    formats_ready = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, url: str):
        super().__init__()
        self.url = url.strip()

    def run(self):
        try:
            if self.isInterruptionRequested():
                return
            ydl_opts = {'quiet': True, 'no_warnings': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url, download=False)
                if self.isInterruptionRequested():
                    return
                formats = info.get('formats', [info])
                simple = []
                for f in formats:
                    if self.isInterruptionRequested():
                        return
                    meta = {
                        'format_id': f.get('format_id'),
                        'ext': f.get('ext', ''),
                        'height': f.get('height'),
                        'fps': f.get('fps'),
                        'vcodec': f.get('vcodec'),
                        'acodec': f.get('acodec'),
                        'filesize': f.get('filesize') or f.get('filesize_approx'),
                        'tbr': f.get('tbr'),
                        'abr': f.get('abr'),
                    }
                    simple.append(meta)

                def sort_key(x):
                    h = x.get('height') or 0
                    is_audio_only = 1 if (x.get('acodec') and (not x.get('vcodec') or x.get('vcodec') in (None, 'none'))) else 0
                    return (-h, is_audio_only)
                simple.sort(key=sort_key)

                title = info.get('title') or ""
                thumb_url = info.get('thumbnail')
                thumb_bytes = None
                duration = info.get('duration')
                channel = info.get('channel') or info.get('uploader')

                if self.isInterruptionRequested():
                    return

                if thumb_url:
                    try:
                        with urllib.request.urlopen(thumb_url, timeout=10) as resp:
                            if self.isInterruptionRequested():
                                return
                            thumb_bytes = resp.read()
                    except Exception:
                        thumb_bytes = None

                payload = {
                    'formats': simple,
                    'title': title,
                    'thumbnail_bytes': thumb_bytes,
                    'duration': duration,
                    'channel': channel,
                }
                if self.isInterruptionRequested():
                    return
                self.formats_ready.emit(payload)
        except Exception as e:
            # if interrupted, we may want to quietly return
            if self.isInterruptionRequested():
                return
            self.error.emit(str(e))


# ---------- DownloadWorker ----------
class DownloadWorker(QThread):
    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, url, format_spec, outdir, out_template="%(title)s.%(ext)s", extra_opts=None):
        super().__init__()
        self.url = url.strip()
        self.format_spec = format_spec
        self.outdir = outdir or os.getcwd()
        self.out_template = out_template
        self.extra_opts = extra_opts or {}

    def run(self):
        try:
            if self.isInterruptionRequested():
                self.finished.emit(False, "Download cancelled.")
                return

            def progress_hook(d):
                if self.isInterruptionRequested():
                    # raising will cause yt-dlp to abort
                    raise Exception("Cancelled by user")
                status = d.get('status')
                if status == 'downloading':
                    downloaded = d.get('downloaded_bytes', 0) or 0
                    total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                    speed = d.get('speed') or 0
                    eta = d.get('eta')
                    if total:
                        try:
                            percent = int(downloaded * 100 / total)
                        except Exception:
                            percent = 0
                        percent = max(0, min(100, percent))
                        self.progress.emit(percent)
                        speed_str = human_readable_size(speed) + "/s" if speed else ""
                        eta_str = f"ETA: {eta}s" if eta else ""
                        self.status.emit(f"Downloading: {percent}% — {human_readable_size(downloaded)} / {human_readable_size(total)} {speed_str} {eta_str}")
                    else:
                        speed_str = human_readable_size(speed) + "/s" if speed else ""
                        self.status.emit(f"Downloading: {human_readable_size(downloaded)} {speed_str}")
                elif status == 'finished':
                    self.status.emit("Download finished — merging/processing (if necessary)...")
                    self.progress.emit(99)
                elif status == 'error':
                    self.status.emit("Error during download.")

            outpath = os.path.join(self.outdir, self.out_template)
            ydl_opts = {
                'format': self.format_spec,
                'outtmpl': outpath,
                'merge_output_format': 'mkv',
                'noplaylist': True,
                'progress_hooks': [progress_hook],
                'quiet': True,
                'no_warnings': True,
            }
            ydl_opts.update(self.extra_opts)

            self.status.emit("Starting download...")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if self.isInterruptionRequested():
                    self.finished.emit(False, "Download cancelled.")
                    return
                ydl.download([self.url])

            self.progress.emit(100)
            self.status.emit("Completed.")
            self.finished.emit(True, "Download completed.")
        except Exception as e:
            if self.isInterruptionRequested():
                self.finished.emit(False, "Download cancelled.")
            else:
                self.finished.emit(False, str(e))


# ---------- Main Window ----------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube Downloader — dark")
        self.setFixedSize(2000, 1250)  # Option A
        self.current_list_worker: Optional[ListFormatsWorker] = None
        self.current_download_worker: Optional[DownloadWorker] = None
        self._init_ui()

    def _init_ui(self):
        w = QWidget()
        self.setCentralWidget(w)
        layout = QVBoxLayout()
        w.setLayout(layout)

        self.apply_dark_style()

        # Top row: URL + list button
        row = QHBoxLayout()
        row.addWidget(QLabel("YouTube URL:"))
        self.url_edit = QLineEdit()
        row.addWidget(self.url_edit)
        self.list_btn = QPushButton("List formats")
        row.addWidget(self.list_btn)
        layout.addLayout(row)

        # Output folder
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Output folder:"))
        self.outdir_edit = QLineEdit(os.getcwd())
        row2.addWidget(self.outdir_edit)
        self.browse_btn = QPushButton("Browse")
        row2.addWidget(self.browse_btn)
        layout.addLayout(row2)

        # Middle area (left: title+thumb+list, right: actions)
        mid = QHBoxLayout()

        # ----- left column -----
        left_col = QVBoxLayout()
        left_col.setContentsMargins(16, 8, 16, 8)

        # title
        self.title_label = QLabel("Title will appear here")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setWordWrap(True)
        f = QFont()
        f.setPointSize(12)
        f.setBold(True)
        self.title_label.setFont(f)
        left_col.addWidget(self.title_label)

        # thumbnail + info row (thumb_row)
        thumb_row = QHBoxLayout()
        thumb_row.addStretch()

        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(500, 300)
        self.thumb_label.setStyleSheet("background: #1b1c20; border: 1px solid #2b2b2f;")
        self.thumb_label.setAlignment(Qt.AlignCenter)
        thumb_row.addWidget(self.thumb_label)
        thumb_row.addStretch()

        info_col = QVBoxLayout()
        self.channel_label = QLabel("Channel: -")
        self.channel_label.setStyleSheet("color: #cccccc; font-size: 15px;")
        self.channel_label.setWordWrap(True)
        self.duration_label = QLabel("Duration: -")
        self.duration_label.setStyleSheet("color: #cccccc; font-size: 15px;")

        info_col.addWidget(self.channel_label)
        info_col.addWidget(self.duration_label)
        info_col.addStretch()
        thumb_row.addLayout(info_col)
        thumb_row.addStretch()

        left_col.addLayout(thumb_row)

        # spacing between thumb and list
        left_col.addStretch(1)
        left_col.addSpacing(12)
        left_col.addStretch(1)

        # format list
        self.formats_list = QListWidget()
        self.formats_list.setSelectionMode(QListWidget.SingleSelection)
        self.formats_list.setFixedSize(1200,500)
        left_col.addWidget(self.formats_list)

        # ----- right column (actions) -----
        right_col = QVBoxLayout()
        right_col.addWidget(QLabel("Actions"))
        self.download_btn = QPushButton("Download selected format")
        self.download_8k_btn = QPushButton("Download best 8K (if available)")
        self.download_best_btn = QPushButton("Download best (auto)")
        self.download_mp3_btn = QPushButton("Download as MP3 (audio only)")
        right_col.addWidget(self.download_btn)
        right_col.addWidget(self.download_8k_btn)
        right_col.addWidget(self.download_best_btn)
        right_col.addWidget(self.download_mp3_btn)

        # Cancel button
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        right_col.addWidget(self.cancel_btn)
        right_col.addStretch()

        # Add to mid layout (centered)
        mid.addStretch(1)
        mid.addLayout(left_col, 3)
        mid.addStretch(1)
        mid.addLayout(right_col, 2)
        mid.addStretch(1)

        layout.addLayout(mid)

        # separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep)

        # bottom: spinner, progress, status
        bottom = QHBoxLayout()
        self.spinner_label = QLabel()
        self.spinner_label.setFixedSize(48, 48)
        self.spinner_label.setVisible(False)
        spinner_path = os.path.join(os.path.dirname(__file__), "spinner.gif")
        if os.path.exists(spinner_path):
            try:
                self.spinner_movie = QMovie(spinner_path)
                self.spinner_label.setMovie(self.spinner_movie)
            except Exception:
                self.spinner_movie = None
        else:
            self.spinner_movie = None
        bottom.addWidget(self.spinner_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        bottom.addWidget(self.progress, 1)

        self.status_label = QLabel("Ready")
        bottom.addWidget(self.status_label)

        layout.addLayout(bottom)

        footer = QLabel("Tip: double-click a format to download. MP3 requires ffmpeg.")
        footer.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        layout.addWidget(footer)

        # signals
        self.list_btn.clicked.connect(self.on_list_formats)
        self.browse_btn.clicked.connect(self.on_browse)
        self.download_btn.clicked.connect(self.on_download_selected)
        self.download_8k_btn.clicked.connect(self.on_download_8k)
        self.download_best_btn.clicked.connect(self.on_download_best)
        self.download_mp3_btn.clicked.connect(self.on_download_mp3)
        self.formats_list.itemDoubleClicked.connect(self.on_item_double)
        self.cancel_btn.clicked.connect(self.on_cancel)

    def apply_dark_style(self):
        self.setStyleSheet("""
            QWidget { background: #121316; color: #e6e6e6; font-family: "Segoe UI", Roboto, Arial; }
            QLineEdit, QListWidget, QProgressBar { background: #1b1c20; border: 1px solid #2b2b2f; padding: 6px; border-radius: 6px; }
            QPushButton { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #2b2f33, stop:1 #232629); padding: 8px 10px; border-radius: 8px; border: 1px solid #3b3f43; }
            QPushButton:hover { border: 1px solid #6b9cff; }
            QLabel { color: #dcdcdc; }
            QListWidget::item { padding: 8px; }
            QListWidget::item:selected { background: #2b3a51; color: #ffffff; }
            QProgressBar { height: 18px; border-radius: 9px; text-align: center; }
            QProgressBar::chunk { border-radius: 9px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #5b8cff, stop:1 #2b65d6); }
        """)

    def set_ui_enabled(self, enabled: bool):
        self.list_btn.setEnabled(enabled)
        self.download_btn.setEnabled(enabled)
        self.download_8k_btn.setEnabled(enabled)
        self.download_best_btn.setEnabled(enabled)
        self.download_mp3_btn.setEnabled(enabled)
        self.browse_btn.setEnabled(enabled)
        self.formats_list.setEnabled(enabled)
        self.url_edit.setEnabled(enabled)
        self.outdir_edit.setEnabled(enabled)
        # do NOT touch cancel_btn here - it's managed separately

    def on_browse(self):
        d = QFileDialog.getExistingDirectory(self, "Choose output folder", self.outdir_edit.text() or os.getcwd())
        if d:
            self.outdir_edit.setText(d)

    def _show_spinner(self, show: bool):
        if not getattr(self, "spinner_movie", None):
            return
        if show:
            self.spinner_label.setVisible(True)
            try:
                self.spinner_movie.start()
            except Exception:
                pass
        else:
            try:
                self.spinner_movie.stop()
            except Exception:
                pass
            self.spinner_label.setVisible(False)

    # ---------- listing formats ----------
    def on_list_formats(self):
        url = self.url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "No URL", "Please paste a YouTube URL first.")
            return

        self.formats_list.clear()
        self.title_label.setText("Fetching...")
        self._show_spinner(True)
        self.progress.setRange(0, 0)  # indeterminate
        self.set_ui_enabled(False)
        self.cancel_btn.setEnabled(True)
        self.status_label.setText("Fetching formats...")

        self.current_list_worker = ListFormatsWorker(url)
        self.current_list_worker.formats_ready.connect(self.on_formats_ready)
        self.current_list_worker.error.connect(self.on_list_error)
        self.current_list_worker.start()

    def on_formats_ready(self, payload: dict):
        self.set_ui_enabled(True)
        self.cancel_btn.setEnabled(False)
        self._show_spinner(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        formats = payload.get('formats', [])
        title = payload.get('title') or ""
        thumb_bytes = payload.get('thumbnail_bytes')
        duration = payload.get('duration')
        channel = payload.get('channel')

        if title:
            self.title_label.setText(title)
        else:
            self.title_label.setText("No title")

        if thumb_bytes:
            try:
                pix = QPixmap()
                pix.loadFromData(thumb_bytes)
                pix = pix.scaled(self.thumb_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.thumb_label.setPixmap(pix)
            except Exception:
                self.thumb_label.setText("No thumbnail")
        else:
            self.thumb_label.setText("No thumbnail")

        # channel + duration
        if channel:
            self.channel_label.setText(f"Channel: {channel}")
        else:
            self.channel_label.setText("Channel: Unknown")

        if duration:
            hrs = duration // 3600
            mins = (duration % 3600) // 60
            secs = duration % 60
            dur_str = f"{hrs}:{mins:02d}:{secs:02d}" if hrs > 0 else f"{mins}:{secs:02d}"
            self.duration_label.setText(f"Duration: {dur_str}")
        else:
            self.duration_label.setText("Duration: Unknown")

        # populate formats list
        self.formats_list.clear()
        for fm in formats:
            desc = format_entry_display(fm)
            item = QListWidgetItem(desc)
            item.setData(Qt.UserRole, fm)
            self.formats_list.addItem(item)

        self.status_label.setText(f"Found {len(formats)} formats.")

    def on_list_error(self, msg: str):
        self.set_ui_enabled(True)
        self.cancel_btn.setEnabled(False)
        self._show_spinner(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_label.setText("Failed to get formats.")
        self.title_label.setText("Error")
        self.thumb_label.clear()
        QMessageBox.critical(self, "Error listing formats", msg)

    def on_item_double(self, item):
        self.formats_list.setCurrentItem(item)
        self.on_download_selected()

    # ---------- downloads ----------
    def _start_download(self, format_spec, extra_opts=None, out_template="%(title)s.%(ext)s"):
        url = self.url_edit.text().strip()
        outdir = self.outdir_edit.text().strip() or os.getcwd()
        if not url:
            QMessageBox.warning(self, "No URL", "Please paste a YouTube URL first.")
            return
        if not os.path.isdir(outdir):
            QMessageBox.warning(self, "Bad folder", "Output folder doesn't exist.")
            return

        self.set_ui_enabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_label.setText("Preparing download...")

        self.current_download_worker = DownloadWorker(url, format_spec, outdir, out_template, extra_opts)
        self.current_download_worker.progress.connect(self.progress.setValue)
        self.current_download_worker.status.connect(self.status_label.setText)
        self.current_download_worker.finished.connect(self.on_download_finished)
        self.current_download_worker.start()

    def on_download_selected(self):
        item = self.formats_list.currentItem()
        if not item:
            QMessageBox.information(self, "Select format", "Please select a format from the list first.")
            return
        fmt = item.data(Qt.UserRole)
        fmt_id = fmt.get('format_id')
        vcodec = fmt.get('vcodec')
        acodec = fmt.get('acodec')
        if vcodec and vcodec != 'none' and (not acodec or acodec in (None, 'none')):
            format_spec = f"{fmt_id}+bestaudio/best"
        else:
            format_spec = fmt_id
        self._start_download(format_spec)

    def on_download_8k(self):
        fmt = "bestvideo[height=4320]+bestaudio/best/best"
        self._start_download(fmt)

    def on_download_best(self):
        fmt = "best"
        self._start_download(fmt)

    def on_download_mp3(self):
        postprocessors = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
        extra_opts = {
            'format': 'bestaudio/best',
            'postprocessors': postprocessors,
            'quiet': True,
            'no_warnings': True,
        }
        self._start_download("bestaudio/best", extra_opts=extra_opts, out_template="%(title)s.%(ext)s")

    def on_download_finished(self, success: bool, message: str):
        self.set_ui_enabled(True)
        self.cancel_btn.setEnabled(False)
        if success:
            self.progress.setValue(100)
            self.status_label.setText("Ready")
            QMessageBox.information(self, "Download finished", message)
        else:
            self.status_label.setText("Error")
            QMessageBox.critical(self, "Download failed", message)

    def on_cancel(self):
        # Cancel download worker
        if self.current_download_worker and self.current_download_worker.isRunning():
            self.current_download_worker.requestInterruption()
            self.status_label.setText("Cancelling download…")

        # Cancel format listing worker
        if self.current_list_worker and self.current_list_worker.isRunning():
            self.current_list_worker.requestInterruption()
            self.status_label.setText("Cancelling format fetch…")

        self.cancel_btn.setEnabled(False)

# ---------- main ----------
def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
