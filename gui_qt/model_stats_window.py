"""A Qt-based window for displaying model usage statistics."""

from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView,
    QWidget, QSizePolicy, QTabWidget, QHBoxLayout, QLabel, QRadioButton
)
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from typing import Dict, Any, Optional, List

# Matplotlib integration
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt

from core.prompt_processor import PromptProcessor

class StatsLoaderWorker(QObject):
    """Worker to load model stats in the background."""
    finished = Signal(dict)

    def __init__(self, processor: PromptProcessor):
        super().__init__()
        self.processor = processor

    @Slot()
    def run(self):
        try:
            stats = self.processor.get_model_stats()
            lora_stats = self.processor.get_lora_stats()
            all_invokeai_models = [m['name'] for m in self.processor.get_invokeai_models()] if self.processor.is_invokeai_connected() else None
            self.finished.emit({'success': True, 'stats': stats, 'lora_stats': lora_stats, 'all_invokeai_models': all_invokeai_models})
        except Exception as e:
            self.finished.emit({'success': False, 'error': str(e)})

class MplCanvas(FigureCanvas):
    """A custom Matplotlib canvas widget for Qt."""
    def __init__(self, parent=None, width=5, height=4, dpi=100):
        fig = Figure(figsize=(width, height), dpi=dpi)
        self.axes = fig.add_subplot(111)
        super().__init__(fig)
        self.setParent(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.updateGeometry()

class ModelStatsWindow(QDialog):
    """A window to display model usage statistics."""

    def __init__(self, parent, processor: PromptProcessor):
        super().__init__(parent)
        self.setWindowTitle("Model Usage Statistics")
        self.processor = processor
        self.stats_thread: Optional[QThread] = None
        self.stats: Dict[str, Dict[str, float]] = {}
        self.lora_stats: Dict[str, int] = {}
        self.chart_type_var = "count"

        self._create_widgets()
        self._connect_signals()
        self._start_loading_stats()
        self.resize(900, 700)
        try:
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            self.move(screen_geometry.center() - self.rect().center())
        except Exception:
            pass # Fallback to default positioning

    def _create_widgets(self):
        main_layout = QVBoxLayout(self)

        notebook = QTabWidget()
        main_layout.addWidget(notebook)

        # --- Model Stats Tab ---
        model_stats_tab = QWidget()
        model_stats_layout = QVBoxLayout(model_stats_tab)
        
        chart_controls = QHBoxLayout()
        chart_controls.addWidget(QLabel("Chart:"))
        self.model_count_radio = QRadioButton("Usage Count")
        self.model_count_radio.setChecked(True)
        chart_controls.addWidget(self.model_count_radio)
        self.model_avg_time_radio = QRadioButton("Average Time")
        chart_controls.addWidget(self.model_avg_time_radio)
        self.model_total_time_radio = QRadioButton("Total Time")
        chart_controls.addWidget(self.model_total_time_radio)
        chart_controls.addStretch()
        model_stats_layout.addLayout(chart_controls)

        self.chart_canvas = MplCanvas(self, width=8, height=3, dpi=100)
        model_stats_layout.addWidget(self.chart_canvas)

        self.stats_table = QTableWidget()
        self.stats_table.setColumnCount(6)
        self.stats_table.setHorizontalHeaderLabels(["Model Name", "Generation Count", "Avg. Time (s)", "Total Time (m)", "Min Time (s)", "Max Time (s)"])
        self.stats_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.stats_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.stats_table.verticalHeader().setVisible(False)
        header = self.stats_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.stats_table.setSortingEnabled(True)
        model_stats_layout.addWidget(self.stats_table)
        notebook.addTab(model_stats_tab, "Model Statistics")

        # --- LoRA Stats Tab ---
        lora_stats_tab = QWidget()
        lora_stats_layout = QVBoxLayout(lora_stats_tab)
        self.lora_chart_canvas = MplCanvas(self, width=8, height=3, dpi=100)
        lora_stats_layout.addWidget(self.lora_chart_canvas)

        self.lora_stats_table = QTableWidget()
        self.lora_stats_table.setColumnCount(2)
        self.lora_stats_table.setHorizontalHeaderLabels(["LoRA Name", "Usage Count"])
        self.lora_stats_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.lora_stats_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.lora_stats_table.verticalHeader().setVisible(False)
        lora_header = self.lora_stats_table.horizontalHeader()
        lora_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.lora_stats_table.setSortingEnabled(True)
        lora_stats_layout.addWidget(self.lora_stats_table)
        notebook.addTab(lora_stats_tab, "LoRA Statistics")

    def _connect_signals(self):
        self.model_count_radio.clicked.connect(self._update_model_chart)
        self.model_avg_time_radio.clicked.connect(self._update_model_chart)
        self.model_total_time_radio.clicked.connect(self._update_model_chart)

    def _start_loading_stats(self):
        self.stats_table.setRowCount(1)
        self.stats_table.setItem(0, 0, QTableWidgetItem("Loading stats..."))
        self.lora_stats_table.setRowCount(1)
        self.lora_stats_table.setItem(0, 0, QTableWidgetItem("Loading stats..."))

        self.stats_thread = QThread(self)
        worker = StatsLoaderWorker(self.processor)
        worker.moveToThread(self.stats_thread)

        self.stats_thread.started.connect(worker.run)
        worker.finished.connect(self._on_stats_loaded)
        worker.finished.connect(self.stats_thread.quit)
        worker.finished.connect(worker.deleteLater)
        self.stats_thread.finished.connect(self.stats_thread.deleteLater)
        self.stats_thread.start()

    @Slot(dict)
    def _on_stats_loaded(self, result: dict):
        self.stats_table.clearContents()
        self.lora_stats_table.clearContents()
        if not result['success']:
            self.stats_table.setRowCount(1)
            self.stats_table.setItem(0, 0, QTableWidgetItem(f"Error: {result['error']}"))
            self.lora_stats_table.setRowCount(1)
            self.lora_stats_table.setItem(0, 0, QTableWidgetItem(f"Error: {result['error']}"))
            return

        self.stats = result.get('stats', {})
        all_invokeai_models = result.get('all_invokeai_models')
        if all_invokeai_models:
            for model_name in all_invokeai_models:
                if model_name not in self.stats:
                    self.stats[model_name] = {'count': 0, 'avg_duration': 0.0, 'total_duration': 0.0, 'min_duration': 0.0, 'max_duration': 0.0}

        sorted_stats = sorted(self.stats.items(), key=lambda item: item[1]['count'], reverse=True)

        self.stats_table.setRowCount(len(sorted_stats))
        for row, (model_name, data) in enumerate(sorted_stats):
            self.stats_table.setItem(row, 0, QTableWidgetItem(model_name))
            self.stats_table.setItem(row, 1, QTableWidgetItem(str(data.get('count', 0))))
            self.stats_table.setItem(row, 2, QTableWidgetItem(f"{data.get('avg_duration', 0.0):.2f}"))
            self.stats_table.setItem(row, 3, QTableWidgetItem(f"{data.get('total_duration', 0.0) / 60:.2f}"))
            self.stats_table.setItem(row, 4, QTableWidgetItem(f"{data.get('min_duration', 0.0):.2f}"))
            self.stats_table.setItem(row, 5, QTableWidgetItem(f"{data.get('max_duration', 0.0):.2f}"))

        self.lora_stats = result.get('lora_stats', {})
        sorted_lora_stats = sorted(self.lora_stats.items(), key=lambda item: item[1], reverse=True)

        self.lora_stats_table.setRowCount(len(sorted_lora_stats))
        for row, (lora_name, count) in enumerate(sorted_lora_stats):
            self.lora_stats_table.setItem(row, 0, QTableWidgetItem(lora_name))
            self.lora_stats_table.setItem(row, 1, QTableWidgetItem(str(count)))

        self._update_model_chart()
        self._update_lora_chart()

    def _update_model_chart(self):
        if self.model_count_radio.isChecked():
            chart_key = "count"
            title = "Image Generation Count per Model"
        elif self.model_avg_time_radio.isChecked():
            chart_key = "avg_duration"
            title = "Average Generation Time per Model (s)"
        else:
            chart_key = "total_duration"
            title = "Total Generation Time per Model (minutes)"

        if chart_key == 'total_duration':
            chart_data = {model: data[chart_key] / 60 for model, data in self.stats.items() if data[chart_key] > 0}
        else:
            chart_data = {model: data[chart_key] for model, data in self.stats.items() if data[chart_key] > 0}

        self._draw_horizontal_bar_chart(self.chart_canvas.axes, self.chart_canvas.figure, self.chart_canvas, chart_data, title, chart_key != 'count')

    def _update_lora_chart(self):
        self._draw_horizontal_bar_chart(self.lora_chart_canvas.axes, self.lora_chart_canvas.figure, self.lora_chart_canvas, self.lora_stats, "LoRA Usage Count", False)

    def _draw_horizontal_bar_chart(self, ax, fig, canvas, data: Dict[str, float], title: str, is_float: bool):
        ax.clear()
        MAX_ITEMS_TO_SHOW = 20
        all_sorted_items = sorted(data.items(), key=lambda item: item[1], reverse=True)

        if len(all_sorted_items) > MAX_ITEMS_TO_SHOW:
            title += f" (Top {MAX_ITEMS_TO_SHOW})"
        
        items_to_plot = sorted(all_sorted_items[:MAX_ITEMS_TO_SHOW], key=lambda item: item[1])

        if not items_to_plot:
            ax.text(0.5, 0.5, "No data to display.", ha='center', va='center', fontsize=10)
            canvas.draw()
            return

        models = [item[0] for item in items_to_plot]
        values = [item[1] for item in items_to_plot]

        cmap = plt.cm.get_cmap('viridis_r')
        norm = plt.Normalize(min(values) if values else 0, max(values) if values else 1)
        bar_colors = cmap(norm(values))

        bars = ax.barh(models, values, color=bar_colors, edgecolor='black', linewidth=0.5, alpha=0.9)

        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.grid(axis='x', linestyle=':', linewidth=0.5, alpha=0.5)
        ax.set_axisbelow(True)
        ax.set_title(title, fontsize=12, pad=15)

        for bar in bars:
            width = bar.get_width()
            label_text = f'{width:.2f}' if is_float else f'{int(width)}'
            ax.text(width + (ax.get_xlim()[1] * 0.01), bar.get_y() + bar.get_height()/2, label_text, va='center', fontsize=8)

        fig.subplots_adjust(left=0.35, right=0.95, top=0.9, bottom=0.1)
        canvas.draw()